"""The one client for every generative model call: OpenRouter's chat completions API.

No module calls a model provider directly. Each module receives a `ChatClient` (or a fake
with the same `complete` method) as its client argument. Every call goes through
`monitoring.cached_call`, so it is cached on disk and its tokens and latency are recorded.

Reads OPENROUTER_API_KEY and OPENROUTER_BASE_URL from the environment or .env; the key
is never printed or logged. Jev is not served by OpenRouter and keeps its own client
(typesafe_sdk, TYPESAFE_API_KEY).
"""

import json
import os
import threading
import time
from typing import Any, Protocol

import httpx
from dotenv import load_dotenv
from pydantic import BaseModel

from triage_app import thresholds
from triage_app.cache import DiskCache
from triage_app.config import ROOT
from triage_app.monitoring import Recorder, cached_call

DEFAULT_BASE_URL = "https://openrouter.ai/api/v1"

# Process-wide throttle: OpenRouter limits requests per minute per model.
_next_slot: dict[str, float] = {}
_slot_lock = threading.Lock()


def _throttle(model: str) -> None:
    interval = 60.0 / thresholds.OPENROUTER_REQUESTS_PER_MINUTE
    with _slot_lock:
        now = time.monotonic()
        slot = max(now, _next_slot.get(model, 0.0))
        _next_slot[model] = slot + interval
    if slot > now:
        time.sleep(slot - now)


def _retry_delay(resp: httpx.Response, attempt: int) -> float:
    """Seconds to wait before retrying: the provider's reset time when given, else backoff."""
    after = resp.headers.get("retry-after")
    if after and after.replace(".", "", 1).isdigit():
        return min(float(after), thresholds.LLM_RETRY_MAX_S)
    try:
        reset_ms = resp.json()["error"]["metadata"]["headers"]["X-RateLimit-Reset"]
        return min(max(float(reset_ms) / 1000 - time.time(), 1.0), thresholds.LLM_RETRY_MAX_S)
    except (KeyError, TypeError, ValueError):
        return float(min(thresholds.LLM_RETRY_BASE_S * 2 ** attempt, thresholds.LLM_RETRY_MAX_S))


def failure_note(error: Exception) -> str:
    """A short, text-free description of a failed call for stage logs.

    OpenRouter errors carry the status code and the provider's message (never the email);
    anything else is reported by its type only.
    """
    text = str(error)
    if isinstance(error, RuntimeError) and text.startswith("OpenRouter "):
        return text.split(":", 1)[0] + (": " + text.split('"message":"', 1)[1].split('"', 1)[0][:80]
                                        if '"message":"' in text else "")
    return type(error).__name__


class Message(BaseModel):
    role: str  # "system" | "user" | "assistant"
    content: str


class Completion(BaseModel):
    text: str
    model: str
    input_tokens: int | None = None
    output_tokens: int | None = None


class ChatClient(Protocol):
    def complete(self, *, model: str, messages: list[Message], max_tokens: int = thresholds.LLM_MAX_TOKENS,
                 temperature: float = thresholds.LLM_TEMPERATURE, response_format: dict[str, Any] | None = None,
                 namespace: str = "chat", criteria_version: str = "") -> Completion: ...


class OpenRouterClient:
    """Chat completions over OpenRouter, cached and monitored."""

    def __init__(self, *, api_key: str | None = None, base_url: str | None = None,
                 cache: DiskCache | None = None, use_cache: bool = True,
                 recorder: Recorder | None = None, timeout: float = thresholds.LLM_TIMEOUT_S) -> None:
        load_dotenv(ROOT / ".env")
        self._api_key = api_key or os.environ.get("OPENROUTER_API_KEY", "")
        self.base_url = (base_url or os.environ.get("OPENROUTER_BASE_URL") or DEFAULT_BASE_URL).rstrip("/")
        self.cache = (cache or DiskCache()) if use_cache else None
        self.recorder = recorder
        self.timeout = timeout

    def _post(self, body: dict[str, Any]) -> Completion:
        if not self._api_key:
            raise RuntimeError("OPENROUTER_API_KEY is not set")
        for attempt in range(thresholds.LLM_MAX_RETRIES + 1):
            _throttle(body["model"])
            resp = httpx.post(
                f"{self.base_url}/chat/completions",
                headers={"Authorization": f"Bearer {self._api_key}", "Content-Type": "application/json"},
                json=body, timeout=self.timeout,
            )
            retryable = resp.status_code == 429 or resp.status_code >= 500
            if retryable and attempt < thresholds.LLM_MAX_RETRIES:
                time.sleep(_retry_delay(resp, attempt))
                continue
            break
        if resp.status_code >= 400:
            raise RuntimeError(f"OpenRouter {resp.status_code}: {resp.text[:500]}")
        data = resp.json()
        usage = data.get("usage") or {}
        return Completion(
            text=data["choices"][0]["message"].get("content") or "",
            model=data.get("model", body["model"]),
            input_tokens=usage.get("prompt_tokens"),
            output_tokens=usage.get("completion_tokens"),
        )

    def complete(self, *, model: str, messages: list[Message], max_tokens: int = thresholds.LLM_MAX_TOKENS,
                 temperature: float = thresholds.LLM_TEMPERATURE, response_format: dict[str, Any] | None = None,
                 namespace: str = "chat", criteria_version: str = "") -> Completion:
        body: dict[str, Any] = {
            "model": model,
            "messages": [m.model_dump() for m in messages],
            "max_tokens": max_tokens,
            "temperature": temperature,
            "usage": {"include": True},
        }
        if response_format is not None:
            body["response_format"] = response_format
        return cached_call(
            namespace=namespace, model=model, payload=body,
            call=lambda: self._post(body),
            dump=lambda c: c.model_dump(), load=Completion.model_validate,
            usage=lambda c: (c.input_tokens, c.output_tokens),
            input_text=json.dumps(body["messages"]), criteria_version=criteria_version,
            cache=self.cache, recorder=self.recorder,
        )
