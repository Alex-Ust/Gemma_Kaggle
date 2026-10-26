"""Dump the OpenAI-format tool declarations the harness sends to vLLM for a bundle (for SFT rendering fidelity).
Usage: .venv/bin/python scripts/dump_tools.py submissions/v12_think1024 -o research/lora/tools.json
"""
import json, sys, argparse
sys.path.insert(0, "vendor/src")
import yaml
from pathlib import Path
from google.adk.tools import FunctionTool
from google.adk.models import lite_llm
from swegemma.tools import create_tools

ap = argparse.ArgumentParser(); ap.add_argument("bundle"); ap.add_argument("-o", default="research/lora/tools.json"); a = ap.parse_args()
cfg = yaml.safe_load(Path(a.bundle, "agent.yaml").read_text().replace("!include", ""))
names = [t for t in cfg.get("tools", []) if isinstance(t, str)]
funcs = create_tools(None)
tools = []
for n in names:
    decl = FunctionTool(funcs[n])._get_declaration()
    tools.append(lite_llm._function_declaration_to_tool_param(decl))
# skills toolset (run_skill_script / load_skill) if the bundle has skills
if Path(a.bundle, "skills").is_dir():
    try:
        from google.adk.tools.skill_toolset import SkillToolset
        from google.adk.skills import load_skill_from_dir
        import asyncio
        skills = [load_skill_from_dir(p) for p in sorted(Path(a.bundle, "skills").iterdir()) if p.is_dir()]
        ts = SkillToolset(skills=skills)
        for t in asyncio.run(ts.get_tools()):
            tools.append(lite_llm._function_declaration_to_tool_param(t._get_declaration()))
    except Exception as e:
        print("skills toolset failed:", type(e).__name__, str(e)[:200])
json.dump(tools, open(a.o, "w"), indent=1)
print("tools:", [t["function"]["name"] for t in tools], "->", a.o)
