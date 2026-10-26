"""Memory-light attention for training Gemma 4 on long sequences: queries are processed in chunks and
each chunk is recomputed in backward, so the T x T attention matrix is never materialized in full.
Needed because Gemma 4's global layers use head_dim 512 (no flash-attn / flex kernels) and the sdpa
math path needs ~16 GB per layer at 8k tokens. Register once, then load with attn_implementation="chunked".
"""
import os
import torch
import torch.nn.functional as F
from torch.utils.checkpoint import checkpoint
from transformers import AttentionInterface
from transformers.integrations.sdpa_attention import repeat_kv

CHUNK = int(os.environ.get("ATTN_CHUNK", "1024"))


def _chunk(q, k, v, m, scaling):
    return F.scaled_dot_product_attention(q, k, v, attn_mask=m, scale=scaling)


def chunked_attention_forward(module, query, key, value, attention_mask, dropout=0.0, scaling=None,
                              is_causal=None, sliding_window=None, **kwargs):
    groups = getattr(module, "num_key_value_groups", 1)
    if groups > 1:
        key = repeat_kv(key, groups)
        value = repeat_kv(value, groups)
    B, H, T, D = query.shape
    Tk = key.shape[2]
    is_causal = is_causal if is_causal is not None else getattr(module, "is_causal", True)
    causal_same = bool(is_causal) and Tk == T
    outs = []
    for s in range(0, T, CHUNK):
        e = min(T, s + CHUNK)
        k0 = 0
        if causal_same and sliding_window:
            k0 = max(0, s - sliding_window + 1)
        k1 = e if causal_same else Tk
        q = query[:, :, s:e]
        k_c, v_c = key[:, :, k0:k1], value[:, :, k0:k1]
        if attention_mask is not None:
            m = attention_mask[:, :, s:e, k0:k1] if attention_mask.shape[2] == T else attention_mask[:, :, :, k0:k1]
        elif is_causal:
            qi = torch.arange(s, e, device=query.device)[:, None]
            ki = torch.arange(k0, k1, device=query.device)[None, :]
            allowed = ki <= qi
            if sliding_window:
                allowed = allowed & ((qi - ki) < sliding_window)
            m = allowed[None, None]
        else:
            m = None
        outs.append(checkpoint(_chunk, q, k_c, v_c, m, scaling, use_reentrant=False))
    out = torch.cat(outs, dim=2).transpose(1, 2).contiguous()
    return out, None


def register():
    AttentionInterface.register("chunked", chunked_attention_forward)
    try:
        from transformers.masking_utils import ALL_MASK_ATTENTION_FUNCTIONS, AttentionMaskInterface
        AttentionMaskInterface.register("chunked", ALL_MASK_ATTENTION_FUNCTIONS["sdpa"])
    except Exception as e:  # older/newer API: masks default to the eager float path, still correct
        print("mask interface registration skipped:", type(e).__name__, e)


register()
