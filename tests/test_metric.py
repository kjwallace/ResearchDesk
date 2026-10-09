from typing import Any

import pytest

from triage_app.evals import metric
from triage_app.schema import (
    AttentionNote,
    EmailLabel,
    EmailResult,
    ExistingThesis,
    LinkedSection,
    RedundancyRecord,
    Suggestion,
    TriageRecord,
)


def label(email_id: str, triage: str, tickers: list[str] | None = None, topics: list[str] | None = None,
          attention: bool = False) -> EmailLabel:
    return EmailLabel.model_validate({
        "email_id": email_id, "triage": triage, "additional_labels": topics or [],
        "affected_tickers": tickers or [], "human_attention": attention, "reason": "r"})


def result(email_id: str, triage: str | None, gate: str = "pass", tickers: list[str] | None = None,
           topics: list[str] | None = None, attention: bool = False) -> EmailResult:
    quarantined = gate == "quarantine"
    return EmailResult.model_validate({
        "email_id": email_id, "triage": None if quarantined else triage,
        "decided_by": "quarantine" if quarantined else "jev", "redundant_of": None,
        "affected_tickers": [] if quarantined else tickers or [],
        "additional_labels": [] if quarantined else topics or [],
        "human_attention": False if quarantined else attention,
        "signal_score": 0.5, "gate": gate, "reason": "r"})


def by_id(items: list[Any]) -> dict[str, Any]:
    return {i.email_id: i for i in items}


LABELS = by_id([
    label("a", "thesis_relevant", ["MSFT"], ["sector"], attention=True),
    label("b", "thesis_relevant", ["AAPL"]),
    label("c", "monitor", ["NVDA"]),
    label("d", "low_value"),
    label("e", "redundant", ["GOOGL"]),
])
RESULTS = by_id([
    result("a", "thesis_relevant", tickers=["MSFT", "NVDA"], topics=["sector"], attention=True),
    result("b", None, gate="quarantine"),            # quarantined: a miss everywhere
    result("c", "monitor", tickers=["NVDA"]),
    result("d", "irrelevant", gate="stop", attention=True),
    result("e", "monitor", gate="stop", tickers=["GOOGL"]),
])


def test_gate_recall_counts_quarantine_as_miss() -> None:
    s = metric.gate_recall(RESULTS, LABELS)
    assert s.value == 0.5
    assert [(m.email_id, m.got) for m in s.misses] == [("b", "quarantine")]
    assert metric.monitor_gate_recall(RESULTS, LABELS).value == 1.0


def test_gate_reduction_includes_quarantine() -> None:
    assert metric.gate_reduction(RESULTS, LABELS).value == 0.6


def test_signal_and_triage_accuracy() -> None:
    sig = metric.signal_accuracy(RESULTS, LABELS)
    assert sig.value == 0.6  # a, c, d right (d: noise = noise); b quarantined; e redundant vs signal
    assert {m.email_id for m in sig.misses} == {"b", "e"}
    tri = metric.triage_accuracy(RESULTS, LABELS)
    assert tri.value == 0.4
    assert {(m.email_id, m.got) for m in tri.misses} == {("b", "quarantined"), ("d", "irrelevant"), ("e", "monitor")}


def test_confusion_has_quarantined_column() -> None:
    table = metric.confusion(RESULTS, LABELS)
    assert table["thesis_relevant"] == {"thesis_relevant": 1, "quarantined": 1}
    assert table["redundant"] == {"monitor": 1}


def test_ticker_f1_micro() -> None:
    s = metric.ticker_f1(RESULTS, LABELS)
    # tp: MSFT, NVDA(c), GOOGL = 3; fp: NVDA(a) = 1; fn: AAPL(b, quarantined) = 1
    assert s.value == pytest.approx(round(6 / 8, 4))
    assert {(m.email_id, m.expected, m.got) for m in s.misses} == {("a", "MSFT", "NVDA,MSFT"), ("b", "AAPL", "none")}


