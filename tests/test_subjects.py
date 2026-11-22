import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event

from foliomind.discovery import draft_folder
from foliomind.library import CatalogError, Library
from foliomind.proposals import ProposalStore
from foliomind.subjects import build_subject_proposal


class SubjectTests(unittest.TestCase):
    def setUp(self):
        root = Path(self.enterContext(TemporaryDirectory()))
        self.folder = root / "mixed"
        self.folder.mkdir()
        self.library = Library(root / "catalog.sqlite3")
        self.store = ProposalStore(self.library)

    def classify(self):
        return draft_folder(self.library, self.store, self.folder, Event(), lambda *_: None,
                            build_subject_proposal)

    def test_uses_course_names_and_rejects_out_of_scope_or_ambiguous_documents(self):
        documents = {
            "01.txt": ("VLAN 隔离广播域，交换机收到报文后检查编号。", "计算机网络"),
            "02.txt": ("NAT 设备按转换表修改公网地址，记录数据报文走向。", "计算机网络"),
            "03.txt": ("查询执行计划对比，组合索引减少回表次数。", "数据库"),
            "04.txt": ("Spring Bean 通过代理处理事务注解，Controller 调用服务入口。", "Java 后端"),
            "05.txt": ("泰勒展开用于近似函数，定积分可求曲线围成的面积。", "高等数学"),
            "计算机网络.doc.txt": ("文艺复兴时期的雕塑强调人体比例和古典形式。", ""),
            "07.txt": ("TCP 连接的报文发生重传。数据库用执行计划检查 SQL 查询。", ""),
        }
        for name, (body, _) in documents.items():
            (self.folder / name).write_text(body, encoding="utf-8")
        proposal = self.classify()
        self.assertEqual(proposal.mode, "subject")
        self.assertEqual(self.store.get(proposal.id), proposal)
        results = {self.library.get(row.id).path.name: row for row in proposal.rows}
        self.assertEqual(set(results), set(documents))
        for name, (body, course) in documents.items():
            row = results[name]
            self.assertEqual(row.course, course, row.detail)
            self.assertEqual(row.review, not bool(course))
            self.assertEqual(row.purpose, "")
            if course:
                self.assertIn(row.evidence[0].quote, body)
        self.assertIn("同时匹配", results["07.txt"].detail)

    def test_confirmation_only_writes_course_and_preserves_prior_metadata(self):
        path = self.folder / "test.txt"
        body = "数据库事务用隔离级别控制行锁，避免死锁。"
        path.write_text(body, encoding="utf-8")
        row = self.classify().rows[0]
        self.library.classify(row.id, row.digest, "原归属", "讲义", ["复习"], "事务讲义")
        proposal = self.classify()
        with self.assertRaisesRegex(CatalogError, "只保存课程归属"):
            self.store.apply(proposal, {row.id}, {"classification", "tags"})
        self.store.apply(proposal, {row.id}, {"classification"})
        record = self.library.get(row.id)
        self.assertEqual((record.course, record.purpose, record.tags, record.proposed_name),
                         ("数据库", "讲义", ("复习",), "事务讲义"))
        self.assertEqual(path.read_text(encoding="utf-8"), body)
