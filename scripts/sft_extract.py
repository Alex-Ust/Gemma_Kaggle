"""Extract successful agent trajectories (ATIF traces) into OpenAI-style chat messages for LoRA SFT.

Usage: python3 scripts/sft_extract.py runs/<run> [runs/<run> ...] -o research/lora/sft_messages.jsonl [--per-task 3]
Each output row: {"instance_id", "run", "messages": [...], "n_calls", "n_edits", "chars"}
Assistant turns carry "reasoning_content" (thought parts) and "tool_calls" in OpenAI format; tool
results are role "tool" rows with the raw JSON string the harness returned. Compaction summaries are
ignored: the full raw history is used.
"""
import argparse, glob, json, os, sys


def trace_to_messages(trace):
    msgs = []
    pending = {"reasoning": [], "content": []}
    steps = trace["steps"]
    for s in steps:
        ex = s.get("extra") or {}
        et = ex.get("event_type")
        src = s["source"]
        if src == "system" and et == "system_instruction":
            msgs.append({"role": "system", "content": s["message"]}); continue
        if src == "user" and et == "task_prompt":
            msgs.append({"role": "user", "content": s["message"]}); continue
        if src == "system":  # continuation nudge etc. -> user turn
            if s.get("message"):
                msgs.append({"role": "user", "content": s["message"]})
            continue
        if src != "agent":
            continue
        msg = s.get("message") or ""
        if et == "thinking" and msg:
            pending["reasoning"].append(msg)
        elif et in ("text", "final") and msg:
            pending["content"].append(msg)
        calls = s.get("tool_calls") or []
        if calls:
            a = {"role": "assistant", "content": "\n".join(pending["content"]) or None}
            if pending["reasoning"]:
                a["reasoning_content"] = "\n".join(pending["reasoning"])
            a["tool_calls"] = [{"id": c["tool_call_id"], "type": "function",
                                "function": {"name": c["function_name"], "arguments": json.dumps(c["arguments"], ensure_ascii=False)}}
                               for c in calls]
            msgs.append(a)
            pending = {"reasoning": [], "content": []}
            obs = s.get("observation") or {}
            content = obs.get("content")
            if content is None:
                return None  # incomplete step (killed mid-call); drop the trajectory
            msgs.append({"role": "tool", "tool_call_id": calls[-1]["tool_call_id"], "name": calls[-1]["function_name"],
                         "content": content if isinstance(content, str) else json.dumps(content)})
    if pending["content"] or pending["reasoning"]:
        a = {"role": "assistant", "content": "\n".join(pending["content"]) or ""}
        if pending["reasoning"]:
            a["reasoning_content"] = "\n".join(pending["reasoning"])
        msgs.append(a)
    return msgs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("runs", nargs="+")
    ap.add_argument("-o", default="research/lora/sft_messages.jsonl")
    ap.add_argument("--per-task", type=int, default=3)
    ap.add_argument("--max-chars", type=int, default=70000, help="drop trajectories longer than this (chars of all messages)")
    a = ap.parse_args()
    rows = []
    for run in a.runs:
        # Kaggle layout runs/<run>/output/results/, pod layout runs/<run>/results/ or a results dir passed directly
        res_dir = next((d for d in (os.path.join(run, "output/results"), os.path.join(run, "results"), run)
                        if os.path.exists(os.path.join(d, "task_results.jsonl"))), None)
        if res_dir is None:
            print("skip (no results):", run); continue
        res_path = os.path.join(res_dir, "task_results.jsonl")
        resolved = {json.loads(l)["instance_id"] for l in open(res_path) if json.loads(l)["resolved"]}
        for f in sorted(glob.glob(os.path.join(res_dir, "traces/*.json"))):
            iid = os.path.basename(f)[6:-5]
            if iid not in resolved:
                continue
            msgs = trace_to_messages(json.load(open(f)))
            if not msgs:
                continue
            calls = [c for m in msgs if m["role"] == "assistant" for c in m.get("tool_calls", [])]
            n_edits = sum(1 for c in calls if c["function"]["name"] in ("edit_file", "write_file"))
            if n_edits == 0:
                continue
            chars = sum(len(m.get("content") or "") + len(m.get("reasoning_content") or "") + sum(len(c["function"]["arguments"]) for c in m.get("tool_calls", [])) for m in msgs)
            rows.append({"instance_id": iid, "run": os.path.basename(run), "messages": msgs, "n_calls": len(calls), "n_edits": n_edits, "chars": chars})
    # per task keep the shortest N
    by = {}
    for r in rows:
        by.setdefault(r["instance_id"], []).append(r)
    out = []
    for iid, rs in sorted(by.items()):
        rs = sorted(rs, key=lambda r: r["chars"])
        rs = [r for r in rs if r["chars"] <= a.max_chars][: a.per_task]
        out.extend(rs)
    with open(a.o, "w") as f:
        for r in out:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    import statistics as st
    print(f"candidates {len(rows)} from {len(by)} tasks -> kept {len(out)} trajectories over {len({r['instance_id'] for r in out})} tasks")
    if out:
        print("chars: median", st.median(r["chars"] for r in out), "max", max(r["chars"] for r in out), " calls: median", st.median(r["n_calls"] for r in out))
        print("per run:", {k: sum(1 for r in out if r["run"] == k) for k in sorted({r["run"] for r in out})})


if __name__ == "__main__":
    main()
