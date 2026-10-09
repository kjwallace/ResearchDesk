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


def test_chat_adapter_sections_become_a_json_object() -> None:
    reply = '[[ ## claims ## ]]\n```json\n["x"]\n```\n\n[[ ## completed ## ]]'
    assert json.loads(normalize_reply(OneField, reply)) == {"claims": ["x"]}
    two = '[[ ## a ## ]]\nhello\n\n[[ ## b ## ]]\n{"k": 1}'
    assert json.loads(normalize_reply(TwoFields, two)) == {"a": "hello", "b": {"k": 1}}


def test_well_formed_tool_markup_becomes_a_json_object() -> None:
    reply = '\n<parameter name="a">think</parameter>\n<parameter name="b">{"k": [1]}</parameter>\n</invoke>'
    assert json.loads(normalize_reply(TwoFields, reply)) == {"a": "think", "b": {"k": [1]}}


def test_malformed_tool_markup_is_left_for_the_adapter_to_reject() -> None:
    reply = '<parameter name="a">x</parameter name="b">y</parameter>'
    assert normalize_reply(TwoFields, reply) == reply


def test_unparseable_reply_is_retried_under_a_fresh_namespace() -> None:
    import pytest
    from dspy.utils.exceptions import AdapterParseError

    from fakes import FakeChat
    from triage_app import thresholds
    from triage_app.modules.lm import RouterLM, json_adapter, retry_unparseable

    chat = FakeChat(["<invoke_name: nonsense", '{"claims": ["x"]}'])
    lm = RouterLM("m", chat, namespace="extract")

    def predict() -> dspy.Prediction:
        with dspy.context(adapter=json_adapter()):
            return dspy.Predict(OneField)(text="t", lm=lm)

    assert retry_unparseable(lm, predict).claims == ["x"]
    assert [c["namespace"] for c in chat.calls] == ["extract", "extract.retry1"]
    assert lm.namespace == "extract"

    bad_chat = FakeChat(lambda _m: "<invoke_name: nonsense")
    always_bad = RouterLM("m", bad_chat, namespace="extract")

    def bad() -> dspy.Prediction:
        with dspy.context(adapter=json_adapter()):
            return dspy.Predict(OneField)(text="t", lm=always_bad)

    with pytest.raises(AdapterParseError):
        retry_unparseable(always_bad, bad)
    assert len(bad_chat.calls) == thresholds.LLM_PARSE_RETRIES + 1
