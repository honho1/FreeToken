#!/bin/bash
# usage: [MODEL=dir NAME=name] serve.sh <logname> [ft serve args...]  — FreeToken on 127.0.0.1:8096 (default Qwen3.6-35B-A3B-FP8 as qwen-ft); always --enable-cache-report (ERRORS.md F6)
V=/data/freetoken/.venv
# CUDA toolkit for FlashInfer JIT: the system install (apt cuda-toolkit-13-0, 2026-10-15) if present,
# else the pip copy in the venv (vm/setup-venv.sh). Both must be 13.0.x to match torch.
if [ -x /usr/local/cuda/bin/nvcc ]; then export CUDA_HOME=/usr/local/cuda; else export CUDA_HOME=$V/lib/python3.12/site-packages/nvidia/cu13; fi
export PATH=$CUDA_HOME/bin:$V/bin:$PATH
M=${MODEL:-$(ls -d /data/models/hf/hub/models--Qwen--Qwen3.6-35B-A3B-FP8/snapshots/*)}; NAME=${NAME:-qwen-ft}
log=$1; shift
mkdir -p /data/freetoken-test; cd /data/freetoken-test
exec $V/bin/ft serve --model $M --served-model-name $NAME --host 127.0.0.1 --port 8096 --enable-cache-report "$@" > $log.log 2>&1 < /dev/null
