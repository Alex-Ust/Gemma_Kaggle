"""Run the official harness locally (Docker sandbox) against an OpenAI-compatible endpoint.

Used with scripts/fake_llm_server.py to test bundle mechanics and skills without a GPU.

  python scripts/local_eval.py submissions/v05 --task-ids rich_3130 fastapi_14986 \
      --api-base http://127.0.0.1:8011/v1 --out runs/local/v05-gold --concurrency 2
"""
import argparse
import asyncio
import json
import logging
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
os.environ.setdefault("LITELLM_LOCAL_MODEL_COST_MAP", "True")
os.environ.setdefault("LITELLM_TELEMETRY", "False")
os.environ.setdefault("OTEL_SDK_DISABLED", "true")
if "DOCKER_HOST" not in os.environ:
    host = subprocess.run(["docker", "context", "inspect", "-f", "{{.Endpoints.docker.Host}}"],
                          capture_output=True, text=True).stdout.strip()
    if host:
        os.environ["DOCKER_HOST"] = host

import litellm  # noqa: E402
import yaml  # noqa: E402
from adk_submission import ModelRegistry, discover_adapters, validate_directory  # noqa: E402
from adk_submission.discovery import discover_declared_models  # noqa: E402
from google.adk.agents.context_cache_config import ContextCacheConfig  # noqa: E402
from google.adk.apps._configs import EventsCompactionConfig  # noqa: E402
from google.adk.models.lite_llm import LiteLlm  # noqa: E402
from swegemma.config import ALLOWED_ADAPTER_EXTENSIONS, EvalConfig, build_submission_limits  # noqa: E402
from swegemma.evaluate import Evaluator  # noqa: E402

for name in ("LiteLLM", "litellm", "httpx", "openai"):
    logging.getLogger(name).setLevel(logging.WARNING)
litellm.drop_params = True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("bundle")
    ap.add_argument("--task-ids", nargs="+", required=True)
    ap.add_argument("--api-base", default="http://127.0.0.1:8011/v1")
    ap.add_argument("--out", required=True)
    ap.add_argument("--concurrency", type=int, default=2)
    a = ap.parse_args()

    agent_dir = (ROOT / a.bundle).resolve()
    limits, gen = build_submission_limits()
    validate_directory(agent_dir, limits=limits)
    model = next(iter(discover_declared_models(agent_dir)))
    models = ModelRegistry()
    models.register(model, LiteLlm(model=f"openai/{model}", api_base=a.api_base, api_key="EMPTY", num_retries=1))
    ev = (yaml.safe_load((agent_dir / "eval_config.yaml").read_text()) or {}).get("evaluation", {}) \
        if (agent_dir / "eval_config.yaml").exists() else {}
    data = ROOT / "data"
    out = (ROOT / a.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    cfg = EvalConfig(
        tasks_path=data / "tasks.jsonl", snapshots_dir=data / "snapshots", results_dir=out,
        submission_dir=agent_dir, models=models, sandbox="docker",
        timeout_seconds=int(ev.get("timeout_seconds", 300)), verification_timeout_seconds=300,
        max_time_minutes=float(ev.get("max_time_minutes", 60)), max_tool_calls=int(ev.get("max_tool_calls", 100)),
        max_turns=int(ev["max_turns"]) if ev.get("max_turns") else None,
        limits=limits, generation_constraints=gen,
        adapter_manifest=discover_adapters(str(agent_dir), adapter_extensions=ALLOWED_ADAPTER_EXTENSIONS),
        context_cache_config=ContextCacheConfig(min_tokens=2048, ttl_seconds=1800, cache_intervals=10),
        events_compaction_config=EventsCompactionConfig(compaction_interval=15, overlap_size=2,
                                                        token_threshold=14336, event_retention_size=5),
        graph_dir=str(data / "graphs"), embeddings_dir=str(data / "embeddings"), wheels_dir=data / "wheels",
        task_ids=a.task_ids, concurrency=a.concurrency, display_mode="quiet",
    )
    res = asyncio.run(Evaluator(cfg).run())
    for r in res.task_results:
        print(json.dumps({"id": r.instance_id, "resolved": r.resolved, "error": r.error,
                          "secs": round(r.duration_seconds), "tool_calls": r.tool_calls}))


if __name__ == "__main__":
    main()
