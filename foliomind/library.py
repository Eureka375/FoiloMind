"""Explicit sources, read-only enumeration, and the persistent local catalog."""

import json
import os
import sqlite3
import stat
from collections.abc import Iterable, Iterator
from contextlib import closing, contextmanager
from dataclasses import asdict, dataclass
from pathlib import Path
from threading import Event
from uuid import uuid4

from .documents import Extracted, Segment, ensure_unlinked, extract, identity, ordinary
from .windows_move import guarded_directory


PROTECTED = {".git", ".svn", ".venv", "node_modules", "__pycache__", "$recycle.bin",
             "system volume information", "windows", "program files", "program files (x86)", "appdata"}
READABLE = {"EXTRACTED", "PARTIAL"}


class CatalogError(Exception):
    public = True


def absolute(path: Path) -> Path:
    return Path(os.path.abspath(path))


def path_key(path: Path) -> str:
    return os.path.normcase(str(absolute(path)))


def allowed_path(path: Path) -> bool:
    return not any(part.casefold() in PROTECTED or ":" in part for part in path.parts[1:])


@dataclass(frozen=True)
class Source:
    path: Path
    kind: str
    recursive: bool = True
    exclusions: tuple[str, ...] = ()
    signature: str = ""

    @classmethod
    def directory(cls, path: Path, *, recursive=True, exclusions=()):
        path = absolute(path)
        if path == path.parent or not allowed_path(path):
            raise CatalogError("请选择普通资料目录，不能选择磁盘根目录、系统目录或目录链接。")
        info = ensure_unlinked(path)
        if not stat.S_ISDIR(info.st_mode):
            raise CatalogError("所选位置不是目录。")
        rules = []
        for value in exclusions:
            rule = Path(value.strip().replace("\\", "/"))
            if not rule.parts or rule.anchor or ".." in rule.parts:
                raise CatalogError("排除项必须是资料目录下的相对路径。")
            rules.append(rule.as_posix())
        return cls(path, "directory", recursive, tuple(dict.fromkeys(rules)), identity(info))

    @classmethod
    def file(cls, path: Path, *, validate=True):
        path = absolute(path)
        if not validate:
            return cls(path, "file", False)
        if not allowed_path(path):
            raise CatalogError("只可选择普通资料文件。")
        info = ensure_unlinked(path)
        if not stat.S_ISREG(info.st_mode):
            raise CatalogError("只可选择普通资料文件。")
        return cls(path, "file", False, signature=identity(info))

    def is_current(self) -> bool:
        try:
            return bool(self.signature and identity(ensure_unlinked(self.path)) == self.signature)
        except OSError:
            return False

    def excludes(self, path: Path) -> bool:
        return self.kind == "directory" and any(
            path.is_relative_to(self.path / rule) for rule in self.exclusions
        )

    def covers(self, path: Path) -> bool:
        if self.kind == "file":
            return path == self.path
        return path != self.path and path.is_relative_to(self.path) and (self.recursive or path.parent == self.path)


def authorized(path: Path, sources: Iterable[Source]) -> bool:
    rules = tuple(sources)
    return allowed_path(path) and any(s.covers(path) for s in rules) and not any(s.excludes(path) for s in rules)


def currently_authorized(path, sources):
    return authorized(path, sources) and any(source.covers(path) and source.is_current() for source in sources)


def candidates(source: Source, sources: tuple[Source, ...], stop: Event) -> Iterator[Path]:
    if stop.is_set():
        return
    if not source.is_current():
        raise OSError("source identity changed")
    if source.kind == "file":
        if authorized(source.path, sources):
            yield source.path
        return

    def visit(folder: Path) -> Iterator[Path]:
        with guarded_directory(folder):
            if not source.is_current():
                raise OSError("source identity changed")
            ensure_unlinked(folder)
            with os.scandir(folder) as iterator:
                entries = sorted(iterator, key=lambda entry: entry.name.casefold())
        for entry in entries:
            if stop.is_set():
                return
            path = Path(entry.path)
            if not allowed_path(path) or any(s.excludes(path) for s in sources):
                continue
            try:
                info = entry.stat(follow_symlinks=False)
            except OSError:
                if authorized(path, sources):
                    yield path
                continue
            if not ordinary(info):
                continue
            if stat.S_ISDIR(info.st_mode):
                if source.recursive:
                    try:
                        yield from visit(path)
                    except OSError:
                        # Keep processing siblings. The failed entry appears as a diagnostic.
                        yield path
            elif stat.S_ISREG(info.st_mode) and authorized(path, sources):
                yield path

    yield from visit(source.path)


