"""Reproducible synthetic end-to-end benchmark, including source-byte integrity."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from make_demo import generate


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output', help='New benchmark directory')
    parser.add_argument('--model')
    parser.add_argument('--tessdata')
    args = parser.parse_args()
    root = Path(args.output).resolve()
    root.mkdir(parents=True, exist_ok=False)
    source = root / 'input'
    expected = generate(source)
    def hashes():
        return {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in source.iterdir()}
    before = hashes()
    command = [sys.executable, '-B', str(Path(__file__).with_name('classify.py')), str(source),
               '--output', str(root / 'report'), '--clusters', '3']
    if args.model:
        command += ['--method', 'both', '--model', args.model]
    if args.tessdata:
        command += ['--ocr', 'auto', '--ocr-language', 'eng', '--tessdata', args.tessdata]
        expected['scan.pdf'] = 'database'
    result = subprocess.run(command)
    unchanged = before == hashes()
    report = json.loads((root / 'report/report.json').read_text(encoding='utf-8'))
    from sklearn.metrics import adjusted_rand_score
    quality = {}
    for name, method in report['methods'].items():
        if method['status'] == 'ok':
            quality[name] = dict(adjusted_rand_index=adjusted_rand_score(
                [expected[p] for p in method['files']], method['assignments']),
                documents=len(method['files']), metrics=method['metrics'])
        else:
            quality[name] = dict(error=method['error'])
    summary = dict(source_hashes_unchanged=unchanged, source_files=len(before),
                   algorithm_exit_code=result.returncode, counts=report['counts'],
                   metrics=report['metrics'], methods=quality,
                   note='Synthetic repeated-topic fixture, not real-world accuracy')
    (root / 'summary.json').write_text(json.dumps(summary, indent=2), encoding='utf-8')
    print(json.dumps(summary, indent=2))
    raise SystemExit(0 if unchanged and result.returncode == 0 else 2)
