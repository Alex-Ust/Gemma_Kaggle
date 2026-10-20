"""Render a logged OpenAI chat request through Gemma 4's chat template (what the model actually reads).

  render_prompt.py stub.jsonl [index] > prompt.txt
"""
import json
import sys

import jinja2


def render(req, template_path="research/gemma_template/chat_template.jinja"):
    env = jinja2.Environment(loader=jinja2.FileSystemLoader("."), trim_blocks=False)
    env.globals["raise_exception"] = lambda m: (_ for _ in ()).throw(Exception(m))
    tpl = env.from_string(open(template_path).read())
    msgs = []
    for m in req["messages"]:
        m = dict(m)
        for tc in m.get("tool_calls") or []:
            if isinstance(tc["function"].get("arguments"), str):
                tc["function"]["arguments"] = json.loads(tc["function"]["arguments"])
        msgs.append(m)
    kw = req.get("chat_template_kwargs") or {}
    return tpl.render(messages=msgs, tools=req.get("tools"), add_generation_prompt=True, bos_token="<bos>", **kw)


if __name__ == "__main__":
    lines = open(sys.argv[1]).read().splitlines()
    i = int(sys.argv[2]) if len(sys.argv) > 2 else -1
    sys.stdout.write(render(json.loads(lines[i])))
