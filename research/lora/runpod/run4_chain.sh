#!/bin/bash
# Adapter v4 cycle on the EXISTING pod (model, evalenv, wheelhouse, adapters dir already there). Run from the Mac:
#   bash research/lora/runpod/run4_chain.sh <ip> <port> [tag=v4]
# Before: research/lora/sft_messages.jsonl is the NEW dataset (verified with verify_render), `python3 scripts/runpod_lora.py upload <pod>`.
# Phases: 1 start train.py directly (no bootstrap pip step; OUT=/workspace/adapter_<tag>)  2 poll every 5 min until "] done"
#         3 fetch adapter -> research/lora/adapters/<tag>/adapter  4 precheck.sh (gate)  5 stage <tag>.* and run the sound-71 LoRA arm
#         6 sync results every 10 min, fetch traces.
set -u
cd /Users/alex_ust/Desktop/Gemma_kaggle
IP=$1; PORT=$2; TAG=${3:-v4}
OPTS="-o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o LogLevel=ERROR -o ConnectTimeout=30 -i runpod/id_ed25519"
A="ssh $OPTS -p $PORT root@$IP"
RUNDIR=runs/v22-lora-$TAG-pod
OUT=/workspace/adapter_$TAG
scp $OPTS -P $PORT $RUNDIR/kernel/run.py root@$IP:/workspace/run_lora4.py || exit 1
$A "pgrep -f '[p]ython -u train.py' >/dev/null && { echo 'train.py already running'; exit 0; }; pkill -f '[a]pi_server' 2>/dev/null; cd /workspace/lora && export MODEL_DIR=/workspace/model DATA_DIR=/workspace/lora/data OUT=$OUT THINK=1 MAX_LEN=20480 QUANT=0 ATTN=chunked SAVE_ON_CPU=1 ATTN_CHUNK=1024 EPOCHS=2 RANK=16 ALPHA=32 LR=1e-4 && (setsid nohup python -u train.py > /workspace/train_$TAG.log 2>&1 < /dev/null &); echo \"training started \$(date -u +%H:%M) -> $OUT\"" || exit 1
while true; do
  out=$($A "grep -E '^\[' /workspace/train_$TAG.log 2>/dev/null | tail -1 | cut -c1-150; grep -c -E 'OOM|Traceback' /workspace/train_$TAG.log 2>/dev/null; pgrep -f '[p]ython -u train.py' >/dev/null && echo ALIVE || echo NOTRAIN; nvidia-smi --query-gpu=utilization.gpu,memory.used --format=csv,noheader" 2>&1 | tr '\n' ' ')
  echo "$(date -u +%H:%M) TRAIN $out"
  case "$out" in *"] done"*) break;; *NOTRAIN*) echo "=== training process gone without done; see /workspace/train_$TAG.log"; exit 1;; esac
  sleep 300
done
if ! $A "test -f $OUT/adapter_model.safetensors"; then echo "NO ADAPTER — see /workspace/train_$TAG.log"; exit 1; fi
mkdir -p research/lora/adapters/$TAG && scp $OPTS -r -P $PORT root@$IP:$OUT research/lora/adapters/$TAG/adapter && echo "adapter fetched: $(ls -la research/lora/adapters/$TAG/adapter | tail -2)"
scp $OPTS -P $PORT research/lora/runpod/precheck.sh research/lora/runpod/vllm_start.sh research/lora/runpod/probe/rawprobe3.py research/lora/runpod/probe/probe2_msgs.json research/lora/tools.json root@$IP:/workspace/
echo "$(date -u +%H:%M) adapter pre-check"
mkdir -p $RUNDIR/results
$A "bash /workspace/precheck.sh $OUT $TAG" 2>&1 | tail -6 | tee $RUNDIR/precheck.txt
grep -q PRECHECK_OK $RUNDIR/precheck.txt || { echo "=== PRECHECK FAILED: not starting the 71-task arm (pod still running, decide manually)"; exit 2; }
$A "D=/kaggle/input/datasets/alexust/gemma-lora-adapters; mkdir -p \$D; cp $OUT/adapter_config.json \$D/$TAG.adapter_config.json; cp $OUT/adapter_model.safetensors \$D/$TAG.adapter_model.safetensors; pkill -f '[a]pi_server' 2>/dev/null; rm -rf /kaggle/working/*; mkdir -p /kaggle/working; cd /kaggle/working && (setsid nohup /workspace/evalenv/bin/python /workspace/run_lora4.py > /workspace/run_lora4.log 2>&1 < /dev/null &); echo \"LoRA arm started \$(date -u +%H:%M)\""
while true; do
  out=$($A 'grep -E "^\[" /workspace/run_lora4.log | tail -1 | cut -c1-120; f=/kaggle/working/results/task_results.jsonl; echo "done $(wc -l < $f 2>/dev/null || echo 0) resolved $(grep -c "\"resolved\": true" $f 2>/dev/null || echo 0)"; pgrep -f "[r]un_lora4.py" >/dev/null && echo ALIVE || echo DEAD' 2>&1 | tr '\n' ' ')
  echo "$(date -u +%H:%M) EVAL $out"
  scp $OPTS -q -P $PORT root@$IP:/kaggle/working/results/task_results.jsonl $RUNDIR/results/task_results.jsonl 2>/dev/null
  case "$out" in *DONE*|*DEAD*) break;; esac
  sleep 600
done
scp $OPTS -q -r -P $PORT root@$IP:/kaggle/working/results/traces $RUNDIR/results/ && echo "traces fetched"
echo "=== $TAG chain finished"
