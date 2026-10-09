from datetime import UTC, datetime

from triage_app.schema import LinkedSection, LogEntry, Pillar
from triage_app.state.fold import fold, load_seed, net_contradicting, next_pillar_id

SEC = [LinkedSection(email_id="e1", quote="q")]


def entry(i: str, change: str, item: str, **kw: object) -> LogEntry:
    return LogEntry(id=i, at=datetime.now(UTC), suggestion_id="s", change=change, item_id=item,  # type: ignore[arg-type]
                    sections=SEC, **kw)  # type: ignore[arg-type]


def test_empty_log_returns_seed() -> None:
    seed = load_seed()
    state = fold(seed, [])
    assert [state.theses[t.ticker] for t in seed.theses] == seed.theses
    assert [state.models[m.ticker] for m in seed.models] == seed.models
    assert all(v == [] for v in state.evidence.values()) and state.applied == []


def test_driver_update_and_undo() -> None:
    seed = load_seed()
    log = [entry("l1", "driver_updated", "NVDA.data_center_growth", before=1.0, after=99.0)]
    state = fold(seed, log)
    assert next(d for d in state.models["NVDA"].drivers if d.id == "NVDA.data_center_growth").analyst == 99.0
    undone = fold(seed, [*log, entry("l2", "driver_updated", "NVDA.data_center_growth", reverses="l1")])
    assert undone.models["NVDA"] == seed.models[[m.ticker for m in seed.models].index("NVDA")]
    redone = fold(seed, [*log, entry("l2", "driver_updated", "x", reverses="l1"),
                         entry("l3", "driver_updated", "x", reverses="l2")])
    assert next(d for d in redone.models["NVDA"].drivers if d.id == "NVDA.data_center_growth").analyst == 99.0


def test_seed_is_not_mutated() -> None:
    seed = load_seed()
    before = seed.model_copy(deep=True)
    fold(seed, [entry("l1", "conviction_changed", "AAPL", after=5)])
    assert seed == before


def test_evidence_and_net_contradicting() -> None:
    seed = load_seed()
    state = fold(seed, [
        entry("l1", "pillar_evidence", "MSFT.p3", stance="contradicts", strength=3),
        entry("l2", "pillar_evidence", "MSFT.p3", stance="contradicts", strength=2),
        entry("l3", "pillar_evidence", "MSFT.p3", stance="supports", strength=1),
    ])
    assert net_contradicting(state, "MSFT.p3") == 4


def test_pillar_added_and_conviction() -> None:
    seed = load_seed()
    state = fold(seed, [])
    pid = next_pillar_id(state, "AAPL")
    assert pid == "AAPL.p4"
    p = Pillar(id=pid, statement="s", wrong_if="w", driver_ids=[])
    state = fold(seed, [entry("l1", "pillar_added", pid, pillar=p), entry("l2", "conviction_changed", "AAPL", after=1)])
    assert state.theses["AAPL"].pillars[-1] == p and state.theses["AAPL"].conviction == 1
    assert pid in state.evidence
