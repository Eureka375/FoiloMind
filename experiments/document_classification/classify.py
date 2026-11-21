"""Offline, read-only batch classification spike. No client imports or database writes."""
from __future__ import annotations

import argparse
from collections import Counter
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import stat
import sys
import threading
import time
import zipfile

FORMATS = {'.pdf', '.docx', '.txt', '.md'}
SKIP_DIRS = {'.git', '.venv', '__pycache__', 'node_modules'}
MAX_BYTES = 32 * 1024 * 1024


def linked(path):
    s = path.lstat()
    return stat.S_ISLNK(s.st_mode) or bool(getattr(s, 'st_file_attributes', 0) & 0x400)


def validate_paths(source, output):
    # Inspect lexical ancestors before resolve() removes links / junctions.
    for path in (source.absolute(), output.absolute()):
        for ancestor in (path, *path.parents):
            if ancestor.exists() and linked(ancestor):
                raise ValueError(f'Linked/reparse path is not allowed: {ancestor}')
    source, output = source.resolve(), output.resolve()
    if not source.is_dir():
        raise ValueError('Source must be an existing directory')
    if output == source or source in output.parents:
        raise ValueError('Output must be outside source')
    if output.exists():
        raise ValueError('Output must be a new directory (no overwrite)')
    return source, output


def scan(root, excludes=()):
    """Prune links and exclusions before opening any document."""
    excludes = [os.path.normcase(os.path.normpath(x.replace('\\', '/'))).replace('\\', '/') for x in excludes]
    def excluded(p):
        rel = os.path.normcase(str(p.relative_to(root))).replace('\\', '/')
        return any(x == '.' or rel == x or rel.startswith(x + '/') for x in excludes)
    for base, dirs, files in os.walk(root, followlinks=False):
        dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS
                         and not excluded(Path(base) / d) and not linked(Path(base) / d))
        for name in sorted(files):
            path = Path(base) / name
            if not excluded(path) and not linked(path) and path.is_file():
                yield path


def sample_indices(total, count):
    if total <= 0:
        return []
    count = min(total, count)
    if count == 1:
        return [0]
    return sorted({int(i * (total - 1) / (count - 1) + .5) for i in range(count)})


def tokens(text):
    # Latin words and Chinese bigrams avoid a language-specific segmenter.
    words = re.findall(r'[a-zA-Z][a-zA-Z0-9_]+|[\u4e00-\u9fff]+', text.lower())
    return [piece for word in words for piece in
            ([word[i:i+2] for i in range(len(word)-1)] if re.fullmatch(r'[\u4e00-\u9fff]+', word)
             and len(word) > 1 else [word])]


def diverse(texts):
    sets = [set(tokens(t)) for t in texts]
    pairs = [(a, b) for i, a in enumerate(sets) for b in sets[i+1:]]
    return any(len(a & b) / max(1, len(a | b)) < .2 for a, b in pairs)


def adaptive_sample(units, initial=3, maximum=9):
    selected = sample_indices(len(units), initial)
    if diverse([units[i] for i in selected]) or any(len(units[i].strip()) < 24 for i in selected):
        selected = sample_indices(len(units), maximum)
    return selected


