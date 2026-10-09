"""A DSPy language model that sends every call through triage_app.llm (OpenRouter).

DSPy modules (stages A, 5 and 6 and the verify agent) bind this LM, so their calls share
the project's disk cache and are recorded by monitoring like any other model call.

    lm = RouterLM(config.ANALYSIS_MODEL, client)      # client: a ChatClient or a fake
    predictor = dspy.Predict(MySignature)
    out = predictor(..., lm=lm)
"""

import json
import re
from typing import Any

import numpy  # noqa: F401  # import before dspy: its lazy importer breaks a later numpy import
import dspy

from triage_app import thresholds
from triage_app.llm import ChatClient, Message


class RouterLM(dspy.BaseLM):
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


_FENCE = re.compile(r"^\s*```[a-zA-Z]*\s*\n(.*?)\n\s*```\s*$", re.DOTALL)


class LenientJSONAdapter(dspy.JSONAdapter):
    """DSPy's JSON adapter, tolerant of two ways small models answer a one-field signature.

    Some models wrap the JSON in a Markdown code fence, or return the field's value bare
    (a list of claims) instead of an object keyed by the field name ({"claims": [...]}).
    Before the usual parse, strip the fence and, when the signature has exactly one output
    field and the reply is not keyed by it, wrap the value under that field. The value
    itself is still validated against the signature's type.
    """

    def parse(self, signature: type[dspy.Signature], completion: str) -> dict[str, Any]:
        parsed: dict[str, Any] = super().parse(signature, normalize_reply(signature, completion))
        return parsed


def normalize_reply(signature: type[dspy.Signature], completion: str) -> str:
    text = completion
    fenced = _FENCE.match(text)
    if fenced:
        text = fenced.group(1)
    outputs = list(signature.output_fields)
    if len(outputs) == 1:
        try:
            value = json.loads(text)
        except ValueError:
            return text
        if not (isinstance(value, dict) and outputs[0] in value):
            return json.dumps({outputs[0]: value})
    return text


def json_adapter() -> LenientJSONAdapter:
    """The adapter every DSPy module in this project uses."""
    return LenientJSONAdapter()
