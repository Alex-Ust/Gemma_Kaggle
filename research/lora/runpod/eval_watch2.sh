#!/bin/bash
# Launch an eval script on the pod and sync results every 10 min.
# usage: eval_watch2.sh <ip> <port> <pod script> <pod log> <local results dir> [launch=1]
# vs eval_watch.sh: refuses to launch while another /workspace/run_*.py driver is alive (audit finding 1),
# detects DONE anywhere in the log, reports DONE vs CRASHED, fetches the whole results dir + pod log (finding 3).
set -u
cd /Users/alex_ust/Desktop/Gemma_kaggle
IP=$1; PORT=$2; SCRIPT=$3; LOG=$4; DEST=$5; LAUNCH=${6:-1}
OPTS="-o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o LogLevel=ERROR -o ConnectTimeout=30 -i runpod/id_ed25519"
A="ssh $OPTS -p $PORT root@$IP"
BASE=$(basename $SCRIPT)
PAT="[$(echo $BASE | cut -c1)]$(echo $BASE | cut -c2-)"
mkdir -p $DEST
if [ "$LAUNCH" = 1 ]; then
  # separate ssh call so the guard's own command line holds only bracketed patterns
  busy=$($A "pgrep -af '[/]workspace/run_.*[.]py' | grep -v pgrep" 2>&1)
  if [ -n "$busy" ]; then echo "REFUSING TO LAUNCH: another driver is alive: $busy"; exit 1; fi
  rm -rf $DEST/traces $DEST/results_full
  $A "pkill -f '[a]pi_server' 2>/dev/null; sleep 5; rm -rf /kaggle/working/*; mkdir -p /kaggle/working; cd /kaggle/working && (setsid nohup /workspace/evalenv/bin/python $SCRIPT > $LOG 2>&1 < /dev/null &); echo 'started $(date -u +%H:%M)'"
fi
state=RUNNING
while true; do
  out=$($A "grep -E 'DONE resolved' $LOG | tail -1 | cut -c1-100; f=/kaggle/working/results/task_results.jsonl; echo \"done \$(wc -l < \$f 2>/dev/null || echo 0) resolved \$(grep -c '\"resolved\": true' \$f 2>/dev/null || echo 0)\"; pgrep -f '$PAT' >/dev/null && echo ALIVE || echo DEAD" 2>&1 | tr '\n' ' ')
  echo "$(date -u +%H:%M) EVAL $DEST $out"
  scp $OPTS -q -P $PORT root@$IP:/kaggle/working/results/task_results.jsonl $DEST/task_results.jsonl 2>/dev/null
  case "$out" in *"DONE resolved"*) state=DONE; break;; *DEAD*) state=CRASHED; break;; esac
  sleep 600
done
scp $OPTS -q -r -P $PORT root@$IP:/kaggle/working/results/traces $DEST/ && echo "traces fetched -> $DEST"
scp $OPTS -q -r -P $PORT root@$IP:/kaggle/working/results $DEST/results_full && echo "full results dir fetched -> $DEST/results_full"
scp $OPTS -q -P $PORT root@$IP:$LOG $DEST/pod.log && echo "pod log fetched -> $DEST/pod.log"
if [ "$state" = DONE ]; then echo "=== eval finished $DEST"; else echo "=== eval CRASHED $DEST (see pod.log)"; tail -n 20 $DEST/pod.log 2>/dev/null | cut -c1-200; fi
