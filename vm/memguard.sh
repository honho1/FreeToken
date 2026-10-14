#!/bin/bash
# Kill FreeToken if VM MemAvailable drops below $1 MiB (default 4096). Logs to memguard.log.
lim=${1:-4096}
while pgrep -f "[b]in/ft serve" >/dev/null; do
  a=$(awk "/MemAvailable/{print int(\$2/1024)}" /proc/meminfo)
  if [ "$a" -lt "$lim" ]; then echo "$(date +%T) MemAvailable ${a} MiB < ${lim}: killing ft serve"; pgrep -f "[b]in/ft serve" | xargs -r kill -9; break; fi
  sleep 1
done
echo "$(date +%T) memguard exit"