def test_topic_f1_and_attention() -> None:
    assert metric.topic_f1(RESULTS, LABELS).value == 1.0
    assert metric.attention_precision(RESULTS, LABELS).value == 0.5
    assert metric.attention_recall(RESULTS, LABELS).value == 1.0


def test_quarantine_misses_attention_recall() -> None:
    labels = by_id([label("x", "monitor", attention=True)])
    results = by_id([result("x", None, gate="quarantine")])
    assert metric.attention_recall(results, labels).value == 0.0
    assert metric.attention_precision(results, labels).value is None


def test_missing_result_is_a_miss() -> None:
    labels = by_id([label("x", "thesis_relevant")])
    assert metric.gate_recall({}, labels).value == 0.0
    assert metric.triage_accuracy({}, labels).misses[0].got == "quarantined"


def test_repeats() -> None:
    red = [RedundancyRecord(email_id=i, nearest="a" if f else None, content_similarity=0.9 if f else None,
                            subject_score=0.7 if f else None, flagged=f)
           for i, f in [("a", False), ("d", True), ("e", True)]]
    assert metric.repeat_flagged(red).value == 2.0
    s = metric.repeat_precision(red, LABELS)
    assert s.value == 0.5 and s.misses[0].email_id == "d"
    assert metric.repeat_precision([], LABELS).value is None


def suggestion(sid: str, email_id: str, quote: str) -> Suggestion:
    return Suggestion(id=sid, body=ExistingThesis(kind="existing_thesis", pillar_id="MSFT.p1", stance="supports",
                                                  strength=1), rationale="r", claim_ids=[f"{email_id}.c1"],
                      sections=[LinkedSection(email_id=email_id, quote=quote)], status="open")


def test_stray_suggestions() -> None:
    s = metric.stray_suggestions([suggestion("s1", "a", "q"), suggestion("s2", "d", "q")], LABELS)
    assert s.value == 1.0 and s.misses[0].got.startswith("s2")


def test_quote_faithfulness_over_notes_and_suggestions() -> None:
    bodies = {"a": "Azure  growth\nwas 26% in the quarter.", "d": "nothing here"}
    note = AttentionNote(email_id="d", summary="s", why_attention="w", action="reply",
                         sections=[LinkedSection(email_id="d", quote="nothing   here")])
    s = metric.quote_faithfulness([note], [suggestion("s1", "a", "growth was 26%"),
                                           suggestion("s2", "a", "growth was 30%")], bodies)
    assert s.value == pytest.approx(0.6667)
    assert len(s.misses) == 1
    assert metric.quote_faithfulness([], [], bodies).value is None


def triage_record(email_id: str, kind: str) -> TriageRecord:
    return TriageRecord(email_id=email_id, criteria_version="v", triage_probs={}, ticker_probs={}, attention=0.0,
                        topic_probs={}, kind=kind, kind_probs={}, safety={}, truncated=False)


def test_meetings_share() -> None:
    records = [triage_record("a", "invitation"), triage_record("b", "newsletter"),
               triage_record("c", "research"), triage_record("d", "news")]
    assert metric.meetings_share(records).value == 0.5


def test_review_keys() -> None:
    rows = [
        {"id": "s1", "kind": "existing_thesis", "right_pillar": "yes", "right_stance": "yes", "sections_support": "y"},
        {"id": "s2", "kind": "existing_thesis", "right_pillar": "yes", "right_stance": "no", "sections_support": "yes"},
        {"id": "s3", "kind": "existing_thesis", "right_pillar": "yes", "right_stance": "", "sections_support": ""},
        {"id": "n1", "kind": "new_thesis", "new_to_book": "yes", "sections_support": "yes", "right_pillar": ""},
    ]
    assert metric.suggestion_review(rows) == 0.5     # s3 not yet reviewed
    assert metric.new_thesis_review(rows) == 1.0
    assert metric.note_review([{"id": "x", "kind": "note"}]) is None
