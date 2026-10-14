"""Streamed decode speed: tps.py <port> <model> [keyfile]. Counts content + reasoning tokens via usage."""
import json
import sys
import time
import urllib.request

port, model = sys.argv[1], sys.argv[2]
headers = {"Content-Type": "application/json"}
if len(sys.argv) > 3:
    headers["Authorization"] = "Bearer " + open(sys.argv[3]).read().strip()
prompt = "Write a detailed 600-word explanation of how a Mixture-of-Experts transformer routes tokens."

for i in range(2):
    body = json.dumps({"model": model, "messages": [{"role": "user", "content": prompt}],
                       "max_tokens": 512, "temperature": 0, "stream": True,
                       "stream_options": {"include_usage": True},
                       "chat_template_kwargs": {"enable_thinking": False}}).encode()
    req = urllib.request.Request(f"http://127.0.0.1:{port}/v1/chat/completions", body, headers)
    t0 = time.time(); first = None; chunks = 0; text = ""; reasoning = 0; usage = None
    with urllib.request.urlopen(req, timeout=900) as r:
        for line in r:
            line = line.decode().strip()
            if not line.startswith("data:") or line.endswith("[DONE]"):
                continue
            d = json.loads(line[5:])
            usage = d.get("usage") or usage
            if not d.get("choices"):
                continue
            delta = d["choices"][0].get("delta", {})
            c = delta.get("content") or ""
            rc = delta.get("reasoning_content") or delta.get("reasoning") or ""
            if c or rc:
                if first is None:
                    first = time.time()
                chunks += 1; text += c; reasoning += bool(rc)
    t1 = time.time()
    if first is None:
        print(f"run{i}: no tokens streamed in {t1 - t0:.1f}s, usage={usage}")
        continue
    toks = (usage or {}).get("completion_tokens") or chunks
    print(f"run{i}: ttft {first - t0:.2f}s, {toks} tokens ({reasoning} reasoning chunks), "
          f"decode {toks / (t1 - first):.1f} tok/s, total {t1 - t0:.1f}s")
print("sample:", text[:200].replace("\n", " "))
