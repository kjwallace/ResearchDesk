"""A DSPy language model that sends every call through triage_app.llm (OpenRouter).

DSPy modules (stages A, 5 and 6 and the verify agent) bind this LM, so their calls share
the project's disk cache and are recorded by monitoring like any other model call.

    lm = RouterLM(config.ANALYSIS_MODEL, client)      # client: a ChatClient or a fake
    predictor = dspy.Predict(MySignature)
    out = predictor(..., lm=lm)
"""

from typing import Any

import numpy  # noqa: F401  # import before dspy: its lazy importer breaks a later numpy import
import dspy

from triage_app import thresholds
from triage_app.llm import ChatClient, Message


class RouterLM(dspy.BaseLM):  # type: ignore[misc]
    def __init__(self, model: str, client: ChatClient, *, namespace: str = "dspy",
                 temperature: float = thresholds.LLM_TEMPERATURE,
                 max_tokens: int = thresholds.DSPY_MAX_TOKENS) -> None:
        # DSPy's own cache is off: the project's DiskCache, inside the client, caches instead.
        super().__init__(model=model, model_type="chat", temperature=temperature,
                         max_tokens=max_tokens, cache=False)
        self.client = client
        self.namespace = namespace

    def forward(self, prompt: str | None = None, messages: list[dict[str, Any]] | None = None,
                **kwargs: Any) -> dict[str, Any]:
        msgs = messages or [{"role": "user", "content": prompt or ""}]
        merged = {**self.kwargs, **kwargs}
        completion = self.client.complete(
            model=self.model,
            messages=[Message(role=m["role"], content=_text(m["content"])) for m in msgs],
            max_tokens=int(merged.get("max_tokens", thresholds.DSPY_MAX_TOKENS)),
            temperature=float(merged.get("temperature", thresholds.LLM_TEMPERATURE)),
            namespace=self.namespace,
        )
        return {
            "model": completion.model,
            "choices": [{"index": 0, "finish_reason": "stop",
                         "message": {"role": "assistant", "content": completion.text}}],
            "usage": {"prompt_tokens": completion.input_tokens or 0,
                      "completion_tokens": completion.output_tokens or 0},
        }


def _text(content: Any) -> str:
    """DSPy may send content as a list of parts; keep the text parts."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(p.get("text", "") for p in content if isinstance(p, dict))
    return str(content)
