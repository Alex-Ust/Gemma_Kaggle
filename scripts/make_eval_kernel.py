"""Build (and optionally push) a Kaggle GPU script that evaluates a bundle on the public training tasks.

Usage:
  python scripts/make_eval_kernel.py submissions/v02_no_graph --tag smoke --n 8 --concurrency 4 [--push]
  python scripts/make_eval_kernel.py submissions/v02_no_graph --tag full --push         # all 129 tasks

The kernel is written to runs/<bundle>-<tag>/kernel/. Pull results later with scripts/pull_eval.py.
"""
import argparse
import base64
import json
import os
import random
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
USER = "alexust"
MODELS = {
    "gemma-4-31b-it-qat-w4a16-ct": "google/gemma-4/Other/gemma-4-31b-it-qat-w4a16-ct/2",
    "gemma-4-12b-it-qat-w4a16-ct": "google/gemma-4/Other/gemma-4-12b-it-qat-w4a16-ct/2",
    "gemma-4-e4b-it-qat-w4a16-ct": "google/gemma-4/Other/gemma-4-e4b-it-qat-w4a16-ct/2",
    "gemma-4-e2b-it-qat-w4a16-ct": "google/gemma-4/Other/gemma-4-e2b-it-qat-w4a16-ct/2",
}
# Same image as the official starter notebook, so vLLM/CUDA match the scorer.
DOCKER_IMAGE = "gcr.io/kaggle-private-byod/python@sha256:37c64f7dd9c54116ecd1bcc88817c5469b88387388fade02bfa8bf3fc647d461"


def pick_tasks(n, seed=0):
    rows = [json.loads(line) for line in open(ROOT / "data/tasks.jsonl")]
    ids = [r["instance_id"] for r in rows]
    if n is None or n >= len(ids):
        return None  # all
    # stratify by repo so a small run still covers every repo
    by_repo = {}
    for i in ids:
        by_repo.setdefault(i.split("_")[0], []).append(i)
    rng = random.Random(seed)
    for v in by_repo.values():
        rng.shuffle(v)
    out = []
    while len(out) < n:
        for v in by_repo.values():
            if v and len(out) < n:
                out.append(v.pop())
    return sorted(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("bundle")
    ap.add_argument("--tag", required=True)
    ap.add_argument("--n", type=int, default=None, help="number of tasks (default: all 129)")
    ap.add_argument("--task-ids", nargs="*")
    ap.add_argument("--set", choices=["sound"], help="use a named task set from data/task_sets.json")
    ap.add_argument("--concurrency", type=int, default=4)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--mode", default="agent", choices=["agent", "gold", "empty", "fake"],
                    help="gold/empty: CPU-only check with the reference / an empty patch")
    ap.add_argument("--ood", action="store_true", help="run on OOD-45 (rodrigospalma/ood45-bugfix-split)")
    ap.add_argument("--push", action="store_true")
    a = ap.parse_args()

    bundle = (ROOT / a.bundle).resolve()
    files = {str(p.relative_to(bundle)): base64.b64encode(p.read_bytes()).decode()
             for p in sorted(bundle.rglob("*")) if p.is_file() and p.name != ".DS_Store"}
    text = (bundle / "agent.yaml").read_text()
    model = next(m for m in MODELS if m in text)
    if a.task_ids:  # tolerate one space-separated string (zsh does not word-split $VAR)
        a.task_ids = [t for x in a.task_ids for t in x.split()]
    task_ids = a.task_ids or (json.load(open(ROOT / "data/task_sets.json"))[a.set] if a.set else pick_tasks(a.n, a.seed))
    run = {"task_ids": None if a.ood else task_ids, "concurrency": a.concurrency, "bundle": bundle.name,
           "tag": a.tag, "mode": a.mode, "ood": a.ood, "ood_ids": a.task_ids if a.ood else None}
    gpu = a.mode == "agent"

    name = f"{bundle.name}-{a.tag}".replace("_", "-").lower()
    slug = f"gemma-eval-{name}"[:50].rstrip("-")
    kdir = ROOT / "runs" / name / "kernel"
    kdir.mkdir(parents=True, exist_ok=True)
    tpl = (ROOT / "scripts/eval_kernel_template.py").read_text()
    code = (tpl.replace("__BUNDLE_B64__", base64.b64encode(json.dumps(files).encode()).decode())
               .replace("__RUN_B64__", base64.b64encode(json.dumps(run).encode()).decode())
               .replace("__FAKE_B64__", base64.b64encode((ROOT / "scripts/fake_llm_server.py").read_bytes()).decode()))
    (kdir / "run.py").write_text(code)
    meta = {
        "id": f"{USER}/{slug}",
        "title": slug,
        "code_file": "run.py",
        "language": "python",
        "kernel_type": "script",
        "is_private": True,
        "enable_gpu": gpu,
        "enable_tpu": False,
        "enable_internet": False,
        "dataset_sources": ["metric/gemma-4-developer-agent-wheelhouse"]
        + (["rodrigospalma/ood45-bugfix-split"] if a.ood else []),
        "competition_sources": ["gemma-4-developer-agent"],
        "kernel_sources": [],
        "model_sources": [MODELS[model]] if gpu else [],
        "docker_image": DOCKER_IMAGE,
    }
    if gpu:
        meta["machine_shape"] = "NvidiaL4"
    (kdir / "kernel-metadata.json").write_text(json.dumps(meta, indent=2))
    (kdir.parent / "run.json").write_text(json.dumps({**run, "slug": meta["id"], "model": model}, indent=2))
    print(f"kernel: {kdir}  slug={meta['id']}  model={model}  tasks={len(task_ids) if task_ids else 129}")

    if a.push:
        env = {**os.environ, "KAGGLE_API_TOKEN": str(ROOT / "kaggle/access_token")}
        r = subprocess.run([str(ROOT / ".venv/bin/kaggle"), "kernels", "push", "-p", str(kdir)],
                           env=env, capture_output=True, text=True)
        print(r.stdout, r.stderr)
        sys.exit(r.returncode)


if __name__ == "__main__":
    main()
