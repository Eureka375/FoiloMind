"""Explicit, separate network setup. This script never reads source documents."""
import argparse
from pathlib import Path

MODEL = 'sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2'

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('destination')
    parser.add_argument('--revision', required=True, help='Reviewed Hugging Face commit hash')
    parser.add_argument('--direct-mirror', action='store_true', help='Use direct HTTPS mirror downloads if Hub metadata fails')
    args = parser.parse_args()
    if args.direct_mirror:
        import requests
        import hashlib
        root = Path(args.destination)
        for name in ('config.json', 'config_sentence_transformers.json', 'modules.json',
                     'sentence_bert_config.json', 'special_tokens_map.json', 'tokenizer_config.json',
                     'tokenizer.json', 'sentencepiece.bpe.model', '1_Pooling/config.json',
                     'model.safetensors'):
            target = root / name
            if target.exists() and target.stat().st_size:
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            url = f'https://hf-mirror.com/{MODEL}/resolve/{args.revision}/{name}'
            digest = hashlib.sha256()
            partial = target.with_suffix(target.suffix + '.partial')
            with requests.get(url, stream=True, timeout=(20, 40)) as response:
                response.raise_for_status()
                with partial.open('wb') as stream:
                    for chunk in response.iter_content(1024*1024):
                        stream.write(chunk)
                        digest.update(chunk)
            partial.replace(target)
            print(name, target.stat().st_size, digest.hexdigest(), flush=True)
    else:
        from huggingface_hub import snapshot_download
        snapshot_download(MODEL, revision=args.revision, local_dir=Path(args.destination),
                          allow_patterns=['*.json', '*.safetensors', 'tokenizer*', '*.model',
                                          'vocab.txt', '1_Pooling/*', 'README.md'], max_workers=2)
    print(f'Prepared {MODEL}@{args.revision} in {args.destination}')
