#!/bin/bash
# Pod-side: download the complete OOD-45 dataset (rodrigospalma/ood45-bugfix-split, ~5.6 GB: 45 snapshots + 2 GB
# wheels/house) into /kaggle/input, verify SHA256SUMS, replace the partial local copy, delete the Kaggle token.
# The copy staged from the Mac had only 30/45 snapshots and no wheels/ -> ood45_harness.setup() fails.
set -uo pipefail
D=/kaggle/input/datasets/rodrigospalma/ood45-bugfix-split
export KAGGLE_API_TOKEN=/workspace/kaggle_token
[ -s /workspace/kaggle_token ] || { echo "no token"; exit 1; }
rm -rf $D.new; mkdir -p $D.new
/workspace/evalenv/bin/kaggle datasets download -d rodrigospalma/ood45-bugfix-split -p $D.new --unzip 2>&1 | tail -2
rm -f /workspace/kaggle_token
cd $D.new || exit 1
ls; echo "snapshots $(ls snapshots | wc -l) wheels/house $(ls wheels/house 2>/dev/null | wc -l)"
if sha256sum -c --quiet SHA256SUMS 2>&1 | tail -3; [ ${PIPESTATUS[0]} -eq 0 ]; then
  rm -rf $D.partial; mv $D $D.partial; mv $D.new $D; rm -rf $D.partial; du -sh $D; echo OOD_FULL_OK
else
  echo "OOD_SHA_FAIL"
fi
