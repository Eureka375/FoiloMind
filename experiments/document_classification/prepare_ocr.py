"""Download only official OCR language data; never reads document directories."""
import argparse
import hashlib
from pathlib import Path
import urllib.request

REVISION = '87416418657359cb625c412a48b6e1d6d41c29bd'

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('destination')
    args = parser.parse_args()
    root = Path(args.destination)
    root.mkdir(parents=True, exist_ok=True)
    for language in ('eng', 'chi_sim'):
        destination = root / f'{language}.traineddata'
        if destination.exists():
            raise SystemExit(f'Refusing to overwrite: {destination}')
        url = f'https://raw.githubusercontent.com/tesseract-ocr/tessdata_fast/{REVISION}/{language}.traineddata'
        with urllib.request.urlopen(url, timeout=60) as response:
            data = response.read()
        destination.write_bytes(data)
        print(language, hashlib.sha256(data).hexdigest())
