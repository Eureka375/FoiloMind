"""Tk controls for batch consent, evidence review and revision."""

import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk

from .analysis import AnalysisService, Profile, request_json
from .discovery import draft_folder
from .library import CatalogError
from .proposals import ProposalStore, RevisionInput
from .subjects import SUBJECT_NAMES, build_subject_proposal


class ProfileDialog(simpledialog.Dialog):
    def __init__(self, parent, profile):
        self.profile = profile
        super().__init__(parent, "云端分析配置")

    def body(self, master):
        self.entries = {}
        for row, (name, initial) in enumerate((
            ("HTTPS 服务地址", self.profile.base_url if self.profile else ""),
            ("模型名", self.profile.model if self.profile else ""),
            ("API Key（留空保留已有密钥）", ""),
        )):
            ttk.Label(master, text=name).grid(row=row, column=0, sticky="w", padx=6, pady=6)
            entry = ttk.Entry(master, width=44, show="*" if row == 2 else "")
            entry.insert(0, initial)
            entry.grid(row=row, column=1, padx=6, pady=6)
            self.entries[row] = entry
        return self.entries[0]

    def validate(self):
        try:
            self.result = (Profile(self.entries[0].get(), self.entries[1].get()), self.entries[2].get())
        except CatalogError as error:
            messagebox.showerror("配置有误", str(error), parent=self)
            return False
        return True


class CourseDialog(simpledialog.Dialog):
    def __init__(self, parent, initial, count):
        self.initial, self.count = initial, count
        super().__init__(parent, "修改课程分类")

    def body(self, master):
        ttk.Label(master, text=f"为所选 {self.count} 份资料选择或输入课程名。留空转待确认。").pack(anchor="w", pady=6)
        self.course = ttk.Combobox(master, values=SUBJECT_NAMES, width=30)
        self.course.set(self.initial)
        self.course.pack(fill="x")
        return self.course

    def apply(self):
        self.result = self.course.get().strip()


