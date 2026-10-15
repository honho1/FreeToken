#!/bin/bash
# Fresh gpt-oss server per run, then repro_683.py. usage: repro_683_runs.sh <label> <runs> [ft serve args]
# Prints one line per run: label run N: exit 0 (survived) / 1 (backend died) + the assertion if any.
label=$1; runs=$2; shift 2
V=/data/freetoken/vm; cd /data/freetoken-test
for r in $(seq 1 "$runs"); do
  pgrep -f "[b]in/ft serve" | xargs -r kill; while pgrep -f "[b]in/ft serve" >/dev/null; do sleep 2; done
  log=repro_${label}_$r
  (setsid nohup $V/serve-gptoss.sh "$log" --max-prefill-length 2048 "$@" >/dev/null 2>&1 < /dev/null &)
  sleep 3; (setsid nohup $V/memguard.sh 4096 >> memguard_repro.log 2>&1 < /dev/null &)
  $V/wait-ready.sh gpt-oss 1200 >/dev/null || { echo "$label run $r: server never became ready"; continue; }
  out=$(python3 $V/repro_683.py --delays 20,100,300 2>&1); rc=$?
  sleep 3
  echo "$label run $r: exit $rc | $(grep -m1 -o 'cache_type=[^,]*' $log.log) | $(echo "$out" | tail -1)"
  grep -m1 "AssertionError" $log.log | cut -c1-160
done
pgrep -f "[b]in/ft serve" | xargs -r kill
