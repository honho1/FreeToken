# FreeToken on VM 101: error log

One entry per problem: what happened, cause, status, fix plan. Newest at the bottom.
Status: **fixed** (done, verified) · **worked around** (outside FreeToken code) · **open** (plan only).
Logs are in /data/freetoken-test/*.log (not committed).

## E1. FlashInfer JIT: "Could not find nvcc", 2026-10-14
- **Seen:** first request after `ft serve` → backend died: `RuntimeError: Could not find nvcc and default cuda_home='/usr/local/cuda' doesn't exist` (flashinfer/jit/cpp_ext.py). API server then shut itself down.
- **Cause:** the nightly wheels prebuild FreeToken's own kernels, but FlashInfer still JIT-compiles attention kernels on first use. The VM has the driver only, no toolkit.
- **Status:** worked around. pip CUDA toolchain in the venv + `CUDA_HOME` in vm/serve.sh; vm/setup-venv.sh rebuilds it.
- **Fix plan (fork):** a `cuda-jit` extra in pyproject.toml pinning `nvidia-cuda-nvcc/crt/cccl/nvvm/nvjitlink==13.0.*` + `ninja`, and set `CUDA_HOME` from the pip location when unset (flashinfer honours it). Worth offering upstream: docs/install.md says a toolkit is needed but not that a pip one works.

## E2. `ninja` not found, 2026-10-14
- **Seen:** `FileNotFoundError: 'ninja'` on the same first request.
- **Cause:** flashinfer builds with ninja, and the `accel` extra doesn't pull it in.
- **Status:** worked around (ninja in the venv, venv bin on PATH in serve.sh).
- **Fix plan:** same `cuda-jit` extra as E1.

## E3. CUDA 13.4 vs 13.0 mismatch, 2026-10-14
- **Seen:** (a) `#error "CUDA compiler and CUDA toolkit headers are incompatible"` (cccl); (b) after pinning nvcc: `ptxas fatal: Unsupported .version 9.4; current version is '9.0'`.
- **Cause:** unpinned `nvidia-cuda-nvcc` resolved to 13.4.92 and pulled nvvm/nvjitlink 13.4. torch 2.14.1 pins `cuda-toolkit==13.0.3`, so runtime/headers were 13.0. Every compiler piece has to be 13.0.x. The nvjitlink bump also changed a torch runtime library.
- **Status:** fixed (all pinned to 13.0.x; torch matmul checked; 3 configs served cleanly).
- **Fix plan:** pins in vm/setup-venv.sh (done); E1's extra must pin `==13.0.*`, never `>=13`.

## E4. `/health` is HTTP 200 while loading or dead, 2026-10-14
- **Seen:** readiness loop said HEALTHY in 10 s; real requests got 503 for ~90 s more.
- **Cause:** by design. control_api.py `/health` always answers 200 and puts `status: loading|ok|error` in the body (api_server.py `maintenance_state`). Not a bug, but plain HTTP probes (systemd, docker, uptime monitors) read 200 as healthy.
- **Status:** worked around. vm/wait-ready.sh waits for a real 8-token completion.
- **Fix plan (fork, small):** `GET /health?strict=1` (or `/ready`) returning 503 unless `status == ok`. Keep the default as is, because the desktop app polls `/health` for load progress.

## E5. Backend death stops the whole server, no restart, 2026-10-14
- **Seen:** after E1/E2 the log says "Backend worker is gone and cannot be restarted; stopping the API server" (api_server.py `_exit_after_backend_death`).
- **Cause:** by design; there is no supervisor. #688 (open upstream) adds opt-in recovery for runtime CUDA OOM only.
- **Status:** open (not needed for testing).
- **Fix plan:** if this becomes a service, run it under a systemd unit with `Restart=on-failure` instead of patching the engine. Track #688 for OOM recovery.

## E6. (ours) `pkill -f`/`pgrep -f` matched the ssh command, 2026-10-14
- **Seen:** `ssh ml 'pkill -f "ft serve --model" …'` exited 255. The pattern matched the remote bash running the command, so it killed itself.
- **Status:** fixed. Use a bracket pattern: `pgrep -f "[b]in/ft serve" | xargs -r kill`.

## E7. gpt-oss: tool without `description` → HTTP 400, 2026-10-14
- **Seen:** `/v1/chat/completions` with `tools=[{function:{name, parameters}}]` (no description) → 400 `could not encode request: 'dict object' has no attribute 'description'`; tokenizer log `UndefinedError`.
- **Cause:** the gpt-oss checkpoint's chat_template.jinja (line 113) emits `"// " + tool.description` unconditionally. The OpenAI API makes `description` optional, and FreeToken passes the tool dict to the template as is.
- **Impact:** low for agents (Claude Code, Codex and OpenCode always send descriptions); any client that omits it fails outright on gpt-oss. The same tool WITH a description returned a correct `tool_calls`.
- **Status:** fixed 2026-10-15 in the fork (branch `vm`, commit "fix(tokenizer): …").
- **Fix:** `tokenizer/tokenize.py` `_render` is the single place every API path (OpenAI, Anthropic, Responses) renders the template. If the render raises `UndefinedError`/`TypeError` and some tool has an absent or None description, it renders once more with `""` filled in (`_with_tool_descriptions`; handles the `{"type":"function","function":{…}}` and flat `{"name":…}` shapes and never mutates the request). Templates that already accept a missing description get the tools untouched, so their prompts stay byte-identical; errors unrelated to descriptions still raise.
- **Verified:**
  - 5 new tests in tests/tokenizer/test_tokenize.py: red before the fix (3 failed), green after.
  - `tests/server` + `tests/tokenizer`: 678 passed, 24 skipped (need weights).
  - Real gpt-oss tokenizer: a missing description renders identically to `""`.
  - Live gpt-oss-120b on the source build: OpenAI tools with description missing / `null` / set → all HTTP 200 with a correct `get_weather` call. Anthropic `/v1/messages` tool without description → `tool_use` get_weather {city: Paris}. 0 "tokenization failed" lines, decode 141 tok/s (same as the wheel).
- **Upstream:** template-agnostic and small; can be offered as a PR to FlashML-org/FreeToken.

## E8. `usage.prompt_tokens_details.cached_tokens` not reported, 2026-10-14
- **Seen:** second identical 9.3k-token prompt: server log `#cached-token: 9310`, but the response `usage` has no `prompt_tokens_details`.
- **Impact:** cosmetic; clients can't see prefix-cache hits (OpenAI-style cost and latency dashboards).
- **Status:** open, low priority.
- **Fix plan:** fill `prompt_tokens_details.cached_tokens` from the scheduler's cached-token count in the OpenAI usage builder (the Anthropic API has `cache_read_input_tokens` for the same thing).

## Watch list (open upstream, not hit yet)
- #681 a request field msgpack can't pack → 500 + permanently leaked `requests.active`.
- #682 `/v1/completions` ignores `n`.
- #683 SWA radix cache frees its own slots under a specific prefix-cache pattern.
- #688 runtime CUDA OOM recovery is opt-in.
