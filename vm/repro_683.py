"""Repro for the SWA radix-cache double free (upstream #683), written from the report's description.

A: long raw-completion prompt (> 2048 tokens, so it prefills in two chunks), streamed, max_tokens 200.
B: sent `delay` ms later, short prompt sharing A's first few tokens, max_tokens 4 (must decode).
Then polls /health: exit 1 if the backend died, 0 if it stayed "ok".

usage: repro_683.py [--port 8096] [--model gpt-oss] [--delays 20,100,300] [--words 400]
"""
import argparse
import json
import random
import string
import sys
import threading
import time
import urllib.request

ap = argparse.ArgumentParser()
ap.add_argument("--port", default="8096")
ap.add_argument("--model", default="gpt-oss")
ap.add_argument("--delays", default="20,100,300")
ap.add_argument("--words", type=int, default=400)
ap.add_argument("--b-max-tokens", type=int, default=4)
args = ap.parse_args()
base = f"http://127.0.0.1:{args.port}"


def post(body, stream):
    req = urllib.request.Request(base + "/v1/completions", json.dumps(body).encode(),
                                 {"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=600) as r:
        if stream:
            for _ in r:
                pass
            return "streamed"
        return json.load(r)["choices"][0]["text"]


def health():
    try:
        return json.load(urllib.request.urlopen(base + "/health", timeout=5))
    except Exception as e:  # server gone entirely
        return {"status": "unreachable", "error": repr(e)}


def word(rng):
    return "".join(rng.choice(string.ascii_lowercase) for _ in range(rng.randint(4, 9)))


for trial, delay in enumerate(int(d) for d in args.delays.split(",")):
    rng = random.Random(trial)
    nonce = "".join(rng.choice(string.ascii_lowercase) for _ in range(10))
    prompt_a = f"{nonce}r0 " + " ".join(f"{nonce}{word(rng)}" for _ in range(args.words))
    prompt_b = f"{nonce}probe0 hi"
    errors = []

    def run(body, stream):
        try:
            post(body, stream)
        except Exception as e:
            errors.append(repr(e))

    ta = threading.Thread(target=run, args=({"model": args.model, "prompt": prompt_a, "max_tokens": 200,
                                             "temperature": 0, "stream": True}, True))
    tb = threading.Thread(target=run, args=({"model": args.model, "prompt": prompt_b,
                                             "max_tokens": args.b_max_tokens, "temperature": 0}, False))
    ta.start(); time.sleep(delay / 1000); tb.start(); ta.join(); tb.join()
    status = health()
    for _ in range(15):  # the integrity check runs when the scheduler goes idle
        time.sleep(1)
        status = health()
        if status.get("status") != "ok":
            break
    print(f"trial {trial} delay {delay} ms: request errors={errors or 'none'} health={status.get('status')} "
          f"{status.get('message') or status.get('error') or ''}", flush=True)
    if status.get("status") != "ok":
        sys.exit(1)
print("survived all trials")
