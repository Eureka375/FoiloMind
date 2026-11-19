"""Tk view for explicit import, extracted evidence, and local management."""

import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk
from pathlib import Path

from .library import CatalogError, Source


STATUS = {
    "EXTRACTED": "已提取", "PARTIAL": "部分可提取", "EMPTY": "无文字",
    "FAILED": "读取失败", "UNSUPPORTED": "格式不支持", "STALE": "待刷新", "MISSING": "路径失效",
}


class CatalogView:
    def __init__(self, frame, library, run):
        self.frame, self.library, self.run = frame, library, run
        toolbar = ttk.Frame(frame)
        toolbar.pack(fill="x")
        self.recursive = tk.BooleanVar(frame, value=True)
        for text, action in (("添加文件夹", self.add_folder), ("添加文件", self.add_files),
                             ("刷新", self.refresh), ("来源管理", self.manage_sources),
                             ("编辑分类", self.edit), ("忽略", self.ignore), ("恢复忽略项", self.restore)):
            ttk.Button(toolbar, text=text, command=action).pack(side="left", padx=(0, 5))
        ttk.Checkbutton(toolbar, text="包含子目录", variable=self.recursive).pack(side="left")
        ttk.Label(frame, text="相对排除路径（分号分隔，添加文件夹时应用）").pack(anchor="w", pady=(6, 0))
        self.exclusions = tk.StringVar(frame)
        ttk.Entry(frame, textvariable=self.exclusions).pack(fill="x")

        search = ttk.Frame(frame)
        search.pack(fill="x", pady=8)
        self.query, self.course, self.tag, self.ext = (tk.StringVar(frame) for _ in range(4))
        self.purpose = ""
        self.unclassified = False
        for label, value, width in (("关键词", self.query, 20), ("课程", self.course, 12), ("标签", self.tag, 10),
                                    ("格式", self.ext, 6)):
            ttk.Label(search, text=label).pack(side="left", padx=(0, 4))
            field = ttk.Entry(search, textvariable=value, width=width)
            field.pack(side="left", padx=(0, 7))
            field.bind("<Return>", lambda _: self.search())
        ttk.Button(search, text="搜索", command=self.search).pack(side="left")
        ttk.Button(search, text="清除筛选", command=self.clear_search).pack(side="left", padx=5)

        panes = ttk.Panedwindow(frame, orient="vertical")
        panes.pack(fill="both", expand=True)
        grid, preview = ttk.Frame(panes), ttk.Frame(panes)
        panes.add(grid, weight=2)
        panes.add(preview, weight=1)
        self.navigation = ttk.Treeview(grid, show="tree", height=8, selectmode="browse")
        self.navigation.column("#0", width=168, stretch=False)
        self.navigation.pack(side="left", fill="y", padx=(0, 8))
        self.navigation.bind("<<TreeviewSelect>>", self.select_category)
        file_table = ttk.Frame(grid)
        file_table.pack(side="left", fill="both", expand=True)
        self.tree = ttk.Treeview(file_table, columns=("filename", "course", "purpose", "status"),
                                 show="headings", height=8)
        for key, name, width in (("filename", "文件", 270), ("course", "课程", 115),
                                 ("purpose", "用途", 95), ("status", "提取状态", 95)):
            self.tree.heading(key, text=name)
            self.tree.column(key, width=width)
        y = ttk.Scrollbar(file_table, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=y.set)
        y.pack(side="right", fill="y")
        self.tree.pack(fill="both", expand=True)
        self.tree.bind("<<TreeviewSelect>>", self.show_document)
        self.preview = tk.Text(preview, height=8, wrap="word", state="disabled")
        scroller = ttk.Scrollbar(preview, orient="vertical", command=self.preview.yview)
        self.preview.configure(yscrollcommand=scroller.set)
        scroller.pack(side="right", fill="y")
        self.preview.pack(fill="both", expand=True)
        self.status = tk.StringVar(frame, value="选择要管理的资料。")
        ttk.Label(frame, textvariable=self.status, wraplength=750).pack(anchor="w", pady=(6, 0))
        self.rows = {}
        self.hits = {}
        self.categories = {}
        self.bind_drop()
        self.render(library.documents())

    def bind_drop(self):
        if not hasattr(self.frame.tk, "call") or not hasattr(self.frame, "drop_target_register"):
            return
        try:
            self.tree.drop_target_register("DND_Files")
            self.tree.dnd_bind("<<Drop>>", lambda event: self.add_paths(self.frame.tk.splitlist(event.data)))
        except tk.TclError:
            return

    def add_folder(self):
        path = filedialog.askdirectory(parent=self.frame)
        if path:
            self.add_paths((path,))

    def add_files(self):
        paths = filedialog.askopenfilenames(parent=self.frame)
        if paths:
            self.add_paths(paths)

    def add_paths(self, paths):
        recursive = self.recursive.get()
        exclusions = tuple(filter(str.strip, self.exclusions.get().split(";")))

        def work(stop, progress):
            try:
                sources = [
                    Source.directory(Path(path), recursive=recursive, exclusions=exclusions)
                    if Path(path).is_dir() else Source.file(Path(path))
                    for path in paths
                ]
            except OSError as error:
                raise CatalogError("无法验证所选文件或目录。") from error
            for source in sources:
                if stop.is_set():
                    break
                self.library.set_source(source)
            return self.library.refresh(stop, progress)

        self.run("导入资料", work, self.render)

    def refresh(self):
        self.run("刷新资料", self.library.refresh, self.render)

    def search(self):
        search, course, tag, ext = (self.query.get().strip(), self.course.get().strip(),
                                     self.tag.get().strip(), self.ext.get().strip().lower())
        library, purpose, unclassified = self.library, self.purpose, self.unclassified

        def work(_stop, _progress):
            suffix = "." + ext.lstrip(".") if ext else ""
            hits = library.search(search, course=course, purpose=purpose, tag=tag,
                                  extension=suffix, unclassified=unclassified)
            return [(library.get(hit.document_id), hit.evidence) for hit in hits]

        self.run("查找资料", work, self.render_hits)

    def render_hits(self, pairs):
        self.render([record for record, _ in pairs], {record.id: evidence for record, evidence in pairs}, False)

    def clear_search(self):
        for var in (self.query, self.course, self.tag, self.ext):
            var.set("")
        self.purpose, self.unclassified = "", False
        library = self.library
        self.run("加载资料", lambda *_: library.documents(), self.render)

    def render(self, documents, hits=None, rebuild=True):
        if rebuild:
            self.render_categories(documents)
        self.rows = {doc.id: doc for doc in documents}
        self.hits = hits or {}
        self.tree.delete(*self.tree.get_children())
        for doc in documents:
            self.tree.insert("", "end", iid=doc.id,
                             values=(doc.path.name, doc.course or "待分类", doc.purpose, STATUS.get(doc.status, doc.status)))
        self.status.set(f"{len(documents)} 份资料。选择一项可查看原文与定位。")
        self.set_preview("")

    def render_categories(self, documents):
        self.navigation.delete(*self.navigation.get_children())
        self.categories = {
            self.navigation.insert("", "end", text="全部资料"): ("", "", False),
            self.navigation.insert("", "end", text="待分类"): ("", "", True),
        }
        parents = {}
        for course, purpose in sorted({(doc.course, doc.purpose) for doc in documents if doc.course}):
            if course not in parents:
                parents[course] = self.navigation.insert("", "end", text=course, open=True)
                self.categories[parents[course]] = (course, "", False)
            if purpose:
                key = self.navigation.insert(parents[course], "end", text=purpose)
                self.categories[key] = (course, purpose, False)

    def select_category(self, _=None):
        selected = self.navigation.selection()
        if not selected or selected[0] not in self.categories:
            return
        course, self.purpose, self.unclassified = self.categories[selected[0]]
        self.course.set(course)
        self.search()

    def set_preview(self, text):
        self.preview.configure(state="normal")
        self.preview.delete("1.0", "end")
        self.preview.insert("1.0", text)
        self.preview.configure(state="disabled")

    def selected(self):
        return [self.rows[key] for key in self.tree.selection() if key in self.rows]

    def show_document(self, _event=None):
        chosen = self.selected()
        if not chosen:
            return
        doc = chosen[0]
        header = [str(doc.path), doc.detail, "标签：" + "、".join(doc.tags)]
        if doc.proposed_name:
            header.append("拟用名称：" + doc.proposed_name)
        hit = self.hits.get(doc.id)
        if hit:
            header.append(f"命中 · {hit.label}\n{hit.text}")
        parts = [f"{s.label} · {s.text}" for s in doc.segments]
        self.set_preview("\n\n".join([*header, "\n".join(parts)]))

    def edit(self):
        selected = self.selected()
        if not selected:
            return
        doc = selected[0]
        result = simpledialog.askstring(
            "编辑分类", "输入课程；用途；逗号分隔标签；拟用名称（可留空）",
            initialvalue=f"{doc.course}；{doc.purpose}；{','.join(doc.tags)}；{doc.proposed_name}", parent=self.frame,
        )
        if result is None:
            return
        fields = result.replace("；", ";").split(";")
        if len(fields) != 4 or any(len(field) > 240 for field in fields):
            messagebox.showerror("格式错误", "请填写四个分号分隔的字段。", parent=self.frame)
            return
        course, purpose, tags, name = map(str.strip, fields)

        def work(*_):
            self.library.classify(doc.id, doc.digest, course, purpose,
                                  [t.strip() for t in tags.replace("，", ",").split(",") if t.strip()], name)
            return self.library.documents()

        self.run("保存分类", work, self.render)

    def ignore(self):
        ids = tuple(doc.id for doc in self.selected())
        if not ids or not messagebox.askyesno("忽略资料", "从资料库隐藏所选项？磁盘文件保留。", parent=self.frame):
            return

        def work(*_):
            for doc_id in ids:
                self.library.ignore(doc_id)
            return self.library.documents()

        self.run("忽略资料", work, self.render)

    def restore(self):
        docs = self.library.documents(ignored=True)
        doc = self.pick("恢复忽略项", docs, lambda item: str(item.path))
        if doc:
            def work(stop, progress):
                self.library.restore(doc.id)
                return self.library.refresh(stop, progress)
            self.run("恢复资料", work, self.render)

    def manage_sources(self):
        selected = self.pick("选择要移除的授权来源", self.library.sources(), lambda source: str(source.path))
        if selected and messagebox.askyesno("移除来源", "移除此来源、已提取正文和相关分析历史？磁盘文件保留。", parent=self.frame):
            def work(*_):
                self.library.revoke(selected.path)
                return self.library.documents()
            self.run("移除来源", work, self.render)

    def pick(self, title, items, label):
        if not items:
            self.status.set("没有可选择的项目。")
            return None
        prompt = "\n".join(f"{i}. {label(item)}" for i, item in enumerate(items, 1))
        number = simpledialog.askinteger(title, prompt, minvalue=1, maxvalue=len(items), parent=self.frame)
        return items[number - 1] if number is not None else None
