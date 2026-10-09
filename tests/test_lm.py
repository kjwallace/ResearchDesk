import json

import numpy  # noqa: F401  # import before dspy
import dspy

from triage_app.modules.lm import normalize_reply


class OneField(dspy.Signature):
    """One output field."""
    text: str = dspy.InputField()
    claims: list[str] = dspy.OutputField()


class TwoFields(dspy.Signature):
    """Two output fields."""
    text: str = dspy.InputField()
    a: str = dspy.OutputField()
    b: str = dspy.OutputField()


def test_bare_list_in_a_fence_is_wrapped_under_the_field() -> None:
    reply = '```json\n["x", "y"]\n```'
    assert json.loads(normalize_reply(OneField, reply)) == {"claims": ["x", "y"]}


def test_keyed_reply_is_left_alone() -> None:
    reply = '{"claims": ["x"]}'
    assert normalize_reply(OneField, reply) == reply


def test_bare_object_is_wrapped_when_not_keyed_by_the_field() -> None:
    assert json.loads(normalize_reply(OneField, '{"quote": "q"}')) == {"claims": {"quote": "q"}}


def test_multi_field_signatures_only_lose_the_fence() -> None:
    assert normalize_reply(TwoFields, '```\n{"a": "1", "b": "2"}\n```') == '{"a": "1", "b": "2"}'


def test_non_json_passes_through() -> None:
    assert normalize_reply(OneField, "not json") == "not json"


def test_adapter_parses_a_bare_list() -> None:
    from triage_app.modules.lm import json_adapter
    assert json_adapter().parse(OneField, '```json\n["x"]\n```') == {"claims": ["x"]}
