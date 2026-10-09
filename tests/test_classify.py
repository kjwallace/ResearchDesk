import json
import logging
import shutil
from pathlib import Path
from typing import Any

import pytest
from fakes import FIXTURE_EMAILS, FakeJev, fixture_emails

from triage_app import thresholds
from triage_app import config
from triage_app.cache import DiskCache
from triage_app.criteria import criteria_text, load
from triage_app.modules.classify import QUESTION_IDS, classify, load_wording, parse_wording
from triage_app.pipeline import classify as stage
from triage_app.pipeline.context import RunContext
from triage_app.pipeline.io import read_list
from triage_app.schema import Email, TriageRecord

OUT = config.FIXTURES_DIR / "out"
EMAILS = fixture_emails()
EXPECTED = {r.email_id: r for r in read_list(OUT / "triage.json", TriageRecord)}
BY_SUBJECT = {e.subject: EXPECTED[e.email_id] for e in EMAILS}


@pytest.fixture(autouse=True)
def jev_model(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JEV_MODEL", "jev-fake")


def answers_for(record: TriageRecord) -> dict[str, Any]:
    return {
        "triage": record.triage_probs,
        **{f"affects_{t}": p for t, p in record.ticker_probs.items()},
        "human_attention": record.human_attention,
        **{f"topic_{t}": p for t, p in record.topic_probs.items()},
        "email_type": record.email_type_probs,
        **record.safety,
    }


def fixture_jev() -> FakeJev:
    return FakeJev(lambda state: answers_for(BY_SUBJECT[state["subject"]]))


def test_every_fixture_email_gets_one_record(tmp_path: Path) -> None:
    jev = fixture_jev()
    ctx = RunContext("day_1", jev=jev, use_cache=False, emails_path=FIXTURE_EMAILS)
    stage.run(tmp_path, tmp_path, ctx)

    records = read_list(tmp_path / "triage.json", TriageRecord)
    assert [r.email_id for r in records] == [e.email_id for e in EMAILS]
    assert len(jev.requests) == len(EMAILS)                     # one request per email
    assert all(list(r["questions"]) == list(QUESTION_IDS) for r in jev.requests)  # all 14 at once
    version = load().version
    for r in records:
        want = EXPECTED[r.email_id].model_copy(update={"criteria_version": version})
        assert r == want
    assert [t.email_id for t in ctx.recorder.timings if t.stage == "classify"] == [e.email_id for e in EMAILS]
    assert len(ctx.recorder.calls) == len(EMAILS) and {c.model for c in ctx.recorder.calls} == {"jev-fake"}


def test_request_holds_only_the_email_and_criteria() -> None:
    criteria = load()
    jev = fixture_jev()
    email = EMAILS[0]
    classify(email, criteria, jev)
    sent = jev.requests[0]

    assert sent["state"] == {"sender": email.sender, "sender_email": email.sender_email,
                             "subject": email.subject, "body": email.body}
    questions = {name: q.model_dump() for name, q in sent["questions"].items()}
    text = json.dumps(questions)

    # The criteria and wording, as written.
    assert questions["triage"]["criteria"] == {lab: criteria_text(criteria, lab) for lab in config.TRIAGE_LABELS}
    assert questions["affects_MSFT"]["criteria"] == {"true": criteria_text(criteria, "affected_tickers")}
    assert questions["topic_macro"]["criteria"] == {"true": criteria_text(criteria, "macro")}
    assert questions["human_attention"]["criteria"] == {"true": criteria_text(criteria, "human_attention")}
    assert "criteria" not in questions["instructs_ai"] and "criteria" not in questions["possible_mnpi"]
    assert "Microsoft" in questions["affects_MSFT"]["instructions"]
    assert questions["email_type"]["criteria"].keys() == set(config.EMAIL_TYPES)

    # Nothing else: no other email, no label or its reason, no redundancy flag, no book.
    for other in EMAILS[1:]:
        assert other.subject not in text and other.body[:60] not in text
    labels = [json.loads(line) for line in (config.FIXTURES_DIR / "labels.jsonl").read_text().splitlines()]
    for label in labels:
        assert label["reason"][:60] not in text
    for word in ("redundan" + "cy_check", "flagged", "content_similarity", "nearest"):
        assert word not in text
    theses = json.loads((config.SEED_DIR / "theses.json").read_text())
    for thesis in theses:
        for pillar in thesis["pillars"]:
            assert pillar["id"] not in text and pillar["statement"][:50] not in text
        assert str(thesis["size_bps"]) + " bps" not in text


def test_truncation_keeps_the_start_of_the_body(monkeypatch: pytest.MonkeyPatch) -> None:
    email = EMAILS[0].model_copy(update={"body": "START " + "x" * 50_000})
    jev = fixture_jev()
    record = classify(email, load(), jev)
    assert not record.truncated and jev.requests[0]["state"]["body"] == email.body

    monkeypatch.setattr(thresholds, "JEV_INPUT_LIMIT_TOKENS", 5_000)
    record = classify(email, load(), jev)
    sent = jev.requests[1]["state"]["body"]
    assert record.truncated
    assert sent.startswith("START ") and email.body.startswith(sent) and len(sent) < len(email.body)
    longest = max(len(json.dumps(q.model_dump())) for q in jev.requests[1]["questions"].values())
    total = sum(len(v) for v in jev.requests[1]["state"].values()) + longest
    assert total <= 5_000 * thresholds.CHARS_PER_TOKEN


def test_cache_replays_without_calling_jev(tmp_path: Path) -> None:
    jev = fixture_jev()
    cache = DiskCache(tmp_path)
    first = classify(EMAILS[1], load(), jev, cache=cache)
    second = classify(EMAILS[1], load(), jev, cache=cache)
    assert first == second and len(jev.requests) == 1


def test_wording_file_covers_every_question(caplog: pytest.LogCaptureFixture) -> None:
    load_wording.cache_clear()
    with caplog.at_level(logging.WARNING):
        wording = load_wording()
    assert not caplog.records
    assert set(wording.questions) == set(QUESTION_IDS)
    assert wording.type_options["company_release"] != "company release"
    assert set(wording.type_options) == set(config.EMAIL_TYPES)


def test_missing_wording_falls_back_to_stubs(caplog: pytest.LogCaptureFixture) -> None:
    text = "| ID | Type | Instructions |\n|----|----|----|\n| `triage` | Choice | Which label? |\n"
    with caplog.at_level(logging.WARNING):
        wording = parse_wording(text)
    assert wording.questions["triage"] == "Which label?"
    assert "Apple" in wording.questions["affects_AAPL"]
    assert wording.type_options["company_release"] == "company release"
    assert any("affects_AAPL" in r.getMessage() for r in caplog.records)
