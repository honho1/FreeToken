#!/bin/bash
# Wait until FreeToken on :8096 answers a real completion (its /health says 200 too early).
# usage: wait-ready.sh <served-name> [timeout-s]   exit 0 ready, 1 server died, 2 timeout
name=$1; limit=${2:-900}; t0=$(date +%s)
while [ $(( $(date +%s) - t0 )) -lt "$limit" ]; do
  sleep 10
  pgrep -f "[b]in/ft serve" >/dev/null || { echo "DIED after $(( $(date +%s) - t0 ))s"; exit 1; }
  c=$(curl -s -o /dev/null -w '%{http_code}' -m 600 http://127.0.0.1:8096/v1/chat/completions \
      -H 'Content-Type: application/json' \
      -d "{\"model\":\"$name\",\"messages\":[{\"role\":\"user\",\"content\":\"hi\"}],\"max_tokens\":8}")
  [ "$c" = 200 ] && { echo "READY after $(( $(date +%s) - t0 ))s"; exit 0; }
done
echo "TIMEOUT after ${limit}s"; exit 2
