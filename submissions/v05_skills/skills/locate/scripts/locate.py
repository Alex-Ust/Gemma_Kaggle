"""Rank the repository's Python functions/classes by relevance to an issue description.

Prints the most likely files to edit, with the best-matching symbols and their line ranges.
Stdlib only: runs inside the offline sandbox.

  locate.py --query "<issue text or keywords>" [--k 6] [--root /workspace]
"""
import argparse
import ast
import math
import os
import re
import sys
from collections import Counter, defaultdict

SKIP_DIRS = {".git", "__pycache__", "node_modules", "build", "dist", ".venv", "venv", "site-packages",
             ".tox", ".mypy_cache", ".pytest_cache", "site", "htmlcov", ".eggs"}
STOP = set("""a an the and or not of to in on for with without is are was were be been being it its this that
these those as at by from if then else when while do does did done can could should would will shall may might
must have has had i we you he she they them our your my me us so but than too very just also only any all some
no yes there here what which who whom whose how why where after before into onto over under up down out about
use used using get set new make like want need see seems issue bug fix error problem expected actual behavior
behaviour example code python version case cases work works working return returns returned value values
true false none self cls def class import let currently instead same other because e g ie etc one two
fixes fixed closes https http www github com pull request pr discussion transcript ai disclaimer checklist
tests test coverage documentation docs prompt model link team member typo description summary details thanks
please would""".split())

# Non-library directories: still searchable, but ranked lower.
AUX_DIRS = ("scripts/", "examples/", "benchmarks/", "docs/", "tools/", "bench/", "demo/")


def clean_query(q):
    q = re.sub(r"<!--.*?-->", " ", q, flags=re.S)  # PR template comments
    q = re.sub(r"https?://\S+", " ", q)
    q = re.sub(r"^\s*[-*]\s*\[[ xX]\].*$", " ", q, flags=re.M)  # checklist lines
    q = re.sub(r"</?(details|summary)>", " ", q)
    return q

CAMEL = re.compile(r"[A-Z]+(?=[A-Z][a-z])|[A-Z]?[a-z]+|[A-Z]+|\d+")


def find_root(cli_root):
    cands = [cli_root, sys.path[0] if sys.path else None, os.environ.get("PWD"), "/workspace", os.getcwd()]
    for c in cands:
        if c and os.path.isdir(c) and (os.path.isdir(os.path.join(c, ".git"))
                                       or os.path.exists(os.path.join(c, "pyproject.toml"))
                                       or os.path.exists(os.path.join(c, "setup.py"))):
            return c
    return cli_root or os.getcwd()


def split_ident(tok):
    parts = []
    for p in re.split(r"[_\W]+", tok):
        if p:
            parts.extend(m.lower() for m in CAMEL.findall(p))
    return parts


def tokenize(text):
    out = []
    for tok in re.findall(r"[A-Za-z_][A-Za-z0-9_]*", text):
        low = tok.lower()
        if len(low) > 1 and low not in STOP:
            out.append(low)
        sub = split_ident(tok)
        if len(sub) > 1:
            out.extend(s for s in sub if len(s) > 1 and s not in STOP)
    return out


def query_terms(q):
    """Plain terms get weight 1; code-looking identifiers get extra weight."""
    w = Counter()
    for t in tokenize(q):
        w[t] += 1.0
    code_like = set(re.findall(r"`([^`]{2,80})`", q))
    code_like |= set(re.findall(r"\b[A-Za-z_]*[a-z][A-Z][A-Za-z0-9_]*\b", q))  # camelCase / CamelCase
    code_like |= set(re.findall(r"\b[A-Za-z]+_[A-Za-z0-9_]+\b", q))  # snake_case
    code_like |= set(re.findall(r"\b[A-Za-z_]+(?:\.[A-Za-z_]+)+\b", q))  # dotted.path
    code_like |= set(re.findall(r"\b([A-Za-z_][A-Za-z0-9_]*)\(", q))  # call(
    exact = set()
    for c in code_like:
        for t in re.findall(r"[A-Za-z_][A-Za-z0-9_]*", c):
            if len(t) > 2 and t.lower() not in STOP:
                exact.add(t.lower())
                w[t.lower()] += 2.0
    return w, exact


class Unit:
    __slots__ = ("path", "name", "kind", "start", "end", "tf", "length", "names")

    def __init__(self, path, name, kind, start, end, text_tokens, names):
        self.path, self.name, self.kind, self.start, self.end = path, name, kind, start, end
        self.tf = Counter(text_tokens)
        self.length = len(text_tokens)
        self.names = names


def node_tokens(node):
    toks = []
    for n in ast.walk(node):
        if isinstance(n, ast.Name):
            toks.append(n.id)
        elif isinstance(n, ast.Attribute):
            toks.append(n.attr)
        elif isinstance(n, ast.arg):
            toks.append(n.arg)
        elif isinstance(n, ast.Constant) and isinstance(n.value, str) and len(n.value) < 300:
            toks.append(n.value)
        elif isinstance(n, ast.keyword) and n.arg:
            toks.append(n.arg)
    return tokenize(" ".join(toks))


