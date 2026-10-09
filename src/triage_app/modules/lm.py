"""A DSPy language model that sends every call through triage_app.llm (OpenRouter).

DSPy modules (stages A, 5 and 6 and the verify agent) bind this LM, so their calls share
the project's disk cache and are recorded by monitoring like any other model call.

    lm = RouterLM(config.ANALYSIS_MODEL, client)      # client: a ChatClient or a fake
    predictor = dspy.Predict(MySignature)
    out = predictor(..., lm=lm)
"""

import json
import re
from collections.abc import Callable
from typing import Any, TypeVar

import numpy  # noqa: F401  # import before dspy: its lazy importer breaks a later numpy import
import dspy
from dspy.utils.exceptions import AdapterParseError

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

    Some models wrap the JSON in a Markdown code fence, answer in DSPy's chat-adapter format
    ("[[ ## claims ## ]]" headers) or in tool-call markup (<parameter name="...">), or return the field's value bare (a list of claims)
    instead of an object keyed by the field name ({"claims": [...]}). Before the usual
    parse, turn those into the expected JSON object. The values are still validated
    against the signature's types.
    """

    def parse(self, signature: type[dspy.Signature], completion: str) -> dict[str, Any]:
        parsed: dict[str, Any] = super().parse(signature, normalize_reply(signature, completion))
        return parsed


_SECTION = re.compile(r"^\[\[ ## (\w+) ## \]\]\s*$", re.MULTILINE)


def _unfence(text: str) -> str:
    fenced = _FENCE.match(text)
    return fenced.group(1) if fenced else text


def _sections(text: str) -> dict[str, Any] | None:
    """DSPy chat-adapter style replies ("[[ ## field ## ]]" headers) as a field -> value dict."""
    marks = list(_SECTION.finditer(text))
    if not marks:
        return None
    out: dict[str, Any] = {}
    for i, m in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(text)
        raw = _unfence(text[m.end():end].strip())
        if m.group(1) == "completed":
            continue
        try:
            out[m.group(1)] = json.loads(raw)
        except ValueError:
            out[m.group(1)] = raw
    return out


_PARAMETER = re.compile(r'<(?:invoke:)?parameter name="(\w+)">(.*?)</parameter>', re.DOTALL)


def _tool_parameters(text: str, fields: list[str]) -> dict[str, Any] | None:
    """Tool-call markup (<parameter name="field">value</parameter>) as a field -> value dict.

    Used only when every output field appears exactly once in well-formed markup;
    anything partial or malformed is left for the adapter to reject.
    """
    found: dict[str, list[str]] = {}
    for name, value in _PARAMETER.findall(text):
        found.setdefault(name, []).append(value.strip())
    if not fields or any(len(found.get(f, [])) != 1 for f in fields):
        return None
    out: dict[str, Any] = {}
    for f in fields:
        raw = found[f][0]
        try:
            out[f] = json.loads(raw)
        except ValueError:
            out[f] = raw
    return out


def normalize_reply(signature: type[dspy.Signature], completion: str) -> str:
    """Turn the reply shapes small models produce into the JSON object JSONAdapter expects."""
    outputs = list(signature.output_fields)
    parameters = _tool_parameters(completion, outputs)
    if parameters is not None:
        return json.dumps(parameters)
    sections = _sections(completion)
    if sections is not None:
        return json.dumps(sections)
    text = _unfence(completion.strip())
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


T = TypeVar("T")


def retry_unparseable(lm: RouterLM, call: Callable[[], T]) -> T:
    """Run a prediction; when the reply cannot be parsed, ask again under a fresh cache namespace.

    The cache stores raw replies, so replaying a malformed one would fail forever. Each
    retry uses `<namespace>.retry<n>`, which is a new cache key and so a new model call;
    a good retry is then cached like any other reply. After `LLM_PARSE_RETRIES` the error
    propagates and the stage records the email as failed.
    """
    base = lm.namespace
    try:
        for attempt in range(thresholds.LLM_PARSE_RETRIES + 1):
            lm.namespace = base if attempt == 0 else f"{base}.retry{attempt}"
            try:
                return call()
            except AdapterParseError:
                if attempt == thresholds.LLM_PARSE_RETRIES:
                    raise
        raise AssertionError("unreachable")
    finally:
        lm.namespace = base
