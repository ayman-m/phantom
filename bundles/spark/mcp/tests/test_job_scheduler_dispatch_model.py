"""How a scheduled job's model reaches the chat route, and how a refusal comes back.

The scheduler never resolves or rewrites a model: it sends the job's
`model_id` as `body.model`, verbatim, and the chat route decides. When the
route cannot serve the model it ends the stream with an `error` event
(code MODEL_UNAVAILABLE) and no `done` response, and the run fails with that
text, which is what raises the existing job-run-failed notification.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import httpx
import pytest

from src.usecase.job_scheduler import CroniterJobScheduler


@pytest.fixture
def scheduler(tmp_path: Path) -> CroniterJobScheduler:
    async def _noop(tool_name: str, args: dict[str, Any], **_kw: Any) -> dict[str, Any]:
        return {"ok": True}

    return CroniterJobScheduler(definitions=[], dispatcher=_noop, data_root=tmp_path)


class _FakeResponse:
    def __init__(self, status_code: int, lines: list[str]) -> None:
        self.status_code = status_code
        self._lines = lines

    async def __aenter__(self) -> "_FakeResponse":
        return self

    async def __aexit__(self, *exc: Any) -> None:
        return None

    async def aread(self) -> bytes:
        return "\n".join(self._lines).encode()

    async def aiter_lines(self):
        for line in self._lines:
            yield line


def _install_fake_client(monkeypatch: pytest.MonkeyPatch, lines: list[str], status: int = 200) -> list[dict[str, Any]]:
    """Replace httpx.AsyncClient; return the list that collects each POST."""
    calls: list[dict[str, Any]] = []

    class _FakeClient:
        def __init__(self, *_a: Any, **_kw: Any) -> None:
            pass

        async def __aenter__(self) -> "_FakeClient":
            return self

        async def __aexit__(self, *exc: Any) -> None:
            return None

        def stream(self, method: str, url: str, *, json: Any = None, headers: Any = None) -> _FakeResponse:
            calls.append({"method": method, "url": url, "json": json, "headers": headers})
            return _FakeResponse(status, lines)

    monkeypatch.setattr(httpx, "AsyncClient", _FakeClient)
    return calls


def _sse(event: str, data: Any) -> list[str]:
    return [f"event: {event}", f"data: {json.dumps(data)}", ""]


OK_STREAM = (
    _sse("meta", {"session_id": "s1", "run_id": "r1"})
    + _sse("text_delta", {"text": "done"})
    + _sse("done", {"response": "done"})
)


def _dispatch(sched: CroniterJobScheduler, **kw: Any) -> dict[str, Any]:
    return asyncio.run(sched._dispatch_chat("hello", "nightly", **kw))


def test_a_canonical_ref_is_sent_verbatim_as_body_model(scheduler, monkeypatch) -> None:
    calls = _install_fake_client(monkeypatch, OK_STREAM)
    out = _dispatch(scheduler, model_id="anthropic/claude-opus-5-5")
    assert calls[0]["json"] == {"message": "hello", "model": "anthropic/claude-opus-5-5"}
    assert out["response"] == "done"


def test_a_legacy_bare_id_is_not_rewritten(scheduler, monkeypatch) -> None:
    calls = _install_fake_client(monkeypatch, OK_STREAM)
    _dispatch(scheduler, model_id="gemini-3.7-flash")
    assert calls[0]["json"] == {"message": "hello", "model": "gemini-3.7-flash"}


def test_no_model_id_sends_no_model_so_the_install_default_applies(scheduler, monkeypatch) -> None:
    calls = _install_fake_client(monkeypatch, OK_STREAM)
    _dispatch(scheduler)
    assert calls[0]["json"] == {"message": "hello"}


def test_thinking_and_policy_keep_their_existing_shape(scheduler, monkeypatch) -> None:
    calls = _install_fake_client(monkeypatch, OK_STREAM)
    _dispatch(
        scheduler, model_id="vertex/gemini-3.1-pro-preview", thinking_enabled=True,
        permission_policy={"deny": ["x"]},
    )
    assert calls[0]["json"] == {
        "message": "hello",
        "model": "vertex/gemini-3.1-pro-preview",
        "thinking": True,
        "permission_policy": {"deny": ["x"]},
    }
    assert calls[0]["method"] == "POST"
    assert calls[0]["url"].endswith("/api/chat")


def test_a_model_refusal_ends_the_run_with_the_model_unavailable_text(scheduler, monkeypatch) -> None:
    refusal = {
        "error": "Model unavailable: anthropic/claude-haiku-4-5 is retired. Try anthropic/claude-haiku-5-5.",
        "code": "MODEL_UNAVAILABLE",
        "suggestions": ["anthropic/claude-haiku-5-5"],
    }
    _install_fake_client(monkeypatch, _sse("meta", {"session_id": "s1"}) + _sse("error", refusal))
    with pytest.raises(RuntimeError) as err:
        _dispatch(scheduler, model_id="anthropic/claude-haiku-4-5")
    assert "MODEL_UNAVAILABLE" in str(err.value)
    assert "claude-haiku-5-5" in str(err.value)
