"""Next-action probes with the real ADK stack.

For each (variant bundle, decision point, sample) the official agent is compiled from the bundle, the recorded
session is replayed up to the cut point (recorded model turns are returned by a replay model, recorded tool
results by a plugin, so nothing executes), and the real model is asked for exactly one more turn.
The request therefore has the same system prompt assembly, tool declarations and history encoding as in the
harness; only the system prompt / skills of the variant differ.

  probe_runner.py --points pts.json --variant v05=submissions/v05_skills --variant v06=submissions/v06 \
      --api-base http://127.0.0.1:8012/v1 --out probe.jsonl [--samples 1] [--concurrency 16]
In the Kaggle kernel the real model comes from the vLLM model registry (see probe_kernel_template.py).
"""
import argparse
import asyncio
import json
import random
import time
from typing import Any

from google.adk.models.base_llm import BaseLlm
from google.adk.plugins.base_plugin import BasePlugin
from google.genai import types

SKILL_TOOLS = {"load_skill", "load_skill_resource", "run_skill_script", "list_skills"}


class StopProbe(Exception):
    pass


class ProbeState:
    """Mutable per-probe state. Kept outside the pydantic model: ADK deep-copies model objects."""

    def __init__(self, real, steps, cut):
        self._real, self._steps, self._cut = real, steps, cut
        self._i = 0
        self._out = {}


STATES: dict = {}


class ReplayLlm(BaseLlm):
    """Returns recorded model turns until the cut, then delegates one turn to the real model."""

    probe_key: str = ""

    async def generate_content_async(self, llm_request, stream: bool = False):
        from google.adk.models.llm_response import LlmResponse

        self = STATES[self.probe_key]  # noqa: PLW0642 - all state lives in ProbeState
        k = self._i
        self._i += 1
        if k < self._cut:
            st = self._steps[k]
            parts = []
            if st["thought"]:
                parts.append(types.Part(text=st["thought"], thought=True))
            c = st["call"]
            parts.append(types.Part(function_call=types.FunctionCall(id=c["id"], name=c["name"], args=c["args"])))
            yield LlmResponse(content=types.Content(role="model", parts=parts))
            return
        if k > self._cut:
            raise StopProbe()
        sysi = llm_request.config.system_instruction if llm_request.config else None
        self._out["request"] = {
            "n_contents": len(llm_request.contents or []),
            "system_chars": len(str(sysi or "")),
            "tools": sorted(llm_request.tools_dict.keys()) if getattr(llm_request, "tools_dict", None) else [],
        }
        from adk_submission.resolvers.generation import apply_thinking_config_to_model

        # the harness attaches thinking settings (extra_body.chat_template_kwargs, thinking_token_budget) to a
        # clone of the agent's LiteLlm at compile time; the agent here holds the replay model, so do it now
        real = apply_thinking_config_to_model(self._real, llm_request.config)
        self._out["extra"] = {k: v for k, v in (getattr(real, "_additional_args", None) or {}).items()
                              if k in ("extra_body", "reasoning_effort")}
        t0 = time.time()
        resps = []
        try:
            async for r in real.generate_content_async(llm_request, stream=False):
                resps.append(r)
        except Exception as e:  # keep going: a failed sample is recorded, not fatal
            self._out["error"] = f"{type(e).__name__}: {e}"[:500]
        self._out["latency"] = round(time.time() - t0, 2)
        self._out["response"] = [dump_response(r) for r in resps]
        for r in resps:
            yield r


def dump_response(r):
    d = {"thought": "", "text": "", "calls": [], "finish": str(getattr(r, "finish_reason", "") or "")}
    um = getattr(r, "usage_metadata", None)
    if um is not None:
        d["prompt_tokens"] = getattr(um, "prompt_token_count", None)
        d["completion_tokens"] = getattr(um, "candidates_token_count", None)
    for p in (r.content.parts if r.content and r.content.parts else []):
        if p.function_call:
            d["calls"].append({"name": p.function_call.name, "args": dict(p.function_call.args or {})})
        elif p.text and p.thought:
            d["thought"] += p.text
        elif p.text:
            d["text"] += p.text
    return d


class ReplayTools(BasePlugin):
    """Answers replayed tool calls with the recorded results; nothing runs."""

    def __init__(self, llm: "ProbeState"):
        super().__init__(name="probe_replay_tools")
        self.llm = llm
        self.k = 0

    def _next(self, tool_name):
        k = self.k
        self.k += 1
        if k >= self.llm._cut:
            return {"status": "probe_end"}
        obs = self.llm._steps[k]["obs"]
        if tool_name in SKILL_TOOLS:  # skill tools return dicts: ADK passes them through unchanged
            try:
                v = json.loads(obs)
                return v if isinstance(v, dict) else {"result": v}
            except ValueError:
                return {"result": obs}
        return {"result": obs}  # swegemma tools return a JSON string, which ADK wraps exactly like this

    async def before_tool_callback(self, *, tool, tool_args, tool_context):
        return self._next(getattr(tool, "name", ""))

    async def on_tool_error_callback(self, *, tool, tool_args, tool_context, error):
        return self._next(getattr(tool, "name", ""))


