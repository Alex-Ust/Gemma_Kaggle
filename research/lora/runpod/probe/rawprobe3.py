import json, time, urllib.request, sys, copy
from transformers import AutoTokenizer
MODEL = "/kaggle/input/models/google/gemma-4/other/gemma-4-31b-it-qat-w4a16-ct/2"
tools = json.load(open('/workspace/tools.json'))
msgs = json.load(open('/workspace/probe2_msgs.json'))
tok = AutoTokenizer.from_pretrained(MODEL)
def post(body):
    req = urllib.request.Request("http://127.0.0.1:8000/v1/completions", data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    return json.load(urllib.request.urlopen(req, timeout=600))
for label, m in (("with_thought", msgs), ("no_thought", [{k: v for k, v in x.items() if k != "reasoning_content"} for x in msgs])):
    prompt = tok.apply_chat_template(m, tools=tools, add_generation_prompt=True, tokenize=False)
    for model in sys.argv[1:]:
        r = post({"model": model, "prompt": prompt, "n": 6, "max_tokens": 1500, "temperature": 0.2, "top_p": 0.95, "skip_special_tokens": False, "spaces_between_special_tokens": False})
        outs = []
        for ch in r["choices"]:
            t = ch["text"]; ncalls = t.count("<tool_call|>"); thought = len(t.split("<channel|>")[0]) if "<channel|>" in t else -1
            outs.append(f"{ch['finish_reason']}/calls{ncalls}/thought{thought}")
        print(label, "tokens", len(tok(prompt).input_ids), model[-12:], outs)
