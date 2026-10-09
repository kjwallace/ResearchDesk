import shutil
from datetime import date
from pathlib import Path

import pytest

from fakes import FIXTURE_EMAILS, fixture_emails

from triage_app import thresholds
from triage_app.pipeline import deliver
from triage_app.pipeline.context import RunContext
from triage_app.pipeline.io import read_list, read_one
from triage_app.schema import Brief, Email, EmailResult, ExistingThesis, Suggestion, TriageRecord

OUT = Path(__file__).parent / "fixtures" / "out"


def ctx() -> RunContext:
    return RunContext(use_cache=False, emails_path=FIXTURE_EMAILS)


def placed(brief: Brief, suggestions: dict[str, Suggestion]) -> list[str]:
    """Every email across the suggestion cards, relevant_unlinked, audit and quarantined."""
    out: list[str] = []
    for ids in (brief.thesis_changes, brief.new_theses, brief.worth_watching):
        out += sorted({sec.email_id for i in ids for sec in suggestions[i].sections})
    return [*out, *brief.relevant_unlinked, *brief.audit, *brief.quarantined]


def test_matches_the_fixture_brief() -> None:
    assert deliver.process(OUT, ctx()) == read_one(OUT / "brief.json", Brief)


def test_every_email_appears_exactly_once() -> None:
    brief = deliver.process(OUT, ctx())
    emails = [e.email_id for e in fixture_emails()]
    sugg = {s.id: s for s in read_list(OUT / "suggestions.json", Suggestion)}
    assert sorted(placed(brief, sugg)) == sorted(emails)
    assert set(brief.needs_attention) <= set(emails)
    assert brief.quarantined == ["fixture_003", "fixture_004"]
    assert "fixture_007" in brief.needs_attention and "fixture_007" in brief.relevant_unlinked


def test_run_writes_brief(tmp_path: Path) -> None:
    for f in OUT.iterdir():
        shutil.copy(f, tmp_path / f.name)
    (tmp_path / "brief.json").unlink()
    c = ctx()
    deliver.run(tmp_path, tmp_path, c)
    assert read_one(tmp_path / "brief.json", Brief) == read_one(OUT / "brief.json", Brief)
    assert any(t.stage == "deliver" for t in c.recorder.timings)


def test_missing_optional_files(tmp_path: Path) -> None:
    for name in ("results.json",):
        shutil.copy(OUT / name, tmp_path / name)
    brief = deliver.process(tmp_path, ctx())
    assert brief.thesis_changes == [] and brief.alerts == []
    assert sorted(brief.relevant_unlinked + brief.audit + brief.quarantined) == sorted(
        r.email_id for r in read_list(OUT / "results.json", EmailResult))


@pytest.fixture
def inputs() -> dict[str, object]:
    return {
        "parsed": fixture_emails(),
        "results": read_list(OUT / "results.json", EmailResult),
        "triage": {t.email_id: t for t in read_list(OUT / "triage.json", TriageRecord)},
        "suggestions": read_list(OUT / "suggestions.json", Suggestion),
    }


def assemble(inputs: dict[str, object], suggestions: list[Suggestion] | None = None,
             triage: dict[str, TriageRecord] | None = None) -> Brief:
    return deliver.assemble(
        date(2026, 10, 13), inputs["parsed"], inputs["results"], triage or inputs["triage"],
        [], suggestions if suggestions is not None else inputs["suggestions"], [],
        sizes=deliver.position_sizes())


def test_order_by_position_size_then_strength(inputs: dict[str, object]) -> None:
    sugg: list[Suggestion] = inputs["suggestions"]  # type: ignore[assignment]
    msft = next(s for s in sugg if s.id == "MSFT.p1.supports")
    weak = msft.model_copy(update={"id": "MSFT.p3.contradicts", "body": msft.body.model_copy(
        update={"pillar_id": "MSFT.p3", "stance": "contradicts", "strength": 1})})
    brief = assemble(inputs, [weak, *sugg])
    # AAPL (200 bps) after both MSFT (250 bps); the stronger MSFT suggestion first.
    assert brief.thesis_changes == ["MSFT.p1.supports", "MSFT.p3.contradicts", "AAPL.p1.supports"]


def test_wrong_if_alerts_come_first_and_respect_budget(inputs: dict[str, object]) -> None:
    sugg: list[Suggestion] = inputs["suggestions"]  # type: ignore[assignment]
    base = next(s for s in sugg if s.id == "MSFT.p1.supports")
    assert isinstance(base.body, ExistingThesis)

    def met(pillar: str) -> Suggestion:
        return base.model_copy(update={"id": f"{pillar}.contradicts", "body": base.body.model_copy(
            update={"pillar_id": pillar, "stance": "contradicts", "wrong_if_met": True})})

    # GOOGL is 150 bps (alerts), and NVDA 300 bps alerts before MSFT 250 bps.
    brief = assemble(inputs, [met("GOOGL.p3"), met("MSFT.p3"), met("NVDA.p1"), *sugg])
    assert [a.ref_id for a in brief.alerts] == ["NVDA.p1.contradicts", "MSFT.p3.contradicts", "GOOGL.p3.contradicts"]
    assert len(brief.alerts) == thresholds.ALERTS_PER_DAY
    brief = assemble(inputs, [met("GOOGL.p3"), *sugg])
    assert [(a.kind, a.ref_id) for a in brief.alerts] == [
        ("wrong_if_met", "GOOGL.p3.contradicts"), ("human_attention", "fixture_007")]


def test_human_attention_alert_threshold(inputs: dict[str, object]) -> None:
    triage = dict(inputs["triage"])  # type: ignore[call-overload]
    triage["fixture_007"] = triage["fixture_007"].model_copy(update={"human_attention": thresholds.ALERT_HUMAN_ATTENTION - 0.01})
    assert assemble(inputs, triage=triage).alerts == []


def test_worth_watching_when_every_linked_email_is_monitor(inputs: dict[str, object]) -> None:
    brief = assemble(inputs)
    assert brief.worth_watching == ["NVDA.p2.supports"]
    assert "NVDA.p2.supports" not in brief.thesis_changes
