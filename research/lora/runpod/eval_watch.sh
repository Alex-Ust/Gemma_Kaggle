#!/bin/bash
# Launch an eval script on the pod and sync results every 10 min. usage: eval_watch.sh <ip> <port> <pod script> <pod log> <local results dir> [launch=1]
set -u
cd /Users/alex_ust/Desktop/Gemma_kaggle
IP=$1; PORT=$2; SCRIPT=$3; LOG=$4; DEST=$5; LAUNCH=${6:-1}
OPTS="-o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o LogLevel=ERROR -o ConnectTimeout=30 -i runpod/id_ed25519"
A="ssh $OPTS -p $PORT root@$IP"
PAT="[$(echo $SCRIPT | sed 's#.*/##' | cut -c1)]$(echo $SCRIPT | sed 's#.*/##' | cut -c2-)"
mkdir -p $DEST
if [ "$LAUNCH" = 1 ]; then
  $A "pkill -f '[a]pi_server' 2>/dev/null; rm -rf /kaggle/working/*; mkdir -p /kaggle/working; cd /kaggle/working && (setsid nohup /workspace/evalenv/bin/python $SCRIPT > $LOG 2>&1 < /dev/null &); echo 'started $(date -u +%H:%M)'"
fi
while true; do
  out=$($A "grep -E '^\[' $LOG | tail -1 | cut -c1-100; f=/kaggle/working/results/task_results.jsonl; echo \"done \$(wc -l < \$f 2>/dev/null || echo 0) resolved \$(grep -c '\"resolved\": true' \$f 2>/dev/null || echo 0)\"; pgrep -f '$PAT' >/dev/null && echo ALIVE || echo DEAD" 2>&1 | tr '\n' ' ')
  echo "$(date -u +%H:%M) EVAL $DEST $out"
  scp $OPTS -q -P $PORT root@$IP:/kaggle/working/results/task_results.jsonl $DEST/task_results.jsonl 2>/dev/null
  case "$out" in *DONE*|*DEAD*) break;; esac
  sleep 600
done
scp $OPTS -q -r -P $PORT root@$IP:/kaggle/working/results/traces $DEST/ && echo "traces fetched -> $DEST"
echo "=== eval finished $DEST"
