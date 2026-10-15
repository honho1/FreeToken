# FreeToken on VM 101: error log

One entry per problem: what happened, cause, status, fix plan. Newest at the bottom.
Status: **fixed** (done, verified) · **worked around** (outside FreeToken code) · **open** (plan only).
Logs are in /data/freetoken-test/*.log (not committed).

## E1. FlashInfer JIT: "Could not find nvcc", 2026-10-14
- **Seen:** first request after `ft serve` → backend died: `RuntimeError: Could not find nvcc and default cuda_home='/usr/local/cuda' doesn't exist` (flashinfer/jit/cpp_ext.py). API server then shut itself down.
- **Cause:** the nightly wheels prebuild FreeToken's own kernels, but FlashInfer still JIT-compiles attention kernels on first use. The VM has the driver only, no toolkit.
- **Status:** worked around. pip CUDA toolchain in the venv + `CUDA_HOME` in vm/serve.sh; vm/setup-venv.sh rebuilds it.
- **Fix plan (fork):** a `cuda-jit` extra in pyproject.toml pinning `nvidia-cuda-nvcc/crt/cccl/nvvm/nvjitlink==13.0.*` + `ninja`, and set `CUDA_HOME` from the pip location when unset (flashinfer honours it).

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

## E8. `usage.prompt_tokens_details.cached_tokens` not reported, 2026-10-14
- **Seen:** second identical 9.3k-token prompt: server log `#cached-token: 9310`, but the response `usage` has no `prompt_tokens_details`.
- **Impact:** cosmetic; clients can't see prefix-cache hits (OpenAI-style cost and latency dashboards).
- **Status:** open, low priority.
- **Fix plan:** fill `prompt_tokens_details.cached_tokens` from the scheduler's cached-token count in the OpenAI usage builder (the Anthropic API has `cache_read_input_tokens` for the same thing).

## Watch list (open upstream, not hit yet)
- #681 a request field msgpack can't pack → 500 + permanently leaked `requests.active`.
- #682 `/v1/completions` ignores `n`.
- #683 SWA radix cache frees its own slots under a specific prefix-cache pattern. **Affects gpt-oss** (see F1).
- #688 runtime CUDA OOM recovery is opt-in.

---

# Fork fix plan (2026-10-15)

Policy: every fix goes into this fork (branch `vm`); nothing is sent upstream. Each fix: a test that fails first, the fix, then `tests/server tests/tokenizer` + a live check on VM 101, then a status update in this file.

## F1. #683: SWA radix cache can crash the scheduler on gpt-oss (priority 1)
- **Risk:** gpt-oss (both sizes) runs `cache_type='swa_radix'` (seen in our log). Two overlapping requests that share their first tokens (agents reusing a system prompt) can kill the scheduler (`SWA-slot leak/double-free` assertion), and then the whole server exits (E5). Reported 9/9 reproducible on gpt-oss-20b.
- **Step 1, workaround (minutes):** serve gpt-oss with `--cache-type naive` until fixed. The report confirms it survives. Cost: no prefix reuse, so every prompt is prefilled in full (~3 s per 9k tokens at our measured ~2.9k tok/s).
- **Step 2, reproduce here:** script the report's two-request sequence (long prompt still running + short prompt sharing its head) against gpt-oss-120b → expect the assertion.
- **Step 3, fix:** merge open PR #651 (same assertion family, #204; 3 files, mergeable) into the fork and rerun the repro. If it still dies, fix `_cache_req_swa` / `match_prefix` along the report's analysis: an unfinished commit must re-point B's page-table row at the tree's slots for the whole committed span, not only `m.cached_len`.
- **Can it be fixed?** Yes, probably. It's the hardest item. If step 3 doesn't converge, step 1 stays as the permanent setting for gpt-oss and I'll tell you.
- **Status 2026-10-15: fixed in the fork** by PR #651 (cherry-picked as bed7b1b onto `vm`). `vm/serve-gptoss.sh` is back on `--cache-type radix` + `--enable-cache-report`. Smoke test: resolved `swa_radix`, 20-request stress 0 errors, 10 responses reporting cached tokens.
  - Step 1: `vm/serve-gptoss.sh` (all tested gpt-oss flags + `--cache-type naive`; a later `--cache-type radix` overrides it).
  - Step 2, reproduced: `vm/repro_683.py` (own script written from the report, not the reporter's gist) via `vm/repro_683_runs.sh` (fresh server per run, `--max-prefill-length 2048`).
    - **radix, before the fix: 3/3 runs crashed** on the first 20 ms trial: `AssertionError: SWA-slot leak/double-free: free(12690) + tree(425) != capacity(13110)` (+5 = the shared head), then "backend worker exited". Log: A's 2nd chunk and B prefilled in one batch, as reported.
    - naive: 2/2 runs survived all trials (20/100/300 ms).
  - Step 3, fixed: PR #651's commit applies cleanly. When an unfinished request's commit would free its copy of a tombstone another request still locks, it skips that commit and commits at finish.
    - Tests `tests/scheduler tests/kvcache tests/server tests/tokenizer -m "not slow"`: 1051 passed, 25 skipped.
    - Repro with #651: **3/3 runs survived** (9 trials), plus 2 more trials with B decoding 8 tokens.
    - `vm/stress_683.py` (60 requests, 4 at a time, prompt heads shared 0–3k tokens, idle checks between waves), 2 seeds: 120/120 ok, no integrity failures. Prefix cache still active: 59 responses with cached tokens, up to 1525.
    - **Control: same stress, seed 0, without #651 → crashed** in wave 2: `free(8860) + tree(4317) != capacity(13110)` (+67). So the stress test does catch the bug and #651 fixes it.

## F2. E5: server exits when the backend dies (priority 2)
- **Plan:** systemd unit `freetoken.service` (User=beyond1, ExecStart=vm/serve.sh, `Restart=on-failure`, `RestartSec=10`) so any crash (F1, OOM, etc.) self-heals. memguard becomes a sidecar unit. Optional later: merge open PR #688 (`--oom-recovery`, 4 commits, 35 files, mergeable) for in-process recovery from runtime CUDA OOM. It's large, so only if OOMs actually happen.
- **Seen 2026-10-15 (F1 control run):** after the backend died, the API server hung in "Waiting for connections to close" and the in-flight requests got no error; the clients just waited for their own timeout (600 s here). The unit must therefore use `TimeoutStopSec=20` + `KillMode=mixed` so systemd SIGKILLs a stuck shutdown and restarts.
- **Can it be fixed?** Yes.

## F3. #681: unpackable request field → HTTP 500 + leaked `requests.active` (priority 3)
- **Cause:** `state.new_user()` registers the uid (ack_map, event_map, stats) before `send_one` msgpack-packs the message. A pack error leaves the uid registered forever.
- **Plan:** in `generation.submit_generation` (and the two raw paths in openai_api.py ~L412/L428), wrap `send_one` in try/except. On failure, pop `ack_map`/`event_map`, call `stats.on_abort(uid)`, and raise a 400 (`invalid_request_error`). Test: `max_tokens=2**64` → 400, and `/v1/stats` active back to 0.
- **Can it be fixed?** Yes, small.

## F4. E4: `/health` always HTTP 200 (priority 4)
- **Plan:** `GET /health?strict=1` → 503 unless `status == "ok"` (control_api.py `health()`); the default stays for the desktop app. The systemd watchdog and wait-ready.sh use strict mode.
- **Can it be fixed?** Yes, small.

## F5. #682: `/v1/completions` silently ignores `n` (priority 5)
- **Plan:** copy chat's guard (`if req.n != 1: return create_error_response("Only n=1 is supported", param="n")`, openai_api.py L167) into `handle_completion`. Test: n=2 → 400.
- **Can it be fixed?** Yes, trivial.

## F6. E8: cached tokens missing from `usage` (priority 6)
- **Finding:** not a bug. FreeToken reports them only with `--enable-cache-report` (args.py). **Plan:** add the flag to serve.sh defaults.
- **Status 2026-10-15: done.** `vm/serve.sh` (the base every launcher uses) always passes `--enable-cache-report`. Live check on Qwen3.6-35B FP8 (offload 25%): the same 3804-token prompt twice → 2nd response `usage.prompt_tokens_details.cached_tokens = 3776`, 1st none.
- **Can it be fixed?** Yes, config only.

## F7. E1–E3: install needs a manual CUDA toolchain (priority 7)
- **Plan:** a `cuda-jit` extra in the fork's pyproject.toml (`nvidia-cuda-nvcc/crt/cccl/nvvm/nvjitlink==13.0.*`, `ninja`), and set `CUDA_HOME` to the pip `nvidia/cu13` dir at startup when unset and it exists. Then serve.sh no longer needs its exports.
- **Can it be fixed?** Yes.

## F8. Keeping the fork current
- **Plan:** `git fetch upstream && git merge upstream/main` into `vm` when wanted, then rerun the tests + a gpt-oss smoke run. Our fixes are small and local, so conflicts should be rare. Re-check whether upstream fixed #683/#681/#682 itself, and drop our version if so.

## Not fixable in software (limits, not bugs)
- **Host RAM ceiling:** offload keeps every expert in pinned host RAM. VM 101 has 86 GB (~72 usable), so ~65 GB of experts is the practical max (gpt-oss-120b fits; GLM-5.2-class models don't). Only fix: give VM 101 more RAM (pve has 124 GB, VM 100 takes 20, the host needs ≥12) or add DIMMs.
- **Offload speed:** speed falls as fewer experts fit on the GPU (Qwen 25% → 135, 10% → 82 tok/s; gpt-oss 4-way → 52/stream). That's PCIe-bound (measured 53 GB/s, already Gen5 x16).
- **Slower than vLLM when the model fits** (211 vs 224 tok/s): engine design. Use vLLM for models that fit.