def collect_units(root):
    units = []
    for dirpath, dirnames, filenames in os.walk(root):
        rel_dir = os.path.relpath(dirpath, root)
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and not d.startswith(".")]
        parts = set(rel_dir.replace("\\", "/").split("/"))
        is_test_dir = bool(parts & {"tests", "test", "testing"})
        for fn in filenames:
            # skip hidden files: the harness drops its skill wrapper (.adk_exec_*.py) into the repo root
            if not fn.endswith(".py") or fn.startswith("."):
                continue
            if is_test_dir or fn.startswith("test_") or fn.endswith("_test.py") or fn == "conftest.py":
                continue
            path = os.path.normpath(os.path.join(rel_dir, fn)).replace("\\", "/")
            full = os.path.join(dirpath, fn)
            try:
                if os.path.getsize(full) > 800_000:
                    continue
                src = open(full, encoding="utf-8", errors="replace").read()
                tree = ast.parse(src)
            except (SyntaxError, ValueError, OSError):
                continue
            path_toks = tokenize(path.replace("/", " ").replace(".py", ""))
            mod_toks = []
            for node in tree.body:
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    visit(node, path, path_toks, units, prefix="")
                else:
                    mod_toks.extend(node_tokens(node))
            doc = ast.get_docstring(tree) or ""
            units.append(Unit(path, "<module>", "module", 1, len(src.splitlines()),
                              path_toks * 2 + tokenize(doc) + mod_toks[:400], set()))
    return units


def visit(node, path, path_toks, units, prefix):
    qual = f"{prefix}{node.name}"
    name_toks = tokenize(node.name)
    doc = ast.get_docstring(node) or ""
    kind = "class" if isinstance(node, ast.ClassDef) else "def"
    if kind == "class":
        # class unit = header + docstring + attribute names, methods become their own units
        body_toks = []
        for b in node.body:
            if not isinstance(b, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                body_toks.extend(node_tokens(b))
        bases = tokenize(" ".join(ast.unparse(b) for b in node.bases)) if hasattr(ast, "unparse") else []
        toks = name_toks * 4 + path_toks + bases * 2 + tokenize(doc) + body_toks
        end = getattr(node, "end_lineno", node.lineno)
        units.append(Unit(path, qual, kind, node.lineno, end, toks, {node.name.lower()}))
        for b in node.body:
            if isinstance(b, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                visit(b, path, path_toks, units, prefix=qual + ".")
    else:
        cls_toks = tokenize(prefix.rstrip(".")) if prefix else []
        toks = name_toks * 4 + cls_toks * 2 + path_toks + tokenize(doc) + node_tokens(node)
        end = getattr(node, "end_lineno", node.lineno)
        start = node.decorator_list[0].lineno if node.decorator_list else node.lineno
        units.append(Unit(path, qual, kind, start, end, toks, {node.name.lower()}))


def rank(root, query, k1=1.2, b=0.75):
    units = collect_units(root)
    if not units:
        return [], {}
    w, exact = query_terms(clean_query(query))
    n = len(units)
    df = Counter()
    for u in units:
        for t in u.tf:
            if t in w:
                df[t] += 1
    avg = sum(u.length for u in units) / n or 1.0
    scored = []
    for u in units:
        s = 0.0
        for t, qw in w.items():
            tf = u.tf.get(t)
            if not tf:
                continue
            idf = math.log(1 + (n - df[t] + 0.5) / (df[t] + 0.5))
            s += qw * idf * tf * (k1 + 1) / (tf + k1 * (1 - b + b * u.length / avg))
        if u.names & exact:
            s *= 1.6  # the issue names this exact symbol
        if u.path.startswith(AUX_DIRS):
            s *= 0.5
        if s > 0:
            scored.append((s, u))
    scored.sort(key=lambda x: -x[0])
    by_file = defaultdict(list)
    for s, u in scored:
        by_file[u.path].append((s, u))
    file_scores = {}
    for p, lst in by_file.items():
        top = [s for s, _ in lst[:3]]
        file_scores[p] = top[0] + 0.25 * sum(top[1:])
    return sorted(file_scores.items(), key=lambda x: -x[1]), by_file


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--query", "-q", default="")
    ap.add_argument("--k", type=int, default=6)
    ap.add_argument("--root", default=None)
    ap.add_argument("rest", nargs="*")
    a, unknown = ap.parse_known_args()
    query = " ".join([a.query] + a.rest + [u for u in unknown if not u.startswith("-")]).strip()
    if not query:
        print("usage: locate.py --query '<issue text or keywords>'")
        return
    root = find_root(a.root)
    files, by_file = rank(root, query)
    if not files:
        print(f"no matches under {root}")
        return
    print(f"Most relevant source files for the issue (root={root}); best symbols with line ranges:")
    for path, fs in files[: a.k]:
        syms = [u for _, u in by_file[path] if u.kind != "module"][:3]
        sym_txt = ", ".join(f"{u.name} L{u.start}-{u.end}" for u in syms) or "(module level)"
        print(f"{fs:6.1f}  {path}: {sym_txt}")
    print("Read the top symbol's line range with read_file before editing; test files are excluded here.")


if __name__ == "__main__":
    main()
