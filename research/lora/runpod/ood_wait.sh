#!/bin/bash
# Mac-side: wait for the user's `! scp` of the Kaggle token to the pod, then run ood_fetch.sh there (network only,
# does not touch the GPU). usage: bash research/lora/runpod/ood_wait.sh <ip> <port>
cd /Users/alex_ust/Desktop/Gemma_kaggle
IP=$1; PORT=$2
OPTS="-o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o LogLevel=ERROR -o ConnectTimeout=30 -i runpod/id_ed25519"
scp $OPTS -P $PORT research/lora/runpod/ood_fetch.sh root@$IP:/workspace/ood_fetch.sh
while true; do
  if ssh $OPTS -p $PORT root@$IP 'test -s /workspace/kaggle_token' 2>/dev/null; then
    echo "$(date -u +%H:%M) token present, fetching OOD-45"
    ssh $OPTS -p $PORT root@$IP 'bash /workspace/ood_fetch.sh 2>&1 | tail -12'
    echo "=== ood fetch finished $(date -u +%H:%M)"; break
  fi
  sleep 60
done
