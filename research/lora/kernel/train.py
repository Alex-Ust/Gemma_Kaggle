"""LoRA SFT of Gemma 4 31B (bf16) on successful SWE-agent trajectories. Kaggle 4x L4 (96 GB), device_map=auto.
Inputs (Kaggle): model google/gemma-4/Transformers/gemma-4-31b-it, dataset with sft_messages.jsonl + tools.json + sft_render.py
Env knobs: THINK (1 keep thoughts, 0 strip), MAX_LEN, RANK, ALPHA, LR, EPOCHS, ACCUM, DRY (render only), MODEL_DIR/DATA_DIR overrides.
Output: /kaggle/working/adapter/{adapter_config.json, adapter_model.safetensors}
"""
import os, sys, json, glob, math, time, random, subprocess, re
os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")

THINK = int(os.environ.get("THINK", "1"))
MAX_LEN = int(os.environ.get("MAX_LEN", "16384"))
RANK = int(os.environ.get("RANK", "16"))
ALPHA = int(os.environ.get("ALPHA", "32"))
LR = float(os.environ.get("LR", "1e-4"))
EPOCHS = float(os.environ.get("EPOCHS", "2"))
ACCUM = int(os.environ.get("ACCUM", "4"))
DRY = int(os.environ.get("DRY", "0"))
KEY_STYLE = os.environ.get("KEY_STYLE", "hf")
QUANT = int(os.environ.get("QUANT", "0"))  # 1: QLoRA, base in 4-bit nf4 (48 GB cards)
ATTN = os.environ.get("ATTN", "chunked")  # chunked: query-chunked recomputed attention (see chunked_attn.py); or sdpa
SAVE_ON_CPU = int(os.environ.get("SAVE_ON_CPU", "1"))  # offload checkpointed activations to pinned CPU memory  # hf: keep PEFT names; causal: drop 'language_model.' from keys
OUT = os.environ.get("OUT", "/kaggle/working/adapter")
T0 = time.time()


def log(*a):
    print(f"[{time.time()-T0:7.0f}s]", *a, flush=True)


def find_model():
    if os.environ.get("MODEL_DIR"):
        return os.environ["MODEL_DIR"]
    cands = [p for p in glob.glob("/kaggle/input/**/config.json", recursive=True) if "gemma-4-31b-it" in p and "qat" not in p]
    assert cands, "bf16 gemma-4-31b-it not attached"
    return os.path.dirname(cands[0])


def find_data():
    if os.environ.get("DATA_DIR"):
        return os.environ["DATA_DIR"]
    return os.path.dirname(glob.glob("/kaggle/input/**/sft_messages.jsonl", recursive=True)[0])


MODEL = find_model(); DATA = find_data()
sys.path.insert(0, DATA)
from sft_render import render  # noqa: E402
log("model", MODEL, "data", DATA, "think", THINK, "attn", ATTN, "save_on_cpu", SAVE_ON_CPU, "quant", QUANT, "max_len", MAX_LEN)

from transformers import AutoTokenizer  # noqa: E402
tok = AutoTokenizer.from_pretrained(MODEL)
tools = json.load(open(os.path.join(DATA, "tools.json")))
rows = [json.loads(l) for l in open(os.path.join(DATA, "sft_messages.jsonl"))]
examples = []
dropped = {"long": 0, "nothought": 0}
for r in rows:
    has_thought = any(m.get("reasoning_content") for m in r["messages"] if m["role"] == "assistant")
    if THINK and not has_thought:
        dropped["nothought"] += 1; continue
    text, ids, mask = render(tok, r["messages"], tools, bool(THINK))
    if len(ids) > MAX_LEN:
        dropped["long"] += 1; continue
    examples.append((r["instance_id"], r["run"], ids, mask))
log(f"examples {len(examples)} dropped {dropped}; tokens median {sorted(len(e[2]) for e in examples)[len(examples)//2]} "
    f"trained-token share {sum(sum(e[3]) for e in examples)/max(1,sum(len(e[2]) for e in examples)):.2f}")
if DRY:
    sys.exit(0)

try:
    import peft  # noqa: F401
except ImportError:
    subprocess.run([sys.executable, "-m", "pip", "install", "-q", "peft"], check=True)
import torch  # noqa: E402
from torch.utils.checkpoint import checkpoint  # noqa: E402
from transformers import AutoConfig, AutoModelForCausalLM, AutoModelForImageTextToText  # noqa: E402
from peft import LoraConfig, get_peft_model  # noqa: E402
if ATTN == "chunked":
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import chunked_attn  # noqa: E402,F401  registers the "chunked" attention implementation

cfg = AutoConfig.from_pretrained(MODEL)
arch = (cfg.architectures or [""])[0]
cls = AutoModelForImageTextToText if "ConditionalGeneration" in arch else AutoModelForCausalLM
log("loading", arch, "via", cls.__name__, "gpus", torch.cuda.device_count())
load_kw = dict(dtype=torch.bfloat16, device_map="auto", attn_implementation=ATTN, low_cpu_mem_usage=True)
if QUANT:
    from transformers import BitsAndBytesConfig
    load_kw["quantization_config"] = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type="nf4", bnb_4bit_use_double_quant=True,
                                                        bnb_4bit_compute_dtype=torch.bfloat16, llm_int8_skip_modules=["lm_head", "embed_tokens", "vision_tower", "embed_vision", "embed_audio", "audio_tower"])
