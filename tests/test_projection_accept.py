"""Accepting a projection change: a driver updates the assumption; an output metric is noted."""

from triage_app.schema import LinkedSection, ProjectionChange, Suggestion
from triage_app.state import apply
from triage_app.state.compute import metric_value
from triage_app.state.fold import fold, load_seed

SEED = load_seed()


def projection(metric: str, value: float) -> Suggestion:
    model = fold(SEED, []).models["MSFT"]
    book = metric_value(model, metric, "analyst")
    consensus = metric_value(model, metric, "consensus")
    assert book is not None and consensus is not None
    return Suggestion(
        id=f"MSFT.{metric.removeprefix('MSFT.')}.proj1",
        body=ProjectionChange(kind="projection_change", ticker="MSFT", metric=metric, period="FY2027",
                              stated_value=value, book_value=book, consensus_value=consensus),
        rationale="r", claim_ids=["fixture_001.c1"],
        sections=[LinkedSection(email_id="fixture_001", quote="q")], status="open")


def test_accepting_a_driver_projection_updates_the_driver() -> None:
    s = projection("MSFT.intelligent_cloud_growth", 26.0)
    entry = apply.accept(SEED, [], s)
    assert entry.change == "driver_updated" and entry.item_id == "MSFT.intelligent_cloud_growth"
    assert (entry.before, entry.after) == (24.0, 26.0) and entry.suggestion_id == s.id
    model = fold(SEED, [entry]).models["MSFT"]
    assert metric_value(model, "MSFT.intelligent_cloud_growth", "analyst") == 26.0


def test_accepting_an_eps_projection_notes_it_against_computed_eps() -> None:
    s = projection("eps", 19.4)
    entry = apply.accept(SEED, [], s)
    assert entry.change == "projection_noted" and entry.item_id == "MSFT.eps"
    assert entry.before == metric_value(fold(SEED, []).models["MSFT"], "eps", "analyst")
    assert entry.after == 19.4 and entry.sections == s.sections


def test_an_accepted_projection_is_no_longer_open() -> None:
    from triage_app.state.apply import accept, accepted_ids, status_of
    seed = load_seed()
    s = projection("MSFT.intelligent_cloud_growth", 26.0)
    log = [accept(seed, [], s)]
    assert s.id in accepted_ids(log) and status_of(s, log, []) == "accepted"
