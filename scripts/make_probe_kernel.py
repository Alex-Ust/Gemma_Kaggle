"""Build (and optionally push) a Kaggle kernel that runs next-action probes for several bundle variants.

  make_probe_kernel.py --tag p1 --points research/probes/v05_points.json \
      --variant v05=submissions/v05_skills --variant v06=submissions/v06_edit_early \
      [--kinds first,plan,late] [--samples 1] [--concurrency 16] [--mode stub] [--push]

--mode stub runs on CPU against a canned server (free plumbing test); the default uses vLLM on 4xL4.
Results: runs/probe-<tag>/output/probe.jsonl (pull with: kaggle kernels output <slug> -p runs/probe-<tag>/output).
"""
import argparse
import base64
import gzip
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from make_eval_kernel import DOCKER_IMAGE, MODELS, USER  # noqa: E402


def bundle_files(path):
    b = (ROOT / path).resolve()
    return {str(p.relative_to(b)): base64.b64encode(p.read_bytes()).decode()
            for p in sorted(b.rglob("*")) if p.is_file() and p.name != ".DS_Store" and "__pycache__" not in p.parts}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", required=True)
    ap.add_argument("--points", required=True)
    ap.add_argument("--variant", action="append", required=True, help="name=bundle_dir")
    ap.add_argument("--kinds", default="")
    ap.add_argument("--samples", type=int, default=1)
    ap.add_argument("--concurrency", type=int, default=16)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--mode", default="vllm", choices=["vllm", "stub"])
    ap.add_argument("--push", action="store_true")
    a = ap.parse_args()

    pts = json.load(open(ROOT / a.points))
    if a.kinds:
        pts = [p for p in pts if p["kind"] in a.kinds.split(",")]
    if a.limit:
        pts = pts[: a.limit]
    variants = dict(v.split("=", 1) for v in a.variant)
    vfiles = {k: bundle_files(v) for k, v in variants.items()}
    model = next(m for m in MODELS if m in (ROOT / list(variants.values())[0] / "agent.yaml").read_text())
    run = {"tag": a.tag, "samples": a.samples, "concurrency": a.concurrency, "mode": a.mode,
           "variants": variants, "points": a.points, "kinds": a.kinds, "n_points": len(pts)}
    gpu = a.mode == "vllm"
    name = f"probe-{a.tag}".replace("_", "-").lower()
    slug = f"gemma-{name}"[:50].rstrip("-")
    kdir = ROOT / "runs" / name / "kernel"
    kdir.mkdir(parents=True, exist_ok=True)
    tpl = (ROOT / "scripts/probe_kernel_template.py").read_text()
    code = (tpl.replace("__VARIANTS_B64__", base64.b64encode(json.dumps(vfiles).encode()).decode())
               .replace("__POINTS_B64__", base64.b64encode(gzip.compress(json.dumps(pts).encode(), 9)).decode())
               .replace("__RUN_B64__", base64.b64encode(json.dumps(run).encode()).decode())
               .replace("__RUNNER_B64__", base64.b64encode((ROOT / "scripts/probe_runner.py").read_bytes()).decode())
               .replace("__STUB_B64__", base64.b64encode((ROOT / "scripts/stub_llm_server.py").read_bytes()).decode()))
    (kdir / "run.py").write_text(code)
    meta = {
        "id": f"{USER}/{slug}", "title": slug, "code_file": "run.py", "language": "python",
        "kernel_type": "script", "is_private": True, "enable_gpu": gpu, "enable_tpu": False,
        "enable_internet": False, "dataset_sources": ["metric/gemma-4-developer-agent-wheelhouse"],
        "competition_sources": ["gemma-4-developer-agent"], "kernel_sources": [],
        "model_sources": [MODELS[model]] if gpu else [], "docker_image": DOCKER_IMAGE,
    }
    if gpu:
        meta["machine_shape"] = "NvidiaL4"
    (kdir / "kernel-metadata.json").write_text(json.dumps(meta, indent=2))
    (kdir.parent / "run.json").write_text(json.dumps({**run, "slug": meta["id"], "model": model}, indent=2))
    jobs = len(pts) * len(variants) * a.samples
    print(f"kernel: {kdir}  slug={meta['id']}  points={len(pts)}  jobs={jobs}  "
          f"size={(kdir / 'run.py').stat().st_size / 1e6:.2f} MB")
    if a.push:
        env = {**os.environ, "KAGGLE_API_TOKEN": str(ROOT / "kaggle/access_token")}
        r = subprocess.run([str(ROOT / ".venv/bin/kaggle"), "kernels", "push", "-p", str(kdir)],
                           env=env, capture_output=True, text=True)
        print(r.stdout, r.stderr)
        sys.exit(r.returncode)


if __name__ == "__main__":
    main()
