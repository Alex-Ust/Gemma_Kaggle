"""Check the current working-tree change in one call.

1. Lists changed files and flags problems the grader will punish: scratch files left in the repo,
   edited test files or runner config (those edits are discarded before grading).
2. Compiles every changed .py file (syntax / indentation errors).
3. Imports every changed module in a fresh interpreter (NameError at import time, broken imports).
4. Finds existing tests that reference the changed modules and runs them (quick, with a timeout).

Stdlib only: runs inside the offline sandbox.
  check.py [--tests "tests/test_x.py::test_y tests/test_z.py"] [--no-tests] [--timeout 60]
"""
import argparse
import os
import py_compile
import re
import subprocess
import sys

TEST_RE = re.compile(r"(^|/)(tests?|testing)/|(^|/)test_[^/]*\.py$|_test\.py$")
CONFIG_FILES = {"conftest.py", "pytest.ini", "pyproject.toml", "tox.ini", "setup.cfg", ".pytest.ini"}
MAX_OUT = 3500


def find_root(cli_root):
    cands = [cli_root, sys.path[0] if sys.path else None, os.environ.get("PWD"), "/workspace", os.getcwd()]
    for c in cands:
        if c and os.path.isdir(os.path.join(c, ".git")):
            return c
    return cli_root or os.getcwd()


def sh(cmd, cwd, timeout=60):
    try:
        r = subprocess.run(cmd, cwd=cwd, shell=isinstance(cmd, str), capture_output=True, text=True,
                           timeout=timeout)
        return r.returncode, r.stdout, r.stderr
    except subprocess.TimeoutExpired as e:
        return -9, e.stdout or "", f"timed out after {timeout}s"


def changed_files(root):
    _, tracked, _ = sh(["git", "diff", "--name-only", "HEAD"], root)
    _, untracked, _ = sh(["git", "ls-files", "--others", "--exclude-standard"], root)
    t = [f for f in tracked.split("\n") if f]
    u = [f for f in untracked.split("\n") if f]
    return t, u


def module_name(root, path):
    """Dotted module for a changed file, or None if it is not importable from root."""
    if not path.endswith(".py"):
        return None
    parts = path[:-3].split("/")
    if parts[0] == "src" and len(parts) > 1:
        parts = parts[1:]
    if parts[-1] == "__init__":
        parts = parts[:-1]
    if not parts or not all(p.isidentifier() for p in parts):
        return None
    return ".".join(parts)


GENERIC = {"utils", "util", "base", "core", "main", "compat", "types", "models", "common", "helpers",
           "exceptions", "errors", "config", "constants", "_compat", "__main__", "v1", "v2", "shared"}


def related_tests(root, modules, limit=3):
    """Test files (test_*.py / *_test.py) that import or mention the changed modules, most specific first."""
    test_files = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if not d.startswith(".") and d not in ("node_modules", "__pycache__")]
        rel = os.path.relpath(dirpath, root)
        for fn in filenames:
            if fn.endswith(".py") and (fn.startswith("test_") or fn.endswith("_test.py")):
                test_files.append(os.path.normpath(os.path.join(rel, fn)).replace("\\", "/"))
    scored = []
    for tf in test_files:
        try:
            src = open(os.path.join(root, tf), encoding="utf-8", errors="replace").read()
        except OSError:
            continue
        score = 0
        base = os.path.basename(tf)[:-3]
        for m in modules:
            leaf = m.split(".")[-1]
            parent = m.split(".")[-2] if "." in m else ""
            if re.search(rf"\b{re.escape(m)}\b", src):
                score += 3  # full dotted path, e.g. from pkg.dependencies.utils import x
            if leaf not in GENERIC:
                if re.search(rf"\b(from|import)\s+[\w.]*\b{re.escape(leaf)}\b", src):
                    score += 2
                if leaf in base:
                    score += 4
            elif parent and parent not in GENERIC and parent in base:
                score += 2
            if base in (f"test_{leaf}", f"{leaf}_test"):
                # test_<module>.py: strong signal; for generic names require the parent package in the path
                if leaf not in GENERIC:
                    score += 6
                elif set(m.split(".")[:-1]) & set(tf.split("/")[:-1]):
                    score += 5
        if score:
            scored.append((score, -len(src), tf))
    scored.sort(reverse=True)
    return [tf for _, _, tf in scored[:limit]]


def summarize_pytest(out):
    lines = out.strip().splitlines()
    tail = [l for l in lines if re.search(r"\d+ (passed|failed|error)", l)]
    fails = [l for l in lines if l.startswith(("FAILED", "ERROR"))][:8]
    errs = [l for l in lines if l.startswith("E ")][:10]
    return "\n".join((tail[-1:] or ["(no summary line)"]) + fails + errs)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tests", default="")
    ap.add_argument("--no-tests", action="store_true")
    ap.add_argument("--timeout", type=int, default=60)
    ap.add_argument("--root", default=None)
    a, _ = ap.parse_known_args()
    root = find_root(a.root)
    out = []
    tracked, untracked = changed_files(root)
    src = [f for f in tracked + untracked if not TEST_RE.search(f) and os.path.basename(f) not in CONFIG_FILES]
    bad_tests = [f for f in tracked + untracked if TEST_RE.search(f) or os.path.basename(f) in CONFIG_FILES]
    out.append(f"changed source files: {src or 'NONE - nothing will be graded'}")
    if bad_tests:
        out.append(f"WARNING test/config files changed (discarded by grader, restore with git checkout -- or rm): {bad_tests}")
    scratch = [f for f in untracked if f in src and not f.startswith(("src/",)) and "/" not in f]
    if scratch:
        out.append(f"WARNING untracked files at repo root will be part of the patch; delete if scratch: {scratch}")
    ok = True
    for f in src:
        if f.endswith(".py") and os.path.exists(os.path.join(root, f)):
            try:
                py_compile.compile(os.path.join(root, f), doraise=True)
            except py_compile.PyCompileError as e:
                ok = False
                out.append(f"SYNTAX ERROR {f}: {str(e).strip()[-400:]}")
    mods = [m for m in (module_name(root, f) for f in src) if m]
    for m in mods:
        if m.startswith(("docs_src", "docs", "scripts", "examples")):
            continue
        code, so, se = sh([sys.executable, "-c", f"import {m}"], root, timeout=60)
        if code != 0:
            ok = False
            last = (se.strip().splitlines() or ["?"])[-1]
            out.append(f"IMPORT FAILED {m}: {last[:300]}")
    if ok:
        out.append("compile + import: OK")
    if not a.no_tests:
        targets = a.tests.split() if a.tests else related_tests(root, mods)
        if targets:
            cmd = [sys.executable, "-m", "pytest", "-x", "-q", "-p", "no:cacheprovider", *targets]
            code, so, se = sh(cmd, root, timeout=a.timeout)
            out.append(f"tests run: {' '.join(targets)}")
            out.append(summarize_pytest(so + "\n" + se) if code != -9 else f"pytest {se}")
            out.append("A failure matters only if it checks behaviour the issue did NOT ask to change. A test that "
                       "asserts the old behaviour the issue asks to change is expected to fail (hidden tests replace "
                       "it): keep your fix. Failures from missing fixtures or unrelated imports are pre-existing.")
        else:
            out.append("no related existing tests found; check behaviour with a short python -c instead")
    text = "\n".join(out)
    print(text[:MAX_OUT])


if __name__ == "__main__":
    main()
