"""Tkinter desktop shell. All widget updates run on the GUI thread."""

import tkinter as tk
from tkinter import ttk

from .diagnostics import check_python, check_sqlite
from .jobs import Job, JobEvent, JobRequest, JobService, JobState


STATE_LABEL = {
    JobState.QUEUED: "等待运行",
    JobState.RUNNING: "正在运行",
    JobState.COMPLETED: "已完成",
    JobState.PARTIAL: "部分失败",
    JobState.CANCELLED: "已取消",
    JobState.FAILED: "失败",
}
ACTIVE_STATES = (JobState.QUEUED, JobState.RUNNING)


class DesktopApp:
    def __init__(self, root: tk.Tk, service: JobService | None = None) -> None:
        self.root = root
        self.service = service if service is not None else JobService()
        self.current_job: Job | None = None
        self.closing = False
        self.cancelling = False

        root.title("FolioMind · 智序文件管家")
        root.geometry("760x480")
        root.minsize(620, 400)
        root.option_add("*Font", ("Microsoft YaHei UI", 10))
        root.protocol("WM_DELETE_WINDOW", self.close)

        container = ttk.Frame(root, padding=20)
        container.pack(fill="both", expand=True)
        ttk.Label(container, text="FolioMind", font=("Segoe UI", 22, "bold")).pack(anchor="w")
        self.tabs = ttk.Notebook(container)
        self.tabs.pack(fill="both", expand=True, pady=(14, 0))
        self.workspace = ttk.Frame(self.tabs, padding=20)
        self.tabs.add(self.workspace, text="文件库")
        ttk.Label(self.workspace, text="尚无受管理的资料", font=("Microsoft YaHei UI", 14)).pack(anchor="w")
        ttk.Label(self.workspace, text="目录授权接入后，可以从这里选择要管理的文件夹。").pack(anchor="w", pady=(10, 0))

        self.tasks = ttk.Frame(self.tabs, padding=20)
        self.tabs.add(self.tasks, text="后台任务")
        self.run_button = ttk.Button(self.tasks, text="检查运行环境", command=self.start_diagnostics)
        self.run_button.pack(anchor="w")
        self.task_status = tk.StringVar(root, value="暂无后台任务")
        ttk.Label(self.tasks, textvariable=self.task_status, wraplength=520).pack(anchor="w", pady=(18, 6))
        self.progress = ttk.Progressbar(self.tasks)
        self.progress.pack(fill="x")
        self.counts = tk.StringVar(root, value="")
        ttk.Label(self.tasks, textvariable=self.counts).pack(anchor="w", pady=(8, 8))
        self.cancel_button = ttk.Button(self.tasks, text="取消任务", command=self.cancel, state="disabled")
        self.cancel_button.pack(anchor="w")
        ttk.Label(container, text="模型状态  未接入").pack(anchor="w", pady=(10, 0))
        root.after(30, self.poll)

    def start_diagnostics(self) -> None:
        if self.closing or self.run_button.instate(["disabled"]):
            return
        request = JobRequest("runtime_check", None, 0, {})
        self.current_job = self.service.submit(request, "检查 Python 与 SQLite", (check_python, check_sqlite))
        self.run_button.state(["disabled"])
        self.cancel_button.state(["!disabled"])

    def show_event(self, event: JobEvent) -> None:
        if self.current_job is None or self.current_job.id != event.job_id:
            return
        active = event.state in ACTIVE_STATES
        label = "正在取消，等待当前步骤结束" if active and self.cancelling else STATE_LABEL[event.state]
        self.task_status.set(f"{event.phase} · {label}")
        total = f" / {event.total}" if event.total is not None else ""
        self.counts.set(f"已处理 {event.processed}{total}，失败 {event.failed}")
        if event.total is None and active:
            if str(self.progress["mode"]) != "indeterminate":
                self.progress.configure(mode="indeterminate")
                self.progress.start()
        else:
            self.progress.stop()
            self.progress.configure(mode="determinate", maximum=max(1, event.total or event.processed), value=event.processed)
        if not active:
            self.cancel_button.state(["disabled"])
            if not self.closing:
                self.run_button.state(["!disabled"])
            self.cancelling = False

    def poll(self) -> None:
        for event in self.service.drain():
            self.show_event(event)
        if self.closing and (self.current_job is None or not self.current_job.thread.is_alive()):
            self.root.destroy()
            return
        self.root.after(30, self.poll)

    def cancel(self) -> None:
        if self.current_job is not None and self.current_job.thread.is_alive():
            self.cancelling = True
            self.current_job.cancel()
            self.cancel_button.state(["disabled"])
            self.task_status.set("正在取消，等待当前步骤结束")

    def close(self) -> None:
        self.closing = True
        self.run_button.state(["disabled"])
        self.cancel()


def main() -> None:
    root = tk.Tk()
    DesktopApp(root)
    root.mainloop()
