"""Check the current working-tree change in one call, within a fixed time budget.

1. Lists changed files and flags problems the grader will punish: scratch files left in the repo,
   edited test files or runner config (those edits are discarded before grading).
2. Compiles every changed .py file (syntax / indentation errors).
3. Imports every changed library module in a fresh interpreter (NameError at import time, broken imports),
   in parallel with step 4.
4. Finds existing tests that reference the changed modules or functions and runs them; when they are quick,
   each failure is re-run on the untouched HEAD and labelled pre-existing or caused by the edit.

The whole check stays under BUDGET seconds: on heavy repositories (big imports, slow test suites) a timed-out
step is reported as slow, never as an error, and the agent is told not to retry it.

Stdlib only: runs inside the offline sandbox.
  check.py [names of changed functions or test files ...] [--tests "tests/test_x.py::test_y"] [--no-tests]
"""
import argparse
import ast
import atexit
import keyword
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time

T0 = time.time()
BUDGET = 45  # seconds for the whole check; the harness kills a skill script at its command timeout (90 s)
TEST_TIMEOUT = 28
IMPORT_TIMEOUT = 20
BASELINE_MAX_FIRST_RUN = 12  # compare with HEAD only when the first test run was this quick

TEST_RE = re.compile(r"(^|/)(tests?|testing)/|(^|/)test_[^/]*\.py$|_test\.py$")
CONFIG_FILES = {"conftest.py", "pytest.ini", "pyproject.toml", "tox.ini", "setup.cfg", ".pytest.ini"}
MAX_OUT = 3500
DIFF_CHARS = 1500


def left():
    return BUDGET - (time.time() - T0)


def find_root(cli_root):
    cands = [cli_root, sys.path[0] if sys.path else None, os.environ.get("PWD"), "/workspace", os.getcwd()]
    for c in cands:
        if c and os.path.isdir(os.path.join(c, ".git")):
            return c
    return cli_root or os.getcwd()


def sh(cmd, cwd, timeout=60, env=None):
    try:
        r = subprocess.run(cmd, cwd=cwd, shell=isinstance(cmd, str), capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=timeout, env=env)
        return r.returncode, r.stdout, r.stderr
    except subprocess.TimeoutExpired as e:
        so = e.stdout or ""
        if isinstance(so, bytes):
            so = so.decode("utf-8", "replace")
        return -9, so, f"timed out after {timeout}s"


# Everything check starts is stopped before it exits, also when the harness stops check itself
# (SIGTERM from its command timeout): no test process may outlive check and keep writing to /workspace.
LIVE_JOBS = []
WORKTREES = []
READ_LIMIT = 200_000  # bytes of each output file kept (the tail: the pytest summary is at the end)


def kill_group(p):
    try:
        os.killpg(p.pid, signal.SIGKILL)
    except OSError:
        try:
            p.kill()
        except OSError:
            pass


def cleanup():
    for job in list(LIVE_JOBS):
        kill_group(job.p)
    del LIVE_JOBS[:]
    for root, wt in list(WORKTREES):
        try:
            subprocess.run(["git", "worktree", "remove", "--force", wt], cwd=root, capture_output=True, timeout=3)
        except Exception:
            pass
        shutil.rmtree(wt, ignore_errors=True)
    del WORKTREES[:]


def on_signal(signum, frame):
    cleanup()
    os._exit(128 + signum)


def read_tail(f):
    f.flush()
    size = f.seek(0, 2)
    f.seek(max(0, size - READ_LIMIT))
    return f.read().decode("utf-8", "replace")


class Job:
    """A subprocess in its own session with output in temp files (no pipe dead-locks when several run at once)."""

    def __init__(self, cmd, cwd, env=None):
        self.t0 = time.time()
        self.out = tempfile.TemporaryFile()
        self.err = tempfile.TemporaryFile()
        self.p = subprocess.Popen(cmd, cwd=cwd, stdin=subprocess.DEVNULL, stdout=self.out, stderr=self.err,
                                  env=env, start_new_session=True)
        LIVE_JOBS.append(self)

    def wait(self, deadline):
        """(returncode or -9 on timeout, stdout, stderr, seconds)."""
        try:
            self.p.wait(timeout=max(0.5, deadline - time.time()))
            code = self.p.returncode
        except subprocess.TimeoutExpired:
            code = -9
        kill_group(self.p)  # on timeout the whole test run; after a normal exit any leftover children
        self.p.wait()
        if self in LIVE_JOBS:
            LIVE_JOBS.remove(self)
        return code, read_tail(self.out), read_tail(self.err), time.time() - self.t0


