"""Download selected files of a Kaggle dataset one by one (resumable).

Usage: KAGGLE_API_TOKEN=kaggle/access_token .venv/bin/python scripts/download_dataset.py \
          rodrigospalma/ood45-bugfix-split data_ood tasks.jsonl snapshots/ statements/
"""
import sys
import zipfile
from pathlib import Path

from kaggle.api.kaggle_api_extended import KaggleApi


def main():
    ref, out, *prefixes = sys.argv[1:]
    out = Path(out)
    api = KaggleApi()
    api.authenticate()
    owner, slug = ref.split("/")
    files, tok = [], None
    while True:
        r = api.dataset_list_files(ref, page_token=tok, page_size=200)
        files += [(f.name, f.total_bytes) for f in r.files]
        tok = r.next_page_token
        if not tok:
            break
    if prefixes:
        files = [f for f in files if any(f[0].startswith(p) for p in prefixes)]
    total = sum(s for _, s in files)
    print(f"{len(files)} files, {total / 1e9:.2f} GB", flush=True)
    for i, (name, size) in enumerate(sorted(files, key=lambda x: x[1]), 1):
        dest = out / name
        if dest.exists() and dest.stat().st_size == size:
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        for attempt in range(3):
            try:
                api.dataset_download_file(ref, name, path=str(dest.parent), force=True, quiet=True)
                break
            except Exception as e:
                print(f"retry {name}: {e}", flush=True)
        z = dest.parent / (dest.name + ".zip")
        if z.exists():
            with zipfile.ZipFile(z) as zf:
                zf.extractall(dest.parent)
            z.unlink()
        ok = dest.exists() and dest.stat().st_size == size
        if i % 10 == 0 or not ok:
            print(f"[{i}/{len(files)}] {'ok' if ok else 'BAD'} {name}", flush=True)
    print("done", flush=True)


if __name__ == "__main__":
    main()
