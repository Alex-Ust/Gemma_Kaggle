"""Download all competition files into data/, one by one, skipping files already present.

Usage: KAGGLE_API_TOKEN=kaggle/access_token .venv/bin/python scripts/download_data.py [prefix ...]
Without prefixes downloads everything (small files first, snapshots last).
"""
import os
import sys
import zipfile
from pathlib import Path

from kaggle.api.kaggle_api_extended import KaggleApi

COMP = "gemma-4-developer-agent"
ROOT = Path(__file__).resolve().parent.parent / "data"


def list_files(api):
    rows, tok = [], None
    while True:
        r = api.competition_list_files(COMP, page_token=tok, page_size=200)
        rows += [(f.name, f.total_bytes) for f in r.files]
        tok = r.next_page_token
        if not tok:
            return rows


def order(name):
    for i, p in enumerate(["sample_submission/", "sandbox/", "docker/", "wheels/", "graphs/", "embeddings/", "snapshots/"]):
        if name.startswith(p):
            return i
    return -1


def main():
    prefixes = sys.argv[1:]
    api = KaggleApi()
    api.authenticate()
    files = sorted(list_files(api), key=lambda x: (order(x[0]), x[1]))
    if prefixes:
        files = [f for f in files if any(f[0].startswith(p) for p in prefixes)]
    total = sum(s for _, s in files)
    done = 0
    for i, (name, size) in enumerate(files, 1):
        dest = ROOT / name
        if dest.exists() and dest.stat().st_size == size:
            done += size
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        for attempt in range(3):
            try:
                api.competition_download_file(COMP, name, path=str(dest.parent), force=True, quiet=True)
                break
            except Exception as e:  # network hiccups
                print(f"retry {attempt + 1} {name}: {e}", flush=True)
        # Kaggle may wrap a file in a zip
        z = dest.parent / (dest.name + ".zip")
        if z.exists():
            with zipfile.ZipFile(z) as zf:
                zf.extractall(dest.parent)
            z.unlink()
        ok = dest.exists() and dest.stat().st_size == size
        done += size
        print(f"[{i}/{len(files)}] {'ok ' if ok else 'BAD'} {name} {size / 1e6:.1f}MB  total {done / 1e9:.2f}/{total / 1e9:.2f}GB", flush=True)


if __name__ == "__main__":
    main()