class ReviewView:
    def __init__(self, frame, catalog, run, show_tab):
        self.frame, self.catalog, self.run, self.show_tab = frame, catalog, run, show_tab
        self.library = catalog.library
        self.service = AnalysisService(self.library)
        self.store = ProposalStore(self.library)
        self.proposal = None
        self.rows = {}
        discovery = ttk.Frame(frame)
        discovery.pack(fill="x", pady=(0, 6))
        self.discovery_button = ttk.Button(discovery, text="选择文件夹并按课程分类", command=self.discover)
        self.discovery_button.pack(side="left")
        ttk.Button(discovery, text="修改课程分类", command=self.change_group).pack(side="left", padx=6)
        bar = ttk.Frame(frame)
        bar.pack(fill="x")
        for title, action in (
            ("云端配置", self.configure), ("测试连接", self.ping), ("文件库选中项 · 分析", self.analyze),
            ("历史方案", self.open_existing), ("手动调整", self.manual), ("文字修订", self.revise),
        ):
            ttk.Button(bar, text=title, command=action).pack(side="left", padx=(0, 6))
        row = ttk.Frame(frame)
        row.pack(fill="x", pady=8)
        ttk.Label(row, text="云端分析课程清单（可选，逗号分隔）").pack(side="left")
        self.courses = tk.StringVar(frame)
        ttk.Entry(row, textvariable=self.courses).pack(side="left", fill="x", expand=True, padx=6)

        tree_frame = ttk.Frame(frame)
        tree_frame.pack(fill="both", expand=True)
        self.tree = ttk.Treeview(tree_frame, columns=("review", "coverage"), height=10)
        self.tree.heading("#0", text="课程 / 用途 / 文件")
        self.tree.heading("review", text="审核状态")
        self.tree.heading("coverage", text="分析覆盖")
        self.tree.column("review", width=115)
        self.tree.column("coverage", width=150)
        y = ttk.Scrollbar(tree_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=y.set)
        y.pack(side="right", fill="y")
        self.tree.pack(fill="both", expand=True)
        self.tree.bind("<<TreeviewSelect>>", self.show_selection)
        self.preview = tk.Text(frame, height=8, wrap="word", state="disabled")
        self.preview.pack(fill="x", pady=(6, 0))

        bar = ttk.Frame(frame)
        bar.pack(fill="x", pady=6)
        self.flags = {}
        self.aspect_controls = {}
        for key, label in (("classification", "主分类"), ("tags", "标签"), ("name", "拟用名称")):
            value = tk.BooleanVar(frame, value=key == "classification")
            self.flags[key] = value
            self.aspect_controls[key] = ttk.Checkbutton(bar, text=label, variable=value)
            self.aspect_controls[key].pack(side="left", padx=(0, 8))
        self.accept_button = ttk.Button(bar, text="接受选中项", command=self.apply)
        self.accept_button.pack(side="left")
        self.status = tk.StringVar(frame, "选择文件夹，按内置的常见课程自动分类。")
        ttk.Label(frame, textvariable=self.status, wraplength=740).pack(anchor="w")

    def get_profile(self):
        profile = Profile.load(self.library)
        if profile is None:
            raise CatalogError("请先填写云端配置。")
        return profile

    def display_error(self, error):
        messagebox.showerror("分析与审核", str(error), parent=self.frame)

    def configure(self):
        dialog = ProfileDialog(self.frame, Profile.load(self.library))
        if dialog.result:
            profile, key = dialog.result
            library = self.library
            self.run("保存云端配置", lambda *_: (profile.save(library, key) or True),
                     lambda _: self.status.set("配置已保存。可以测试连接。"))

    def ping(self):
        try:
            profile = self.get_profile()
        except CatalogError as error:
            self.display_error(error)
            return
        self.run("测试云端连接", lambda *_: request_json(profile, profile.key(), "ping", {}),
                 lambda _: self.status.set("服务已返回可解析的响应。未发送文档。"))

    def discover(self):
        folder = filedialog.askdirectory(parent=self.frame, mustexist=True, title="选择待分类的文件夹")
        if not folder:
            return
        recursive = self.catalog.recursive.get()
        exclusions = tuple(value.strip() for value in self.catalog.exclusions.get().split(";") if value.strip())
        scope = "包含子目录" if recursive else "仅处理当前目录"
        excluded = "、".join(exclusions) or "无额外排除项"
        if not messagebox.askyesno(
            "确认本地课程分类",
            f"{folder}\n新来源：{scope}，排除项：{excluded}。已导入来源沿用原范围。"
            "\n同意读取并加入本地资料库？课程分类在本机运行，确认分类只会更新资料库。",
            parent=self.frame,
        ):
            return
        library, store = self.library, self.store

        def work(stop, progress):
            proposal = draft_folder(library, store, Path(folder), stop, progress, build_subject_proposal,
                                    recursive=recursive, exclusions=exclusions)
            return proposal, library.documents()

        def complete(result):
            proposal, documents = result
            self.catalog.render(documents)
            if proposal is not None:
                for name, flag in self.flags.items():
                    flag.set(name == "classification")
                self.render(proposal)

        self.run("按课程分类", work, complete)

    def change_group(self):
        rows = self.selected_rows()
        if not rows:
            self.status.set("请选择需要修改分类的文件或课程。")
            return
        group = CourseDialog(self.frame, rows[0].course, len(rows)).result
        if group is None:
            return
        try:
            diff = self.store.preview(self.proposal, [{"id": row.id, "course": group} for row in rows])
        except CatalogError as error:
            self.display_error(error)
            return
        self.present_diff(diff)

    def analyze(self):
        try:
            service, store = self.service, self.store
            profile = self.get_profile()
            courses = self.courses.get().replace("，", ",").split(",")
            preview = service.prepare((doc.id for doc in self.catalog.selected()), courses, profile)
        except CatalogError as error:
            self.display_error(error)
            return
        lines = []
        for doc in preview.documents:
            count = sum(len(f.text) for chunk in doc.chunks for f in chunk)
            headings = [f.locator for chunk in doc.chunks for f in chunk]
            subset = f"{headings[0]} 至 {headings[-1]}" if headings else "无可发送文字"
            lines.append(f"{doc.record.path.name} · {subset} · {count} 字符 · {len(doc.chunks)} 组")
        prompt = (f"发送至 {profile.base_url}\n模型 {profile.model}\n\n" + "\n".join(lines)
                  + "\n\n仅发送以上可提取的正文、所填课程清单，以及由本次分析所得的摘要和引用。")
        if not messagebox.askyesno("确认发送范围", prompt, parent=self.frame):
            return
        consent = service.approve(preview)

        def work(stop, progress):
            proposal = service.run(preview, consent, profile.key(), stop, progress)
            if proposal.rows:
                store.create(proposal)
            return proposal

        self.run("分析并归纳课程资料", work, self.render)

    def open_existing(self):
        proposals = self.store.recent()
        chosen = self.catalog.pick("选择审核方案", proposals,
                                   lambda p: f"{p.id[:8]} · 第 {p.revision} 版 · {len(p.rows)} 份")
        if chosen:
            self.render(chosen)

    def render(self, proposal):
        self.proposal = proposal
        self.rows = {}
        self.tree.delete(*self.tree.get_children())
        for key in ("tags", "name"):
            control = self.aspect_controls[key]
            if proposal.mode == "subject":
                self.flags[key].set(False)
                control.pack_forget()
            elif not control.winfo_manager():
                control.pack(side="left", padx=(0, 8), before=self.accept_button)
        self.tree.heading("#0", text="课程 / 用途 / 文件" if any(row.purpose for row in proposal.rows) else "课程 / 文件")
        groups = {}
        for row in proposal.rows:
            try:
                doc = self.library.get(row.id)
            except CatalogError:
                continue
            group_name = "待确认" if row.review else row.course or "待确认"
            group_key = (group_name,)
            if group_key not in groups:
                groups[group_key] = self.tree.insert("", "end", text=group_name, open=True)
            parent = groups[group_key]
            if row.purpose:
                subgroup = (group_name, row.purpose)
                if subgroup not in groups:
                    groups[subgroup] = self.tree.insert(parent, "end", text=row.purpose, open=True)
                parent = groups[subgroup]
            label = "待核对" if row.review else "可审核"
            if doc.digest != row.digest:
                label = "资料已变化"
            coverage = {"COMPLETE": "完整", "PARTIAL": "部分", "FAILED": "失败", "STALE": "过时"}.get(row.coverage)
            self.tree.insert(parent, "end", iid=row.id, text=doc.path.name,
                             values=(label, f"{coverage} · {row.covered}/{row.total}"))
            self.rows[row.id] = row
        self.status.set(f"第 {proposal.revision} 版 · {proposal.rationale}")
        self.set_preview("")
        self.show_tab()

    def set_preview(self, text):
        self.preview.configure(state="normal")
        self.preview.delete("1.0", "end")
        self.preview.insert("1.0", text)
        self.preview.configure(state="disabled")

    def selected_rows(self):
        ids = set()

        def collect(item):
            if item in self.rows:
                ids.add(item)
            else:
                for child in self.tree.get_children(item):
                    collect(child)

        for key in self.tree.selection():
            collect(key)
        return [row for row in self.proposal.rows if row.id in ids] if self.proposal else []

    def show_selection(self, _event=None):
        rows = self.selected_rows()
        if not rows:
            return
        row = rows[0]
        try:
            doc = self.library.get(row.id)
        except CatalogError:
            self.set_preview("该资料已从文件库移除。")
            return
        if doc.digest != row.digest:
            self.set_preview("原文已变化。请重新分析以核对证据。")
            return
        lines = [f"候选课程：{row.course or '待确认'}"]
        lines.extend(f"{title}：{value}" for title, value in (
            ("用途", row.purpose), ("主题", row.topic), ("摘要", row.summary),
            ("标签", "、".join(row.tags)), ("拟用名称", row.name),
        ) if value)
        if row.detail:
            lines.append(row.detail)
        lines.extend(f"原文依据 · {e.locator}：{e.quote}" for e in row.evidence)
        self.set_preview("\n".join(lines))

    def manual(self):
        if self.proposal and self.proposal.mode == "subject":
            self.change_group()
            return
        rows = self.selected_rows()
        if not rows:
            return
        row = rows[0]
        value = simpledialog.askstring(
            "编辑草案", f"为 {len(rows)} 个选中项输入：课程；用途；逗号分隔标签；拟用名称",
            initialvalue=f"{row.course}；{row.purpose}；{','.join(row.tags)}；{row.name}",
            parent=self.frame,
        )
        if value is None:
            return
        fields = value.replace("；", ";").split(";")
        if len(fields) != 4:
            messagebox.showerror("格式错误", "请填四个分号分隔的字段。", parent=self.frame)
            return
        course, purpose, tags, name = fields
        try:
            diff = self.store.preview(self.proposal, [
                {"id": row.id, "course": course, "purpose": purpose, "tags": tags.replace("，", ",").split(","), "name": name}
                for row in rows
            ])
        except CatalogError as error:
            self.display_error(error)
            return
        self.present_diff(diff)

    def revise(self):
        if not self.proposal:
            return
        if self.proposal.mode == "subject":
            self.status.set("请选择资料或整门课，再点击“修改课程分类”。")
            return
        value = simpledialog.askstring("文字修订", "只描述对当前分类方案的修改。", parent=self.frame)
        if not value:
            return
        try:
            profile = self.get_profile()
        except CatalogError as error:
            self.display_error(error)
            return
        if len(value) > 1500:
            self.display_error(CatalogError("修订请求超过 1500 字符。"))
            return
        prepared = RevisionInput(self.proposal, profile, value)
        consent_text = (f"发送至 {profile.base_url} · {profile.model}\n草案第 {self.proposal.revision} 版"
                        f"的 {len(self.proposal.rows)} 项分类、标签和拟用名称，以及下列要求。\n\n"
                        f"{value}\n\n本次不发送原文。")
        if not messagebox.askyesno("确认发送修订要求", consent_text, parent=self.frame):
            return
        service, store = self.service, self.store
        token = service.approve(prepared)
        self.run("生成修订差异", lambda stop, _: store.text_preview(prepared, token, service, profile.key(), stop),
                 self.present_diff)

    def present_diff(self, diff):
        if not messagebox.askyesno("应用草案差异", "\n".join(diff.lines), parent=self.frame):
            return
        store = self.store
        self.run("保存草案新版本", lambda *_: store.confirm(diff), self.render)

    def apply(self):
        rows = self.selected_rows()
        aspects = {name for name, flag in self.flags.items() if flag.get()}
        if not rows or not aspects:
            self.status.set("请选择资料及要接受的项目。")
            return
        label = "、".join(title for key, title in (("classification", "主分类"), ("tags", "标签"), ("name", "拟用名称"))
                        if key in aspects)
        if not messagebox.askyesno("确认保存", f"将所选 {len(rows)} 项的{label}写入资料库？原文件保留。", parent=self.frame):
            return
        store, proposal = self.store, self.proposal
        ids = {row.id for row in rows}
        library = self.library

        def work(*_):
            store.apply(proposal, ids, aspects)
            return library.documents()

        def complete(documents):
            self.catalog.render(documents)
            self.status.set(f"已保存 {len(rows)} 项的{label}。")

        self.run("确认分类结果", work, complete)
