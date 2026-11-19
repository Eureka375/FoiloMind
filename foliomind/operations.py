"""Confirmed filesystem plans, per-item recovery journal, and conditional undo."""

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from threading import Lock
from uuid import uuid4

from .documents import FORMATS, ensure_unlinked, identity, read_document
from .library import CatalogError, Source, absolute, allowed_path, authorized, currently_authorized, path_key
from .windows_move import rename_verified


RESERVED = {"con", "prn", "aux", "nul", "conin$", "conout$",
            *(head + number for head in ("com", "lpt") for number in "123456789¹²³")}


def safe_component(value: str, fallback: str = "") -> str:
    name = value.strip() or fallback
    if (not name or len(name) > 180 or name.endswith((" ", "."))
            or name.split(".")[0].rstrip().casefold() in RESERVED
            or any(c in '<>:"/\\|?*' or ord(c) < 32 for c in name)):
        raise CatalogError("名称中含不可用于 Windows 文件的字符或保留名称。")
    return name


def occupied(path):
    try:
        path.lstat()
    except FileNotFoundError:
        return False
    except OSError:
        return True
    return True


@dataclass(frozen=True)
class MoveItem:
    document_id: str
    source: Path
    target: Path
    digest: str
    identity: str
    root: Path
    root_identity: str
    blocked: str = ""


@dataclass(frozen=True)
class MovePlan:
    id: str
    items: tuple[MoveItem, ...]
    reversing: str = ""


