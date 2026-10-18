"""Validate a submission directory against the harness rules and pack it into submission.zip.

Usage: python3 scripts/pack.py submissions/<name>
Writes submissions/out/<name>/submission.zip
"""
import re
import sys
import zipfile
from pathlib import Path

import yaml

ALLOWED_EXT = {".yaml", ".yml", ".md", ".txt", ".py", ".json", ".safetensors"}
ROOTS = ["agent.yaml", "agent.yml", "root_agent.yaml", "root_agent.yml"]
ALLOWED_MODELS = {
    "gemma-4-31b-it-qat-w4a16-ct",
    "gemma-4-12b-it-qat-w4a16-ct",
    "gemma-4-e4b-it-qat-w4a16-ct",
    "gemma-4-e2b-it-qat-w4a16-ct",
}
TOOLS = {"run_command", "read_file", "edit_file", "write_file", "get_status", "submit_patch",
         "get_code_neighbors", "search_similar_code", "get_code_subgraph"}


class Loader(yaml.SafeLoader):
    pass


def _include(loader, node):
    rel = loader.construct_scalar(node)
    path = (Path(loader.name).parent / rel).resolve()
    if not path.is_file():
        raise SystemExit(f"FAIL: !include {rel} not found (from {loader.name})")
    if path.suffix in (".yaml", ".yml"):
        return load_yaml(path)
    text = path.read_text(encoding="utf-8")
    # ADK interpolates {name} placeholders from session state; stray braces break the prompt
    bad = set(re.findall(r"\{([^{}]*)\}", text)) - {"problem_description", "hints"}
    if bad:
        raise SystemExit(f"FAIL: {rel} has template placeholders {sorted(bad)[:5]} (ADK would try to fill them)")
    return text


Loader.add_constructor("!include", _include)


def load_yaml(path):
    with open(path, encoding="utf-8") as f:
        loader = Loader(f)
        loader.name = str(path)
        try:
            return loader.get_single_data()
        finally:
            loader.dispose()


def check_agent(cfg, base, models, seen):
    models.add(cfg.get("model"))
    for t in cfg.get("tools", []) or []:
        if isinstance(t, str):
            if t not in TOOLS:
                raise SystemExit(f"FAIL: unknown tool {t}")
        elif isinstance(t, dict) and "agent_tool" in t:
            sub = base / t["agent_tool"]["config_path"]
            check_agent(load_yaml(sub), sub.parent, models, seen)
    for s in cfg.get("sub_agents", []) or []:
        sub = base / s["config_path"]
        check_agent(load_yaml(sub), sub.parent, models, seen)
    gc = cfg.get("generate_content_config") or {}
    if gc.get("max_output_tokens", 0) > 32768:
        raise SystemExit("FAIL: max_output_tokens > 32768")


def main(d):
    root = Path(d).resolve()
    roots = [r for r in ROOTS if (root / r).exists()]
    assert len(roots) == 1, f"FAIL: need exactly one root config, found {roots}"
    files = [p for p in root.rglob("*") if p.is_file() and p.name != ".DS_Store"]
    for p in root.rglob("*"):
        assert not p.is_symlink(), f"FAIL: symlink {p}"
    bad = [str(p.relative_to(root)) for p in files if p.suffix.lower() not in ALLOWED_EXT]
    assert not bad, f"FAIL: disallowed extensions {bad}"
    total = sum(p.stat().st_size for p in files)
    assert total < 3 * 1024**3, "FAIL: > 3 GiB"
    models = set()
    check_agent(load_yaml(root / roots[0]), root, models, set())
    assert len(models) == 1 and models <= ALLOWED_MODELS, f"FAIL: models {models}"
    ev = root / "eval_config.yaml"
    if ev.exists():
        e = yaml.safe_load(ev.read_text())["evaluation"]
        print("eval_config:", e)
    # Kaggle rejects any other file name
    out = root.parent / "out" / root.name / "submission.zip"
    out.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        for p in sorted(files):
            info = zipfile.ZipInfo(str(p.relative_to(root)), date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            zf.writestr(info, p.read_bytes())
    with zipfile.ZipFile(out) as zf:
        assert zf.testzip() is None
        names = zf.namelist()
    print(f"OK model={models.pop()} files={names} -> {out} ({out.stat().st_size} bytes)")


if __name__ == "__main__":
    main(sys.argv[1])
