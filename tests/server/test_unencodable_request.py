"""#681: a request field msgpack cannot pack (an int >= 2**64, a lone UTF-16 surrogate) must answer
400 and leave no request registered. Before the fix it answered 500 and leaked one
`requests.active` forever, because new_user() registers the uid before send_one() packs it."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import msgpack
import pytest
import zmq
from fastapi import FastAPI
from fastapi.testclient import TestClient
from freetoken.message import BaseTokenizerMsg, TokenizeMsg
from freetoken.server.api_models import CompletionRequest
from freetoken.server.api_server import FrontendManager, UnencodableRequestError, install_unencodable_handler
from freetoken.server.openai_api import handle_completion
from freetoken.server.stats import StatsTracker
from freetoken.utils.mp import ZmqAsyncPushQueue


@pytest.fixture
def frontend(tmp_path):
    addr = f"ipc://{tmp_path}/tok.sock"
    state = FrontendManager(
        config=SimpleNamespace(max_output_tokens=None),
        send_tokenizer=ZmqAsyncPushQueue(addr, create=True, encoder=BaseTokenizerMsg.encoder),
        recv_tokenizer=None,
        maintenance_state="serving",
        initialized=True,  # no listener task: nothing answers in this test
        stats=StatsTracker(),
    )
    ctx = zmq.Context()
    pull = ctx.socket(zmq.PULL)
    pull.connect(addr)
    pull.setsockopt(zmq.RCVTIMEO, 2000)
    yield state, pull
    pull.close()
    ctx.term()
    state.send_tokenizer.stop()


def _submit(state, **fields):
    """Run the completions handler up to the point where it would wait for the engine's reply."""
    async def go():
        task = asyncio.ensure_future(handle_completion(
            CompletionRequest(model="m", prompt="hi", **fields), request=None, state=state, model_sampling={}))
        await asyncio.sleep(0.2)
        if task.done():
            return task.result()
        task.cancel()
        return "sent"
    return asyncio.run(go())


@pytest.mark.parametrize("fields", [{"top_k": 2**64}, {"stop": ["\ud800"]}])
def test_unpackable_field_raises_and_releases_the_request(frontend, fields):
    state, _ = frontend
    with pytest.raises(UnencodableRequestError):
        _submit(state, **fields)
    assert state.stats.active == 0
    assert state.ack_map == {} and state.event_map == {}


def test_packable_request_still_reaches_the_tokenizer(frontend):
    state, pull = frontend
    assert _submit(state, top_k=40) == "sent"
    msg = BaseTokenizerMsg.decoder(msgpack.unpackb(pull.recv(), raw=False))
    assert isinstance(msg, TokenizeMsg) and msg.text == "hi" and msg.sampling_params.top_k == 40
    assert state.stats.active == 1  # admitted and still in flight (no engine here to finish it)


@pytest.mark.parametrize("path,shape", [
    ("/v1/chat/completions", "openai"), ("/v1/completions", "openai"),
    ("/v1/responses", "openai"), ("/v1/messages", "anthropic"),
])
def test_handler_maps_the_error_to_a_400_in_each_protocol(path, shape):
    app = FastAPI()
    install_unencodable_handler(app)

    @app.post(path)
    async def boom():
        raise UnencodableRequestError("request contains a value the server cannot encode: Integer value out of range")

    r = TestClient(app).post(path, json={})
    assert r.status_code == 400
    body = r.json()
    if shape == "anthropic":
        assert body["type"] == "error"
    assert body["error"]["type"] == "invalid_request_error"
    assert "cannot encode" in body["error"]["message"]
