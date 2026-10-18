#!/bin/bash
# Wait until a GPU session slot frees up, then push a prepared eval kernel.
# Usage: scripts/push_when_free.sh <bundle_dir> <tag>
cd "$(dirname "$0")/.."
export KAGGLE_API_TOKEN=$PWD/kaggle/access_token
for i in $(seq 1 180); do
  out=$(.venv/bin/python scripts/make_eval_kernel.py "$1" --tag "$2" --concurrency 4 --push 2>&1)
  echo "$(date +%H:%M) $out" | tail -2
  echo "$out" | grep -q "successfully pushed" && exit 0
  sleep 120
done
