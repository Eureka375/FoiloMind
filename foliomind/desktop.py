"""Tkinter desktop shell. All widget updates run on the GUI thread."""

import sqlite3
import sysconfig
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk

from .catalog_view import CatalogView
from .diagnostics import check_python, check_sqlite
from .jobs import Job, JobEvent, JobRequest, JobService, JobState
from .library import Library
from .settings import Settings, SettingsError, SettingsStore, StartupPage


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
    def __init__(self, root: tk.Tk, settings_store: SettingsStore | None = None) -> None:
        self.root = root
        self.service = JobService()
        self.current_job: Job | None = None
        self.completion = None
        self.closing = False
        self.cancelling = False
        self.settings = Settings()
        self.settings_store = None
        storage_error = ""
        try:
            store = settings_store if settings_store is not None else SettingsStore.for_current_user()
            self.settings = store.load()
            self.settings_store = store
        except SettingsError as error:
            storage_error = str(error)

        root.title("FolioMind · 智序文件管家")
        root.geometry("1020x690")
        root.minsize(800, 530)
        root.option_add("*Font", ("Microsoft YaHei UI", 10))
        root.protocol("WM_DELETE_WINDOW", self.close)

        container = ttk.Frame(root, padding=20)
        container.pack(fill="both", expand=True)
        ttk.Label(container, text="FolioMind", font=("Segoe UI", 22, "bold")).pack(anchor="w")
        self.tabs = ttk.Notebook(container)
        self.tabs.pack(fill="both", expand=True, pady=(14, 0))
        self.workspace = ttk.Frame(self.tabs, padding=20)
        self.tabs.add(self.workspace, text="文件库")
        self.catalog = None
        if self.settings_store is not None:
            try:
                self.catalog = CatalogView(self.workspace,
                                           Library(self.settings_store.path.with_name("library.sqlite3")),
                                           self.start_work)
            except (OSError, sqlite3.Error):
                ttk.Label(self.workspace, text="资料库不可用，请检查应用数据目录权限。").pack(anchor="w")
        else:
            ttk.Label(self.workspace, text="本地存储不可用。详情见设置。").pack(anchor="w")

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

        preferences = ttk.Frame(self.tabs, padding=20)
        self.tabs.add(preferences, text="设置")
        ttk.Label(preferences, text="启动时打开").pack(anchor="w")
        self.startup_page = tk.StringVar(root, value=self.settings.startup_page.value)
        for page, name in ((StartupPage.WORKSPACE, "文件库"), (StartupPage.TASKS, "后台任务")):
            ttk.Radiobutton(preferences, text=name, value=page.value, variable=self.startup_page).pack(anchor="w", pady=(8, 0))
        self.save_button = ttk.Button(preferences, text="保存设置", command=self.save_settings)
        self.save_button.pack(anchor="w", pady=(16, 8))
        self.settings_status = tk.StringVar(root, value=storage_error)
        ttk.Label(preferences, textvariable=self.settings_status, wraplength=500).pack(anchor="w")
        if storage_error:
            self.save_button.state(["disabled"])
            ttk.Label(container, text="本地设置暂不可用。详情见“设置”。").pack(anchor="w", pady=(10, 0))

        self.tabs.select(self.tasks if self.settings.startup_page == StartupPage.TASKS else self.workspace)
        self.task_summary = tk.StringVar(root, "暂无后台任务")
        ttk.Label(container, textvariable=self.task_summary).pack(anchor="w", pady=(10, 0))
        root.after(30, self.poll)

    def save_settings(self) -> None:
        if self.settings_store is None:
            return
        page = StartupPage(self.startup_page.get())
        try:
            self.settings = self.settings_store.save(page, self.settings.revision)
        except SettingsError as error:
            self.settings_status.set(str(error))
        else:
            self.settings_status.set("已保存。下次启动时生效。")

    def start_diagnostics(self) -> None:
        if self.closing or self.run_button.instate(["disabled"]):
            return
        request = JobRequest("runtime_check", None, self.settings.revision, {})
        self.current_job = self.service.submit(request, "检查 Python 与 SQLite", (check_python, check_sqlite))
        self.run_button.state(["disabled"])
        self.cancel_button.state(["!disabled"])

    def start_work(self, phase, work, complete) -> None:
        if self.closing or self.run_button.instate(["disabled"]):
            messagebox.showinfo("后台任务", "已有任务运行，请等待或在“后台任务”中取消。", parent=self.root)
            return
        self.completion = complete
        self.current_job = self.service.submit_work(JobRequest("work", None, 0, {}), phase, work)
        self.run_button.state(["disabled"])
        self.cancel_button.state(["!disabled"])

    def show_event(self, event: JobEvent) -> None:
        if self.current_job is None or self.current_job.id != event.job_id:
            return
        active = event.state in ACTIVE_STATES
        label = "正在取消，等待当前步骤结束" if active and self.cancelling else STATE_LABEL[event.state]
        self.task_status.set(f"{event.phase} · {label}")
        self.task_summary.set(event.message or f"{event.phase} · {label} · 已处理 {event.processed}")
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
            complete, self.completion = self.completion, None
            self.cancel_button.state(["disabled"])
            if not self.closing:
                self.run_button.state(["!disabled"])
            self.cancelling = False
            if complete is not None and not self.closing:
                if event.message:
                    messagebox.showerror("后台任务", event.message, parent=self.root)
                elif event.result is not None:
                    complete(event.result)

    def poll(self) -> None:
        for event in self.service.drain():
            self.show_event(event)
        if self.closing and (self.current_job is None or not self.current_job.thread.is_alive()):
            self.completion = None
            if self.catalog is not None:
                self.catalog.run = None
            self.root.update_idletasks()
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


def setup_drag_drop(root) -> bool:
    try:
        import tkinterdnd2
    except ImportError:
        return False
    platform_dir = {"win-amd64": "win-x64", "win32": "win-x86", "win-arm64": "win-arm64"}.get(
        sysconfig.get_platform()
    )
    if platform_dir is None:
        return False
    base = Path(tkinterdnd2.__file__).parent / "tkdnd"
    if str(root.tk.call("info", "patchlevel")).startswith("9.") and (base / f"{platform_dir}-tcl9").is_dir():
        platform_dir += "-tcl9"
    try:
        root.tk.call("lappend", "auto_path", str(base / platform_dir))
        root.tk.call("package", "require", "tkdnd")
    except tk.TclError:
        return False
    return True


def main() -> None:
    root = tk.Tk()
    setup_drag_drop(root)
    DesktopApp(root)
    root.mainloop()