class Operations:
    def __init__(self, library):
        self.library = library
        self.approvals = {}
        self.lock = Lock()
        with self.library.connect() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS operation_batches(
                id TEXT PRIMARY KEY, reversing TEXT NOT NULL, state TEXT NOT NULL,
                created TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)""")
            fields = {row["name"] for row in db.execute("PRAGMA table_info(operations)")}
            for field in ("target_root", "root_identity"):
                if field not in fields:
                    db.execute(f"ALTER TABLE operations ADD COLUMN {field} TEXT NOT NULL DEFAULT ''")

    def build(self, ids, destination, *, use_names=False, numbered=False, in_place=False, override=""):
        ids = tuple(dict.fromkeys(ids))
        if not ids or len(ids) > 200 or (override and len(ids) != 1):
            raise CatalogError("请选择 1 至 200 份资料。自定义文件名只适用于一个文件。")
        if destination is None and not (use_names or in_place or override):
            raise CatalogError("请指定整理目标或启用改名。")
        if destination is not None:
            destination = absolute(destination)
            try:
                destination_identity = identity(ensure_unlinked(destination))
            except OSError as error:
                raise CatalogError("无法验证目标目录。") from error
            if not destination.is_dir() or destination == destination.parent or not allowed_path(destination):
                raise CatalogError("请选择普通目标文件夹。")
        sources = self.library.sources()
        reserved, items = set(), []
        for doc_id in ids:
            doc = self.library.get(doc_id)
            root = destination or doc.path.parent
            folder, target, reason, root_identity = root, doc.path, "", ""
            try:
                root_identity = destination_identity if destination is not None else identity(ensure_unlinked(root))
                if destination is not None or in_place:
                    if not doc.course:
                        raise CatalogError("请先确认课程分类。")
                    folder /= safe_component(doc.course)
                    if doc.purpose:
                        folder /= safe_component(doc.purpose)
                name = override or (doc.proposed_name if use_names else "") or doc.path.name
                name = safe_component(name)
                if not name.casefold().endswith(doc.path.suffix.casefold()):
                    name = safe_component(name + doc.path.suffix)
                target = folder / name
                if (doc.path.suffix.lower() not in FORMATS or not doc.digest or not doc.identity
                        or not currently_authorized(doc.path, sources) or not allowed_path(target)):
                    raise CatalogError("资料或目标路径不在可操作范围内。")
                if doc.path == target:
                    raise CatalogError("目标与当前位置相同。")
                if doc.path.drive != target.drive:
                    raise CatalogError("首版只在同一 Windows 磁盘内整理。")
                if occupied(target) or path_key(target) in reserved:
                    if not numbered:
                        raise CatalogError("目标已存在")
                    base = target
                    for n in range(2, 1001):
                        candidate = base.with_stem(f"{base.stem} ({n})")
                        if not occupied(candidate) and path_key(candidate) not in reserved:
                            safe_component(candidate.name)
                            target = candidate
                            break
                    else:
                        raise CatalogError("无法生成可用编号。")
                reserved.add(path_key(target))
            except CatalogError as error:
                reason = str(error)
            except OSError:
                reason = "目标目录已变化或不可验证"
            items.append(MoveItem(doc.id, doc.path, target, doc.digest, doc.identity, root, root_identity, reason))
        return MovePlan(uuid4().hex, tuple(items))

    def approve(self, plan):
        token = uuid4().hex
        with self.lock:
            self.approvals[token] = plan
        return token

    def execute(self, plan, token, stop, progress=lambda *_: None):
        with self.lock:
            approved = self.approvals.pop(token, None)
        if approved is not plan:
            raise CatalogError("操作必须使用本次已经确认的预览。")
        with self.library.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if db.execute("SELECT 1 FROM operation_batches WHERE id=?", (plan.id,)).fetchone():
                raise CatalogError("这份计划已经提交。")
            db.execute("INSERT INTO operation_batches(id,reversing,state) VALUES(?,?,'RUNNING')",
                       (plan.id, plan.reversing))
            db.executemany(
                """INSERT INTO operations(batch,item,document_id,source,target,digest,identity,
                   target_root,root_identity,state,detail) VALUES(?,?,?,?,?,?,?,?,?,'PENDING','')""",
                [(plan.id, i, item.document_id, str(item.source), str(item.target), item.digest, item.identity,
                  str(item.root), item.root_identity)
                 for i, item in enumerate(plan.items)],
            )
        rejected = 0
        for index, item in enumerate(plan.items):
            success = self.execute_item(plan, index, item, stop)
            rejected += not success
            progress(index + 1, rejected)
        with self.library.connect() as db:
            db.execute("UPDATE operation_batches SET state='CLOSED' WHERE id=?", (plan.id,))
        return plan.id, self.history(plan.id)

    def execute_item(self, plan, index, item, stop):
        reason = "用户取消" if stop.is_set() else item.blocked
        if reason or occupied(item.target):
            return self.state(plan.id, index, "SKIPPED", reason or "目标已存在")
        with self.library.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT path,digest,identity,status,ignored FROM documents WHERE id=?",
                             (item.document_id,)).fetchone()
            if (not row or row["ignored"] or row["status"] in {"EXCLUDED", "STALE", "MISSING"}
                    or Path(row["path"]) != item.source or row["digest"] != item.digest or row["identity"] != item.identity
                    or not currently_authorized(item.source, self.library.sources_from(db))):
                db.execute("UPDATE operations SET state='SKIPPED',detail='当前记录或授权已变化' WHERE batch=? AND item=?",
                           (plan.id,index))
                return False
            db.execute("UPDATE operations SET state='INTENT',detail='' WHERE batch=? AND item=?", (plan.id,index))
        with self.library.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            intent = db.execute("SELECT state FROM operations WHERE batch=? AND item=?", (plan.id, index)).fetchone()
            if intent["state"] != "INTENT":
                return False
            if stop.is_set() or not currently_authorized(item.source, self.library.sources_from(db)):
                db.execute("UPDATE operations SET state='SKIPPED',detail='取消或授权已变化' WHERE batch=? AND item=?",
                           (plan.id, index))
                return False
            try:
                rename_verified(item.source, item.target, item.digest, item.identity, item.root, item.root_identity)
            except OSError:
                db.execute("""UPDATE operations SET state='FAILED',detail='原文件已变化、被占用，或目标不可安全写入'
                              WHERE batch=? AND item=?""", (plan.id, index))
                return False
            self.finish(db, plan.id, index, item.document_id, item.source, item.target, item.identity)
        return True

    def state(self, batch, item, state, detail):
        with self.library.connect() as db:
            db.execute("UPDATE operations SET state=?,detail=? WHERE batch=? AND item=?", (state, detail, batch, item))
        return False

    def finish(self, db, batch, item, doc_id, source, target, expected_identity):
        old_key, new_key = path_key(source), path_key(target)
        exact = Source.file(target)
        if exact.signature != expected_identity:
            raise CatalogError("已执行磁盘操作，但目标状态变化。请在操作历史中核对中断。")
        current = db.execute("SELECT path_key,identity FROM documents WHERE id=?", (doc_id,)).fetchone()
        if not current or current["path_key"] != old_key or current["identity"] != expected_identity:
            raise CatalogError("磁盘结果与资料库记录不同，请在操作历史中核对。")
        db.execute("DELETE FROM sources WHERE source_key=? AND kind='file'", (old_key,))
        source_key = next((path_key(s.path) for s in self.library.sources_from(db)
                           if s.covers(target) and not s.excludes(target) and s.is_current()), None)
        if source_key is None:
            source_key = path_key(exact.path)
            db.execute("INSERT OR REPLACE INTO sources VALUES(?,?,'file',0,'[]',?)",
                       (source_key,str(target),exact.signature))
        self.library.scope_changed(db)
        db.execute("UPDATE documents SET path_key='former:'||id,status='MISSING',segments='[]' WHERE path_key=? AND id!=?",
                   (new_key, doc_id))
        db.execute("UPDATE documents SET path=?,path_key=?,source_key=? WHERE id=? AND path_key=?",
                   (str(target), new_key, source_key, doc_id, old_key))
        if not authorized(target, self.library.sources_from(db)):
            self.library.hide(db, doc_id, "EXCLUDED", "目标不在目前的读取范围")
        db.execute("UPDATE operations SET state='SUCCEEDED',detail='' WHERE batch=? AND item=?", (batch,item))

    def history(self, batch):
        with self.library.connect() as db:
            return [dict(row) for row in db.execute("SELECT * FROM operations WHERE batch=? ORDER BY item", (batch,))]

    def batches(self):
        with self.library.connect() as db:
            return [dict(row) for row in db.execute("SELECT * FROM operation_batches ORDER BY created DESC,rowid DESC")]

    def preview_undo(self, batch):
        items = []
        for row in reversed(self.history(batch)):
            if row["state"] != "SUCCEEDED":
                continue
            source, target = Path(row["target"]), Path(row["source"])
            problem, root_identity = "", ""
            if not allowed_path(target) or source == target:
                problem = "目标不可安全恢复"
            elif occupied(target):
                problem = "目标已存在"
            if not problem:
                try:
                    root_identity = identity(ensure_unlinked(target.parent))
                except OSError:
                    problem = "原目录不可验证"
            items.append(MoveItem(row["document_id"], source, target, row["digest"], row["identity"],
                                  target.parent, root_identity, problem))
        if not items:
            raise CatalogError("本批没有可尝试恢复的成功项目。")
        return MovePlan(uuid4().hex, tuple(items), batch)

    def reconcile(self, stop, progress=lambda *_: None):
        with self.library.connect() as db:
            rows = [dict(row) for row in db.execute("SELECT * FROM operations WHERE state IN ('INTENT','UNKNOWN')")]
        for i, row in enumerate(rows, 1):
            if stop.is_set():
                break
            source, target = Path(row["source"]), Path(row["target"])
            with self.library.connect() as db:
                db.execute("BEGIN IMMEDIATE")
                current = db.execute("SELECT state FROM operations WHERE batch=? AND item=?",
                                     (row["batch"], row["item"])).fetchone()
                if current["state"] not in {"INTENT", "UNKNOWN"}:
                    continue
                status, detail = "UNKNOWN", "请人工核对源和目标"
                if (not allowed_path(target) or not authorized(source, self.library.sources_from(db))):
                    detail = "来源授权已变更，请人工核对"
                elif not valid_recovery_root(target, row):
                    detail = "确认时的目标目录已变化，请人工核对"
                elif matches(target, row) and not occupied(source):
                    try:
                        self.finish(db, row["batch"], row["item"], row["document_id"], source, target, row["identity"])
                    except (OSError, CatalogError):
                        detail = "目标与资料库记录无法对应，请人工核对"
                    else:
                        continue
                elif matches(source, row) and not occupied(target):
                    status, detail = "FAILED", "已核对：中断前未完成移动"
                db.execute("UPDATE operations SET state=?,detail=? WHERE batch=? AND item=?",
                           (status, detail, row["batch"], row["item"]))
            progress(i, 0)
        return self.batches()


def matches(path, row):
    try:
        data, file_identity = read_document(path, expected_identity=row["identity"])
    except (OSError, OverflowError):
        return False
    return file_identity == row["identity"] and sha256(data).hexdigest() == row["digest"]


def valid_recovery_root(target, row):
    root = Path(row["target_root"])
    try:
        return (root.is_absolute() and target.parent.is_relative_to(root)
                and identity(ensure_unlinked(root)) == row["root_identity"])
    except OSError:
        return False
