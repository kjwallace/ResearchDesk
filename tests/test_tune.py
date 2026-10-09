from pathlib import Path

import pytest

from triage_app import thresholds
from triage_app import config
from triage_app.evals import tune
from triage_app.pipeline.io import write_one
from triage_app.schema import EmailLabel, Thresholds, TriageRecord


def record(email_id: str, tr: float, mon: float, *, attention: float = 0.0, msft: float = 0.0,
           macro: float = 0.0, mnpi: float = 0.0, truncated: bool = False) -> TriageRecord:
    rest = max(0.0, 1.0 - tr - mon)
    return TriageRecord(
        email_id=email_id, criteria_version="v",
        triage_probs={"thesis_relevant": tr, "monitor": mon, "redundant": 0.0, "low_value": rest, "irrelevant": 0.0},
        ticker_probs={t: (msft if t == "MSFT" else 0.0) for t in config.TICKERS}, attention=attention,
        topic_probs={t: (macro if t == "macro" else 0.0) for t in config.TOPICS}, kind="research", kind_probs={},
        safety={"possible_mnpi": mnpi, "instructs_ai": 0.0}, truncated=truncated)


def label(email_id: str, triage: str, *, attention: bool = False, msft: bool = False, macro: bool = False) -> EmailLabel:
    return EmailLabel.model_validate({
        "email_id": email_id, "triage": triage, "additional_labels": ["macro"] if macro else [],
        "affected_tickers": ["MSFT"] if msft else [], "human_attention": attention, "reason": "r"})


def test_pass_threshold_is_highest_that_keeps_recall() -> None:
    # every relevant passes; 19 of 20 monitor pass (95%)
    monitor = [0.9] * 18 + [0.55, 0.2]
    assert tune.fit_pass_threshold([0.8, 0.7, 0.92], monitor, 0.6) == 0.55
    assert tune.fit_pass_threshold([0.5], monitor, 0.6) == 0.5
    assert tune.fit_pass_threshold([], [], 0.6) == 0.6
    assert tune.fit_pass_threshold([0.71], [0.9, 0.3], 0.6) == 0.3  # 95% of 2 monitor is both


def test_f1_threshold_sits_between_classes() -> None:
    probs = [0.1, 0.3, 0.7, 0.9]
    assert tune.fit_f1_threshold(probs, [False, False, True, True], 0.6) == 0.5
    assert tune.fit_f1_threshold(probs, [False, False, False, False], 0.6) == 0.6  # no positives: keep start


def test_fit_thresholds_on_synthetic_set(tmp_path: Path) -> None:
    triage = [
        record("r1", 0.8, 0.1, attention=0.9, msft=0.8),
        record("r2", 0.6, 0.15, msft=0.7, macro=0.6),
        record("m1", 0.2, 0.5, attention=0.2, msft=0.4),
        record("n1", 0.05, 0.1, msft=0.2, macro=0.1),
        record("q1", 0.0, 0.0, mnpi=0.9),                 # quarantined: never constrains
        record("t1", 0.0, 0.1, truncated=True),           # truncated: always passes
        record("v1", 0.9, 0.05),                          # validation only: ignored by the fit
    ]
    labels = {lab.email_id: lab for lab in [
        label("r1", "thesis_relevant", attention=True, msft=True),
        label("r2", "thesis_relevant", msft=True, macro=True),
        label("m1", "monitor", msft=True),
        label("n1", "irrelevant"),
        label("q1", "thesis_relevant", msft=True),
        label("t1", "thesis_relevant"),
        label("v1", "low_value"),
    ]}
    th = tune.fit_thresholds(triage, labels, {"r1", "r2", "m1", "n1", "q1", "t1"})
    assert th.pass_signal == 0.7
    assert th.attention == 0.55
    assert th.ticker["MSFT"] == 0.3
    assert th.ticker["NVDA"] == thresholds.TICKER_THRESHOLD
    assert th.topic["macro"] == 0.35
    assert (th.content_similarity, th.content_similarity_with_subject, th.subject_match) == (
        thresholds.CONTENT_SIMILARITY, thresholds.CONTENT_SIMILARITY_WITH_SUBJECT, thresholds.SUBJECT_MATCH)

    path = tmp_path / "tuned" / "thresholds.json"
    write_one(path, th)
    assert Thresholds.model_validate_json(path.read_text()) == th
    assert thresholds.load_thresholds(path).pass_signal == 0.7


def test_pending_without_tuning_output(tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
                                       capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setattr(config, "out_dir", lambda _set: tmp_path / "missing")
    monkeypatch.setattr(config, "TUNED_THRESHOLDS", tmp_path / "thresholds.json")
    tune.main()
    assert capsys.readouterr().out.strip() == tune.PENDING
    assert not (tmp_path / "thresholds.json").exists()
