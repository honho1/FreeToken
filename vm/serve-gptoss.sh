#!/bin/bash
# gpt-oss-120b on 127.0.0.1:8096 as "gpt-oss" with the tested offload settings.
# usage: serve-gptoss.sh <logname> [extra ft serve args]   (later flags override these defaults)
# --cache-type radix: prefix caching on. Safe since PR #651 (bed7b1b) fixed the SWA radix-cache
#   crash (ERRORS.md F1 / upstream #683); pass --cache-type naive to turn it off again.
# --enable-cache-report: usage reports prefix-cached prompt tokens (ERRORS.md E8/F6).
export MODEL=${MODEL:-/data/models/hf/hub/models--openai--gpt-oss-120b/snapshots/b5c939de8f754692c1647ca79fbf85e8c1e70f8a}
export NAME=${NAME:-gpt-oss}
log=$1; shift
exec "$(dirname "$0")/serve.sh" "$log" --moe-strategy offload --moe-cache-auto --kv-reserve-tokens 65536 \
  --memory-ratio 0.8 --max-running-requests 4 --cache-type radix --enable-cache-report "$@"
