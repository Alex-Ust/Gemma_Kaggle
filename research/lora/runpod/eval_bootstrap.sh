#!/bin/bash
# Prepare a RunPod pod to run the Kaggle eval kernel (run.py) locally: separate venv with vLLM, Kaggle layout under /kaggle/input.
# Needs KAGGLE_API_TOKEN=/workspace/kaggle_token (file). Safe to run while training uses the GPU (network/CPU only).
set -uo pipefail
mkdir -p /kaggle/input/datasets/metric /kaggle/input/competitions /kaggle/input/models/google/gemma-4/other/gemma-4-31b-it-qat-w4a16-ct/2 /kaggle/working
if [ ! -x /workspace/evalenv/bin/python ]; then
  python -m venv /workspace/evalenv
  /workspace/evalenv/bin/pip install -q -U pip wheel kaggle 2>&1 | tail -1
  /workspace/evalenv/bin/pip install -q vllm 2>&1 | tail -1
  echo "vllm: $(/workspace/evalenv/bin/python -c 'import vllm; print(vllm.__version__)')"
fi
export PATH=/workspace/evalenv/bin:$PATH
K=/workspace/evalenv/bin/kaggle
if [ ! -d /kaggle/input/datasets/metric/gemma-4-developer-agent-wheelhouse ]; then
  $K datasets download -d metric/gemma-4-developer-agent-wheelhouse -p /kaggle/input/datasets/metric/gemma-4-developer-agent-wheelhouse --unzip 2>&1 | tail -1
fi
if [ ! -f /kaggle/input/competitions/gemma-4-developer-agent/tasks.jsonl ]; then
  mkdir -p /kaggle/input/competitions/gemma-4-developer-agent
  $K competitions download -c gemma-4-developer-agent -p /kaggle/input/competitions/gemma-4-developer-agent 2>&1 | tail -1
  (cd /kaggle/input/competitions/gemma-4-developer-agent && unzip -q -o gemma-4-developer-agent.zip && rm -f gemma-4-developer-agent.zip)
fi
M=/kaggle/input/models/google/gemma-4/other/gemma-4-31b-it-qat-w4a16-ct/2
if [ ! -f $M/config.json ]; then
  $K models instances versions download google/gemma-4/other/gemma-4-31b-it-qat-w4a16-ct/2 -p $M --untar 2>&1 | tail -1
  ls $M
fi
echo "--- layout"; du -sh /kaggle/input/* /kaggle/input/datasets/metric/* 2>/dev/null; ls /kaggle/input/competitions/gemma-4-developer-agent | head; ls $M | head
echo "EVAL_PREP_DONE"

# --- extras added by hand on pod A (2026-10-26), needed for real (non-gold) runs ---
# /workspace/evalenv/bin/pip install torch==2.10.0 torchvision==0.25.0 torchaudio==2.10.0   # match wheelhouse vllm 0.19.1
# /workspace/evalenv/bin/pip install litellm google-adk==1.36.1 pytest pytest-timeout==2.1.0 typer pdm-backend setuptools wheel poetry-core hatchling flit-core editables
# /workspace/evalenv/bin/pip install -U mcp   # litellm 1.106 imports mcp.types.CacheableResult (mcp>=2); gold mode never calls the model, so this only shows in real runs