def scoped_extract(path, sources):
    with guarded_directory(path.parent):
        if not authorized(path, sources):
            return None
        active = [source for source in sources if source.covers(path) and source.is_current()]
        if any(source.kind == "directory" for source in active):
            return extract(path)
        if active:
            return extract(path, expected_identity=active[0].signature)
        return None


def scan_pairs(sources: tuple[Source, ...], stop: Event, ignored=frozenset(), reader=None):
    if reader is None:
        reader = lambda path: scoped_extract(path, sources)
    seen = set()
    for source in sources:
        try:
            for path in candidates(source, sources, stop):
                key = path_key(path)
                if key in seen or key in ignored:
                    continue
                seen.add(key)
                if path.is_dir():
                    yield source, Extracted(path, "FAILED", "子目录不可访问，覆盖不完整")
                else:
                    try:
                        doc = reader(path)
                    except OSError:
                        doc = Extracted(path, "FAILED", "资料目录已变化或无法验证")
                    if doc is not None:
                        yield source, doc
        except OSError:
            yield source, Extracted(source.path, "FAILED", "授权来源已失效或不可访问")


def scan(sources: tuple[Source, ...], stop: Event) -> Iterator[Extracted]:
    for _, document in scan_pairs(sources, stop):
        yield document


@dataclass(frozen=True)
class Record:
    id: str
    path: Path
    status: str
    detail: str
    digest: str
    identity: str
    segments: tuple[Segment, ...]
    course: str
    purpose: str
    tags: tuple[str, ...]
    proposed_name: str
    ignored: bool

    @property
    def available(self):
        return not self.ignored and self.status in READABLE


@dataclass(frozen=True)
class Hit:
    document_id: str
    path: Path
    evidence: Segment | None


SCHEMA = (
    """CREATE TABLE IF NOT EXISTS scope_state (id INTEGER PRIMARY KEY, epoch INTEGER NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS sources (
           source_key TEXT PRIMARY KEY, path TEXT NOT NULL, kind TEXT NOT NULL,
           recursive INTEGER NOT NULL, exclusions TEXT NOT NULL, signature TEXT NOT NULL DEFAULT '')""",
    """CREATE TABLE IF NOT EXISTS documents (
           id TEXT PRIMARY KEY, path_key TEXT NOT NULL UNIQUE, path TEXT NOT NULL,
           source_key TEXT NOT NULL, status TEXT NOT NULL, detail TEXT NOT NULL,
           digest TEXT NOT NULL, identity TEXT NOT NULL, segments TEXT NOT NULL,
           course TEXT NOT NULL DEFAULT '', purpose TEXT NOT NULL DEFAULT '',
           tags TEXT NOT NULL DEFAULT '[]', proposed_name TEXT NOT NULL DEFAULT '',
           ignored INTEGER NOT NULL DEFAULT 0)""",
    """CREATE TABLE IF NOT EXISTS proposals (
           id TEXT PRIMARY KEY, revision INTEGER NOT NULL, payload TEXT NOT NULL,
           state TEXT NOT NULL, created TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)""",
    """CREATE TABLE IF NOT EXISTS proposal_history (
           id TEXT NOT NULL, revision INTEGER NOT NULL, payload TEXT NOT NULL,
           PRIMARY KEY(id, revision))""",
    """CREATE TABLE IF NOT EXISTS operations (
           batch TEXT NOT NULL, item INTEGER NOT NULL, document_id TEXT NOT NULL,
           source TEXT NOT NULL, target TEXT NOT NULL, digest TEXT NOT NULL, identity TEXT NOT NULL,
           target_root TEXT NOT NULL DEFAULT '', root_identity TEXT NOT NULL DEFAULT '',
           state TEXT NOT NULL, detail TEXT NOT NULL, created TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
           PRIMARY KEY(batch, item))""",
)


