"""Minimal OpenAI-compatible chat server for local plumbing tests.

Logs every request body to --log (jsonl) and answers with one fixed tool call (get_status), so a
probe or harness run can be inspected without a GPU.
"""
import argparse
import json
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

LOG = None
SCRIPT = []  # optional list of {"name":..., "args":...} or {"text":...} answers, consumed in order


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
        with open(LOG, "a") as f:
            f.write(json.dumps(body) + "\n")
        step = SCRIPT.pop(0) if SCRIPT else {"name": "get_status", "args": {}}
        if "text" in step:
            msg = {"role": "assistant", "content": step["text"], "reasoning_content": "stub thought"}
            finish = "stop"
        else:
            msg = {"role": "assistant", "content": None, "reasoning_content": "stub thought",
                   "tool_calls": [{"id": f"call_{int(time.time() * 1000)}", "type": "function",
                                   "function": {"name": step["name"], "arguments": json.dumps(step["args"])}}]}
            finish = "tool_calls"
        resp = {
            "id": "stub", "object": "chat.completion", "created": int(time.time()), "model": body.get("model"),
            "choices": [{"index": 0, "finish_reason": finish, "message": msg}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        }
        out = json.dumps(resp).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)


def main():
    global LOG
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8012)
    ap.add_argument("--log", required=True)
    ap.add_argument("--script", default=None, help="json file with a list of scripted answers")
    a = ap.parse_args()
    LOG = a.log
    if a.script:
        SCRIPT.extend(json.load(open(a.script)))
    HTTPServer(("127.0.0.1", a.port), H).serve_forever()


if __name__ == "__main__":
    main()
