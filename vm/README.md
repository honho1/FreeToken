# FreeToken on VM 101

Fork: https://github.com/honho1/FreeToken (branch `vm`; `upstream` = FlashML-org/FreeToken).
Checkout `/data/freetoken`, venv `/data/freetoken/.venv`, logs `/data/freetoken-test/`.

| file | what |
|---|---|
| setup-venv.sh | rebuild the venv: nightly wheels from requirements-vm.lock.txt (or `--source` = editable install of this checkout) + pip CUDA 13.0 toolchain + ninja |
| requirements-vm.lock.txt | `uv pip freeze` of the working venv (2026-10-14) |
| serve.sh | `[MODEL=dir NAME=name] serve.sh <logname> [ft serve args]`: 127.0.0.1:8096, default Qwen3.6-35B-A3B-FP8 as qwen-ft |
| wait-ready.sh | `wait-ready.sh <name> [timeout]`: waits for a real completion (see ERRORS.md E4) |
| memguard.sh | `memguard.sh [MiB]`: kills ft serve if MemAvailable < limit (default 4096). Start after serve. |
| tps.py | `tps.py <port> <model> [keyfile]`: 2x 512-token streamed decode |
| ERRORS.md | every error hit, cause, status, fix plan |

The venv runs the nightly wheel, not this checkout. To run code changes made in the fork: `vm/setup-venv.sh --source`.
Stop the server: `pgrep -f "[b]in/ft serve" | xargs -r kill`.

## Results

`ft bench bw`: CPU STREAM 46.6 GB/s, PCIe H2D 53.7 / D2H 57.3 GB/s (Gen5 x16) → offload for every format.

Qwen3.6-35B-A3B-FP8, batch 1, 512 tokens, vLLM running alongside on the same GPU:

| engine | experts on GPU | tok/s | warm TTFT |
|---|---|---|---|
| vLLM 0.31 (:8095) | all | 224 | 0.02 s |
| FreeToken fused | all | 211 | 0.04 s |
| FreeToken offload | 25% | 135 | 0.6 s |
| FreeToken offload | 10% | 82 | 0.6 s |

Same text as vLLM at temperature 0. OpenAI tool calls and Anthropic /v1/messages both OK.
The first request after a fresh install compiles FlashInfer kernels (~100 s, cached in ~/.cache/flashinfer).