def harness_file(root, f):
    """conftest.py / pytest.ini written by the evaluation harness itself (not an agent edit)."""
    if f not in ("conftest.py", "pytest.ini"):
        return False
    try:
        txt = open(os.path.join(root, f), encoding="utf-8", errors="replace").read(4000)
    except OSError:
        return False
    return "SWE-gemma" in txt or "Hermetic test discovery" in txt or txt.startswith("[pytest]\naddopts = -p no:anyio")


def changed_files(root):
    _, tracked, _ = sh(["git", "diff", "--name-only", "HEAD"], root)
    _, untracked, _ = sh(["git", "ls-files", "--others", "--exclude-standard"], root)
    t = [f for f in tracked.split("\n") if f and not harness_file(root, f)]
    u = [f for f in untracked.split("\n") if f and not harness_file(root, f)]
    return t, u


def module_and_base(root, path):
    """(dotted module, directory to put on sys.path) for a changed .py file, else (None, None).

    Walks up from the file while directories are packages (have __init__.py), so src/ layouts and
    monorepos (package code under a plain sub-directory) resolve to the importable name."""
    if not path.endswith(".py"):
        return None, None
    root = os.path.abspath(root)
    d = os.path.dirname(os.path.join(root, path))
    parts = [os.path.basename(path)[:-3]]
    while d != root and d.startswith(root) and os.path.exists(os.path.join(d, "__init__.py")):
        parts.insert(0, os.path.basename(d))
        d = os.path.dirname(d)
    if parts[-1] == "__init__":
        parts = parts[:-1]
    if not parts or not all(p.isidentifier() for p in parts):
        return None, None
    return ".".join(parts), d


def module_name(root, path):
    return module_and_base(root, path)[0]


def with_pythonpath(dirs):
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join([d for d in dirs if d] + [env.get("PYTHONPATH", "")])
    return env


GENERIC = {"utils", "util", "base", "core", "main", "compat", "types", "models", "common", "helpers",
           "exceptions", "errors", "config", "constants", "_compat", "__main__", "v1", "v2", "shared"}
# function names too common to say anything about which test file covers a change
GENERIC_NAMES = GENERIC | {"get", "set", "run", "call", "init", "update", "render", "parse", "load", "save", "read",
                           "write", "close", "open", "apply", "build", "create", "process", "handle", "validate",
                           "check", "items", "keys", "values", "copy", "name", "value", "data", "self", "cls",
                           "test", "tests", "none", "true", "false", "all", "the", "and", "function", "functions",
                           "changed", "method", "class", "file", "py"}


def changed_names(root, files):
    """Names of the innermost functions/classes whose lines the working-tree change touches."""
    names = []
    for f in files:
        p = os.path.join(root, f)
        if not f.endswith(".py") or not os.path.exists(p):
            continue
        code, so, _ = sh(["git", "diff", "-U0", "HEAD", "--", f], root, timeout=10)
        lines = set()
        for m in re.finditer(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@", so, re.M):
            start, n = int(m.group(1)), int(m.group(2) or 1)
            lines.update(range(start, start + max(n, 1)))
        if not lines and code == 0 and not so:
            continue  # untracked new file: no specific function
        try:
            tree = ast.parse(open(p, encoding="utf-8", errors="replace").read())
        except (SyntaxError, ValueError):
            continue
        hits = []
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                end = getattr(node, "end_lineno", node.lineno) or node.lineno
                if any(node.lineno <= ln <= end for ln in lines):
                    hits.append((end - node.lineno, node.name))
        for _, n in sorted(hits):
            if n not in names:
                names.append(n)
    return names


def useful_names(names):
    out = []
    for n in names:
        n = n.strip("_")
        if len(n) >= 4 and n.lower() not in GENERIC_NAMES and not keyword.iskeyword(n) and n not in out:
            out.append(n)
    return out[:8]


def related_tests(root, modules, names=(), limit=2):
    """Test files (test_*.py / *_test.py) that import or mention the changed modules/functions, most specific first."""
    test_files = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if not d.startswith(".") and d not in ("node_modules", "__pycache__")]
        rel = os.path.relpath(dirpath, root)
        for fn in filenames:
            if fn.endswith(".py") and (fn.startswith("test_") or fn.endswith("_test.py")):
                test_files.append(os.path.normpath(os.path.join(rel, fn)).replace("\\", "/"))
    name_res = [re.compile(rf"\b{re.escape(n)}\b") for n in useful_names(names)]
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
        if score or not modules:
            score += sum(2 for r in name_res if r.search(src))
        if score:
            scored.append((score, -len(src), tf))
    scored.sort(reverse=True)
    return [tf for _, _, tf in scored[:limit]]


