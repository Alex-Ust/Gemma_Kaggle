#!/bin/bash
# Waits for the weekly Kaggle GPU quota reset (Saturday 2026-11-21 00:00 UTC), then runs the queue:
# three more flaky25 passes each for v40_pin and v34_noedit, two sessions at a time (~15 h of quota).
cd "$(dirname "$0")/../.."
START=1795219800   # 2026-11-21 00:10 UTC
until [ "$(date -u +%s)" -ge "$START" ]; do sleep 300; done
exec bash scripts/queue_kernels.sh runs/_queue/flaky-2026-11-21.log \
  runs/v40-pin-flaky-p4 runs/v34-noedit-flaky-p6 runs/v40-pin-flaky-p5 runs/v34-noedit-flaky-p7 \
  runs/v40-pin-flaky-p6 runs/v34-noedit-flaky-p8
