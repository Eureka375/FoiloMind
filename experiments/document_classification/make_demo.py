"""Generate isolated synthetic documents, never use real user files as fixtures."""
import argparse
from pathlib import Path
import json
import pymupdf
from docx import Document


def generate(root):
    root.mkdir(parents=True, exist_ok=False)
    topics = {
        'network': ('TCP network routing congestion packet router', '网络 路由 拥塞控制 数据包 TCP'),
        'database': ('Database SQL index transaction query relational', '数据库 索引 事务 查询 关系表 SQL'),
        'biology': ('Biology cell gene protein evolution organism', '生物 细胞 基因 蛋白质 遗传 进化'),
    }
    expected = {}
    for name, (english, chinese) in topics.items():
        for ext in ('txt', 'md', 'docx', 'pdf'):
            path = root / f'{name}.{ext}'
            text = (english + '\n' + chinese + '\n') * 30
            if ext in ('txt', 'md'):
                path.write_text(text, encoding='utf-8')
            elif ext == 'docx':
                doc = Document()
                doc.add_paragraph(text)
                doc.add_table(rows=1, cols=1).cell(0, 0).text = chinese
                doc.save(path)
            else:
                with pymupdf.open() as pdf:
                    page = pdf.new_page()
                    page.insert_textbox((40, 40, 550, 800), (english + '\n') * 20)
                    pdf.save(path)
            expected[path.name] = name
    # Raster-only PDF and damaged input exercise explicit incomplete statuses.
    with pymupdf.open() as text_pdf:
        page = text_pdf.new_page()
        page.insert_text((50, 70), 'Database SQL transaction index', fontsize=20)
        pix = page.get_pixmap()
        with pymupdf.open() as scanned:
            scanned.new_page().insert_image(page.rect, pixmap=pix)
            scanned.save(root / 'scan.pdf')
    (root / 'broken.pdf').write_bytes(b'not a PDF')
    (root / 'empty.txt').write_text('', encoding='utf-8')
    return expected


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('destination')
    args = parser.parse_args()
    print(json.dumps(generate(Path(args.destination)), ensure_ascii=False, indent=2))
