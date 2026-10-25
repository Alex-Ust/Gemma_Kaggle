"""view: bounded repository reading for the scouts.

Usage (positional_args after --):
  view.py -- <path> [<start> [<end>]]   print a region of a file with line numbers (max 200 lines)
  view.py -- def <name>                 print the whole function or class named <name>
  view.py -- grep <text>                list lines containing the exact text (max 40 hits)

A shared budget (MAX_CALLS calls or MAX_SECS seconds across all scouts of one task) is kept in
/tmp/.scout_budget.json; once it is used up every call returns a stop message.
"""
import ast
import json
import os
import re
import subprocess
import sys
import time

MAX_CALLS = 18
MAX_SECS = 150
BUDGET = "/tmp/.scout_budget.json"
MAX_LINES = 200
STOP = ("READING BUDGET USED UP ({} calls or {} seconds shared by the three scouts). Do not call any tool again. "
        "Answer now with your report in the required format, using what you have already seen.")


def find_root():
    for c in [os.environ.get("PWD"), "/workspace", os.getcwd()]:
        if c and os.path.isdir(c) and (os.path.isdir(os.path.join(c, ".git")) or os.path.exists(os.path.join(c, "pyproject.toml"))
                                       or os.path.exists(os.path.join(c, "setup.py"))):
            return c
    return "/workspace" if os.path.isdir("/workspace") else os.getcwd()


def task_key(root):
    """Identify the current task: HEAD commit plus the creation time of .git (fresh per task)."""
    try:
        head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True).stdout.strip()[:12]
        return f"{head}-{int(os.stat(os.path.join(root, '.git')).st_ctime)}"
    except Exception:
        return "unknown"


def charge(root):
    """Return (ok, used, seconds) after charging one call to the shared per-task budget."""
    now = time.time()
    key = task_key(root)
    budget = os.path.join(root, ".git", "scout_budget.json") if os.path.isdir(os.path.join(root, ".git")) else BUDGET
    try:
        d = json.load(open(budget))
        if d.get("key") != key:
            raise ValueError("other task")
    except Exception:
        d = {"key": key, "n": 0, "t0": now}
    d["n"] = int(d.get("n", 0)) + 1
    d.setdefault("t0", now)
    try:
        with open(budget, "w") as f:
            json.dump(d, f)
    except Exception:
        pass
    secs = now - float(d["t0"])
    return (d["n"] <= MAX_CALLS and secs <= MAX_SECS), d["n"], secs


def budget_line(used, secs):
    left = max(0, MAX_CALLS - used)
    return f"[view budget: {left} calls and {max(0, int(MAX_SECS - secs))} s left for all scouts]"


def print_region(root, path, start, end):
    p = os.path.join(root, path)
    if not os.path.isfile(p):
        hits = subprocess.run(["git", "ls-files", "--", f"*{os.path.basename(path)}"], cwd=root, capture_output=True, text=True).stdout.split()
        print(f"No file {path}." + (f" Similar: {' '.join(hits[:8])}" if hits else ""))
        return
    lines = open(p, encoding="utf-8", errors="replace").read().splitlines()
    n = len(lines)
    s = max(1, start or 1)
    e = min(n, end or (s + 119))
    if e - s + 1 > MAX_LINES:
        e = s + MAX_LINES - 1
    print(f"{path} lines {s}-{e} of {n}")
    for i in range(s, e + 1):
        print(f"{i:5d}| {lines[i-1]}")


def print_def(root, name):
    out = subprocess.run(["git", "grep", "-n", "-E", rf"^[[:space:]]*(async[[:space:]]+def|def|class)[[:space:]]+{re.escape(name)}([^A-Za-z0-9_]|$)", "--", "*.py"],
                         cwd=root, capture_output=True, text=True).stdout.splitlines()
    out = [l for l in out if not re.search(r"(^|/)(tests?|testing)/|test_", l.split(":")[0])] or out
    if not out:
        print(f"No definition of {name} found. Try grep with a shorter name.")
        return
    shown = 0
    for hit in out[:3]:
        path, line = hit.split(":")[0], int(hit.split(":")[1])
        p = os.path.join(root, path)
        src = open(p, encoding="utf-8", errors="replace").read()
        end = None
        try:
            tree = ast.parse(src)
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.name == name and node.lineno <= line <= node.lineno + 1:
                    start = min([node.lineno] + [d.lineno for d in node.decorator_list])
                    end = node.end_lineno
                    line = start
                    break
        except SyntaxError:
            pass
        if end is None:
            end = line + 60
        if end - line + 1 > MAX_LINES:
            end = line + MAX_LINES - 1
            print(f"(definition longer than {MAX_LINES} lines, truncated)")
        print_region(root, path, line, end)
        shown += 1
        if shown >= 2:
            break
    if len(out) > shown:
        print("Other definitions: " + "; ".join(h.split(":")[0] + ":" + h.split(":")[1] for h in out[shown:6]))


def print_grep(root, text):
    r = subprocess.run(["git", "grep", "-n", "-F", "--", text], cwd=root, capture_output=True, text=True)
    hits = r.stdout.splitlines()
    if not hits:
        print(f"No line contains: {text}")
        return
    src = [h for h in hits if not re.search(r"(^|/)(tests?|testing|docs|docs_src|examples)/|test_", h.split(":")[0])]
    other = [h for h in hits if h not in src]
    for h in src[:30]:
        print(h[:200])
    if other:
        print(f"... and {len(other)} hits in tests/docs/examples:")
        for h in other[:10]:
            print(h[:200])
    if len(src) > 30:
        print(f"... {len(src) - 30} more source hits; use a more specific text")


def main():
    argv = sys.argv[1:]
    if "--" in argv:
        argv = argv[argv.index("--") + 1:]
    root = find_root()
    ok, used, secs = charge(root)
    if not ok:
        print(STOP.format(MAX_CALLS, MAX_SECS))
        return
    if not argv:
        print("usage: view <path> [start [end]] | view def <name> | view grep <text>")
    elif argv[0] == "def" and len(argv) >= 2:
        print_def(root, argv[1].strip("`'\" ()"))
    elif argv[0] == "grep" and len(argv) >= 2:
        print_grep(root, " ".join(argv[1:]))
    else:
        path = argv[0].strip("`'\" ")
        nums = [int(re.sub(r"\D", "", a) or 0) for a in argv[1:3]]
        if len(nums) == 1 and "-" in argv[1]:
            a, b = argv[1].split("-", 1)
            nums = [int(a or 1), int(b or 0)]
        start = nums[0] if nums else None
        end = nums[1] if len(nums) > 1 else None
        print_region(root, path, start, end)
    print(budget_line(used, secs))


if __name__ == "__main__":
    main()
