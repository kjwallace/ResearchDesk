from datetime import UTC, datetime
from pathlib import Path

import pytest

from triage_app import thresholds
from triage_app.pipeline.io import read_list
from triage_app.schema import ExistingThesis, LinkedSection, LogEntry, Suggestion, NewThesis
from triage_app.state import apply
from triage_app.state.compute import compute
from triage_app.state.fold import Seed, fold, load_seed, net_contradicting

OUT = Path(__file__).parent / "fixtures" / "out"


@pytest.fixture
def seed() -> Seed:
    return load_seed()


@pytest.fixture
def sugg() -> dict[str, Suggestion]:
    return {s.id: s for s in read_list(OUT / "suggestions.json", Suggestion)}


def contradicting(pillar_id: str, strength: int, n: int) -> Suggestion:
    return Suggestion(
        id=f"{pillar_id}.contradicts.{n}",
        body=ExistingThesis(kind="existing_thesis", pillar_id=pillar_id, stance="contradicts",
                            strength=strength),
        rationale="r", claim_ids=[], sections=[LinkedSection(email_id=f"e{n}", quote="q")], status="open")


def test_accept_existing_logs_evidence(seed: Seed, sugg: dict[str, Suggestion]) -> None:
    s = sugg["MSFT.p1.supports"]
    entry = apply.accept(seed, [], s)
    assert entry.change == "pillar_evidence" and entry.item_id == "MSFT.p1"
    assert entry.stance == "supports" and entry.strength == 2 and entry.sections == s.sections
    state = fold(seed, [entry])
    assert [e.id for e in state.evidence["MSFT.p1"]] == [entry.id]
    assert apply.status_of(s, [entry], set()) == "accepted"
    with pytest.raises(apply.ActionError):
        apply.accept(seed, [entry], s)


def test_edit_strength_on_accept(seed: Seed, sugg: dict[str, Suggestion]) -> None:
    entry = apply.accept(seed, [], sugg["MSFT.p1.supports"], strength=3)
    assert entry.strength == 3


def test_accept_new_thesis_adds_next_pillar(seed: Seed, sugg: dict[str, Suggestion]) -> None:
    entry = apply.accept(seed, [], sugg["AMZN.new1"], statement="  Edited statement. ", wrong_if="")
    assert entry.change == "pillar_added" and entry.item_id == "AMZN.p4"
    assert entry.pillar is not None and entry.pillar.statement == "Edited statement."
    body = sugg["AMZN.new1"].body
    assert isinstance(body, NewThesis) and entry.pillar.wrong_if == body.wrong_if
    state = fold(seed, [entry])
    assert [p.id for p in state.theses["AMZN"].pillars][-1] == "AMZN.p4"


def test_rejected_cannot_be_accepted(seed: Seed) -> None:
    rejected = next(s for s in read_list(OUT / "suggestions_checked.json", Suggestion) if s.status == "rejected")
    with pytest.raises(apply.ActionError):
        apply.accept(seed, [], rejected)


def test_update_driver_fills_before_and_moves_eps(seed: Seed) -> None:
    did = "MSFT.intelligent_cloud_growth"
    before = next(d for m in seed.models for d in m.drivers if d.id == did).analyst
    entry = apply.update_driver(seed, [], did, 26.0, suggestion_id="MSFT.p1.supports")
    assert entry.change == "driver_updated" and entry.before == before and entry.after == 26.0
    eps0 = compute(fold(seed, []).models["MSFT"])["analyst"].eps
    eps1 = compute(fold(seed, [entry]).models["MSFT"])["analyst"].eps
    assert eps1 != eps0
    with pytest.raises(apply.ActionError):
        apply.update_driver(seed, [], did, 10_000.0)
    with pytest.raises(apply.ActionError):
        apply.update_driver(seed, [], "MSFT.nope", 1.0)


def test_set_conviction(seed: Seed) -> None:
    entry = apply.set_conviction(seed, [], "AAPL", 5)
    assert entry.before == 3.0 and entry.after == 5.0
    assert fold(seed, [entry]).theses["AAPL"].conviction == 5
    with pytest.raises(apply.ActionError):
        apply.set_conviction(seed, [], "AAPL", 6)


def test_undo_reverses_last_change_in_effect(seed: Seed, sugg: dict[str, Suggestion]) -> None:
    log: list[LogEntry] = []
    log.append(apply.accept(seed, log, sugg["MSFT.p1.supports"]))
    log.append(apply.update_driver(seed, log, "MSFT.intelligent_cloud_growth", 26.0))
    u1 = apply.undo(log)
    assert u1 is not None and u1.reverses == log[1].id and u1.before == 26.0
    log.append(u1)
    assert fold(seed, log).models == fold(seed, log[:1]).models
    u2 = apply.undo(log)
    assert u2 is not None and u2.reverses == log[0].id
    log.append(u2)
    state = fold(seed, log)
    assert state.evidence["MSFT.p1"] == [] and state.applied == []
    assert apply.status_of(sugg["MSFT.p1.supports"], log, set()) == "open"
    assert apply.undo(log) is None
    assert len({e.id for e in log}) == len(log)


