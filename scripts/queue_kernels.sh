#!/bin/bash
# Push prepared eval kernels from a queue, at most MAXPAR running at once; exit when all are final.
# Usage: scripts/queue_kernels.sh <logfile> <run_dir> [<run_dir> ...]     (run_dir contains kernel/ and run.json)
cd "$(dirname "$0")/.."
export KAGGLE_API_TOKEN=$PWD/kaggle/access_token
MAXPAR=${MAXPAR:-2}
LOG=$1; shift
QUEUE=("$@")
RUNNING=()
slug_of() { .venv/bin/python -c "import json,sys; print(json.load(open(sys.argv[1]))['id'])" "$1/kernel/kernel-metadata.json"; }
log() { echo "$(date -u +%m-%dT%H:%MZ) $*" >> "$LOG"; }
next=0
while [ $next -lt ${#QUEUE[@]} ] || [ ${#RUNNING[@]} -gt 0 ]; do
  # refresh running list
  still=()
  for r in "${RUNNING[@]}"; do
    s=$(.venv/bin/kaggle kernels status "$(slug_of "$r")" 2>&1 | grep "has status" | tail -1)
    case "$s" in
      *COMPLETE*|*ERROR*|*CANCEL*) log "FINISHED $r :: $s" ;;
      *) still+=("$r") ;;
    esac
  done
  RUNNING=("${still[@]}")
  # fill free slots
  while [ ${#RUNNING[@]} -lt $MAXPAR ] && [ $next -lt ${#QUEUE[@]} ]; do
    r=${QUEUE[$next]}
    # restartable: adopt a kernel that is already running, skip one that already finished
    s=$(.venv/bin/kaggle kernels status "$(slug_of "$r")" 2>&1 | grep "has status" | tail -1)
    case "$s" in
      *RUNNING*|*QUEUED*) log "ADOPTED $r :: $s"; RUNNING+=("$r"); next=$((next + 1)); continue ;;
      *COMPLETE*|*ERROR*|*CANCEL*) log "SKIPPED $r :: $s"; next=$((next + 1)); continue ;;
    esac
    out=$(.venv/bin/kaggle kernels push -p "$r/kernel" 2>&1 | tail -1)
    if echo "$out" | grep -q "successfully pushed"; then
      log "PUSHED $r"
      RUNNING+=("$r"); next=$((next + 1))
    else
      log "PUSH FAILED $r :: $out"
      break
    fi
  done
  sleep 120
done
log "ALL DONE"
