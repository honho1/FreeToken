#!/bin/bash
# Run a FreeToken launcher under watch, for systemd (ERRORS.md F2).
# usage: [SERVE=vm/serve-gptoss.sh] [MEMGUARD_MIB=4096] supervise.sh <logname> [ft serve args...]
#
# Exit codes, which decide whether systemd's Restart=on-failure restarts the service:
#   1  the backend died (/health status "error") or ft serve exited on its own -> restart
#   0  stopped on purpose: systemd stop (SIGTERM) or low memory (MemAvailable < MEMGUARD_MIB),
#      so a memory squeeze can't turn into a restart loop.
# FreeToken shuts its API down by itself after a backend death and may exit 0, or hang in
# "Waiting for connections to close" while clients wait; either way systemd alone would not
# notice, hence this wrapper. A hung stop gets SIGKILL after STOP_GRACE seconds.
V=$(cd "$(dirname "$0")" && pwd)
SERVE=${SERVE:-$V/serve.sh}
MEMGUARD_MIB=${MEMGUARD_MIB:-4096}
STOP_GRACE=${STOP_GRACE:-20}
PORT=${PORT:-8096}

log() { echo "$(date '+%F %T') supervise: $*"; }

stop_ft() {
  kill -TERM "$pid" 2>/dev/null
  for _ in $(seq 1 "$STOP_GRACE"); do kill -0 "$pid" 2>/dev/null || return; sleep 1; done
  log "ft serve did not stop within ${STOP_GRACE}s; SIGKILL"
  pkill -KILL -P "$pid" 2>/dev/null
  kill -KILL "$pid" 2>/dev/null
}

"$SERVE" "$@" &
pid=$!
log "started $SERVE (pid $pid) $*"
spid=
trap 'log "stop requested"; kill "$spid" 2>/dev/null; stop_ft; exit 0' TERM INT

while kill -0 "$pid" 2>/dev/null; do
  sleep 5 & spid=$!; wait $spid   # wait (not a foreground sleep) so the TERM trap runs at once
  avail=$(awk '/MemAvailable/{print int($2/1024)}' /proc/meminfo)
  if [ "$avail" -lt "$MEMGUARD_MIB" ]; then
    log "MemAvailable ${avail} MiB < ${MEMGUARD_MIB}; stopping without restart"
    stop_ft; exit 0
  fi
  status=$(curl -s -m 5 "http://127.0.0.1:$PORT/health" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("status",""))' 2>/dev/null)
  if [ "$status" = "error" ]; then
    log "backend died ($(curl -s -m 5 "http://127.0.0.1:$PORT/health" | head -c 200)); stopping for restart"
    stop_ft; exit 1
  fi
done
wait "$pid"; rc=$?
log "ft serve exited on its own (rc $rc); exiting 1 for restart"
exit 1