def test_dismiss_is_status_only(seed: Seed, sugg: dict[str, Suggestion]) -> None:
    s = sugg["NVDA.p2.supports"]
    assert apply.status_of(s, [], {s.id}) == "dismissed"


def test_conviction_review_raised_at_threshold(seed: Seed) -> None:
    log: list[LogEntry] = []
    log.append(apply.accept(seed, log, contradicting("NVDA.p3", 3, 1)))
    assert net_contradicting(fold(seed, log), "NVDA.p3") == 3
    assert apply.conviction_reviews(seed, log) == []
    log.append(apply.accept(seed, log, contradicting("NVDA.p3", 1, 2)))
    assert net_contradicting(fold(seed, log), "NVDA.p3") == thresholds.CONVICTION_REVIEW_STRENGTH
    reviews = apply.conviction_reviews(seed, log)
    assert [r.id for r in reviews] == ["NVDA.p3.review"]
    review = reviews[0]
    assert review.body.kind == "conviction_review" and review.body.ticker == "NVDA"
    assert {s.email_id for s in review.sections} == {"e1", "e2"}
    # Dismissing the review closes it; so does setting conviction against it.
    assert apply.conviction_reviews(seed, log, {review.id}) == []
    entry = apply.set_conviction(seed, log, "NVDA", 2, suggestion_id=review.id)
    assert entry.sections and apply.conviction_reviews(seed, [*log, entry]) == []
    # Undoing the conviction change reopens the review.
    undone = [*log, entry]
    u = apply.undo(undone)
    assert u is not None
    assert [r.id for r in apply.conviction_reviews(seed, [*undone, u])] == ["NVDA.p3.review"]


def test_accept_never_mutates_seed(seed: Seed, sugg: dict[str, Suggestion]) -> None:
    before = seed.model_copy(deep=True)
    log = [apply.accept(seed, [], sugg["AMZN.new1"], at=datetime(2026, 10, 13, tzinfo=UTC))]
    fold(seed, log)
    assert seed == before


# ---- Manual changes to pillars ----

def test_manual_add_edit_remove_and_undo(seed: Seed) -> None:
    log: list[LogEntry] = []
    log.append(apply.add_pillar(seed, log, "AAPL", "Enterprise demand grows on AI features.",
                                driver_ids=["AAPL.other_products_growth"]))
    state = fold(seed, log)
    added = state.theses["AAPL"].pillars[-1]
    assert added.id == "AAPL.p4" and added.driver_ids == ["AAPL.other_products_growth"]
    assert log[-1].suggestion_id == "" and state.evidence["AAPL.p4"] == []

    log.append(apply.edit_pillar(seed, log, "AAPL.p1", statement="The upgrade cycle disappoints."))
    state = fold(seed, log)
    p1 = next(p for p in state.theses["AAPL"].pillars if p.id == "AAPL.p1")
    assert p1.statement == "The upgrade cycle disappoints." and log[-1].pillar_before is not None
    assert [p.id for p in state.theses["AAPL"].pillars][0] == "AAPL.p1"   # edited in place

    log.append(apply.remove_pillar(seed, log, "AAPL.p4"))
    state = fold(seed, log)
    assert "AAPL.p4" not in [p.id for p in state.theses["AAPL"].pillars] and "AAPL.p4" in state.removed
    # A removed pillar's ID is never reused.
    assert apply.add_pillar(seed, log, "AAPL", "Another.").item_id == "AAPL.p5"

    undo = apply.undo(log)
    assert undo is not None
    log.append(undo)
    assert "AAPL.p4" in [p.id for p in fold(seed, log).theses["AAPL"].pillars]


def test_manual_changes_are_checked(seed: Seed) -> None:
    with pytest.raises(apply.ActionError):
        apply.add_pillar(seed, [], "AAPL", "   ")
    with pytest.raises(apply.ActionError):
        apply.add_pillar(seed, [], "AAPL", "Uses an NVDA driver.", driver_ids=["NVDA.capex"])
    with pytest.raises(apply.ActionError):
        apply.edit_pillar(seed, [], "AAPL.p9", statement="No such pillar.")
    p1 = next(p for t in seed.theses for p in t.pillars if p.id == "AAPL.p1")
    with pytest.raises(apply.ActionError):
        apply.edit_pillar(seed, [], "AAPL.p1", statement=p1.statement)   # nothing changed


def test_manual_evidence_counts_toward_conviction_review(seed: Seed) -> None:
    log: list[LogEntry] = []
    for _ in range(2):
        log.append(apply.log_evidence(seed, log, "MSFT.p1", "contradicts", 3))
    assert net_contradicting(fold(seed, log), "MSFT.p1") == 6
    assert any(r.id == "MSFT.p1.review" for r in apply.conviction_reviews(seed, log))


def test_suggestion_on_a_removed_pillar_cannot_be_accepted(seed: Seed) -> None:
    log = [apply.remove_pillar(seed, [], "MSFT.p1")]
    s = Suggestion(id="MSFT.p1.supports", body=ExistingThesis(kind="existing_thesis", pillar_id="MSFT.p1",
                   stance="supports", strength=1), rationale="r", claim_ids=[], sections=[], status="open")
    with pytest.raises(apply.ActionError):
        apply.accept(seed, log, s)
