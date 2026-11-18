import time
import tkinter as tk
import unittest
from threading import Event
from unittest.mock import patch

from foliomind.desktop import DesktopApp
from foliomind.jobs import JobEvent, JobState


class DesktopTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = tk.Tk()
        self.app = DesktopApp(self.root)
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


if __name__ == "__main__":
    unittest.main()
