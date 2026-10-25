"""Scripted OpenAI-compatible chat server that stands in for Gemma in local harness tests.

For each task it replays a fixed plan: locate skill -> apply a given patch -> check skill -> submit_patch.
This exercises the real harness (sandbox, skills, patch extraction, verification) with no model.

Usage: python scripts/fake_llm_server.py --patches <dir with <instance_id>.patch | "gold"> [--port 8011]
"""
import argparse
import base64
import json
import re
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TASKS = []
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
    steps = [("run_skill_script", {"skill_name": "locate", "file_path": "locate.py", "positional_args": [q]})]
    if patch:
        if not patch.endswith("\n"):
            patch += "\n"  # git apply needs the final newline
        b64 = base64.b64encode(patch.encode()).decode()
        cmd = f"echo {b64} | base64 -d > /tmp/agent.diff && (git apply --recount /tmp/agent.diff || git apply -3 /tmp/agent.diff || git apply --ignore-whitespace /tmp/agent.diff || patch -p1 --batch --forward < /tmp/agent.diff) && git status --short"
        steps.append(("run_command", {"command": cmd}))
    names = " ".join(dict.fromkeys(re.findall(r"^@@[^@]*@@\s*(?:async\s+)?(?:def|class)\s+(\w+)", patch or "", re.M)))
    steps.append(("run_skill_script", {"skill_name": "check", "file_path": "check.py", "positional_args": [names or "none"]}))
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
        sysmsg = "\n".join(text_of(m.get("content")) for m in msgs if m.get("role") in ("system", "developer"))
        n_done = sum(1 for m in msgs if m.get("role") == "assistant")
        if "You are scout" in sysmsg:
            # scout sub-agent: one bounded view call, then a fixed report (tests the skill + output_key plumbing)
            msg = {"role": "assistant", "content": None}
            if n_done == 0:
                msg["tool_calls"] = [{"id": f"call_{uuid.uuid4().hex[:8]}", "type": "function",
                                      "function": {"name": "run_skill_script", "arguments": json.dumps(
                                          {"skill_name": "view", "file_path": "view.py", "positional_args": ["grep", "def "]})}}]
                finish = "tool_calls"
            else:
                last_tool = next((text_of(m.get("content")) for m in reversed(msgs) if m.get("role") == "tool"), "")
                msg["content"] = "VERDICT: fake scout report.\nFILE: none\nCONFIDENCE: low\nVIEW_OK: " + ("yes" if "view budget" in last_tool else "no")
                finish = "stop"
            self._send({"id": f"chatcmpl-{uuid.uuid4().hex[:10]}", "object": "chat.completion",
                        "created": int(time.time()), "model": req.get("model", "fake"),
                        "choices": [{"index": 0, "message": msg, "finish_reason": finish}],
                        "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}})
            return
        task = find_task(msgs)
        patch = None
        if task:
            if self.patches == "gold":
                patch = task["patch"]
            else:
                p = Path(self.patches) / f"{task['instance_id']}.patch"
                patch = p.read_text() if p.exists() else None
        steps = plan(task, patch) if task else []
        if "SCOUT REPORTS" in sysmsg:
            steps = [("scouts", {"request": "report"})] + steps
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
    global LOG
    ap = argparse.ArgumentParser()
    ap.add_argument("--patches", default="gold")
    ap.add_argument("--port", type=int, default=8011)
    ap.add_argument("--tasks", default=str(ROOT / "data/tasks.jsonl"))
    ap.add_argument("--log", default=str(LOG))
    a = ap.parse_args()
    LOG = Path(a.log)
    TASKS.extend(json.loads(line) for line in open(a.tasks))
    Handler.patches = a.patches
    LOG.parent.mkdir(exist_ok=True)
    ThreadingHTTPServer(("127.0.0.1", a.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
