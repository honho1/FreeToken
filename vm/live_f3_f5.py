"""Live check of F3 (#681), F4 (/health?strict) and F5 (n on /v1/completions) against a running server.

usage: live_f3_f5.py [--port 8096] [--model qwen-ft]
Sends each #681 shape next to a packable control and checks HTTP status + /v1/stats requests.active.
Exit 0 only if every check passes.
"""
import argparse
import json
import sys
import urllib.error
import urllib.request

ap = argparse.ArgumentParser()
ap.add_argument("--port", default="8096")
ap.add_argument("--model", default="qwen-ft")
a = ap.parse_args()
base = f"http://127.0.0.1:{a.port}"
BIG, NEG = 2**64, -(2**63) - 1


def call(method, path, body=None):
    data = None if body is None else json.dumps(body).encode()  # json.dumps keeps lone surrogates as \ud800
    req = urllib.request.Request(base + path, data, {"Content-Type": "application/json",
                                                     "anthropic-version": "2023-06-01"}, method=method)
    try:
        with urllib.request.urlopen(req, timeout=300) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")


def active():
    return json.loads(call("GET", "/v1/stats")[1])["requests"]["active"]


chat = lambda **kw: ("/v1/chat/completions", {"model": a.model, "max_tokens": 4, "messages": [{"role": "user", "content": "Say hi."}], **kw})  # noqa: E731
cmpl = lambda **kw: ("/v1/completions", {"model": a.model, "max_tokens": 4, "prompt": "Say hi.", **kw})  # noqa: E731
msgs = lambda **kw: ("/v1/messages", {"model": a.model, "max_tokens": 4, "messages": [{"role": "user", "content": "Say hi."}], **kw})  # noqa: E731
resp = lambda **kw: ("/v1/responses", {"model": a.model, "max_output_tokens": 16, "input": "Say hi.", **kw})  # noqa: E731

SHAPES = [
    ("chat ctk int 2**64", chat(chat_template_kwargs={"x": BIG}), chat(chat_template_kwargs={"x": 1})),
    ("chat ctk int < -2**63", chat(chat_template_kwargs={"x": NEG}), chat(chat_template_kwargs={"x": -1})),
    ("chat top_k 2**64", chat(top_k=BIG), chat(top_k=40)),
    ("chat max_tokens 2**64", chat(max_tokens=BIG), chat(max_tokens=4)),
    ("chat stop lone surrogate", chat(stop=["\ud800"]), chat(stop=["zz"])),
    ("completions max_tokens 2**64", cmpl(max_tokens=BIG), cmpl(max_tokens=4)),
    ("completions top_k 2**64", cmpl(top_k=BIG), cmpl(top_k=40)),
    ("messages top_k 2**64", msgs(top_k=BIG), msgs(top_k=40)),
    ("messages stop lone surrogate", msgs(stop_sequences=["\ud800"]), msgs(stop_sequences=["zz"])),
    ("responses top_k 2**64", resp(top_k=BIG), resp(top_k=40)),
]

ok = True
before = active()
for name, (p, hostile), (_, control) in SHAPES:
    hs, hb = call("POST", p, hostile)
    cs, _ = call("POST", p, control)
    after = active()
    good = 400 <= hs < 500 and cs == 200 and after == before
    ok &= good
    print(f"{'PASS' if good else 'FAIL'}  {name:30} hostile HTTP {hs}  control HTTP {cs}  active {before}->{after}  {hb[:90]!r}")
    before = after

s, b = call("POST", *cmpl(n=2))
good = s == 400 and '"param":"n"' in b.replace(" ", "")
ok &= good
print(f"{'PASS' if good else 'FAIL'}  completions n=2 -> HTTP {s} {b[:100]!r}")

s_plain, b_plain = call("GET", "/health")
s_strict, _ = call("GET", "/health?strict=1")
good = s_plain == 200 and s_strict == 200 and json.loads(b_plain)["status"] == "ok"
ok &= good
print(f"{'PASS' if good else 'FAIL'}  /health {s_plain} / strict {s_strict} while serving")
print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
