"""Fake clients shared by every test. No test calls a live model or the network."""

import hashlib
import json
from collections.abc import Callable
from typing import Any

import numpy as np

from triage_app.embed import Vector
from triage_app.llm import Completion, Message
from triage_app.monitoring import cached_call


class FakeChat:
    """Answers chat calls from a script: a fixed string, a list consumed in order, or a function.

    Reports fixed token counts so monitoring can be tested. Records every call it saw.
    """

    def __init__(self, reply: str | list[str] | Callable[[list[Message]], str] = "{}",
                 input_tokens: int = 100, output_tokens: int = 20) -> None:
        self.reply = reply
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens
        self.calls: list[dict[str, Any]] = []

    def complete(self, *, model: str, messages: list[Message], max_tokens: int = 4096,
                 temperature: float = 0.0, response_format: dict[str, Any] | None = None,
                 namespace: str = "chat", criteria_version: str = "") -> Completion:
        self.calls.append({"model": model, "messages": messages, "namespace": namespace})
        if callable(self.reply):
            text = self.reply(messages)
        elif isinstance(self.reply, list):
            text = self.reply.pop(0)
        else:
            text = self.reply
        return cached_call(
            namespace=namespace, model=model, payload=[m.model_dump() for m in messages],
            call=lambda: Completion(text=text, model=model, input_tokens=self.input_tokens,
                                    output_tokens=self.output_tokens),
            dump=lambda c: c.model_dump(), load=Completion.model_validate,
            usage=lambda c: (c.input_tokens, c.output_tokens),
        )


class FakeEmbedder:
    """Deterministic bag-of-words vectors: texts sharing words have high cosine similarity."""

    model = "fake-embedder"
    max_tokens = 64

    def __init__(self, dim: int = 64) -> None:
        self.dim = dim

    def count_tokens(self, text: str) -> int:
        return len(text.split())

    def _vec(self, text: str) -> list[float]:
        v = np.zeros(self.dim, dtype=np.float64)
        for word in text.lower().split():
            h = int(hashlib.sha256(word.strip(".,;:!?\"'()").encode()).hexdigest(), 16)
            v[h % self.dim] += 1.0
        n = float(np.linalg.norm(v))
        return [float(x) for x in (v / n if n else v)]

    def embed(self, texts: list[str]) -> Vector:
        rows = [cached_call(namespace="embed", model=self.model, payload=t,
                            call=lambda t=t: self._vec(t), dump=lambda v: v, load=list,  # type: ignore[misc]
                            usage=lambda _v, t=t: (self.count_tokens(t), 0))  # type: ignore[misc]
                for t in texts]
        return np.asarray(rows, dtype=np.float32)


class FakeJev:
    """Stands in for typesafe_sdk.TypeSafeClient.system_one.

    `answers` maps a question name to a probability (Noul) or a probability dict (Choice);
    a function of the state gives per-email answers. Unlisted Nouls get 0.0. Records each
    request so tests can check what Jev was sent.
    """

    def __init__(self, answers: dict[str, Any] | Callable[[dict[str, Any]], dict[str, Any]] | None = None,
                 model: str = "jev-fake") -> None:
        self.answers = answers or {}
        self.model = model
        self.requests: list[dict[str, Any]] = []

    def system_one(self, state: Any, questions: Any, **_: Any) -> Any:
        from typesafe_sdk import ChoiceAnswer, NoulAnswer, SystemOneResponse, Usage

        self.requests.append({"state": state, "questions": questions})
        given = self.answers(state) if callable(self.answers) else self.answers
        out: dict[str, Any] = {}
        for name, q in questions.items():
            kind = q.get("type") if isinstance(q, dict) else getattr(q, "type", None)
            value = given.get(name)
            if kind == "choice":
                criteria = q["criteria"] if isinstance(q, dict) else q.criteria
                probs = value or {opt: 1.0 / len(criteria) for opt in criteria}
                best = max(probs, key=lambda k: probs[k])
                out[name] = ChoiceAnswer(type="choice", choice=best, confidence=probs[best], probabilities=probs)
            else:
                out[name] = NoulAnswer(type="noul", noul=float(value or 0.0))
        return SystemOneResponse.model_construct(
            model=self.model, usage=Usage(input_tokens=1000, output_tokens=14), answers=out)


def as_json(obj: Any) -> str:
    return json.dumps(obj)
