"""Concurrent prefix-sharing stress for the SWA radix cache (#683 family).

N requests, C at a time, raw completions whose prompts share heads of random length (0 to ~3k
tokens) built from a few base texts; random max_tokens 1-64. After all finish and after each
idle pause, /health must stay "ok" (the scheduler's integrity check runs when idle).

usage: stress_683.py [--port 8096] [--model gpt-oss] [--n 60] [--conc 4] [--seed 0]
"""
import argparse
import json
import random
import string
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor

ap = argparse.ArgumentParser()
ap.add_argument("--port", default="8096")
ap.add_argument("--model", default="gpt-oss")
ap.add_argument("--n", type=int, default=60)
ap.add_argument("--conc", type=int, default=4)
ap.add_argument("--seed", type=int, default=0)
args = ap.parse_args()
base = f"http://127.0.0.1:{args.port}"
rng = random.Random(args.seed)


def words(k):
    return " ".join("".join(rng.choice(string.ascii_lowercase) for _ in range(rng.randint(3, 9))) for _ in range(k))


heads = [words(450) for _ in range(3)]  # ~3k tokens each
jobs = []
for i in range(args.n):
    h = rng.choice(heads)
    cut = rng.choice([0, 5, 40, 140, 700, len(h)])
    jobs.append((h[:cut] + f" req{i} " + words(rng.choice([2, 20, 300])), rng.randint(1, 64)))


def health():
    try:
        return json.load(urllib.request.urlopen(base + "/health", timeout=5)).get("status")
    except Exception:
        return "unreachable"


def one(job):
    prompt, max_tokens = job
    time.sleep(rng.random() * 0.2)
    body = json.dumps({"model": args.model, "prompt": prompt, "max_tokens": max_tokens, "temperature": 0.8})
    req = urllib.request.Request(base + "/v1/completions", body.encode(), {"Content-Type": "application/json"})
    try:
        d = json.load(urllib.request.urlopen(req, timeout=600))
        return (d.get("usage") or {}).get("prompt_tokens_details") or {}, None
    except Exception as e:
        return None, repr(e)[:120]


t0 = time.time()
errors, cached_hits = [], 0
for start in range(0, len(jobs), 20):  # 3 waves with an idle gap, so the idle check runs between them
    with ThreadPoolExecutor(args.conc) as ex:
        for details, err in ex.map(one, jobs[start:start + 20]):
            if err:
                errors.append(err)
            elif details and details.get("cached_tokens"):
                cached_hits += 1
    time.sleep(4)
    status = health()
    print(f"wave {start // 20}: health={status}, errors so far={len(errors)}", flush=True)
    if status != "ok":
        print("BACKEND DIED", errors[:3]); sys.exit(1)
print(f"survived {len(jobs)} requests in {time.time() - t0:.0f}s, errors={len(errors)}, "
      f"responses reporting cached tokens={cached_hits}")
sys.exit(1 if errors else 0)