model = cls.from_pretrained(MODEL, **load_kw)
model.config.use_cache = False
model.gradient_checkpointing_enable(gradient_checkpointing_kwargs={"use_reentrant": False})
model.enable_input_require_grads()
lcfg = LoraConfig(r=RANK, lora_alpha=ALPHA, lora_dropout=0.05, bias="none", task_type="CAUSAL_LM",
                  target_modules=r"^(?!.*vision).*layers\.\d+\.(self_attn|mlp)\.(q_proj|k_proj|v_proj|o_proj|gate_proj|up_proj|down_proj)$")
model = get_peft_model(model, lcfg)
model.print_trainable_parameters()
inner = model.get_base_model()
backbone = inner.model
lm_head = inner.lm_head
softcap = getattr(getattr(cfg, "text_config", cfg), "final_logit_softcapping", None)
first_dev = next(backbone.parameters()).device
head_dev = next(lm_head.parameters()).device
params = [p for p in model.parameters() if p.requires_grad]
opt = torch.optim.AdamW(params, lr=LR, weight_decay=0.0, betas=(0.9, 0.99))
steps_total = math.ceil(len(examples) * EPOCHS / ACCUM)
warm = max(1, min(5, steps_total // 10))
sched = torch.optim.lr_scheduler.LambdaLR(opt, lambda s: min(1.0, (s + 1) / warm) * 0.5 * (1 + math.cos(math.pi * min(1.0, s / max(1, steps_total)))))
CH = 1024


def chunk_loss(h, lab):
    logits = lm_head(h).float()
    if softcap:
        logits = torch.tanh(logits / softcap) * softcap
    return torch.nn.functional.cross_entropy(logits.view(-1, logits.size(-1)), lab.view(-1), ignore_index=-100, reduction="sum")


def example_loss(ids, mask):
    x = torch.tensor([ids], device=first_dev)
    labels = torch.tensor([[t if m else -100 for t, m in zip(ids, mask)]], device=head_dev)
    import contextlib
    ctx = torch.autograd.graph.save_on_cpu(pin_memory=True) if SAVE_ON_CPU else contextlib.nullcontext()
    with ctx:
        h = backbone(input_ids=x).last_hidden_state.to(head_dev)  # [1, T, H]
    h = h[:, :-1]; lab = labels[:, 1:]
    n = (lab != -100).sum().clamp(min=1)
    total = 0.0
    for s in range(0, h.size(1), CH):
        total = total + checkpoint(chunk_loss, h[:, s:s + CH], lab[:, s:s + CH], use_reentrant=False)
    return total / n, int(n)


model.train()
step = 0; seen = 0; t_ep = time.time()
order = list(range(len(examples)))
n_examples_total = int(len(examples) * EPOCHS)
random.seed(0)
ex_i = 0; ep = 0
while ex_i < n_examples_total:
    if ex_i % len(examples) == 0:
        random.shuffle(order); ep += 1; log(f"epoch {ep}")
    iid, run, ids, mask = examples[order[ex_i % len(examples)]]
    t1 = time.time()
    try:
        loss, n = example_loss(ids, mask)
        (loss / ACCUM).backward()
    except torch.OutOfMemoryError:
        log(f"OOM on {iid} ({run}) tokens {len(ids)}: skipped")
        opt.zero_grad(set_to_none=True); torch.cuda.empty_cache(); ex_i += 1
        continue
    seen += 1; ex_i += 1
    log(f"ex {ex_i}/{n_examples_total} {iid} ({run}) tokens {len(ids)} trained {n} loss {loss.item():.3f} {time.time()-t1:.0f}s")
    if seen % ACCUM == 0 or ex_i == n_examples_total:
        torch.nn.utils.clip_grad_norm_(params, 1.0)
        opt.step(); sched.step(); opt.zero_grad(set_to_none=True); step += 1
        log(f"step {step}/{steps_total} lr {sched.get_last_lr()[0]:.2e} mem {torch.cuda.max_memory_allocated()/2**30:.1f} GiB")
    if ex_i % len(examples) == 0 or ex_i == n_examples_total:
        model.save_pretrained(OUT, safe_serialization=True)
        log("saved adapter to", OUT, "epoch time", f"{time.time()-t_ep:.0f}s"); t_ep = time.time()

# finalize adapter files for the harness
from safetensors.torch import load_file, save_file  # noqa: E402
acfg = json.load(open(os.path.join(OUT, "adapter_config.json")))
acfg["base_model_name_or_path"] = "google/gemma-4-31b-it"
acfg["inference_mode"] = True
json.dump(acfg, open(os.path.join(OUT, "adapter_config.json"), "w"), indent=1)
w = load_file(os.path.join(OUT, "adapter_model.safetensors"))
if KEY_STYLE == "causal":
    w = {k.replace("language_model.", ""): v for k, v in w.items()}
    save_file(w, os.path.join(OUT, "adapter_model.safetensors"), metadata={"format": "pt"})
log("adapter keys", len(w), "sample", next(iter(w)), "size MB", os.path.getsize(os.path.join(OUT, "adapter_model.safetensors")) // 2**20)
for f in glob.glob(os.path.join(OUT, "*")):
    if os.path.basename(f) not in ("adapter_config.json", "adapter_model.safetensors"):
        os.remove(f)
log("done")
