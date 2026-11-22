import hashlib
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np

from foliomind.discovery import discover_folder, local_embeddings
from foliomind.library import CatalogError, Library, Source
from foliomind.proposals import ProposalStore


class DiscoveryTests(unittest.TestCase):
    def setUp(self):
        root = Path(self.enterContext(TemporaryDirectory()))
        self.folder = root / "selected"
        self.folder.mkdir()
        self.library = Library(root / "catalog.sqlite3")
        self.store = ProposalStore(self.library)

    def write_examples(self):
        texts = {
            "a.txt": "数据库事务 隔离级别 行锁 死锁 索引 查询 数据库事务",
            "b.txt": "数据库事务 查询 索引 行锁 死锁 隔离级别 数据库事务",
            "c.txt": "网络报文 交换机 路由器 子网 掩码 网络协议 报文转发",
            "d.md": "网络报文 路由器 交换机 子网 掩码 网络协议 路由表",
            "review.txt": "古典音乐 木管乐器 作曲 管弦乐团 小提琴",
            "empty.txt": "",
        }
        for name, content in texts.items():
            (self.folder / name).write_text(content, encoding="utf-8")
        return texts

    def test_discovers_named_groups_and_saves_only_explicit_review(self):
        texts = self.write_examples()
        before = {name: hashlib.sha256((self.folder / name).read_bytes()).hexdigest() for name in texts}
        proposal = discover_folder(self.library, self.store, self.folder, Event(), lambda *_: None)
        rows = {self.library.get(row.id).path.name: row for row in proposal.rows}
        self.assertEqual(set(rows), set(texts))
        self.assertTrue(rows["a.txt"].course)
        self.assertTrue(rows["c.txt"].course)
        self.assertEqual(rows["a.txt"].course, rows["b.txt"].course)
        self.assertEqual(rows["c.txt"].course, rows["d.md"].course)
        self.assertNotEqual(rows["a.txt"].course, rows["c.txt"].course)
        for name in ("review.txt", "empty.txt"):
            self.assertTrue(rows[name].review)
            self.assertEqual(rows[name].course, "")
        for name in ("a.txt", "b.txt", "c.txt", "d.md"):
            evidence = rows[name].evidence[0]
            self.assertIn(evidence.quote, texts[name])
            self.assertEqual(texts[name][evidence.offset:evidence.offset + len(evidence.quote)], evidence.quote)
        self.assertEqual(self.store.get(proposal.id), proposal)
        self.assertTrue(all(not record.course for record in self.library.documents()))
        candidate = self.store.confirm(self.store.preview(proposal, [
            {"id": rows["a.txt"].id, "course": "数据库笔记"},
            {"id": rows["b.txt"].id, "course": "数据库笔记"},
        ]))
        self.store.apply(candidate, {rows["a.txt"].id, rows["b.txt"].id}, {"classification"})
        self.assertEqual(self.library.get(rows["a.txt"].id).course, "数据库笔记")
        self.assertEqual(self.library.get(rows["c.txt"].id).course, "")
        self.assertEqual(before, {name: hashlib.sha256((self.folder / name).read_bytes()).hexdigest()
                                  for name in texts})

    def test_discovery_keeps_saved_scope_and_leaves_other_sources_untouched(self):
        self.write_examples()
        hidden = self.folder / "ignore.txt"
        hidden.write_text("私人资料", encoding="utf-8")
        other = self.folder.parent / "other"
        other.mkdir()
        unrelated = other / "other.txt"
        unrelated.write_text("无关资料", encoding="utf-8")
        self.library.set_source(Source.directory(other))
        self.library.set_source(Source.directory(self.folder, exclusions=("ignore.txt",)))
        self.library.refresh(Event())
        other_record = next(row for row in self.library.documents() if row.path == unrelated)
        unrelated.unlink()
        proposal = discover_folder(self.library, self.store, self.folder, Event(), lambda *_: None)
        self.assertNotIn(other_record.id, {row.id for row in proposal.rows})
        self.assertEqual(self.library.get(other_record.id), other_record)
        self.assertNotIn(hidden, {row.path for row in self.library.documents()})
        self.assertEqual(self.store.recent()[0], proposal)

    def test_cancelled_discovery_leaves_no_draft(self):
        self.write_examples()
        stop = Event()
        result = discover_folder(self.library, self.store, self.folder, stop, lambda *_: stop.set())
        self.assertIsNone(result)
        self.assertEqual(self.store.recent(), [])

    def test_revoked_document_cannot_enter_new_draft(self):
        self.write_examples()
        proposal = discover_folder(self.library, self.store, self.folder, Event(), lambda *_: None)
        self.library.revoke(self.folder)
        with self.assertRaisesRegex(CatalogError, "已变化"):
            self.store.create(proposal, check_current=True)
        self.assertEqual(self.store.recent(), [])

    def test_local_encoder_uses_exact_token_budget_and_blocks_remote_code(self):
        calls = []

        class Encoder:
            max_seq_length = 6
            tokenizer = SimpleNamespace(
                num_special_tokens_to_add=lambda **_: 2,
                encode=lambda text, **_: list(text),
            )

            def __init__(self, model_path, **options):
                calls.append((model_path, options))

            def encode(self, pieces, **_):
                calls.append(pieces)
                return np.asarray([[1.0, 0.0] for _ in pieces])

        with patch.dict("sys.modules", {"sentence_transformers": SimpleNamespace(SentenceTransformer=Encoder)}):
            vectors = local_embeddings(["中文文本很长"], self.folder, Event())
        self.assertTrue(calls[0][1]["local_files_only"])
        self.assertFalse(calls[0][1]["trust_remote_code"])
        self.assertTrue(calls[0][1]["model_kwargs"]["use_safetensors"])
        self.assertEqual("".join(calls[1]), "中文文本很长")
        self.assertTrue(all(len(piece) <= 4 for piece in calls[1]))
        np.testing.assert_allclose(vectors, [[1, 0]])
