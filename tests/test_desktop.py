import sqlite3
import time
import tkinter as tk
import unittest
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event
from unittest.mock import patch

from foliomind.desktop import DesktopApp
from foliomind.analysis import Profile
from foliomind.jobs import JobEvent, JobState
from foliomind.settings import SettingsStore, StartupPage


class DesktopTests(unittest.TestCase):
    def setUp(self) -> None:
        directory = self.enterContext(TemporaryDirectory())
        self.store = SettingsStore(Path(directory) / "profile" / "foliomind.sqlite3")
        self.root = tk.Tk()
        self.app = DesktopApp(self.root, self.store)
        self.addCleanup(self.close_window)

    def close_window(self) -> None:
        self.app.close()
        self.root.wait_window()

    def wait_for(self, condition) -> None:
        deadline = time.monotonic() + 3
        while not condition():
            self.root.update()
            if time.monotonic() >= deadline:
                self.fail("GUI did not update before timeout")
            time.sleep(0.01)

    def test_window_and_runtime_check(self) -> None:
        self.root.update()
        self.assertTrue(self.root.winfo_viewable())
        self.app.tabs.select(self.app.tasks)
        self.app.run_button.invoke()
        self.wait_for(lambda: "已完成" in self.app.task_status.get())
        self.assertEqual(self.app.counts.get(), "已处理 2 / 2，失败 0")

    def test_delayed_task_can_cancel_after_gui_redraw(self) -> None:
        started, release, redraw = Event(), Event(), Event()

        def delayed_step() -> None:
            started.set()
            if not release.wait(3):
                raise TimeoutError

        with patch("foliomind.desktop.check_python", delayed_step):
            self.app.start_diagnostics()
        try:
            self.wait_for(started.is_set)
            self.root.after_idle(redraw.set)
            self.app.tabs.select(self.app.workspace)
            self.wait_for(redraw.is_set)
            self.assertTrue(self.app.current_job.thread.is_alive())
            self.wait_for(lambda: "正在运行" in self.app.task_status.get())
            self.app.tabs.select(self.app.tasks)
            self.app.cancel_button.invoke()
            self.assertIn("正在取消", self.app.task_status.get())
        finally:
            release.set()
        self.wait_for(lambda: "已取消" in self.app.task_status.get())
        self.assertEqual(self.app.counts.get(), "已处理 1 / 2，失败 0")

    def test_old_event_cannot_overwrite_current_task(self) -> None:
        self.app.start_diagnostics()
        self.wait_for(lambda: "已完成" in self.app.task_status.get())
        old_job_id = self.app.current_job.id
        self.app.start_diagnostics()
        self.wait_for(lambda: self.app.run_button.instate(["!disabled"]))
        current_status = self.app.task_status.get()
        self.app.show_event(JobEvent(old_job_id, JobState.FAILED, "旧任务", 1, 1, 1))
        self.assertEqual(self.app.task_status.get(), current_status)

    def test_unknown_total_switches_progress_mode(self) -> None:
        self.app.start_diagnostics()
        job_id = self.app.current_job.id
        self.app.show_event(JobEvent(job_id, JobState.RUNNING, "处理资料"))
        self.assertEqual(str(self.app.progress["mode"]), "indeterminate")
        self.app.show_event(JobEvent(job_id, JobState.COMPLETED, "处理资料", 2))
        self.assertEqual(str(self.app.progress["mode"]), "determinate")

    def test_failed_save_is_visible_and_keeps_persisted_value(self) -> None:
        self.app.startup_page.set(StartupPage.TASKS.value)
        self.app.save_button.invoke()
        self.assertIn("已保存", self.app.settings_status.get())
        self.app.startup_page.set(StartupPage.WORKSPACE.value)
        with closing(sqlite3.connect(self.store.path)) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            self.app.save_button.invoke()
            self.assertIn("无法保存", self.app.settings_status.get())
        self.assertEqual(self.store.load().startup_page, StartupPage.TASKS)

    def test_import_fixture_and_display_original_line(self):
        sample = Path(__file__).parent / "fixtures/n0-n1/样本目录/开发集/01_未命名.txt"
        self.app.catalog.add_paths((str(sample),))
        self.wait_for(lambda: len(self.app.catalog.rows) == 1)
        doc_id = next(iter(self.app.catalog.rows))
        self.app.catalog.tree.selection_set(doc_id)
        self.app.catalog.show_document()
        self.assertIn("第 2 行", self.app.catalog.preview.get("1.0", "end"))

    def test_review_requires_confirmation_and_displays_verified_evidence(self):
        sample = Path(__file__).parent / "fixtures/n0-n1/样本目录/开发集/01_未命名.txt"
        self.app.catalog.add_paths((str(sample),))
        self.wait_for(lambda: len(self.app.catalog.rows) == 1)
        doc_id = next(iter(self.app.catalog.rows))
        self.app.catalog.tree.selection_set(doc_id)
        review = self.app.review
        profile = Profile("https://example.test/v1", "test")
        profile.save(review.library, "")
        calls = []

        def respond(_, key, stage, payload):
            calls.append(stage)
            if stage == "organize":
                return {"assignments": [{"id": doc_id, "course": "计算机网络", "purpose": "学习笔记"}]}
            fragment = next(item for item in payload["segments"] if "快速重传" in item["text"])
            return {"course": "计算机网络", "evidence": [{"id": fragment["id"], "quote": "快速重传"}]}

        review.service.transport = respond
        with patch("foliomind.review_view.messagebox.askyesno", return_value=False):
            review.analyze()
        self.assertEqual(calls, [])
        with patch.object(Profile, "key", return_value="fixture-key"), patch(
                 "foliomind.review_view.messagebox.askyesno", return_value=True):
            review.analyze()
            self.wait_for(lambda: review.proposal is not None)
        review.tree.selection_set(doc_id)
        review.show_selection()
        self.assertIn("第 2 行：快速重传", review.preview.get("1.0", "end"))
        self.assertEqual(review.library.get(doc_id).course, "")


if __name__ == "__main__":
    unittest.main()
