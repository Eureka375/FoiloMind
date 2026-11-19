"""Revisioned two-level proposals and transactional, per-aspect review."""

import json
from dataclasses import asdict, dataclass, replace

from .analysis import Analysis, Evidence, Profile, Proposal, field, fresh, label, tags_from
from .library import CatalogError


ASPECTS = {"classification", "tags", "name"}
EDIT_KEYS = {"id", "course", "purpose", "tags", "name"}


def serialize(proposal):
    return json.dumps(asdict(proposal), ensure_ascii=False)


def deserialize(payload):
    data = json.loads(payload)
    data["rows"] = tuple(
        Analysis(**{**item, "tags": tuple(item["tags"]), "edited": tuple(item.get("edited", ())),
                    "evidence": tuple(Evidence(**entry) for entry in item["evidence"])})
        for item in data["rows"]
    )
    return Proposal(**data)


@dataclass(frozen=True)
class ChangePreview:
    base: Proposal
    candidate: Proposal
    lines: tuple[str, ...]


@dataclass(frozen=True)
class RevisionInput:
    proposal: Proposal
    profile: Profile
    instruction: str


class ProposalStore:
    def __init__(self, library):
        self.library = library

    def create(self, proposal):
        with self.library.connect() as db:
            blob = serialize(proposal)
            db.execute("INSERT INTO proposals (id,revision,payload,state) VALUES (?,?,?,'DRAFT')",
                       (proposal.id, proposal.revision, blob))
            db.execute("INSERT INTO proposal_history VALUES (?,?,?)", (proposal.id, proposal.revision, blob))

    def get(self, proposal_id):
        with self.library.connect() as db:
            row = db.execute("SELECT payload FROM proposals WHERE id=?", (proposal_id,)).fetchone()
            if row is None:
                raise CatalogError("方案已不存在。")
            return deserialize(row[0])

    def recent(self):
        with self.library.connect() as db:
            return [deserialize(row[0]) for row in db.execute(
                "SELECT payload FROM proposals ORDER BY created DESC,rowid DESC LIMIT 30")]

    def preview(self, proposal, edits):
        if not isinstance(edits, list) or not edits or len(edits) > len(proposal.rows):
            raise CatalogError("没有明确可预览的修改。请说明要改哪些文件及归类。")
        rows = {row.id: row for row in proposal.rows}
        touched, lines = set(), []
        for edit in edits:
            if not isinstance(edit, dict) or set(edit) - EDIT_KEYS:
                raise CatalogError("方案修改只能包含课程、用途、标签和拟用名称。")
            doc_id = field(edit, "id")
            if doc_id not in rows or doc_id in touched:
                raise CatalogError("方案修改包含未知或重复文件。")
            touched.add(doc_id)
            before = rows[doc_id]
            fields = {}
            for key, value in edit.items():
                if key == "id":
                    continue
                if key == "tags":
                    fields[key] = tags_from(value)
                else:
                    if not isinstance(value, str):
                        raise CatalogError("分类修改需要文本值。")
                    fields[key] = label(value)
            after = replace(before, **fields, edited=tuple(sorted({*before.edited, *fields})))
            if not after.course:
                after = replace(after, purpose="")
            if "course" in fields:
                after = replace(after, review=not bool(after.course))
            for key, display in (("course", "课程"), ("purpose", "用途"), ("tags", "标签"), ("name", "拟用名称")):
                old, new = getattr(before, key), getattr(after, key)
                if old != new:
                    try:
                        name = self.library.get(doc_id).path.name
                    except CatalogError:
                        raise CatalogError("方案中的资料已从文件库移除。") from None
                    lines.append(f"{name} · {display}：{format_value(old)} → {format_value(new)}")
            rows[doc_id] = after
        if not lines:
            raise CatalogError("候选方案没有变化。")
        old_groups = {(row.course,row.purpose) for row in proposal.rows if row.course}
        new_groups = {(row.course,row.purpose) for row in rows.values() if row.course}
        for group in sorted(new_groups - old_groups):
            lines.append("新增分类 · " + " / ".join(filter(None, group)))
        for group in sorted(old_groups - new_groups):
            lines.append("移出草案分类 · " + " / ".join(filter(None, group)))
        candidate = replace(proposal, revision=proposal.revision + 1, rows=tuple(rows.values()))
        return ChangePreview(proposal, candidate, tuple(lines))

    def text_preview(self, prepared, consent, service, key, stop):
        service.require_consent(prepared, consent)
        proposal = prepared.proposal
        if self.get(proposal.id) != proposal:
            raise CatalogError("方案已变化，请重新预览发送范围。")
        for row in proposal.rows:
            doc = self.library.get(row.id)
            if row.covered and (doc.digest != row.digest or not fresh(self.library, doc)):
                raise CatalogError("方案引用的资料已经变化，请重新分析。")
        if stop.is_set():
            return None
        payload = {"instruction": prepared.instruction, "assignments": [
            {"id": row.id, "course": row.course, "purpose": row.purpose, "tags": row.tags, "name": row.name}
            for row in proposal.rows
        ]}
        result = service.transport(prepared.profile, key, "revision", payload)
        if stop.is_set():
            return None
        if not result.get("edits"):
            raise CatalogError("这条要求暂未生成可核验改动。请明确要调整的课程、用途或文件。")
        return self.preview(proposal, result["edits"])

    def confirm(self, diff):
        with self.library.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            candidate = diff.candidate
            changed = db.execute("UPDATE proposals SET revision=?,payload=?,state='DRAFT' WHERE id=? AND revision=? AND payload=?",
                                 (candidate.revision, serialize(candidate), candidate.id, diff.base.revision, serialize(diff.base)))
            if changed.rowcount != 1:
                raise CatalogError("方案已变化，请重新生成差异。")
            db.execute("INSERT INTO proposal_history VALUES (?,?,?)",
                       (candidate.id, candidate.revision, serialize(candidate)))
        return candidate

    def apply(self, proposal, ids, aspects):
        if not ids or not aspects or not aspects <= ASPECTS:
            raise CatalogError("请选择资料和确认项目。")
        selected = [row for row in proposal.rows if row.id in ids]
        if len(selected) != len(ids):
            raise CatalogError("方案包含未知文件。")
        for row in selected:
            doc = self.library.get(row.id)
            if doc.digest != row.digest or not fresh(self.library, doc):
                raise CatalogError("部分资料已变化或撤销授权，请刷新后再审核。")
            relevant = {"classification": bool(row.course and row.covered) or "course" in row.edited,
                        "tags": bool(row.tags and row.covered) or "tags" in row.edited,
                        "name": bool(row.name and row.covered) or "name" in row.edited}
            if any(not relevant[aspect] for aspect in aspects):
                raise CatalogError("部分资料没有所选项目的建议。请取消选择或先手动编辑该项。")
        with self.library.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            current = db.execute("SELECT revision,payload FROM proposals WHERE id=?", (proposal.id,)).fetchone()
            if current is None or current["revision"] != proposal.revision or current["payload"] != serialize(proposal):
                raise CatalogError("该方案不是当前版本，请重新打开。")
            db.execute("""CREATE TABLE IF NOT EXISTS proposal_reviews (
                proposal_id TEXT, revision INTEGER, document_id TEXT, aspect TEXT, applied_at
                TEXT DEFAULT CURRENT_TIMESTAMP, PRIMARY KEY(proposal_id,revision,document_id,aspect))""")
            for row in selected:
                saved = db.execute("SELECT * FROM documents WHERE id=? AND digest=? AND ignored=0 AND status IN ('EXTRACTED','PARTIAL','EMPTY','FAILED')",
                                   (row.id, row.digest)).fetchone()
                if saved is None:
                    raise CatalogError("资料已变化，未保存本次审核。")
                db.execute("UPDATE documents SET course=?,purpose=?,tags=?,proposed_name=? WHERE id=?",
                           (row.course if "classification" in aspects else saved["course"],
                            row.purpose if "classification" in aspects else saved["purpose"],
                            json.dumps(row.tags, ensure_ascii=False) if "tags" in aspects else saved["tags"],
                            row.name if "name" in aspects else saved["proposed_name"], row.id))
                db.executemany("INSERT OR REPLACE INTO proposal_reviews (proposal_id,revision,document_id,aspect) VALUES (?,?,?,?)",
                               [(proposal.id, proposal.revision, row.id, aspect) for aspect in sorted(aspects)])
            db.execute("UPDATE proposals SET state='REVIEWED' WHERE id=?", (proposal.id,))


def format_value(value):
    return ("、".join(value) if isinstance(value, tuple) else value) or "（空）"
