import httpx
import pytest

from triage_app import llm, thresholds
from triage_app.llm import Message, OpenRouterClient


def response(status: int, body: dict[str, object], headers: dict[str, str] | None = None) -> httpx.Response:
    return httpx.Response(status, json=body, headers=headers or {},
                          request=httpx.Request("POST", "https://example.test/chat/completions"))


OK = {"model": "m", "choices": [{"message": {"content": "hi"}}], "usage": {"prompt_tokens": 3, "completion_tokens": 1}}
MSG = [Message(role="user", content="x")]


@pytest.fixture(autouse=True)
def no_throttle(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(thresholds, "OPENROUTER_REQUESTS_PER_MINUTE", 10**9)
    monkeypatch.setattr(llm, "_next_slot", {})


def test_retries_rate_limit_then_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    replies = [response(429, {"error": {}}, {"retry-after": "2"}), response(503, {}), response(200, OK)]
    slept: list[float] = []
    monkeypatch.setattr(llm.httpx, "post", lambda *a, **k: replies.pop(0))
    monkeypatch.setattr(llm.time, "sleep", slept.append)
    out = OpenRouterClient(api_key="k", use_cache=False).complete(model="m", messages=MSG)
    assert out.text == "hi" and out.input_tokens == 3
    assert slept[0] == 2.0 and slept[1] == thresholds.LLM_RETRY_BASE_S * 2


def test_gives_up_after_max_retries(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[int] = []

    def post(*a: object, **k: object) -> httpx.Response:
        calls.append(1)
        return response(429, {"error": {}})
    monkeypatch.setattr(llm.httpx, "post", post)
    monkeypatch.setattr(llm.time, "sleep", lambda s: None)
    with pytest.raises(RuntimeError, match="429"):
        OpenRouterClient(api_key="k", use_cache=False).complete(model="m", messages=MSG)
    assert len(calls) == thresholds.LLM_MAX_RETRIES + 1


def test_client_errors_are_not_retried(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[int] = []

    def post(*a: object, **k: object) -> httpx.Response:
        calls.append(1)
        return response(400, {"error": {"message": "bad"}})
    monkeypatch.setattr(llm.httpx, "post", post)
    with pytest.raises(RuntimeError, match="400"):
        OpenRouterClient(api_key="k", use_cache=False).complete(model="m", messages=MSG)
    assert len(calls) == 1


def test_throttle_spaces_calls_per_model(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(thresholds, "OPENROUTER_REQUESTS_PER_MINUTE", 20)
    slept: list[float] = []
    monkeypatch.setattr(llm.time, "monotonic", lambda: 100.0)
    monkeypatch.setattr(llm.time, "sleep", slept.append)
    llm._throttle("a")
    llm._throttle("a")
    llm._throttle("b")
    assert slept == [3.0]