def extract(path, *, ocr='off', tessdata=None, language='chi_sim+eng', max_units=9):
    started = time.perf_counter()
    row = dict(path=str(path), status='error', text='', warnings=[], sampled_units=[],
               total_units=0, ocr_units=[], sha256=None)
    try:
        if path.suffix.lower() not in FORMATS:
            row['status'] = 'unsupported'
            return row
        if linked(path) or path.stat().st_size > MAX_BYTES:
            raise ValueError('Linked file or file over 32 MiB limit')
        before = path.stat()
        # Bounded read also prevents a file growing past the limit during read.
        with path.open('rb') as stream:
            data = stream.read(MAX_BYTES + 1)
        if len(data) > MAX_BYTES:
            raise ValueError('File grew beyond size limit')
        row['sha256'] = hashlib.sha256(data).hexdigest()
        suffix = path.suffix.lower()
        import io
        if suffix == '.pdf':
            import pymupdf
            with pymupdf.open(stream=data, filetype='pdf') as doc:
                if doc.needs_pass:
                    raise ValueError('Encrypted PDF requires a password; skipped')
                total = len(doc)
                chosen = sample_indices(total, min(3, max_units))
                pages = {i: doc[i].get_text() for i in chosen}
                if diverse(list(pages.values())) or any(len(t.strip()) < 24 for t in pages.values()):
                    chosen = sample_indices(total, max_units)
                    pages.update({i: doc[i].get_text() for i in chosen if i not in pages})
                for i in chosen:
                    if len(pages[i].strip()) < 24:
                        if ocr == 'auto':
                            if not tessdata:
                                row['warnings'].append(f'page {i+1}: OCR unavailable; provide --tessdata')
                            else:
                                try:
                                    page = doc[i]  # TextPage holds a weak reference to Page.
                                    data_dir = os.path.relpath(tessdata)
                                    tp = page.get_textpage_ocr(language=language, dpi=150,
                                                              full=True, tessdata=data_dir)
                                    pages[i] = page.get_text(textpage=tp)
                                    row['ocr_units'].append(i+1)
                                except Exception as exc:
                                    row['warnings'].append(f'page {i+1}: OCR failed ({type(exc).__name__}: {str(exc)[:120]})')
                        else:
                            row['warnings'].append(f'page {i+1}: little text; OCR off')
                units = [pages[i][:2000] for i in chosen]
        else:
            if suffix == '.docx':
                with zipfile.ZipFile(io.BytesIO(data)) as archive:
                    if sum(x.file_size for x in archive.infolist()) > 64 * 1024 * 1024:
                        raise ValueError('DOCX expanded size over 64 MiB')
                from docx import Document
                from docx.table import Table
                doc = Document(io.BytesIO(data))
                paragraphs = []
                for block in doc.iter_inner_content():
                    if isinstance(block, Table):
                        paragraphs.extend(' '.join(c.text for c in r.cells) for r in block.rows)
                    else:
                        paragraphs.append(block.text)
                text = '\n'.join(paragraphs)
            else:
                # Strict encodings only; no replacement characters as evidence.
                try:
                    text = data.decode('utf-8-sig')
                except UnicodeDecodeError:
                    text = data.decode('gb18030')
                    row['warnings'].append('decoded as GB18030; review encoding')
                if '\x00' in text:
                    raise ValueError('Binary/NUL content is not supported text')
            all_units = [text[i:i+1600] for i in range(0, len(text), 1600)]
            total = len(all_units)
            chosen = adaptive_sample(all_units, min(3, max_units), max_units)
            units = [all_units[i] for i in chosen]
        after = path.stat()
        if (before.st_size, before.st_mtime_ns, before.st_ino) != (after.st_size, after.st_mtime_ns, after.st_ino):
            raise ValueError('Source changed during extraction')
        row.update(text='\n'.join(units), total_units=total,
                   sampled_units=[i+1 for i in chosen], unit_kind='page' if suffix == '.pdf' else '1600-char block')
        row['status'] = 'ok' if row['text'].strip() else 'no_text'
        row['coverage'] = len(chosen) / total if total else 0
        if len(chosen) < total:
            row['warnings'].append('Partial sample: unseen units may contain other topics')
        if suffix == '.pdf':
            row['warnings'].append('PDF text layer may omit images or have reading-order errors')
    except Exception as exc:
        row.update(status='error', text='', error=f'{type(exc).__name__}: {str(exc)[:250]}')
    finally:
        row['seconds'] = round(time.perf_counter() - started, 6)
    return row


def vectorize(texts):
    from sklearn.feature_extraction.text import TfidfVectorizer
    v = TfidfVectorizer(analyzer=tokens, max_features=12000, sublinear_tf=True)
    return v.fit_transform(texts), v


