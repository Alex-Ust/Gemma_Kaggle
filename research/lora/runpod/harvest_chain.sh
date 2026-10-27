#!/bin/bash
# Harvest new successful trajectories on the pod for SFT: OOD-45 once (temperature 0.2) + the 36 never-solved sound
# tasks three times at temperature 0.7. usage: bash research/lora/runpod/harvest_chain.sh <ip> <port> [adapter_name]
# Each pass: upload its run.py as /workspace/run_h.py, run from /kaggle/working, sync task_results every 10 min,
# fetch traces to runs/<run>/results/<pass>/ when done. Afterwards: scripts/sft_extract.py on those result dirs.
set -u
cd /Users/alex_ust/Desktop/Gemma_kaggle
IP=$1; PORT=$2
OPTS="-o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o LogLevel=ERROR -o ConnectTimeout=30 -i runpod/id_ed25519"
A="ssh $OPTS -p $PORT root@$IP"
run_pass() {  # run_pass <kernel run.py> <local results dir>
  local KERNEL=$1 DEST=$2
  mkdir -p $DEST
  scp $OPTS -P $PORT $KERNEL root@$IP:/workspace/run_h.py || return 1
  $A 'pkill -f "[a]pi_server" 2>/dev/null; rm -rf /kaggle/working/*; mkdir -p /kaggle/working; cd /kaggle/working && (setsid nohup /workspace/evalenv/bin/python /workspace/run_h.py > /workspace/run_h.log 2>&1 < /dev/null &); echo "pass started $(date -u +%H:%M)"'
  while true; do
    out=$($A 'grep -E "^\[" /workspace/run_h.log | tail -1 | cut -c1-100; f=/kaggle/working/results/task_results.jsonl; echo "done $(wc -l < $f 2>/dev/null || echo 0) resolved $(grep -c "\"resolved\": true" $f 2>/dev/null || echo 0)"; pgrep -f "[r]un_h.py" >/dev/null && echo ALIVE || echo DEAD' 2>&1 | tr '\n' ' ')
    echo "$(date -u +%H:%M) HARVEST $DEST $out"
    scp $OPTS -q -P $PORT root@$IP:/kaggle/working/results/task_results.jsonl $DEST/task_results.jsonl 2>/dev/null
    case "$out" in *DONE*|*DEAD*) break;; esac
    sleep 600
  done
  scp $OPTS -q -r -P $PORT root@$IP:/kaggle/working/results/traces $DEST/ && echo "traces fetched -> $DEST"
}
run_pass runs/v12-think1024-podood/kernel/run.py runs/v12-think1024-podood/results
for n in 1 2 3; do run_pass runs/h01-harvest-t07-podhard/kernel/run.py runs/h01-harvest-t07-podhard/results/s$n; done
echo "=== harvest finished"
