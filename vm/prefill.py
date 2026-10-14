"""Long-prompt prefill time: prefill.py <port> <model> [chars]. Run 0 is cold, run 1 shares the prefix."""
import json
import sys
import time
import urllib.request

port, model = sys.argv[1], sys.argv[2]
chars = int(sys.argv[3]) if len(sys.argv) > 3 else 30000
src = open("/data/freetoken/docs/models.md").read() + open("/data/freetoken/docs/cli.md").read()
text = (src * 10)[:chars]

for i in range(2):
    body = json.dumps({"model": model, "max_tokens": 32, "temperature": 0, "messages": [
        {"role": "user", "content": text + f"\n\nRun {i}. Summarise the above in one sentence."}]}).encode()
    req = urllib.request.Request(f"http://127.0.0.1:{port}/v1/chat/completions", body,
                                 {"Content-Type": "application/json"})
    t0 = time.time()
    d = json.load(urllib.request.urlopen(req, timeout=900))
    dt = time.time() - t0
    u = d["usage"]
    cached = (u.get("prompt_tokens_details") or {}).get("cached_tokens")
    print(f"run{i}: prompt {u['prompt_tokens']} tok (cached {cached}), {dt:.1f}s total, "
          f"~{u['prompt_tokens'] / dt:.0f} prompt tok/s")
