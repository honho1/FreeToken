"""What does Qwen3.6-35B-A3B cost to keep loaded on VM 101, per backend? (VRAM, host RAM, decode speed)

Runs on the VM: python3 measure_cost.py [--runs 6] > cost.tsv
- vllm:            the OpenDots vLLM already running on :8095 (FP8, gpu-util 0.45); measured, not restarted
- ollama:          the Trading Platform desk model tp-desk-qwen3.6-35b-a3b-q8 (Q8 GGUF), loaded with keep_alive 1m
- freetoken-*:     vm/serve.sh on :8096 (FP8), --num-tokens 65536, experts all on GPU (fused) or a share cached (offload)
Decode = streamed completion tokens / time after first token, 512 tokens, temperature 0, batch 1.
"""
import argparse
import json
import statistics
import subprocess
import time
import urllib.request

ap = argparse.ArgumentParser()
ap.add_argument("--runs", type=int, default=6)
a = ap.parse_args()
PROMPT = "Write a detailed 600-word explanation of how a Mixture-of-Experts transformer routes tokens."
KEY = open("/data/opendots-stack/vllm.key").read().strip()


def sh(cmd):
    return subprocess.run(cmd, shell=True, capture_output=True, text=True).stdout.strip()


def gpu_by_pid():
    out = {}
    for line in sh("nvidia-smi --query-compute-apps=pid,used_memory --format=csv,noheader,nounits").splitlines():
        pid, mib = [x.strip() for x in line.split(",")]
        out[int(pid)] = int(mib)
    return out


def mem_used_mib():
    m = dict(l.split(":") for l in open("/proc/meminfo"))
    kb = lambda k: int(m[k].split()[0])  # noqa: E731
    return (kb("MemTotal") - kb("MemAvailable")) // 1024


def decode_tps(base, model, headers=None, extra=None):
    body = {"model": model, "messages": [{"role": "user", "content": PROMPT}], "max_tokens": 512,
            "temperature": 0, "stream": True, "stream_options": {"include_usage": True}, **(extra or {})}
    req = urllib.request.Request(base + "/chat/completions", json.dumps(body).encode(),
                                 {"Content-Type": "application/json", **(headers or {})})
    t0 = time.time(); first = None; usage = None; n = 0
    with urllib.request.urlopen(req, timeout=600) as r:
        for line in r:
            line = line.decode().strip()
            if not line.startswith("data:") or line.endswith("[DONE]"):
                continue
            d = json.loads(line[5:])
            usage = d.get("usage") or usage
            ch = d.get("choices") or []
            if ch and (ch[0].get("delta", {}).get("content") or ch[0].get("delta", {}).get("reasoning_content")
                       or ch[0].get("delta", {}).get("reasoning")):
                n += 1
                first = first or time.time()
    toks = (usage or {}).get("completion_tokens") or n
    return toks / (time.time() - first), toks


def measure(name, base, model, gpu_pids, ram_delta, headers=None, extra=None):
    decode_tps(base, model, headers, extra)  # warm-up, not reported
    runs = [decode_tps(base, model, headers, extra) for _ in range(a.runs)]
    tps = [r[0] for r in runs]
    vram = sum(gpu_by_pid().get(p, 0) for p in gpu_pids)
    print(f"{name}\t{vram}\t{ram_delta}\t{statistics.median(tps):.1f}\t{min(tps):.1f}-{max(tps):.1f}\t{len(runs)}\t{min(r[1] for r in runs)}", flush=True)


print("backend\tvram_mib\thost_ram_mib\tdecode_tps_median\trange\truns\tmin_tokens", flush=True)

# vLLM (already running; RAM delta not measurable without restarting it -> blank)
vllm_pid = int(sh("pgrep -f VLLM::EngineCore | head -1") or 0)
measure("vllm (FP8, gpu-util 0.45)", "http://127.0.0.1:8095/v1", "qwen3.6-35b-a3b", [vllm_pid], "",
        {"Authorization": "Bearer " + KEY}, {"chat_template_kwargs": {"enable_thinking": False}})

for name, args in [
    ("freetoken fused (all experts on GPU)", "--moe-strategy fused"),
    ("freetoken offload 50% experts", "--moe-strategy offload --moe-cache-rate 0.5"),
    ("freetoken offload 25% experts", "--moe-strategy offload --moe-cache-rate 0.25"),
    ("freetoken offload 10% experts", "--moe-strategy offload --moe-cache-rate 0.1"),
]:
    before_pids = set(gpu_by_pid()); ram0 = mem_used_mib()
    sh(f"cd /data/freetoken-test && (setsid nohup /data/freetoken/vm/serve.sh cost_probe {args} --num-tokens 65536 "
       "--max-running-requests 4 >/dev/null 2>&1 < /dev/null &)")
    if "READY" not in sh("/data/freetoken/vm/wait-ready.sh qwen-ft 900"):
        print(f"{name}\tFAILED to start", flush=True)
    else:
        pids = set(gpu_by_pid()) - before_pids
        measure(name, "http://127.0.0.1:8096/v1", "qwen-ft", pids, mem_used_mib() - ram0,
                extra={"chat_template_kwargs": {"enable_thinking": False}})
    sh('pgrep -f "[b]in/ft serve" | xargs -r kill')
    for _ in range(60):
        if not sh('pgrep -f "[b]in/ft serve"'):
            break
        time.sleep(1)
    time.sleep(8)

# Ollama desk model (Trading Platform), short keep-alive so it does not stay loaded
before_pids = set(gpu_by_pid()); ram0 = mem_used_mib()
OLL = "http://100.77.232.15:11434"
urllib.request.urlopen(urllib.request.Request(OLL + "/api/generate", json.dumps(
    {"model": "tp-desk-qwen3.6-35b-a3b-q8", "prompt": "hi", "keep_alive": "1m", "stream": False,
     "options": {"num_predict": 1}}).encode(), {"Content-Type": "application/json"}), timeout=600).read()
pids = set(gpu_by_pid()) - before_pids
measure("ollama tp-desk (Q8 GGUF)", OLL + "/v1", "tp-desk-qwen3.6-35b-a3b-q8", pids, mem_used_mib() - ram0,
        extra={"reasoning_effort": "none"})
