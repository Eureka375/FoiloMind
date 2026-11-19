import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event
from unittest.mock import patch

from foliomind.library import CatalogError, Library, Source
from foliomind.operations import Operations


class OperationTests(unittest.TestCase):
    def setUp(self):
        tmp = self.enterContext(TemporaryDirectory(dir=Path(__file__).parent))
        self.root = Path(tmp)
        self.source = self.root / "lecture.txt"
        self.source.write_text("original", encoding="utf-8")
        self.target = self.root / "sorted"
        self.target.mkdir()
        self.lib = Library(self.root / "local.sqlite3")
        self.lib.set_source(Source.file(self.source))
        (self.record,) = self.lib.refresh(Event())
        self.lib.classify(self.record.id, self.record.digest, "网络", "课件", (), "讲义")
        self.ops = Operations(self.lib)

    def test_confirmed_batch_and_undo_keep_bytes_and_identity(self):
        plan = self.ops.build([self.record.id], self.target, use_names=True)
        final = self.target / "网络" / "课件" / "讲义.txt"
        self.assertFalse(final.parent.exists())
        with self.assertRaises(CatalogError):
            self.ops.execute(plan, "", Event())
        self.assertTrue(self.source.exists())
        self.ops.execute(plan, self.ops.approve(plan), Event())
        self.assertFalse(self.source.exists())
        self.assertEqual(final.read_text(), "original")
        self.assertEqual(self.lib.get(self.record.id).path, final)
        undo = self.ops.preview_undo(plan.id)
        self.ops.execute(undo, self.ops.approve(undo), Event())
        self.assertTrue(self.source.exists())
        self.assertFalse(final.exists())

    def test_conflict_after_confirmation_is_not_overwritten(self):
        plan = self.ops.build([self.record.id], None, use_names=True)
        token = self.ops.approve(plan)
        new = plan.items[0].target
        new.write_text("keep", encoding="utf-8")
        self.ops.execute(plan, token, Event())
        self.assertEqual(self.source.read_text(), "original")
        self.assertEqual(new.read_text(), "keep")
        self.assertEqual(self.ops.history(plan.id)[0]["state"], "SKIPPED")

    def test_replaced_target_directory_is_rejected(self):
        plan = self.ops.build([self.record.id], self.target)
        token = self.ops.approve(plan)
        self.target.rename(self.root / "old_sorted")
        self.target.mkdir()
        self.ops.execute(plan, token, Event())
        self.assertTrue(self.source.exists())
        self.assertEqual(list(self.target.iterdir()), [])

    def test_undo_refuses_occupied_source_or_changed_contents(self):
        plan = self.ops.build([self.record.id], None, use_names=True)
        self.ops.execute(plan, self.ops.approve(plan), Event())
        self.source.write_text("occupied", encoding="utf-8")
        self.assertEqual(self.ops.preview_undo(plan.id).items[0].blocked, "目标已存在")
        self.source.unlink()
        plan.items[0].target.write_text("external edit", encoding="utf-8")
        undo = self.ops.preview_undo(plan.id)
        self.ops.execute(undo, self.ops.approve(undo), Event())
        self.assertFalse(self.source.exists())
        self.assertEqual(plan.items[0].target.read_text(), "external edit")

    def test_reconcile_after_rename_but_before_catalog_commit(self):
        plan = self.ops.build([self.record.id], None, use_names=True)
        with patch.object(self.ops, "finish", side_effect=OSError("simulated catalog failure")):
            with self.assertRaises(OSError):
                self.ops.execute(plan, self.ops.approve(plan), Event())
        self.assertTrue(plan.items[0].target.exists())
        self.assertEqual(self.ops.history(plan.id)[0]["state"], "INTENT")
        self.ops.reconcile(Event())
        self.assertEqual(self.ops.history(plan.id)[0]["state"], "SUCCEEDED")
        self.assertEqual(self.lib.get(self.record.id).path, plan.items[0].target)
