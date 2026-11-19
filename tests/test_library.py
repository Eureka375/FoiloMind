import hashlib
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event
from unittest.mock import patch

from foliomind.documents import extract
from foliomind.library import Library, Source, scan


FIXTURES = Path(__file__).parent / "fixtures" / "n0-n1"


class LibraryTests(unittest.TestCase):
    def test_fixture_status_evidence_and_source_integrity(self):
        expected = json.loads((FIXTURES / "expected.json").read_text(encoding="utf-8"))
        root = FIXTURES / expected["import_root"]
        source = Source.directory(root, exclusions=("资料/仅测试排除",))
        documents = {
            doc.path.relative_to(root).as_posix(): doc for doc in scan((source,), Event())
        }
        for sample in expected["samples"]:
            with self.subTest(sample=sample["id"]):
                relative = sample["path"]
                if sample["expected_status"] == "EXCLUDED":
                    self.assertNotIn(relative, documents)
                else:
                    doc = documents[relative]
                    self.assertEqual(sample["expected_status"], doc.status)
                    for proof in sample["evidence"]:
                        matching = [s.text for s in doc.segments if s.locator == proof["locator"]]
                        self.assertTrue(any(proof["text"] in text for text in matching), proof)
                self.assertEqual(hashlib.sha256((root / relative).read_bytes()).hexdigest(), sample["sha256"])

    def test_explicit_file_and_directory_with_no_recursion(self):
        with TemporaryDirectory(dir=Path(__file__).parent) as tmp:
            root = Path(tmp)
            (root / "sub").mkdir()
            (root / "a.txt").write_text("a", encoding="utf-8")
            child = root / "sub" / "b.md"
            child.write_text("# b", encoding="utf-8")
            sources = (Source.directory(root, recursive=False), Source.file(child))
            self.assertEqual({d.path.name for d in scan(sources, Event())}, {"a.txt", "b.md"})
            cancelled = Event()
            cancelled.set()
            self.assertEqual(list(scan(sources, cancelled)), [])

    def test_refresh_invalidates_content_but_keeps_user_classification(self):
        with TemporaryDirectory(dir=Path(__file__).parent) as tmp:
            root = Path(tmp)
            sample = root / "course.txt"
            lib = Library(root / "catalog.db")
            sample.write_text("网络拥塞控制", encoding="utf-8")
            source = Source.file(sample)
            lib.set_source(source)
            first = lib.record(source, extract(sample))
            lib.classify(first.id, first.digest, "计算机网络", "笔记", ("考试",), "")
            sample.write_text("数据库事务", encoding="utf-8")
            new = lib.record(source, extract(sample))
            self.assertEqual(first.id, new.id)
            self.assertNotEqual(first.digest, new.digest)
            self.assertEqual(lib.get(new.id).course, "计算机网络")
            self.assertEqual(lib.search("拥塞"), [])
            self.assertEqual(lib.search("事务")[0].document_id, new.id)
            lib.ignore(new.id)
            self.assertEqual(list(lib.documents()), [])
            self.assertTrue(sample.exists())
            lib.restore(new.id)
            self.assertEqual(lib.documents()[0].status, "STALE")

    def test_revoke_during_scan_hides_old_results_and_stops_file_reads(self):
        with TemporaryDirectory(dir=Path(__file__).parent) as tmp:
            root = Path(tmp)
            files = root / "files"
            files.mkdir()
            for name in ("a.txt", "b.txt"):
                (files / name).write_text(name, encoding="utf-8")
            lib = Library(root / "catalog.db")
            lib.set_source(Source.directory(files))

            def revoke(done, _):
                if done == 1:
                    Library(lib.path).revoke(files)

            with patch("foliomind.library.extract", wraps=extract) as reader:
                self.assertEqual(lib.refresh(Event(), revoke), [])
                reader.assert_called_once_with(files / "a.txt")
            self.assertEqual(lib.search("a.txt"), [])

    def test_ignored_document_can_be_restored_after_reauthorization(self):
        with TemporaryDirectory(dir=Path(__file__).parent) as tmp:
            root = Path(tmp)
            file = root / "readme.txt"
            file.write_text("在已授权资料内检索", encoding="utf-8")
            lib = Library(root / "catalog.db")
            source = Source.file(file)
            lib.set_source(source)
            doc, = lib.refresh(Event())
            lib.ignore(doc.id)
            lib.revoke(file)
            self.assertEqual(lib.documents(ignored=True)[0].id, doc.id)
            lib.set_source(source)
            lib.restore(doc.id)
            self.assertEqual(lib.refresh(Event())[0].id, doc.id)
            for key in ("已授权", "检索"):
                self.assertEqual(lib.search(key)[0].document_id, doc.id)


if __name__ == "__main__":
    unittest.main()
