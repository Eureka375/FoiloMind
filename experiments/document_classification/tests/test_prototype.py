import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE))
import classify as app


class PrototypeTests(unittest.TestCase):
    def test_sampling_covers_ends_and_expands_for_diverse_content(self):
        self.assertEqual(app.sample_indices(100, 3), [0, 50, 99])
        same = ['数据库索引事务 SQL' * 8] * 30
        varied = [chr(0x4e00+i) * 50 for i in range(30)]
        self.assertLess(len(app.adaptive_sample(same, 3, 9)),
                        len(app.adaptive_sample(varied, 3, 9)))
        self.assertIn(99, app.adaptive_sample([chr(0x4e00+i)*50 for i in range(100)], 3, 4))

    def test_four_formats_and_read_only_cli(self):
        import pymupdf
        from docx import Document
        with tempfile.TemporaryDirectory(dir=BASE) as tmp:
            root = Path(tmp) / 'input'
            root.mkdir()
            (root / 'network.txt').write_text('TCP 网络 拥塞控制 路由器 ' * 50, encoding='utf-8')
            (root / 'network.md').write_text('# 网络\nTCP 网络 拥塞控制 路由器 ' * 50, encoding='utf-8')
            doc = Document()
            doc.add_paragraph('数据库 SQL 索引 事务 ' * 50)
            doc.add_table(rows=1, cols=1).cell(0, 0).text = 'table evidence'
            doc.save(root / 'database.docx')
            pdf = pymupdf.open()
            page = pdf.new_page()
            page.insert_text((50, 60), 'Database SQL index transaction')
            pdf.save(root / 'database.pdf')
            pdf.close()
            (root / 'broken.pdf').write_bytes(b'broken')
            (root / 'empty.txt').write_text('', encoding='utf-8')
            (root / 'bad.txt').write_bytes(b'\xff\xff\xff')
            (root / 'old.doc').write_bytes(b'unsupported')
            before = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in root.iterdir()}
            result = subprocess.run([sys.executable, str(BASE / 'classify.py'), str(root),
                                     '--output', str(Path(tmp) / 'report'), '--clusters', '2'],
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            report = json.loads((Path(tmp) / 'report/report.json').read_text(encoding='utf-8'))
            self.assertEqual(len(report['documents']), 8)
            self.assertEqual(len(report['methods']['tfidf']['assignments']), 4)
            self.assertEqual(before, {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in root.iterdir()})
            self.assertGreater(report['metrics']['peak_rss_mb'], 0)
            self.assertIn('table evidence', app.extract(root / 'database.docx')['text'])

    def test_output_inside_source_or_existing_is_rejected(self):
        with tempfile.TemporaryDirectory(dir=BASE) as tmp:
            root = Path(tmp)
            with self.assertRaises(ValueError):
                app.validate_paths(root, root / 'output')
            with self.assertRaises(ValueError):
                app.validate_paths(root, root)

    def test_scan_skips_links_and_excluded_directories(self):
        with tempfile.TemporaryDirectory(dir=BASE) as tmp:
            root = Path(tmp)
            (root / 'keep.txt').write_text('keep')
            (root / 'private').mkdir()
            (root / 'private' / 'secret.txt').write_text('secret')
            rows = list(app.scan(root, ['private']))
            self.assertEqual([p.name for p in rows], ['keep.txt'])
            self.assertEqual([p.name for p in app.scan(root, ['./private'])], ['keep.txt'])

    def test_embedding_windows_preserve_content_without_token_truncation(self):
        text = '甲乙丙丁' * 100
        chunks = app.embedding_chunks(text, lambda value: len(value)*3, 126)
        self.assertEqual(''.join(chunks), text)
        self.assertTrue(all(len(c)*3 <= 126 for c in chunks))

    def test_empty_single_and_identical_corpora(self):
        self.assertEqual(app.cluster_tfidf([], 2)['assignments'], [])
        self.assertEqual(app.cluster_tfidf(['数据库'], 2)['assignments'], [0])
        self.assertEqual(app.cluster_tfidf(['same', 'same'], 2)['assignments'], [0, 0])

    @unittest.skipUnless((BASE / 'tessdata/eng.traineddata').exists(), 'local OCR data not prepared')
    def test_real_ocr_scanned_pdf_and_text_layer_skip(self):
        import pymupdf
        with tempfile.TemporaryDirectory(dir=BASE) as tmp:
            path = Path(tmp) / 'scan.pdf'
            with pymupdf.open() as doc:
                page = doc.new_page()
                page.insert_text((50, 70), 'Database SQL transaction index', fontsize=20)
                pix = page.get_pixmap()
                with pymupdf.open() as scan:
                    scan.new_page().insert_image(page.rect, pixmap=pix)
                    scan.save(path)
                doc.save(Path(tmp) / 'text.pdf')
            self.assertEqual(app.extract(path)['status'], 'no_text')
            row = app.extract(path, ocr='auto', language='eng', tessdata=str(BASE / 'tessdata'))
            self.assertEqual(row['status'], 'ok', row)
            self.assertIn('Database', row['text'])
            self.assertEqual(row['ocr_units'], [1])
            text = app.extract(Path(tmp) / 'text.pdf', ocr='auto', language='eng', tessdata=str(BASE / 'tessdata'))
            self.assertEqual(text['ocr_units'], [])


if __name__ == '__main__':
    unittest.main()
