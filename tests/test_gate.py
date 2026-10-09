import shutil
from pathlib import Path
from typing import Any

import pytest

from fakes import FIXTURE_EMAILS

from triage_app import thresholds
from triage_app import config
from triage_app.pipeline import gate
from triage_app.pipeline.context import RunContext
from triage_app.pipeline.io import read_list
from triage_app.schema import EmailResult, RedundancyRecord, TriageRecord

OUT = config.FIXTURES_DIR / "out"
T = thresholds.starting_thresholds()


def triage(**kw: Any) -> TriageRecord:
    base: dict[str, Any] = dict(
        email_id="e1", criteria_version="v",
        triage_probs={"thesis_relevant": 0.1, "monitor": 0.1, "redundant": 0.1, "low_value": 0.6, "irrelevant": 0.1},
        ticker_probs={t: 0.0 for t in config.TICKERS}, human_attention=0.0,
        topic_probs={t: 0.0 for t in config.TOPICS}, email_type="news_alert",
        email_type_probs={k: 1 / len(config.EMAIL_TYPES) for k in config.EMAIL_TYPES},
        safety={"possible_mnpi": 0.0, "instructs_ai": 0.0}, truncated=False,
    )
    return TriageRecord(**{**base, **kw})


def probs(tr: float, mon: float, red: float = 0.0, low: float = 0.0, irr: float = 0.0) -> dict[str, float]:
    return {"thesis_relevant": tr, "monitor": mon, "redundant": red, "low_value": low, "irrelevant": irr}


NO_REPEAT = RedundancyRecord(email_id="e1", nearest=None, content_similarity=None, subject_score=None, flagged=False)
REPEAT = RedundancyRecord(email_id="e1", nearest="e0", content_similarity=0.91, subject_score=0.7, flagged=True)


def test_reproduces_fixture_results() -> None:
    redundancy = {r.email_id: r for r in read_list(OUT / "redundancy.json", RedundancyRecord)}
    expected = read_list(OUT / "results.json", EmailResult)
    got = [gate.process(t, redundancy.get(t.email_id), T) for t in read_list(OUT / "triage.json", TriageRecord)]
    assert got == expected


def test_run_writes_one_result_per_email(tmp_path: Path) -> None:
    for name in ("triage.json", "redundancy.json"):
        shutil.copy(OUT / name, tmp_path / name)
    ctx = RunContext("day_1", use_cache=False, thresholds=T, emails_path=FIXTURE_EMAILS)
    gate.run(tmp_path, tmp_path, ctx)
    assert read_list(tmp_path / "results.json", EmailResult) == read_list(OUT / "results.json", EmailResult)
    assert len([t for t in ctx.recorder.timings if t.stage == "gate"]) == 10


@pytest.mark.parametrize("question", ["instructs_ai", "possible_mnpi"])
def test_quarantine_on_either_safety_question(question: str) -> None:
    t = triage(triage_probs=probs(0.7, 0.2), safety={"possible_mnpi": 0.0, "instructs_ai": 0.0, question: thresholds.QUARANTINE},
               ticker_probs={**{x: 0.0 for x in config.TICKERS}, "NVDA": 0.9}, human_attention=0.9,
               topic_probs={**{x: 0.0 for x in config.TOPICS}, "macro": 0.9}, truncated=True)
    r = gate.process(t, REPEAT, T)
    assert (r.triage, r.decided_by, r.gate, r.redundant_of) == (None, "quarantine", "quarantine", None)
    assert r.affected_tickers == [] and r.additional_labels == [] and r.human_attention is False
    assert r.signal_score == 0.9                                   # still stored
    assert r.reason == f"quarantined: {question} 0.65 reaches 0.65"


def test_below_quarantine_threshold_is_not_quarantined() -> None:
    r = gate.process(triage(safety={"possible_mnpi": 0.64, "instructs_ai": 0.64}), NO_REPEAT, T)
    assert r.gate == "stop" and r.decided_by == "jev"


def test_quarantine_reason_names_the_higher_question() -> None:
    r = gate.process(triage(safety={"possible_mnpi": 0.5, "instructs_ai": 0.8}), NO_REPEAT, T)
    assert r.reason == "quarantined: instructs_ai 0.80 reaches 0.65"


