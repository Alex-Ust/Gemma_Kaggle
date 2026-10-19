"""Scripted OpenAI-compatible chat server that stands in for Gemma in local harness tests.

For each task it replays a fixed plan: locate skill -> apply a given patch -> check skill -> submit_patch.
This exercises the real harness (sandbox, skills, patch extraction, verification) with no model.

Usage: python scripts/fake_llm_server.py --patches <dir with <instance_id>.patch | "gold"> [--port 8011]
"""
import argparse
import base64
import json
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TASKS = [json.loads(line) for line in open(ROOT / "data/tasks.jsonl")]
LOG = ROOT / "logs/fake_llm.jsonl"


def text_of(content):
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(p.get("text", "") for p in content if isinstance(p, dict))
    return ""


def find_task(messages):
    blob = "\n".join(text_of(m.get("content")) for m in messages if m.get("role") == "user")
    for t in TASKS:
        head = t["problem_statement"].strip()[:200]
        if head and head in blob:
            return t
    return None


def plan(task, patch):
    q = task["problem_statement"].strip().splitlines()[0][:200]
    steps = [("run_skill_script", {"skill_name": "locate", "file_path": "scripts/locate.py", "args": {"query": q}})]
    if patch:
        if not patch.endswith("\n"):
            patch += "\n"  # git apply needs the final newline
        b64 = base64.b64encode(patch.encode()).decode()
        cmd = f"echo {b64} | base64 -d > /tmp/agent.diff && git apply --recount /tmp/agent.diff && git status --short"
        steps.append(("run_command", {"command": cmd}))
    steps.append(("run_skill_script", {"skill_name": "check", "file_path": "scripts/check.py"}))
    steps.append(("submit_patch", {}))
    return steps


class Handler(BaseHTTPRequestHandler):
    patches = None

    def log_message(self, *a):
        pass

    def _send(self, obj):
        body = json.dumps(obj).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        self._send({"object": "list", "data": [{"id": "gemma-4-31b-it-qat-w4a16-ct", "object": "model"}]})

    def do_POST(self):
        req = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
        msgs = req.get("messages", [])
        task = find_task(msgs)
        n_done = sum(1 for m in msgs if m.get("role") == "assistant")
        patch = None
        if task:
            if self.patches == "gold":
                patch = task["patch"]
            else:
                p = Path(self.patches) / f"{task['instance_id']}.patch"
                patch = p.read_text() if p.exists() else None
        steps = plan(task, patch) if task else []
        # record the last tool result so we can inspect skill output later
        last_tool = next((text_of(m.get("content")) for m in reversed(msgs) if m.get("role") == "tool"), None)
        with open(LOG, "a") as f:
            f.write(json.dumps({"task": task and task["instance_id"], "step": n_done,
                                "last_tool": (last_tool or "")[:4000], "t": time.time()}) + "\n")
        msg = {"role": "assistant", "content": None}
        finish = "tool_calls"
        if n_done < len(steps):
            name, args = steps[n_done]
            msg["tool_calls"] = [{"id": f"call_{uuid.uuid4().hex[:8]}", "type": "function",
                                  "function": {"name": name, "arguments": json.dumps(args)}}]
        else:
            msg["content"] = "Done."
            finish = "stop"
        self._send({"id": f"chatcmpl-{uuid.uuid4().hex[:10]}", "object": "chat.completion",
                    "created": int(time.time()), "model": req.get("model", "fake"),
                    "choices": [{"index": 0, "message": msg, "finish_reason": finish}],
                    "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}})


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--patches", default="gold")
    ap.add_argument("--port", type=int, default=8011)
    a = ap.parse_args()
    Handler.patches = a.patches
    LOG.parent.mkdir(exist_ok=True)
    ThreadingHTTPServer(("127.0.0.1", a.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
