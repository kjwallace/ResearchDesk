import json
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from fakes import FakeJev

from triage_app import config
from triage_app import criteria as criteria_files
from triage_app.evals import criteria_check
from triage_app.evals.tune import Split
from triage_app.pipeline.context import RunContext
from triage_app.pipeline.io import read_list
from triage_app.schema import CriteriaHistoryEntry, Email, EmailLabel, EmailResult, RedundancyRecord, Thresholds

NEW_RULE = "- R9: A supplier capacity note with a stated read-through counts as an emerging signal.\n"


class CriteriaJev(FakeJev):
    """Answers depend on the email and on whether the monitor criteria hold NEW_RULE."""

    def system_one(self, state: Any, questions: Any, **kw: Any) -> Any:
        has_rule = "supplier capacity note" in json.dumps(questions["triage"].model_dump())
        self.answers = answers_for(state["subject"], has_rule)
        return super().system_one(state, questions, **kw)


def probs(top: str, p: float) -> dict[str, float]:
    rest = (1.0 - p) / 4
    return {lab: (p if lab == top else rest) for lab in config.TRIAGE_LABELS}


def answers_for(subject: str, has_rule: bool) -> dict[str, Any]:
    if subject.startswith("Reseller"):
        return {"triage": probs("thesis_relevant", 0.8), "affects_MSFT": 0.9}
    if subject.startswith("Supplier"):
        return {"triage": probs("monitor" if has_rule else "low_value", 0.7), "affects_NVDA": 0.8}
    if subject.startswith("Memory"):
        return {"triage": probs("monitor", 0.7), "affects_NVDA": 0.7}
    return {"triage": probs("irrelevant", 0.9)}


EMAILS = [
    ("t1", "Reseller checks on Azure", "thesis_relevant", ["MSFT"], "fit"),
    ("t2", "Supplier capacity note", "monitor", ["NVDA"], "fit"),
    ("t3", "Banking conference", "irrelevant", [], "fit"),
    ("t4", "Memory supply rumor", "monitor", ["NVDA"], "validation"),
]


@pytest.fixture
def tuning(tmp_path: Path) -> dict[str, Any]:
    crit = tmp_path / "criteria"
    shutil.copytree(config.CRITERIA_DIR, crit)
    emails = [Email(email_id=i, received_at=datetime(2026, 10, 15, 9, n, tzinfo=UTC), sender="A. Person, Firm",
                    sender_email="a@example.com", subject=s, body=f"{s}. Details follow.")
              for n, (i, s, *_rest) in enumerate(EMAILS)]
    labels = {i: EmailLabel.model_validate({"email_id": i, "triage": t, "additional_labels": [],
                                            "affected_tickers": tk, "human_attention": False, "reason": "r"})
              for i, _s, t, tk, _p in EMAILS}
    split: dict[str, Split] = {i: "fit" if p == "fit" else "validation" for i, _s, _t, _tk, p in EMAILS}
    redundancy = {e.email_id: RedundancyRecord(email_id=e.email_id, nearest=None, content_similarity=None,
                                               subject_score=None, flagged=False) for e in emails}
    return {"criteria": crit, "emails": emails, "labels": labels, "split": split, "redundancy": redundancy,
            "out": tmp_path / "out", "history": tmp_path / "criteria_history.json"}


def run(t: dict[str, Any]) -> tuple[CriteriaHistoryEntry, CriteriaHistoryEntry | None, Thresholds]:
    ctx = RunContext("tuning", jev=CriteriaJev(), use_cache=False, criteria=criteria_files.load(t["criteria"]))
    return criteria_check.check(t["emails"], t["redundancy"], t["labels"], t["split"], ctx,
                                criteria_dir=t["criteria"], out_dir=t["out"], history_path=t["history"])


def test_check_writes_history_and_reports_label_change(tuning: dict[str, Any]) -> None:
    first, previous, _ = run(tuning)
    assert previous is None and first.changed == []
    assert first.fit["triage_accuracy"] == pytest.approx(0.6667)
    assert first.validation["triage_accuracy"] == 1.0
    assert set(first.files) == {f"{n}.md" for n in config.CRITERIA_FILES}

    monitor = tuning["criteria"] / "monitor.md"
    monitor.write_text(monitor.read_text().rstrip("\n") + "\n" + NEW_RULE)
    second, previous, thresholds = run(tuning)

    assert previous is not None and previous.criteria_version == first.criteria_version
    assert second.criteria_version != first.criteria_version
    assert [(c.email_id, c.before, c.after, c.split, c.now_correct) for c in second.changed] == [
        ("t2", "low_value", "monitor", "fit", True)]
    assert second.fit["triage_accuracy"] == 1.0
    assert "supplier capacity note" in second.files["monitor.md"]

    history = criteria_check.read_history(tuning["history"])
    assert [h.criteria_version for h in history] == [first.criteria_version, second.criteria_version]
    kept = read_list(criteria_check.labels_file(tuning["out"], second.criteria_version), EmailResult)
    assert len(kept) == len(EMAILS)

    text = criteria_check.format_check(second, previous, thresholds, tuning["labels"])
    assert "t2 [fit] low_value -> monitor (now right)" in text
    assert "fixes 1 fit emails" in text


def test_rerun_of_same_version_replaces_its_entry(tuning: dict[str, Any]) -> None:
    run(tuning)
    run(tuning)
    assert len(criteria_check.read_history(tuning["history"])) == 1


def test_pending_without_tuning_output(tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
                                       capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setattr(config, "out_dir", lambda _set: tmp_path / "missing")
    monkeypatch.setattr("sys.argv", ["criteria_check"])
    criteria_check.main()
    assert capsys.readouterr().out.strip() == criteria_check.PENDING
