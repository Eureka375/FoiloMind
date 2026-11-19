import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event

from foliomind.analysis import Analysis, AnalysisService, Profile, Proposal
from foliomind.library import CatalogError, Library, Source
from foliomind.proposals import ProposalStore


class AnalysisTests(unittest.TestCase):
    def setUp(self):
        directory = self.enterContext(TemporaryDirectory(dir=Path(__file__).parent))
        self.file = Path(directory) / "a.txt"
        self.file.write_text("TCP 使用拥塞窗口调整发送速度。\n" * 380, encoding="utf-8")
        self.lib = Library(Path(directory) / "catalog.sqlite3")
        self.lib.set_source(Source.file(self.file))
        (self.record,) = self.lib.refresh(Event())
        self.requests = []
        self.profile = Profile("https://example.test/v1", "mock-model")
        self.service = AnalysisService(self.lib, self.respond)

    def respond(self, profile, key, stage, payload):
        self.requests.append((stage, payload))
        if stage == "segment":
            segment = payload["segments"][0]
            return {"topic": "拥塞控制", "purpose": "学习笔记", "summary": "TCP 拥塞窗口",
                    "course": "计算机网络", "tags": ["TCP"], "name": "拥塞控制",
                    "evidence": [{"id": segment["id"], "quote": "拥塞窗口"},
                                 {"id": segment["id"], "quote": "假造引用"}]}
        if stage == "document":
            return {**payload["results"][0], "summary": "综合 TCP 拥塞控制"}
        if stage == "organize":
            return {"assignments": [{"id": self.record.id, "course": "计算机网络", "purpose": "学习笔记"}]}
        return {"edits": []}

    def test_consent_chunking_and_verified_evidence(self):
        preview = self.service.prepare([self.record.id], ("计算机网络",), self.profile)
        self.assertGreater(len(preview.documents[0].chunks), 1)
        with self.assertRaises(CatalogError):
            self.service.run(preview, "wrong", "fake", Event())
        self.assertEqual(self.requests, [])
        draft = self.service.run(preview, self.service.approve(preview), "fake", Event())
        self.assertEqual(len(draft.rows), 1)
        row = draft.rows[0]
        self.assertEqual(row.course, "计算机网络")
        self.assertEqual(row.covered, row.total)
        self.assertTrue(row.evidence)
        self.assertTrue(all(e.quote == "拥塞窗口" for e in row.evidence))
        self.assertEqual(self.lib.get(self.record.id).course, "")
        self.assertNotIn(str(self.file), repr(self.requests))

    def test_changed_document_is_not_sent_after_confirmation(self):
        preview = self.service.prepare([self.record.id], (), self.profile)
        consent = self.service.approve(preview)
        self.file.write_text("新内容", encoding="utf-8")
        draft = self.service.run(preview, consent, "fake", Event())
        self.assertEqual(self.requests, [])
        self.assertEqual(draft.rows[0].coverage, "STALE")

    def test_revision_compare_and_swap_and_independent_acceptance(self):
        preview = self.service.prepare([self.record.id], (), self.profile)
        initial = self.service.run(preview, self.service.approve(preview), "fake", Event())
        store = ProposalStore(self.lib)
        store.create(initial)
        diff = store.preview(initial, [{"id": self.record.id, "purpose": "复习提纲"}])
        self.assertIn("复习提纲", diff.lines[0])
        self.assertEqual(store.get(initial.id).revision, 1)
        updated = store.confirm(diff)
        with self.assertRaises(CatalogError):
            store.confirm(diff)
        store.apply(updated, {self.record.id}, {"tags"})
        current = self.lib.get(self.record.id)
        self.assertEqual(current.tags, ("TCP",))
        self.assertEqual(current.course, "")
        self.assertEqual(self.file.read_text(encoding="utf-8"), "TCP 使用拥塞窗口调整发送速度。\n" * 380)

    def test_edit_during_first_request_disables_later_chunks(self):
        def change(profile, key, stage, payload):
            result = self.respond(profile, key, stage, payload)
            self.file.write_text("变化后的文件", encoding="utf-8")
            return result

        service = AnalysisService(self.lib, change)
        preview = service.prepare([self.record.id], (), self.profile)
        draft = service.run(preview, service.approve(preview), "fake", Event())
        self.assertEqual([kind for kind, _ in self.requests], ["segment"])
        self.assertEqual(draft.rows[0].coverage, "STALE")

    def test_failed_model_output_does_not_clear_confirmed_values(self):
        self.lib.classify(self.record.id, self.record.digest, "已审核课程", "课件", (), "")
        store = ProposalStore(self.lib)
        draft = Proposal("failed", 1, (Analysis(self.record.id, self.record.digest),))
        store.create(draft)
        with self.assertRaises(CatalogError):
            store.apply(draft, {self.record.id}, {"classification"})
        self.assertEqual(self.lib.get(self.record.id).course, "已审核课程")
