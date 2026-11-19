"""Operation previews and history. Every disk change requires an explicit confirmation."""

import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk

from .library import CatalogError
from .operations import Operations


class OperationView:
    def __init__(self, frame, catalog, run, show_tab):
        self.frame, self.catalog, self.run, self.show_tab = frame, catalog, run, show_tab
        self.service = Operations(catalog.library)
        bar = ttk.Frame(frame)
        bar.pack(fill="x")
        for title, action in (
            ("整理到指定目录", lambda: self.plan("target")),
            ("在原目录内分类整理", lambda: self.plan("original")),
            ("单独改名", lambda: self.plan("rename")),
            ("刷新操作历史", self.history),
            ("核对中断任务", self.recover),
            ("预览撤销", self.undo),
        ):
            ttk.Button(bar, text=title, command=action).pack(side="left", padx=(0, 6))
        row = ttk.Frame(frame)
        row.pack(fill="x", pady=8)
        self.use_names, self.numbered = tk.BooleanVar(frame), tk.BooleanVar(frame)
        ttk.Checkbutton(row, text="使用已接受的拟用名称", variable=self.use_names).pack(side="left", padx=(0, 8))
        ttk.Checkbutton(row, text="预览时为同名目标选择编号", variable=self.numbered).pack(side="left")
        self.tree = ttk.Treeview(frame, columns=("date", "type", "state"), show="headings", height=7)
        for key, label in (("date", "时间（UTC）"), ("type", "任务类型"), ("state", "记录状态")):
            self.tree.heading(key, text=label)
        self.tree.pack(fill="x")
        self.tree.bind("<<TreeviewSelect>>", self.show_history)
        self.detail = tk.Text(frame, height=10, state="disabled", wrap="word")
        self.detail.pack(fill="both", expand=True, pady=8)
        self.status = tk.StringVar(frame, "先在文件库选中文件。执行前会显示逐项路径。")
        ttk.Label(frame, textvariable=self.status).pack(anchor="w")
        self.history()

    def plan(self, mode):
        ids = [doc.id for doc in self.catalog.selected()]
        if not ids:
            self.status.set("请先在文件库选择需要整理的资料。")
            return
        destination, name = None, ""
        if mode == "target":
            chosen = filedialog.askdirectory(parent=self.frame)
            if not chosen:
                return
            destination = Path(chosen)
        elif mode == "rename":
            if len(ids) != 1:
                self.status.set("单独改名时请选择一份文件。")
                return
            current = self.catalog.selected()[0]
            name = simpledialog.askstring("改名", "输入新文件名，保留原扩展名。",
                                          initialvalue=current.proposed_name or current.path.stem, parent=self.frame)
            if not name:
                return
        service = self.service
        options = dict(use_names=self.use_names.get(), numbered=self.numbered.get(),
                       in_place=mode == "original", override=name)
        self.run("预检整理计划", lambda *_: service.build(ids, destination, **options), self.preview)

    def preview(self, plan):
        window = tk.Toplevel(self.frame)
        window.title("撤销确认" if plan.reversing else "实际文件整理确认")
        window.transient(self.frame.winfo_toplevel())
        window.geometry("850x420")
        body = ttk.Frame(window, padding=12)
        body.pack(fill="both", expand=True)
        eligible = sum(not i.blocked for i in plan.items)
        ttk.Label(body, text=f"将变更 {eligible} 份文件。其余项目将跳过。请核对以下源和目标。").pack(anchor="w")
        text = tk.Text(body, wrap="word")
        scroll = ttk.Scrollbar(body, orient="vertical", command=text.yview)
        text.configure(yscrollcommand=scroll.set)
        actions = ttk.Frame(body)
        actions.pack(side="bottom", fill="x", pady=(8, 0))
        scroll.pack(side="right", fill="y")
        text.pack(fill="both", expand=True)
        for item in plan.items:
            text.insert("end", f"{'跳过 · ' + item.blocked if item.blocked else '可执行'}\n"
                               f"源  {item.source}\n目标  {item.target}\n\n")
        text.configure(state="disabled")

        def confirm():
            window.destroy()
            service = self.service
            token = service.approve(plan)
            self.run("执行撤销" if plan.reversing else "执行整理",
                     lambda stop, progress: service.execute(plan, token, stop, progress), self.complete)

        ttk.Button(actions, text="取消", command=window.destroy).pack(side="right", padx=6)
        ttk.Button(actions, text="确认并变更上述文件", command=confirm,
                   state="normal" if eligible else "disabled").pack(side="right")
        window.grab_set()

    def complete(self, result):
        batch, history = result
        self.catalog.render(self.catalog.library.documents())
        self.history()
        self.tree.selection_set(batch)
        self.status.set(f"{sum(row['state']=='SUCCEEDED' for row in history)} / {len(history)} 项成功。")
        self.show_tab()

    def history(self):
        self.tree.delete(*self.tree.get_children())
        for batch in self.service.batches():
            self.tree.insert("", "end", iid=batch["id"],
                             values=(batch["created"], "撤销" if batch["reversing"] else "整理 / 改名",
                                     "已结束" if batch["state"] == "CLOSED" else "进行中 / 待核对"))

    def show_history(self, _=None):
        selected = self.tree.selection()
        if not selected:
            return
        rows = self.service.history(selected[0])
        status = {"PENDING": "待处理", "INTENT": "待核对", "FAILED": "失败",
                  "SKIPPED": "跳过", "UNKNOWN": "结果未知", "SUCCEEDED": "成功"}
        output = "\n\n".join(f"{status.get(r['state'], r['state'])} {r['detail']}\n{r['source']}\n→ {r['target']}" for r in rows)
        self.detail.configure(state="normal")
        self.detail.delete("1.0", "end")
        self.detail.insert("1.0", output)
        self.detail.configure(state="disabled")

    def undo(self):
        selected = self.tree.selection()
        if not selected:
            return
        service = self.service
        batch = selected[0]
        self.run("预检撤销", lambda *_: service.preview_undo(batch), self.preview)

    def recover(self):
        if not messagebox.askyesno("核对中断任务", "读取历史中的源与目标文件，核对已确认操作。不会移动文件。",
                                   parent=self.frame):
            return
        self.run("核对中断任务", self.service.reconcile, lambda _: self.history())
