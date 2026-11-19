"""Tk controls for batch consent, evidence review and revision."""

import tkinter as tk
from tkinter import messagebox, simpledialog, ttk

from .analysis import AnalysisService, Profile, request_json
from .library import CatalogError
from .proposals import ProposalStore, RevisionInput


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


class ReviewView:
    def __init__(self, frame, catalog, run, show_tab):
        self.frame, self.catalog, self.run, self.show_tab = frame, catalog, run, show_tab
        self.library = catalog.library
        self.service = AnalysisService(self.library)
        self.store = ProposalStore(self.library)
        self.proposal = None
        self.rows = {}
        bar = ttk.Frame(frame)
        bar.pack(fill="x")
        for title, action in (
            ("云端配置", self.configure), ("测试连接", self.ping), ("文件库选中项 · 分析", self.analyze),
            ("历史方案", self.open_existing), ("手动调整", self.manual), ("文字修订", self.revise),
        ):
            ttk.Button(bar, text=title, command=action).pack(side="left", padx=(0, 6))
        row = ttk.Frame(frame)
        row.pack(fill="x", pady=8)
        ttk.Label(row, text="可选课程清单（逗号分隔）").pack(side="left")
        self.courses = tk.StringVar(frame)
        ttk.Entry(row, textvariable=self.courses).pack(side="left", fill="x", expand=True, padx=6)
        ttk.Label(row, text="空白时允许提出候选课程").pack(side="left")

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
        for key, label in (("classification", "主分类"), ("tags", "标签"), ("name", "拟用名称")):
            value = tk.BooleanVar(frame, value=key == "classification")
            self.flags[key] = value
            ttk.Checkbutton(bar, text=label, variable=value).pack(side="left", padx=(0, 8))
        ttk.Button(bar, text="接受选中项", command=self.apply).pack(side="left")
        self.status = tk.StringVar(frame, "先从文件库选择资料，再启动分析。")
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
            purpose = row.purpose or "待定用途"
            subgroup = (group_name, purpose)
            if subgroup not in groups:
                groups[subgroup] = self.tree.insert(groups[group_key], "end", text=purpose, open=True)
            label = "待核对" if row.review else "可审核"
            if doc.digest != row.digest:
                label = "资料已变化"
            coverage = {"COMPLETE": "完整", "PARTIAL": "部分", "FAILED": "失败", "STALE": "过时"}.get(row.coverage)
            self.tree.insert(groups[subgroup], "end", iid=row.id, text=doc.path.name,
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
        lines = [f"候选课程：{row.course or '待确认'}", f"用途：{row.purpose or '待确认'}", f"主题：{row.topic}",
                 f"摘要：{row.summary}", f"标签：{'、'.join(row.tags)}", f"拟用名称：{row.name}"]
        if row.detail:
            lines.append(row.detail)
        lines.extend(f"原文依据 · {e.locator}：{e.quote}" for e in row.evidence)
        self.set_preview("\n".join(lines))

    def manual(self):
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