def cluster_tfidf(texts, clusters):
    if not texts:
        return dict(assignments=[], keywords={})
    matrix, vectorizer = vectorize(texts)
    import numpy as np
    from sklearn.cluster import KMeans
    # Do not pretend identical documents form distinct meaningful groups.
    count = min(clusters, len(texts), len(set(texts)))
    from threadpoolctl import threadpool_limits
    with threadpool_limits(limits=4):
        labels = (np.zeros(len(texts), dtype=int) if count == 1 else
                  KMeans(n_clusters=count, random_state=42, n_init=10).fit_predict(matrix))
    terms = vectorizer.get_feature_names_out()
    keywords = {}
    for label in sorted(set(labels)):
        mean = np.asarray(matrix[labels == label].mean(axis=0)).ravel()
        keywords[str(label)] = terms[mean.argsort()[-6:][::-1]].tolist()
    return dict(assignments=labels.tolist(), keywords=keywords)


def embedding_chunks(text, token_count, budget):
    chunks, start = [], 0
    while start < len(text):
        end = min(start + 512, len(text))
        while token_count(text[start:end]) > budget:
            if end - start <= 1:
                raise ValueError('Model token budget cannot represent a single character')
            end = start + (end - start) // 2
        chunks.append(text[start:end])
        start = end
    return chunks


def cluster_embedding(texts, clusters, model_path):
    if not model_path or not Path(model_path).is_dir():
        raise ValueError('Embedding requires --model pointing to a local SentenceTransformer model')
    os.environ['HF_HUB_OFFLINE'] = '1'
    os.environ['TRANSFORMERS_OFFLINE'] = '1'
    from sentence_transformers import SentenceTransformer
    import numpy as np
    from sklearn.cluster import AgglomerativeClustering
    model = SentenceTransformer(str(Path(model_path).resolve()), device='cpu',
                                local_files_only=True, trust_remote_code=False)
    import torch
    torch.set_num_threads(4)
    if not texts:
        return dict(assignments=[], keywords={})
    budget = model.max_seq_length - model.tokenizer.num_special_tokens_to_add(pair=False)
    def token_count(value):
        return len(model.tokenizer.encode(value, add_special_tokens=False, truncation=False))
    pieces, owners = [], []
    for i, text in enumerate(texts):
        for chunk in embedding_chunks(text, token_count, budget):
            pieces.append(chunk)
            owners.append(i)
    encoded = model.encode(pieces, batch_size=32, normalize_embeddings=True, show_progress_bar=False)
    vectors = np.asarray([encoded[np.asarray(owners) == i].mean(axis=0) for i in range(len(texts))])
    vectors /= np.maximum(np.linalg.norm(vectors, axis=1, keepdims=True), 1e-12)
    count = min(clusters, len(texts), len(set(texts)))
    labels = (np.zeros(len(texts), dtype=int) if count <= 1 else
              AgglomerativeClustering(n_clusters=count, metric='cosine', linkage='average').fit_predict(vectors))
    keywords = {str(label): [t for t, _ in Counter(tokens('\n'.join(
        text for text, group in zip(texts, labels) if group == label))).most_common(6)] for label in set(labels)}
    return dict(assignments=labels.tolist(), keywords=keywords, model=str(Path(model_path).resolve()),
                dimensions=int(vectors.shape[1]))


@contextmanager
def measure(metrics):
    import psutil
    process = psutil.Process()
    stop = threading.Event()
    peak = [process.memory_info().rss]
    def monitor():
        while not stop.wait(.02):
            peak[0] = max(peak[0], process.memory_info().rss)
    start, cpu = time.perf_counter(), process.cpu_times()
    worker = threading.Thread(target=monitor, daemon=True)
    worker.start()
    try:
        yield
    finally:
        stop.set()
        worker.join()
        end = process.cpu_times()
        peak[0] = max(peak[0], process.memory_info().rss)
        metrics.update(wall_seconds=round(time.perf_counter()-start, 6),
                       cpu_seconds=round(end.user+end.system-cpu.user-cpu.system, 6),
                       peak_rss_mb=round(peak[0]/1024**2, 2), rss_sampling_ms=20)


