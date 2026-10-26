"""Render SFT rows with the Gemma 4 chat template and build loss masks.
Shared by the local check and the Kaggle training kernel.
mask = 1 on tokens the model generates inside the model turn; 0 on system/user prefix and tool responses.
"""
import json
import re

TOOL_RESP = re.compile(r"<\|tool_response>.*?<tool_response\|>", re.S)
MODEL_TURN = "<|turn>model\n"


def prepare_messages(messages, think):
    """Copy messages for the template. Tool-call arguments must be dicts: the Gemma 4 template renders a mapping
    in the native DSL (key:<|"|>str<|"|>), but passes a pre-serialized JSON string through verbatim, which taught
    adapter v1 to emit JSON quotes that the vLLM gemma4 parser then keeps inside the keys and values."""
    out = []
    for m in messages:
        m = dict(m)
        if not think:
            m.pop("reasoning_content", None)
        if m.get("tool_calls"):
            calls = []
            for tc in m["tool_calls"]:
                tc = dict(tc); fn = dict(tc["function"])
                if isinstance(fn.get("arguments"), str):
                    fn["arguments"] = json.loads(fn["arguments"])
                tc["function"] = fn
                calls.append(tc)
            m["tool_calls"] = calls
        out.append(m)
    return out


def render(tok, messages, tools, think):
    msgs = prepare_messages(messages, think)
    text = tok.apply_chat_template(msgs, tools=tools, tokenize=False, add_generation_prompt=False, enable_thinking=think)
    enc = tok(text, return_offsets_mapping=True, add_special_tokens=False)
    ids = enc["input_ids"]; offs = enc["offset_mapping"]
    start = text.find(MODEL_TURN)
    assert start >= 0, "no model turn"
    gen_start = start + len(MODEL_TURN)
    dead = [(m.start(), m.end()) for m in TOOL_RESP.finditer(text)]
    mask = []
    for (a, b) in offs:
        if a < gen_start:
            mask.append(0); continue
        if any(a >= s and b <= e for s, e in dead):
            mask.append(0); continue
        mask.append(1)
    return text, ids, mask