class Library:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            for query in SCHEMA:
                db.execute(query)
            db.execute("INSERT OR IGNORE INTO scope_state VALUES(1,0)")
            if "signature" not in {row["name"] for row in db.execute("PRAGMA table_info(sources)")}:
                db.execute("ALTER TABLE sources ADD COLUMN signature TEXT NOT NULL DEFAULT ''")
            self.has_fts = self.ensure_search_index(db)

    @staticmethod
    def ensure_search_index(db):
        existing = db.execute("SELECT 1 FROM sqlite_schema WHERE name='body_index'").fetchone()
        try:
            db.execute("CREATE VIRTUAL TABLE IF NOT EXISTS body_index USING fts5(doc_id UNINDEXED, text, tokenize='trigram')")
        except sqlite3.OperationalError as error:
            if not existing and ("no such module" in str(error) or "no such tokenizer" in str(error)):
                return False
            raise
        db.execute("""CREATE TRIGGER IF NOT EXISTS index_document_insert AFTER INSERT ON documents BEGIN
             INSERT INTO body_index(doc_id,text) SELECT new.id,json_extract(value,'$.text')
             FROM json_each(new.segments) WHERE new.status IN ('EXTRACTED','PARTIAL') AND new.ignored=0; END""")
        db.execute("""CREATE TRIGGER IF NOT EXISTS index_document_update AFTER UPDATE OF segments,status,ignored
             ON documents BEGIN
             DELETE FROM body_index WHERE doc_id=old.id;
             INSERT INTO body_index(doc_id,text) SELECT new.id,json_extract(value,'$.text')
             FROM json_each(new.segments) WHERE new.status IN ('EXTRACTED','PARTIAL') AND new.ignored=0; END""")
        db.execute("""CREATE TRIGGER IF NOT EXISTS index_document_delete AFTER DELETE ON documents BEGIN
             DELETE FROM body_index WHERE doc_id=old.id; END""")
        if not existing:
            db.execute("""INSERT INTO body_index(doc_id,text) SELECT documents.id,json_extract(value,'$.text')
                          FROM documents,json_each(documents.segments)
                          WHERE documents.status IN ('EXTRACTED','PARTIAL') AND documents.ignored=0""")
        return True

    @staticmethod
    def epoch(db):
        return db.execute("SELECT epoch FROM scope_state WHERE id=1").fetchone()[0]

    @staticmethod
    def scope_changed(db):
        db.execute("UPDATE scope_state SET epoch=epoch+1 WHERE id=1")

    @contextmanager
    def connect(self):
        with closing(sqlite3.connect(self.path, timeout=2)) as db, db:
            db.row_factory = sqlite3.Row
            db.create_function("fold", 1, str.casefold, deterministic=True)
            yield db

    @staticmethod
    def to_record(row: sqlite3.Row) -> Record:
        return Record(row["id"], Path(row["path"]), row["status"], row["detail"], row["digest"],
                      row["identity"], tuple(Segment(**s) for s in json.loads(row["segments"])),
                      row["course"], row["purpose"], tuple(json.loads(row["tags"])),
                      row["proposed_name"], bool(row["ignored"]))

    def sources(self) -> tuple[Source, ...]:
        with self.connect() as db:
            return self.sources_from(db)

    def set_source(self, source: Source):
        with self.connect() as db:
            db.execute(
                """INSERT INTO sources VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT(source_key) DO UPDATE
                   SET recursive=excluded.recursive, exclusions=excluded.exclusions, signature=excluded.signature""",
                (path_key(source.path), str(source.path), source.kind, source.recursive,
                 json.dumps(source.exclusions), source.signature),
            )
            self.scope_changed(db)
            sources = self.sources_from(db)
            excluded = []
            for row in db.execute("SELECT id, path FROM documents WHERE ignored=0").fetchall():
                if not authorized(Path(row["path"]), sources):
                    self.hide(db, row["id"], "EXCLUDED", "超出当前导入范围")
                    excluded.append(row["id"])
            self.purge_analysis(db, excluded)

    @staticmethod
    def sources_from(db):
        return tuple(Source(Path(r["path"]), r["kind"], bool(r["recursive"]), tuple(json.loads(r["exclusions"])),
                            r["signature"]) for r in db.execute("SELECT * FROM sources ORDER BY source_key"))

    @staticmethod
    def hide(db, doc_id, status, detail):
        db.execute("UPDATE documents SET status=?, detail=?, segments='[]' WHERE id=?", (status, detail, doc_id))

    @staticmethod
    def purge_analysis(db, ids):
        removed = set(ids)
        if not removed:
            return
        affected = set()
        for row in db.execute("SELECT id,payload FROM proposal_history").fetchall():
            if any(item["id"] in removed for item in json.loads(row["payload"])["rows"]):
                affected.add(row["id"])
        for proposal_id in affected:
            db.execute("DELETE FROM proposal_history WHERE id=?", (proposal_id,))
            row = db.execute("SELECT payload FROM proposals WHERE id=?", (proposal_id,)).fetchone()
            if not row:
                continue
            data = json.loads(row[0])
            data["rows"] = [item for item in data["rows"] if item["id"] not in removed]
            if not data["rows"]:
                db.execute("DELETE FROM proposals WHERE id=?", (proposal_id,))
                continue
            data["revision"] += 1
            data["rationale"] = "部分资料已移除，旧版分析历史已清理。"
            payload = json.dumps(data, ensure_ascii=False)
            db.execute("UPDATE proposals SET revision=?,payload=?,state='DRAFT' WHERE id=?",
                       (data["revision"], payload, proposal_id))
            db.execute("INSERT INTO proposal_history VALUES(?,?,?)", (proposal_id, data["revision"], payload))
        if db.execute("SELECT 1 FROM sqlite_schema WHERE name='proposal_reviews'").fetchone():
            db.executemany("DELETE FROM proposal_reviews WHERE document_id=?", [(doc_id,) for doc_id in removed])

    def revoke(self, path: Path):
        with self.connect() as db:
            key = path_key(path)
            db.execute("DELETE FROM sources WHERE source_key=?", (key,))
            self.scope_changed(db)
            rows = db.execute("SELECT id FROM documents WHERE source_key=?", (key,)).fetchall()
            for row in rows:
                self.hide(db, row["id"], "EXCLUDED", "来源已移除")
            self.purge_analysis(db, (row["id"] for row in rows))

    def record(self, source: Source, doc: Extracted, epoch=None) -> Record | None:
        key = path_key(doc.path)
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if epoch is not None and (epoch != self.epoch(db)
                    or not currently_authorized(doc.path, self.sources_from(db))):
                return None
            current = db.execute("SELECT * FROM documents WHERE path_key=?", (key,)).fetchone()
            if current and current["ignored"]:
                return self.to_record(current)
            if current and doc.identity and current["identity"] and doc.identity != current["identity"]:
                db.execute("DELETE FROM documents WHERE id=?", (current["id"],))
                current = None
            doc_id = current["id"] if current else uuid4().hex
            db.execute(
                """INSERT INTO documents (id, path_key, path, source_key, status, detail, digest, identity, segments)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(id) DO UPDATE SET
                   status=excluded.status, detail=excluded.detail, digest=excluded.digest,
                   identity=CASE WHEN excluded.identity='' THEN identity ELSE excluded.identity END,
                   segments=excluded.segments, source_key=excluded.source_key""",
                (doc_id, key, str(doc.path), path_key(source.path), doc.status, doc.detail, doc.digest, doc.identity,
                 json.dumps([asdict(s) for s in doc.segments], ensure_ascii=False)),
            )
            return self.to_record(db.execute("SELECT * FROM documents WHERE id=?", (doc_id,)).fetchone())

    def refresh(self, stop: Event, progress=lambda *_: None):
        with self.connect() as db:
            db.execute("BEGIN")
            sources, epoch = self.sources_from(db), self.epoch(db)
            ignored = {row[0] for row in db.execute("SELECT path_key FROM documents WHERE ignored=1")}

        def read_authorized(path):
            with self.connect() as db:
                db.execute("BEGIN IMMEDIATE")
                if epoch != self.epoch(db):
                    return None
                return scoped_extract(path, self.sources_from(db))

        seen = set()
        failed_paths = []
        processed = failures = 0
        for source, doc in scan_pairs(sources, stop, ignored, read_authorized):
            if stop.is_set():
                break
            seen.add(path_key(doc.path))
            processed += 1
            failures += doc.status == "FAILED"
            if doc.status == "FAILED":
                failed_paths.append(doc.path)
            if source.covers(doc.path):
                saved = self.record(source, doc, epoch)
                if saved is None and doc.status == "FAILED":
                    with self.connect() as db:
                        db.execute("BEGIN IMMEDIATE")
                        if epoch == self.epoch(db):
                            db.execute("UPDATE documents SET segments='[]',status='STALE',detail=? WHERE path_key=?",
                                       (doc.detail, path_key(doc.path)))
            progress(processed, failures)
        if not stop.is_set():
            with self.connect() as db:
                db.execute("BEGIN IMMEDIATE")
                if epoch != self.epoch(db):
                    return self.documents()
                for r in db.execute("SELECT id,path,path_key FROM documents WHERE ignored=0").fetchall():
                    path = Path(r["path"])
                    if r["path_key"] in seen or not authorized(path, sources):
                        continue
                    status = "STALE" if any(path.is_relative_to(p) for p in failed_paths) else "MISSING"
                    self.hide(db, r["id"], status, "本次未能访问" if status == "STALE" else "文件已不在原位置")
        return self.documents()

    def documents(self, *, ignored=False) -> list[Record]:
        with self.connect() as db:
            sql = "SELECT * FROM documents WHERE ignored=? ORDER BY path_key"
            if not ignored:
                sql = "SELECT * FROM documents WHERE ignored=? AND status != 'EXCLUDED' ORDER BY path_key"
            return [self.to_record(r) for r in db.execute(sql, (ignored,))]

    def get(self, doc_id: str) -> Record:
        with self.connect() as db:
            row = db.execute("SELECT * FROM documents WHERE id=?", (doc_id,)).fetchone()
            if row is None or row["ignored"] or row["status"] == "EXCLUDED":
                raise CatalogError("文件已移除或被忽略。")
            return self.to_record(row)

    def classify(self, doc_id, digest, course, purpose, tags, proposed_name):
        with self.connect() as db:
            result = db.execute(
                """UPDATE documents SET course=?, purpose=?, tags=?, proposed_name=?
                   WHERE id=? AND digest=? AND ignored=0 AND status IN ('EXTRACTED','PARTIAL','EMPTY','FAILED')""",
                (course.strip(), purpose.strip(), json.dumps(list(dict.fromkeys(tags)), ensure_ascii=False),
                 proposed_name.strip(), doc_id, digest),
            )
            if result.rowcount != 1:
                raise CatalogError("资料已变化，请刷新后重新审核。")

    def ignore(self, doc_id):
        with self.connect() as db:
            self.hide(db, doc_id, "STALE", "已忽略，可恢复后重新刷新")
            db.execute("UPDATE documents SET ignored=1 WHERE id=?", (doc_id,))

    def restore(self, doc_id):
        with self.connect() as db:
            row = db.execute("SELECT path FROM documents WHERE id=? AND ignored=1", (doc_id,)).fetchone()
            if row is None:
                raise CatalogError("找不到忽略项。")
            sources = self.sources_from(db)
            if not currently_authorized(Path(row["path"]), sources):
                raise CatalogError("恢复前请重新授权该资料。")
            db.execute("UPDATE documents SET ignored=0,status='STALE',detail='等待刷新' WHERE id=?", (doc_id,))

    def search(self, keyword: str, *, course="", purpose="", tag="", extension="", unclassified=False) -> list[Hit]:
        term = keyword.strip().casefold()
        with self.connect() as db:
            sql = """SELECT d.* FROM documents d
                     WHERE d.ignored=0 AND d.status NOT IN ('STALE','MISSING','EXCLUDED')
                       AND (?='' OR d.course=?)
                       AND (?='' OR d.purpose=?)
                       AND (?=0 OR d.course='')
                       AND (?='' OR EXISTS (SELECT 1 FROM json_each(d.tags) WHERE value=?))"""
            params = [course, course, purpose, purpose, unclassified, tag, tag]
            if term:
                if self.has_fts and len(term) >= 3 and all(c.isascii() or "\u4e00" <= c <= "\u9fff" for c in term):
                    body = "d.id IN (SELECT doc_id FROM body_index WHERE body_index MATCH ?)"
                    body_term = '"' + term.replace('"', '""') + '"'
                else:
                    body = """EXISTS (SELECT 1 FROM json_each(d.segments)
                               WHERE instr(fold(json_extract(value,'$.text')),?) > 0)"""
                    body_term = term
                sql += f""" AND ({body} OR instr(fold(d.path),?) > 0 OR instr(fold(d.course),?) > 0
                            OR instr(fold(d.purpose),?) > 0 OR EXISTS (SELECT 1 FROM json_each(d.tags)
                            WHERE instr(fold(value),?) > 0))"""
                params.extend((body_term, term, term, term, term))
            docs = [self.to_record(row) for row in db.execute(sql + " ORDER BY d.path_key", params)]
        results = []
        for doc in docs:
            if extension and doc.path.suffix.lower() != extension.lower():
                continue
            hit = next((segment for segment in doc.segments if term and term in segment.text.casefold()), None)
            metadata = (str(doc.path), doc.course, doc.purpose, *doc.tags)
            if not term or hit or any(term in value.casefold() for value in metadata):
                results.append(Hit(doc.id, doc.path, hit))
        return results
