#!/bin/bash
# Block until a Kaggle kernel reaches a final status (COMPLETE / ERROR / CANCEL*), then print it.
# Network errors (e.g. while switching Wi-Fi) are retried, not treated as the end.
# Usage: scripts/wait_kernel.sh <user/slug> [poll_seconds]
cd "$(dirname "$0")/.."
export KAGGLE_API_TOKEN=$PWD/kaggle/access_token
while true; do
  s=$(.venv/bin/kaggle kernels status "$1" 2>&1 | tail -1)
  case "$s" in
    *COMPLETE*|*ERROR*|*CANCEL*) echo "$(date +%H:%M) FINISHED $s"; exit 0 ;;
    *) sleep "${2:-60}" ;;
  esac
done
