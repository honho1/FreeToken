#!/bin/bash
# Rebuild /data/freetoken/.venv on VM 101 (no system CUDA toolkit needed).
# usage: vm/setup-venv.sh [--source]
#   default   nightly wheels pinned in requirements-vm.lock.txt (prebuilt kernel cache)
#   --source  editable install of this checkout (use once the fork carries code changes)
# The CUDA compiler comes from pip and MUST match torch's cuda-toolkit==13.0.3 pin:
# nvcc/crt/cccl/nvvm/nvjitlink 13.4 give "toolkit headers are incompatible" and "PTX .version 9.4".
set -euo pipefail
R=$(cd "$(dirname "$0")/.." && pwd)
UV=${UV:-$HOME/.local/bin/uv}
cd "$R"
[ -x .venv/bin/python ] || "$UV" venv -q -p 3.12 .venv
if [ "${1:-}" = "--source" ]; then
  CUDA_HOME=$R/.venv/lib/python3.12/site-packages/nvidia/cu13 "$UV" pip install -p .venv/bin/python -e ".[accel,dev]"
else
  "$UV" pip install -p .venv/bin/python -r vm/requirements-vm.lock.txt
fi
"$UV" pip install -p .venv/bin/python ninja \
  "nvidia-cuda-nvcc==13.0.*" "nvidia-cuda-crt==13.0.*" "nvidia-cuda-cccl==13.0.*" \
  "nvidia-nvvm==13.0.*" "nvidia-nvjitlink==13.0.*"
C=$R/.venv/lib/python3.12/site-packages/nvidia/cu13
[ -e "$C/lib64" ] || ln -s lib "$C/lib64"
[ -e "$C/lib/libcudart.so" ] || ln -s libcudart.so.13 "$C/lib/libcudart.so"
"$C/bin/nvcc" --version | tail -1
.venv/bin/ft --version
