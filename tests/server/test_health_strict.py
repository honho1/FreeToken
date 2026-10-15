"""/health?strict=1: an HTTP status a plain probe (systemd, docker, curl -f) can trust."""

from __future__ import annotations

import time
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from freetoken.server.control_api import register_control_routes


def _state(**kw):
    base = dict(instance_id="i-1", fatal_error=None, maintenance_state="serving", load_progress=None,
                ready_at=time.monotonic(), config=SimpleNamespace(served_model_name="m"))
    base.update(kw)
    return SimpleNamespace(**base)


STATES = {
    "loading": _state(maintenance_state="loading", ready_at=None),
    "ok": _state(),
    "error": _state(fatal_error="backend worker freetoken-TP0-scheduler exited"),
    "rebuilding": _state(maintenance_state="rebuilding"),
}


def _client(state) -> TestClient:
    app = FastAPI(version="test")
    register_control_routes(app, lambda: state)
    return TestClient(app)


@pytest.mark.parametrize("name", STATES)
def test_plain_health_stays_200_with_the_state_in_the_body(name):
    r = _client(STATES[name]).get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == {"loading": "loading", "ok": "ok", "error": "error", "rebuilding": "ok"}[name]


@pytest.mark.parametrize("name,code", [("ok", 200), ("loading", 503), ("error", 503), ("rebuilding", 503)])
def test_strict_health_is_503_unless_serving(name, code):
    r = _client(STATES[name]).get("/health", params={"strict": "1"})
    assert r.status_code == code
    assert r.json() == _client(STATES[name]).get("/health").json()  # same body, only the status differs
