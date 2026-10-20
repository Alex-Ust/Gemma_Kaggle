"""Minimal OpenAI-compatible chat server for local plumbing tests.

Logs every request body to --log (jsonl) and answers with one fixed tool call (get_status), so a
probe or harness run can be inspected without a GPU.
"""
import argparse
import json
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

LOG = None


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
        with open(LOG, "a") as f:
            f.write(json.dumps(body) + "\n")
        resp = {
            "id": "stub", "object": "chat.completion", "created": int(time.time()), "model": body.get("model"),
            "choices": [{"index": 0, "finish_reason": "tool_calls", "message": {
                "role": "assistant", "content": None, "reasoning_content": "stub thought",
                "tool_calls": [{"id": "call_stub", "type": "function",
                                "function": {"name": "get_status", "arguments": "{}"}}]}}],
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
    a = ap.parse_args()
    LOG = a.log
    HTTPServer(("127.0.0.1", a.port), H).serve_forever()


if __name__ == "__main__":
    main()
