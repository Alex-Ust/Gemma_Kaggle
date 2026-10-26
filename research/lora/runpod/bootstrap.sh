#!/bin/bash
# RunPod bootstrap: run inside the pod (PyTorch template). Usage: bash bootstrap.sh
set -euo pipefail
cd /workspace
pip install -q -U --break-system-packages "transformers>=5.0" peft bitsandbytes accelerate safetensors "huggingface_hub[hf_transfer]" 2>&1 | tail -1
export HF_HUB_ENABLE_HF_TRANSFER=1
if [ ! -f /workspace/model/config.json ]; then
  hf download unsloth/gemma-4-31b-it --local-dir /workspace/model --exclude "*.gguf" 2>&1 | tail -2
fi
ls /workspace/model | head -20; du -sh /workspace/model
nvidia-smi --query-gpu=name,memory.total --format=csv
cd /workspace/lora
export MODEL_DIR=/workspace/model DATA_DIR=/workspace/lora/data OUT=/workspace/adapter
export THINK=${THINK:-1} MAX_LEN=${MAX_LEN:-20480} QUANT=${QUANT:-0} ATTN=${ATTN:-chunked} SAVE_ON_CPU=${SAVE_ON_CPU:-1} ATTN_CHUNK=${ATTN_CHUNK:-1024} EPOCHS=${EPOCHS:-2} RANK=${RANK:-16} ALPHA=${ALPHA:-32} LR=${LR:-1e-4}
nohup python -u train.py > /workspace/train.log 2>&1 &
echo "training started, log /workspace/train.log"
