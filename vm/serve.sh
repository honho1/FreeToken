#!/bin/bash
# usage: [MODEL=dir NAME=name] serve.sh <logname> [ft serve args...]  — FreeToken on 127.0.0.1:8096 (default Qwen3.6-35B-A3B-FP8 as qwen-ft)
V=/data/freetoken/.venv
export CUDA_HOME=$V/lib/python3.12/site-packages/nvidia/cu13
export PATH=$CUDA_HOME/bin:$V/bin:$PATH
M=${MODEL:-$(ls -d /data/models/hf/hub/models--Qwen--Qwen3.6-35B-A3B-FP8/snapshots/*)}; NAME=${NAME:-qwen-ft}
log=$1; shift
mkdir -p /data/freetoken-test; cd /data/freetoken-test
exec $V/bin/ft serve --model $M --served-model-name $NAME --host 127.0.0.1 --port 8096 "$@" > $log.log 2>&1 < /dev/null