def baseline_failures(root, nodeids, bases, timeout):
    """Run the given test ids on the untouched HEAD in a temporary git worktree (the workspace is not modified).

    Returns the set of ids that also fail without the change, or None if the check could not run."""
    wt = tempfile.mkdtemp(prefix="check_base_")
    WORKTREES.append((root, wt))
    try:
        code, _, _ = sh(["git", "worktree", "add", "--detach", "-f", wt, "HEAD"], root, timeout=max(3, timeout / 2))
        if code != 0:
            return None
        rel_bases = [os.path.join(wt, os.path.relpath(b, os.path.abspath(root))) for b in bases]
        job = Job([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", *nodeids], wt,
                  env=with_pythonpath(rel_bases + [wt]))
        code, so, _, _ = job.wait(time.time() + max(2, timeout - 2))
        if code == -9:
            return None
        bad = set(re.findall(r"^(?:FAILED|ERROR) (\S+)", so, re.M))
        return {n for n in nodeids if any(b == n or b.startswith(n) for b in bad)} if bad else set()
    finally:
        sh(["git", "worktree", "remove", "--force", wt], root, timeout=10)
        sh(["git", "worktree", "prune"], root, timeout=10)
        shutil.rmtree(wt, ignore_errors=True)
        if (root, wt) in WORKTREES:
            WORKTREES.remove((root, wt))


def split_cli_words(root, words):
    """Model-supplied words: test files / node ids become pytest targets, identifiers become function names."""
    targets, names = [], []
    for w in re.split(r"[\s,;]+", " ".join(words)):
        w = w.strip("'\"`()[]{}")
        if not w:
            continue
        path = w.split("::")[0]
        if path.endswith(".py") and TEST_RE.search(path) and os.path.isfile(os.path.join(root, path)):
            targets.append(w)
            continue
        for ident in re.findall(r"[A-Za-z_][A-Za-z0-9_]*", w.split("(")[0]):
            names.append(ident.split(".")[-1])
    return targets, names


SLOW_TESTS = ("the existing tests did not finish within {t:.0f} s: this repository's tests are slow here. Do not run "
              "these tests again. Check the changed behaviour once with a short timeout 20 python -c snippet, or "
              "submit.")


def main():
    atexit.register(cleanup)
    for s in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
        try:
            signal.signal(s, on_signal)
        except (ValueError, OSError):
            pass
    ap = argparse.ArgumentParser()
    ap.add_argument("--tests", default="")
    ap.add_argument("--no-tests", action="store_true")
    ap.add_argument("--timeout", type=int, default=TEST_TIMEOUT)
    ap.add_argument("--root", default=None)
    ap.add_argument("words", nargs="*")
    a, unknown = ap.parse_known_args()
    root = find_root(a.root)
    root_abs = os.path.abspath(root)
    cli_targets, cli_names = split_cli_words(root, a.words + [u for u in unknown if not u.startswith("-")])
    out = []
    tracked, untracked = changed_files(root)
    src = [f for f in tracked + untracked if not TEST_RE.search(f) and os.path.basename(f) not in CONFIG_FILES]
    bad_tests = [f for f in tracked + untracked if TEST_RE.search(f) or os.path.basename(f) in CONFIG_FILES]
    if not src:
        out.append("changed source files: NONE - nothing will be graded. An unedited tree scores zero: make your "
                   "edit to the source file now with edit_file.")
        if bad_tests:
            out.append(f"test/config files changed (discarded by the grader): {bad_tests}")
        print("\n".join(out))
        return
    out.append(f"changed source files: {src}")
    if bad_tests:
        out.append(f"WARNING test/config files changed (discarded by grader, restore with git checkout -- or rm): {bad_tests}")
    scratch = [f for f in untracked if f in src and not f.startswith(("src/",)) and "/" not in f]
    if scratch:
        out.append(f"WARNING untracked files at repo root will be part of the patch; delete if scratch: {scratch}")
    ok = True
    for f in src:
        if f.endswith(".py") and os.path.exists(os.path.join(root, f)):
            try:
                with open(os.path.join(root, f), "rb") as fh:
                    compile(fh.read(), f, "exec", dont_inherit=True)
            except (SyntaxError, ValueError) as e:
                ok = False
                where = f" line {e.lineno}" if getattr(e, "lineno", None) else ""
                out.append(f"SYNTAX ERROR {f}{where}: {type(e).__name__}: {getattr(e, 'msg', str(e))}"[:400])
    mb = [module_and_base(root, f) for f in src]
    mods = [m for m, _ in mb if m]
    bases = sorted({b for m, b in mb if m})
    import_roots = {root_abs, os.path.join(root_abs, "src")}

    # start the import checks, then the tests, and let them run side by side
    imports = []
    for f, (m, b) in zip(src, mb):
        # import only library code: modules inside a package or at the repo/src root.
        # Docs examples and scripts run app code on import, so they get the syntax check only.
        if not ok or not m or f.startswith(("docs_src/", "docs/", "doc/", "scripts/", "examples/", "benchmarks/")):
            continue
        if "." not in m and b not in import_roots:
            continue
        imports.append((m, Job([sys.executable, "-c", f"import {m}"], root, env=with_pythonpath(bases))))
        if len(imports) >= 3:
            break

    test_job = None
    targets = []
    if ok and not a.no_tests:
        if a.tests:
            targets = a.tests.split()
        elif cli_targets:
            targets = cli_targets
        else:
            names = cli_names + changed_names(root, src)
            targets = related_tests(root, mods, names)
        if targets:
            test_job = Job([sys.executable, "-m", "pytest", "--maxfail=3", "-q", "-p", "no:cacheprovider", *targets],
                           root, env=with_pythonpath(bases))

    import_deadline = time.time() + min(IMPORT_TIMEOUT, max(3, left() - 12))
    import_lines = []
    for m, job in imports:
        code, _, se, secs = job.wait(import_deadline)
        if code == -9:
            import_lines.append(f"import of {m} did not finish in {secs:.0f} s (slow import, not an error)")
        elif code != 0:
            ok = False
            last = (se.strip().splitlines() or ["?"])[-1]
            import_lines.append(f"IMPORT FAILED {m}: {last[:300]}")
    out.extend(import_lines)
    if ok:
        out.append("compile + import: OK")

    if a.no_tests:
        pass
    elif test_job is None and not ok:
        out.append("tests not run: fix the error above first")
    elif test_job is None:
        out.append("no related existing tests found; check the behaviour once with a short timeout 20 python -c "
                   "snippet instead")
    else:
        code, so, se, secs = test_job.wait(test_job.t0 + max(5, min(a.timeout, left() - 8)))
        out.append(f"tests run: {' '.join(targets)}")
        if code == -9:
            out.append(SLOW_TESTS.format(t=secs))
        else:
            text = so + "\n" + se
            tail = [l for l in text.splitlines() if re.search(r"\d+ (passed|failed|error|deselected|skipped)", l)]
            out.append((tail[-1:] or ["(no pytest summary line)"])[0][:200])
            failed = re.findall(r"^(?:FAILED|ERROR) (\S+)", so, re.M)[:5]
            pre = None
            if failed and secs <= BASELINE_MAX_FIRST_RUN and left() > 8:
                pre = baseline_failures(root, failed, bases, timeout=min(secs * 2 + 6, left() - 2))
            for n in failed:
                if pre is None:
                    verdict = "could not compare with the original code"
                elif n in pre:
                    verdict = "also fails WITHOUT your change -> pre-existing, ignore it"
                else:
                    verdict = "passes without your change -> your edit changed this behaviour"
                out.append(f"FAILED {n[:150]}: {verdict}")
            errs = [l[:220] for l in text.splitlines() if l.startswith("E ")][:8]
            out.extend(errs)
            if failed:
                out.append("A failure matters only if it checks behaviour the issue did NOT ask to change. A test "
                           "that asserts the old behaviour the issue asks to change is expected to fail (hidden tests "
                           "replace it): keep your fix. Failures from missing fixtures or unrelated imports are "
                           "pre-existing.")
    text = "\n".join(out)[:MAX_OUT]
    diff = source_diff(root, src)
    if diff:
        text += "\n\nyour change (git diff of source files):\n" + diff
    text += f"\n(check took {time.time() - T0:.0f} s)"
    print(text)


def source_diff(root, files, limit=DIFF_CHARS):
    """Compact diff of the changed source files, so the edit can be reviewed without another call."""
    tracked = [f for f in files if f.endswith(".py")]
    if not tracked:
        return ""
    code, so, _ = sh(["git", "diff", "-U1", "HEAD", "--", *tracked], root, timeout=20)
    if code != 0 or not so.strip():
        return ""
    body = "\n".join(l for l in so.splitlines() if not l.startswith(("diff --git", "index ")))
    return body if len(body) <= limit else body[:limit] + "\n... (diff truncated; run git diff for the rest)"


if __name__ == "__main__":
    main()