def test_label_is_jev_argmax() -> None:
    r = gate.process(triage(triage_probs=probs(0.05, 0.1, 0.05, 0.2, 0.6)), NO_REPEAT, T)
    assert (r.triage, r.decided_by, r.redundant_of, r.gate) == ("irrelevant", "jev", None, "stop")
    assert r.reason == "irrelevant 0.60; signal score 0.15 is below 0.60"


def test_redundant_by_jev_alone() -> None:
    r = gate.process(triage(triage_probs=probs(0.1, 0.2, 0.6, 0.1)), NO_REPEAT, T)
    assert (r.triage, r.decided_by, r.redundant_of) == ("redundant", "jev", None)


def test_flagged_repeat_already_redundant_stays_jev() -> None:
    r = gate.process(triage(triage_probs=probs(0.1, 0.2, 0.6, 0.1)), REPEAT, T)
    assert (r.triage, r.decided_by, r.redundant_of) == ("redundant", "jev", None)


def test_redundancy_check_relabels_a_flagged_repeat_below_the_gate() -> None:
    r = gate.process(triage(triage_probs=probs(0.1, 0.45, 0.3, 0.15)), REPEAT, T)
    assert (r.triage, r.decided_by, r.redundant_of, r.gate) == ("redundant", "redundancy_check", "e0", "stop")
    assert r.reason == ("redundant: repeat of e0 (content 0.91, subject 0.70); jev monitor 0.45; "
                        "signal score 0.55 is below 0.60")


def test_flagged_repeat_that_clears_the_gate_keeps_its_label() -> None:
    r = gate.process(triage(triage_probs=probs(0.3, 0.4, 0.2, 0.1)), REPEAT, T)
    assert (r.triage, r.decided_by, r.redundant_of, r.gate) == ("monitor", "jev", None, "pass")


def test_tickers_and_topics_at_their_thresholds() -> None:
    t = triage(ticker_probs={"AMZN": 0.5, "NVDA": 0.49, "MSFT": 0.0, "AAPL": 0.7, "GOOGL": 0.3},
               topic_probs={"macro": 0.5, "sector": 0.2, "government": 0.0, "other": 0.51})
    r = gate.process(t, NO_REPEAT, T)
    assert r.affected_tickers == ["AMZN", "AAPL"] and r.additional_labels == ["macro", "other"]

    tuned = T.model_copy(update={"ticker": {**T.ticker, "AAPL": 0.8, "GOOGL": 0.25},
                                 "topic": {**T.topic, "macro": 0.6}})
    r = gate.process(t, NO_REPEAT, tuned)
    assert r.affected_tickers == ["AMZN", "GOOGL"] and r.additional_labels == ["other"]


def test_attention_threshold() -> None:
    assert gate.process(triage(human_attention=0.6), None, T).human_attention is True
    assert gate.process(triage(human_attention=0.59), None, T).human_attention is False


def test_gate_reads_signal_score_not_label() -> None:
    r = gate.process(triage(triage_probs=probs(0.3, 0.3, 0.0, 0.4)), NO_REPEAT, T)
    assert (r.triage, r.gate, r.signal_score) == ("low_value", "pass", 0.6)
    assert r.reason == "low_value 0.40; signal score 0.60 clears 0.60"


def test_gate_stops_below_threshold() -> None:
    r = gate.process(triage(triage_probs=probs(0.3, 0.29, 0.0, 0.41)), NO_REPEAT, T)
    assert r.gate == "stop"


def test_truncated_email_passes_on_its_first_chunk() -> None:
    r = gate.process(triage(truncated=True), NO_REPEAT, T)
    assert r.gate == "pass"
    assert r.reason == "low_value 0.60; signal score 0.20 is below 0.60; truncated, passed on the first chunk"


def test_pass_threshold_comes_from_thresholds() -> None:
    t = triage(triage_probs=probs(0.2, 0.2, 0.0, 0.6))
    assert gate.process(t, NO_REPEAT, T).gate == "stop"
    r = gate.process(t, NO_REPEAT, T.model_copy(update={"pass_signal": 0.35}))
    assert r.gate == "pass" and r.reason == "low_value 0.60; signal score 0.40 clears 0.35"
