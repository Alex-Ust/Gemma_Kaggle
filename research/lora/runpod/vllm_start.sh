#!/bin/bash
# usage: vllm_start.sh <lora-modules spec, e.g. v1=/path ep1=/path> ; writes /workspace/vllm_manual.log
exec /workspace/evalenv/bin/python -m vllm.entrypoints.openai.api_server \
  --model /kaggle/input/models/google/gemma-4/other/gemma-4-31b-it-qat-w4a16-ct/2 \
  --host 127.0.0.1 --port 8000 --max-model-len 32768 --dtype bfloat16 --gpu-memory-utilization 0.9 \
  --enable-auto-tool-choice --tool-call-parser gemma4 --reasoning-parser gemma4 \
  --reasoning-config '{"reasoning_start_str": "<|channel>", "reasoning_end_str": "<channel|>"}' \
  --no-scheduler-reserve-full-isl --enable-lora --max-loras 2 --max-lora-rank 16 --lora-modules "$@"