def run(args):
    source, output = validate_paths(Path(args.source), Path(args.output))
    for exclusion in args.exclude:
        if '..' in Path(exclusion).parts or Path(exclusion).is_absolute():
            raise ValueError('--exclude must be relative to source, without ..')
    if args.max_files < 1 or args.max_files > 2000 or args.clusters < 1 or not 1 <= args.max_units <= 30:
        raise ValueError('Use 1..2000 files, positive clusters, and 1..30 sample units')
    report = dict(schema_version=1, source=str(source), documents=[], methods={}, metrics={},
                  environment=dict(python=platform.python_version(), platform=platform.platform()),
                  settings=vars(args), review_required=True)
    with measure(report['metrics']):
        paths = []
        for path in scan(source, args.exclude):
            paths.append(path)
            if len(paths) > args.max_files:
                raise ValueError('File limit exceeded; choose a smaller directory or exclude subdirectories')
        for path in paths:
            row = extract(path, ocr=args.ocr, tessdata=args.tessdata,
                          language=args.ocr_language, max_units=args.max_units)
            row['path'] = path.relative_to(source).as_posix()
            if row['status'] == 'ok' and not tokens(row['text']):
                row['status'] = 'no_features'
                row['warnings'].append('No supported word features; manual review required')
            report['documents'].append(row)
        usable = [r for r in report['documents'] if r['status'] == 'ok' and tokens(r['text'])]
        texts = [r['text'] for r in usable]
        for name in (['tfidf', 'embedding'] if args.method == 'both' else [args.method]):
            metrics = {}
            try:
                with measure(metrics):
                    result = cluster_tfidf(texts, args.clusters) if name == 'tfidf' else cluster_embedding(texts, args.clusters, args.model)
                result['status'] = 'ok'
                result['files'] = [r['path'] for r in usable]
            except Exception as exc:
                result = dict(status='error', error=f'{type(exc).__name__}: {exc}')
            result['metrics'] = metrics
            report['methods'][name] = result
        report['counts'] = dict(Counter(r['status'] for r in report['documents']))
        # Persist only a short evidence excerpt; do not log full extracted text.
        for row in report['documents']:
            row['evidence_excerpt'] = row.pop('text')[:160]
    output.mkdir(parents=True, exist_ok=False)
    (output / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    lines = ['# 分类建议（需人工审核）', '', '本次只读取原文件。分组编号不是既定课程类别；关键词不是准确率或置信度。',
             f'文件状态：{report["counts"]}', f'总耗时/内存：{report["metrics"]}', '']
    for name, result in report['methods'].items():
        lines += [f'## {name}', f'状态：{result["status"]}']
        if result['status'] == 'error':
            lines.append(result['error'])
            continue
        for label, keywords in result['keywords'].items():
            lines += ['', f'### 建议分组 {label} · {", ".join(keywords)}']
            lines += [f'- {path}' for path, group in zip(result['files'], result['assignments']) if str(group) == label]
    lines += ['', '## 提取覆盖与待检查项']
    for row in report['documents']:
        lines.append(f'- {row["path"]}: {row["status"]}; units={row["sampled_units"]}/{row["total_units"]}; '
                     f'{row.get("error", "")}; {"; ".join(row["warnings"])}')
    (output / 'suggestions.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    print(f'Report: {output / "report.json"}')
    return 2 if any(r['status'] == 'error' for r in report['methods'].values()) else 0


def main():
    # Windows without WMIC: use logical cores rather than joblib's failed probe.
    os.environ.setdefault('LOKY_MAX_CPU_COUNT', '4')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', help='Explicitly selected document directory')
    parser.add_argument('--output', required=True, help='New directory outside source')
    parser.add_argument('--method', choices=['tfidf', 'embedding', 'both'], default='tfidf')
    parser.add_argument('--clusters', type=int, default=3)
    parser.add_argument('--model', help='Local SentenceTransformer folder; never downloaded at classification time')
    parser.add_argument('--ocr', choices=['off', 'auto'], default='off')
    parser.add_argument('--tessdata', help='Local folder with Tesseract traineddata')
    parser.add_argument('--ocr-language', default='chi_sim+eng')
    parser.add_argument('--max-files', type=int, default=500)
    parser.add_argument('--max-units', type=int, default=9)
    parser.add_argument('--exclude', action='append', default=[], help='Relative directory or file; repeatable')
    args = parser.parse_args()
    try:
        return run(args)
    except (ValueError, OSError, ImportError) as exc:
        print(f'Error: {exc}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
