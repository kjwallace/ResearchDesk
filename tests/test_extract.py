import json
import shutil
from pathlib import Path

import pytest
from fakes import FIXTURE_EMAILS, FakeChat, fixture_emails

from triage_app import config
from triage_app.llm import Message
from triage_app.pipeline import extract
from triage_app.pipeline.context import RunContext
from triage_app.pipeline.io import normalize_ws, read_list, write_list
from triage_app.schema import Claim, Email, EmailResult, RedundancyRecord

OUT = config.FIXTURES_DIR / "out"
LABEL_KEYS = ('"triage"', '"additional_labels"', '"affected_tickers"', '"email_type"',
              '"systemic"', '"angle"', '"reason"', "signal_score", "decided_by")

MSFT_GOOD = ("Our checks with four Azure resellers point to Intelligent Cloud revenue growth of 26% "
             "in FY2027, versus the 21.5% the Street models.")
MSFT_SPACED = ("Two of the resellers said new GPU capacity   in the Iowa and Texas regions\n"
               "was released to customers six weeks early.")
MSFT_BAD = "Resellers report GPU capacity arriving well ahead of schedule."
SHARED = "Terms, pricing and the capital commitment were not disclosed"  # in fixture_005 and fixture_006
NEW_006 = "Alphabet is reportedly close to signing a 1.2 gigawatt power purchase agreement with a Midwest utility"


@pytest.fixture(autouse=True)
def analysis_model(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANALYSIS_MODEL", "fake/analysis-model")


def claim(quote: str, ticker: str = "MSFT", **extra: object) -> dict[str, object]:
    return {"quote": quote, "tickers": [ticker], "entities": [], "kind": "channel_check",
            "first_hand": True, **extra}


def reply(*claims: dict[str, object]) -> str:
    return json.dumps({"claims": list(claims)})


def ctx_with(chat: FakeChat) -> RunContext:
    return RunContext(corpus_set="day_1", chat=chat, use_cache=False, emails_path=FIXTURE_EMAILS)


def text(messages: list[Message]) -> str:
    return "\n".join(m.content for m in messages)


def emails() -> dict[str, Email]:
    return {e.email_id: e for e in fixture_emails()}


def results() -> dict[str, EmailResult]:
    return {r.email_id: r for r in read_list(OUT / "results.json", EmailResult)}


def stage_dir(tmp_path: Path) -> Path:
    for name in ("results.json", "redundancy.json"):
        shutil.copy(OUT / name, tmp_path / name)
    return tmp_path


def test_non_matching_quote_is_dropped_and_counted() -> None:
    chat = FakeChat(reply(claim(MSFT_GOOD, value=26, unit="pct", period="FY2027"), claim(MSFT_BAD),
                          claim(MSFT_SPACED)))
    out = extract.extract(emails()["fixture_001"], results()["fixture_001"], None, ctx_with(chat))
    assert out.dropped_quotes == 1 and out.dropped_repeats == 0
    assert [c.quote for c in out.claims] == [MSFT_GOOD, MSFT_SPACED]   # whitespace collapse still matches
    assert [c.id for c in out.claims] == ["fixture_001.c1", "fixture_001.c2"]  # code numbers kept claims
    assert all(c.email_id == "fixture_001" for c in out.claims)
    assert chat.calls[0]["model"] == "fake/analysis-model"


def test_run_extracts_only_passed_emails_in_order_and_output_validates(tmp_path: Path) -> None:
    def answer(messages: list[Message]) -> str:
        body = text(messages)
        return reply(claim(MSFT_GOOD)) if "Azure resellers" in body else reply()

    chat = FakeChat(answer)
    extract.run(stage_dir(tmp_path), tmp_path, ctx_with(chat))
    claims = read_list(tmp_path / "claims.json", Claim)
    assert [c.id for c in claims] == ["fixture_001.c1"]
    passed = [r.email_id for r in results().values() if r.gate == "pass"]
    assert len(chat.calls) == len(passed)
    sent = "\n".join(text(c["messages"]) for c in chat.calls)
    for e in emails().values():
        if results()[e.email_id].gate != "pass":   # quarantined and stopped bodies reach no model
            assert e.body not in sent


def test_flagged_repeat_gets_earlier_body_and_keeps_only_new_claims(tmp_path: Path) -> None:
    res = list(results().values())
    for i, r in enumerate(res):  # let the fixture repeat pass, so stage 5 sees it
        if r.email_id == "fixture_006":
            res[i] = r.model_copy(update={"gate": "pass"})
    d = stage_dir(tmp_path)
    write_list(d / "results.json", res)

    def answer(messages: list[Message]) -> str:
        body = text(messages)
        if "earlier_email" in messages[-1].content:
            return reply(claim(SHARED, "GOOGL"), claim(NEW_006, "GOOGL"))
        return reply()

    chat = FakeChat(answer)
    extract.run(d, d, ctx_with(chat))
    claims = read_list(d / "claims.json", Claim)
    assert [(c.id, c.quote) for c in claims] == [("fixture_006.c1", NEW_006)]
    repeat_call = [c for c in chat.calls if "earlier_email" in c["messages"][-1].content]
    assert len(repeat_call) == 1
    assert "watching for confirmation at the utility's investor day next month. Hannah" in normalize_ws(text(repeat_call[0]["messages"]))


def test_repeat_of_quarantined_email_gets_no_earlier_context() -> None:
    em, res = emails(), results()
    red = {r.email_id: r for r in read_list(OUT / "redundancy.json", RedundancyRecord)}
    res["fixture_005"] = res["fixture_005"].model_copy(update={"gate": "quarantine", "triage": None})
    assert extract.earlier_context(red["fixture_006"], em, res) is None
    res = results()
    assert extract.earlier_context(red["fixture_006"], em, res) == em["fixture_005"]
    assert extract.earlier_context(red.get("fixture_001"), em, res) is None  # not flagged: absent from the file


def test_stopped_email_is_not_sent() -> None:
    chat = FakeChat(reply())
    out = extract.extract(emails()["fixture_010"], results()["fixture_010"], None, ctx_with(chat))
    assert out.claims == [] and chat.calls == []


def test_prompt_holds_no_label_fields(tmp_path: Path) -> None:
    chat = FakeChat(reply())
    extract.run(stage_dir(tmp_path), tmp_path, ctx_with(chat))
    sent = "\n".join(text(c["messages"]) for c in chat.calls)
    for key in LABEL_KEYS:
        assert key not in sent
    for row in (config.FIXTURES_DIR / "labels.jsonl").read_text().splitlines():
        assert json.loads(row)["reason"] not in sent
