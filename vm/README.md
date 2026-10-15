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
| prefill.py | `prefill.py <port> <model> [chars]`: long-prompt prefill, cold then prefix-cached |
| ERRORS.md | every error hit, cause, status, fix plan |

Since 2026-10-15 the venv is an **editable install of this checkout** (`vm/setup-venv.sh --source`, which also installs pytest), so code edits take effect on the next `ft serve`. requirements-vm.lock.txt still describes the earlier wheel setup: plain `vm/setup-venv.sh` goes back to it, and a copy of that venv is in /data/freetoken-test/venv-wheel-backup.
Tests: `.venv/bin/python -m pytest -q -p no:cacheprovider tests/server tests/tokenizer -m "not slow"`.
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

### gpt-oss-120b (MXFP4, 61 GB; too big for the free VRAM), 2026-10-14

```
MODEL=/data/models/hf/hub/models--openai--gpt-oss-120b/snapshots/b5c939de8f754692c1647ca79fbf85e8c1e70f8a NAME=gpt-oss \
  vm/serve.sh gptoss_auto --moe-strategy offload --moe-cache-auto --kv-reserve-tokens 65536 --memory-ratio 0.8 --max-running-requests 4
vm/memguard.sh 4096 &
```

- Start to first answer: 72 s. Experts load serially into ~57 GB of pinned host RAM, leaving VM MemAvailable at 12 GB. memguard never fired.
- `--moe-cache-auto` → 2719 of 4608 expert slots on GPU (59%), 65k-token KV (2.8 GiB); GPU total 87 GB with vLLM's 44.
- Decode, batch 1, 512 tokens: **129 / 142 tok/s** (cold / warm). Warm TTFT 1.3 s (reasoning model).
- Prefill: 9.3k-token prompt in 3.2 s cold (~2.9k tok/s); repeat hit the prefix cache (9310 tokens), 1.7 s.
- 4 parallel streams × 512 tokens: 208 tok/s aggregate, ~52 per stream. More distinct experts per step means more misses.
- Tool calls OK when the tool has a description (see ERRORS.md E7); /v1/messages OK.
- Needs VRAM shared with nothing big: the Trading Platform desk Ollama model (37 GB, keep-alive 30 min) must be unloaded first.