async def run_probe(point, variant_dir, real_llm, model_name, limits, gen_constraints, ev):
    from adk_submission import ModelRegistry, compile_submission
    from google.adk.agents.run_config import RunConfig
    from google.adk.apps.app import App
    from google.adk.runners import Runner
    from google.adk.sessions import InMemorySessionService
    from swegemma.budget import EvaluationBudget, HarnessLimits
    from swegemma.context import SwegemmaContext

    ctx = SwegemmaContext(
        budget=EvaluationBudget(time_minutes=float(ev.get("max_time_minutes", 8)),
                                tool_calls=int(ev.get("max_tool_calls", 28)), turns=ev.get("max_turns")),
        harness=HarnessLimits(command_timeout_seconds=int(ev.get("timeout_seconds", 90))),
    )
    key = f"p{id(point)}_{random.random()}"
    llm = STATES[key] = ProbeState(real_llm, point["steps"], point["cut"])
    reg = ModelRegistry()
    reg.register(model_name, ReplayLlm(model=getattr(real_llm, "model", model_name), probe_key=key))
    agent = compile_submission(submission_dir=variant_dir, tool_registry=ctx.create_tools(), model_registry=reg,
                               limits=limits, generation_constraints=gen_constraints, code_executor=None,
                               script_timeout=int(ev.get("timeout_seconds", 90)))
    app = App(name="probe", root_agent=agent, plugins=[ReplayTools(llm)])
    svc = InMemorySessionService()
    runner = Runner(app=app, session_service=svc)
    sess = await svc.create_session(app_name="probe", user_id="u", state={"problem_description": ""})
    msg = types.Content(role="user", parts=[types.Part(text=point["user_prompt"])])
    try:
        async for _ in runner.run_async(user_id="u", session_id=sess.id, new_message=msg,
                                        run_config=RunConfig(max_llm_calls=500)):
            pass
    except StopProbe:
        pass
    except Exception as e:  # noqa: BLE001
        if "StopProbe" not in repr(e) and "response" not in llm._out:
            llm._out["error"] = f"{type(e).__name__}: {e}"[:500]
    llm._out["replayed"] = llm._i - 1
    STATES.pop(key, None)
    return llm._out


def load_eval(variant_dir):
    import yaml
    from pathlib import Path

    p = Path(variant_dir) / "eval_config.yaml"
    raw = yaml.safe_load(p.read_text()) if p.exists() else {}
    raw = raw or {}
    return raw.get("evaluation", raw)


async def run_all(points, variants, real_llm, model_name, out_path, samples=1, concurrency=16, log=print):
    from swegemma.config import build_submission_limits

    limits, gen_constraints = build_submission_limits()
    evs = {name: load_eval(d) for name, d in variants.items()}
    jobs = [(name, d, p, s) for p in points for name, d in variants.items() for s in range(samples)]
    random.Random(0).shuffle(jobs)  # mix variants so a slow tail does not bias one of them
    sem = asyncio.Semaphore(concurrency)
    lock = asyncio.Lock()
    done = 0
    t0 = time.time()

    async def one(name, d, p, s):
        nonlocal done
        async with sem:
            out = await run_probe(p, d, real_llm, model_name, limits, gen_constraints, evs[name])
        rec = {"variant": name, "iid": p["iid"], "kind": p["kind"], "cut": p["cut"], "sample": s, **out}
        async with lock:
            with open(out_path, "a") as f:
                f.write(json.dumps(rec) + "\n")
            done += 1
            if done % 20 == 0 or done == len(jobs):
                log(f"probes {done}/{len(jobs)}  {time.time() - t0:.0f}s")

    await asyncio.gather(*(one(*j) for j in jobs))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--points", required=True)
    ap.add_argument("--variant", action="append", required=True, help="name=bundle_dir")
    ap.add_argument("--api-base", required=True)
    ap.add_argument("--model", default="gemma-4-31b-it-qat-w4a16-ct")
    ap.add_argument("--out", required=True)
    ap.add_argument("--samples", type=int, default=1)
    ap.add_argument("--concurrency", type=int, default=8)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--kinds", default="")
    a = ap.parse_args()
    from google.adk.models.lite_llm import LiteLlm

    pts = json.load(open(a.points))
    if a.kinds:
        pts = [p for p in pts if p["kind"] in a.kinds.split(",")]
    if a.limit:
        pts = pts[: a.limit]
    variants = dict(v.split("=", 1) for v in a.variant)
    real = LiteLlm(model=f"openai/{a.model}", api_base=a.api_base, api_key="EMPTY", num_retries=1)
    asyncio.run(run_all(pts, variants, real, a.model, a.out, a.samples, a.concurrency))


if __name__ == "__main__":
    main()
