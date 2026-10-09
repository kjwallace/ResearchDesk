import json
from pathlib import Path

import pytest
from fakes import FIXTURE_EMAILS, FakeEmbedder

from triage_app.config import FIXTURES_DIR
from triage_app.pipeline import merge
from triage_app.pipeline.context import RunContext
from triage_app.pipeline.io import read_list
from triage_app.schema import (
    EmailResult,
    ExistingThesis,
    LinkedAssumption,
    LinkedSection,
    NewThesis,
    Suggestion,
)
from triage_app.state.fold import Seed, load_seed

OUT = FIXTURES_DIR / "out"


@pytest.fixture
def ctx() -> RunContext:
    return RunContext(embedder=FakeEmbedder(), use_cache=False, emails_path=FIXTURE_EMAILS)


@pytest.fixture
def seed() -> Seed:
    return load_seed()


@pytest.fixture
def results() -> list[EmailResult]:
    return read_list(OUT / "results.json", EmailResult)


def checked() -> dict[str, Suggestion]:
    return {s.id: s for s in read_list(OUT / "suggestions_checked.json", Suggestion)}


def existing(sid: str, email: str, pillar: str = "MSFT.p1", stance: str = "supports", strength: int = 1,
             wrong_if_met: bool = False, assumptions: list[LinkedAssumption] | None = None,
             rationale: str = "r") -> Suggestion:
    return Suggestion(
        id=sid,
        body=ExistingThesis(kind="existing_thesis", pillar_id=pillar, stance=stance,
                            strength=strength, wrong_if_met=wrong_if_met,
                            assumptions=assumptions or []),
        rationale=rationale, claim_ids=[f"{email}.c1"],
        sections=[LinkedSection(email_id=email, quote=f"quote from {email}")], status="open",
    )


def new(sid: str, email: str, statement: str, ticker: str = "AMZN", drivers: list[str] | None = None) -> Suggestion:
    return Suggestion(
        id=sid,
        body=NewThesis(kind="new_thesis", ticker=ticker, statement=statement,
                       wrong_if="w", driver_ids=drivers or []),
        rationale=f"from {email}", claim_ids=[f"{email}.c1"],
        sections=[LinkedSection(email_id=email, quote=f"quote from {email}")], status="open",
    )


def merged(items: list[Suggestion], ctx: RunContext, results: list[EmailResult], seed: Seed) -> list[Suggestion]:
    out = merge.process(items, ctx, results, seed)
    for s in out:
        Suggestion.model_validate(s.model_dump())
    return out


def test_run_reproduces_fixture(tmp_path: Path, ctx: RunContext, seed: Seed) -> None:
    merge.run(OUT, tmp_path, ctx, seed)
    written = json.loads((tmp_path / "suggestions.json").read_text())
    assert written == json.loads((OUT / "suggestions.json").read_text())
    read_list(tmp_path / "suggestions.json", Suggestion)


def test_rejected_dropped_and_ids_assigned(ctx: RunContext, results: list[EmailResult], seed: Seed) -> None:
    out = merged(list(checked().values()), ctx, results, seed)
    assert [s.id for s in out] == ["NVDA.p2.supports", "MSFT.p1.supports", "AAPL.p1.supports",
                                  "MSFT.intelligent_cloud_growth.proj1", "AMZN.new1"]
    assert all(s.status == "open" for s in out)


def test_same_pillar_and_stance_merge(ctx: RunContext, results: list[EmailResult], seed: Seed) -> None:
    a = existing("fixture_002.s1", "fixture_002", strength=1, rationale="weak",
                 assumptions=[LinkedAssumption(driver_id="MSFT.intelligent_cloud_growth", stated_value=26.0,
                                               book_value=24.0, consensus_value=21.5)])
    b = existing("fixture_001.s1", "fixture_001", strength=3, rationale="strong",
                 assumptions=[LinkedAssumption(driver_id="MSFT.intelligent_cloud_growth", stated_value=26.0,
                                               book_value=24.0, consensus_value=21.5),
                              LinkedAssumption(driver_id="MSFT.intelligent_cloud_growth", stated_value=28.0,
                                               book_value=24.0, consensus_value=21.5)])
    c = existing("fixture_008.s1", "fixture_008", strength=2, wrong_if_met=True, rationale="middle")
    (out,) = merged([a, b, c], ctx, results, seed)
    assert out.id == "MSFT.p1.supports" and isinstance(out.body, ExistingThesis)
    assert out.body.strength == 3 and out.rationale == "strong"
    assert out.body.wrong_if_met
    assert [(x.driver_id, x.stated_value) for x in out.body.assumptions] == [
        ("MSFT.intelligent_cloud_growth", 26.0), ("MSFT.intelligent_cloud_growth", 28.0)]
    assert [sec.email_id for sec in out.sections] == ["fixture_002", "fixture_001", "fixture_008"]
    assert out.claim_ids == ["fixture_002.c1", "fixture_001.c1", "fixture_008.c1"]


def test_strength_tie_goes_to_higher_signal(ctx: RunContext, results: list[EmailResult], seed: Seed) -> None:
    a = existing("fixture_008.s1", "fixture_008", strength=2, rationale="low signal")   # 0.62
    b = existing("fixture_001.s1", "fixture_001", strength=2, rationale="high signal")  # 0.92
    (out,) = merged([a, b], ctx, results, seed)
    assert out.rationale == "high signal"


def test_opposite_stances_stay_apart(ctx: RunContext, results: list[EmailResult], seed: Seed) -> None:
    a = existing("fixture_001.s1", "fixture_001", stance="supports")
    b = existing("fixture_002.s1", "fixture_002", stance="contradicts")
    out = merged([a, b], ctx, results, seed)
    assert sorted(s.id for s in out) == ["MSFT.p1.contradicts", "MSFT.p1.supports"]


def test_similar_new_theses_merge_first_statement_kept(ctx: RunContext, results: list[EmailResult],
                                                       seed: Seed) -> None:
    first = "In-house AI chips lower AWS cost of AI capacity so operating margin expands."
    a = new("fixture_009.s1", "fixture_009", first, drivers=["AMZN.operating_margin"])
    b = new("fixture_001.s3", "fixture_001", first + " Indeed.", drivers=["AMZN.aws_growth"])
    c = new("fixture_002.s2", "fixture_002", "Grocery delivery density lifts retail returns in rural markets.")
    out = merged([a, b, c], ctx, results, seed)
    assert [s.id for s in out] == ["AMZN.new1", "AMZN.new2"]
    one = out[0] if out[0].claim_ids[0].startswith("fixture_009") else out[1]
    assert isinstance(one.body, NewThesis) and one.body.statement == first
    assert one.body.driver_ids == ["AMZN.operating_margin", "AMZN.aws_growth"]
    assert one.claim_ids == ["fixture_009.c1", "fixture_001.c1"] and one.rationale == "from fixture_009"


def test_new_theses_numbered_per_company(ctx: RunContext, results: list[EmailResult], seed: Seed) -> None:
    out = merged([new("fixture_009.s1", "fixture_009", "Trainium wins inference."),
                  new("fixture_001.s1", "fixture_001", "Copilot seats double.", ticker="MSFT")], ctx, results, seed)
    assert {s.id for s in out} == {"AMZN.new1", "MSFT.new1"}


def test_second_look_recomputed(ctx: RunContext, results: list[EmailResult], seed: Seed) -> None:
    lone = existing("fixture_008.s1", "fixture_008", pillar="AAPL.p1")
    lone = lone.model_copy(update={"second_look": True})
    (out,) = merged([lone], ctx, results, seed)
    assert out.second_look
    joined = existing("fixture_001.s9", "fixture_001", pillar="AAPL.p1")
    (out,) = merged([lone, joined], ctx, results, seed)
    assert not out.second_look


def test_order(ctx: RunContext, results: list[EmailResult], seed: Seed) -> None:
    items = [
        new("fixture_001.s5", "fixture_001", "Copilot seats double.", ticker="MSFT"),          # 250 bps, 0.92
        new("fixture_009.s1", "fixture_009", "Trainium wins inference."),                     # 200 bps
        new("fixture_002.s5", "fixture_002", "Sovereign buyers stay.", ticker="NVDA"),        # 300 bps
        existing("fixture_008.s1", "fixture_008", pillar="AAPL.p1", strength=3),              # 200 bps
        existing("fixture_001.s1", "fixture_001", pillar="MSFT.p2", strength=1),              # 250, 1, 0.92
        existing("fixture_008.s2", "fixture_008", pillar="MSFT.p3", strength=2),              # 250, 2
        existing("fixture_002.s1", "fixture_002", pillar="MSFT.p1", strength=1),              # 250, 1, 0.82
        existing("fixture_009.s2", "fixture_009", pillar="NVDA.p3", strength=1),              # 300
    ]
    out = merged(items, ctx, results, seed)
    assert [s.id for s in out] == [
        "NVDA.p3.supports", "MSFT.p3.supports", "MSFT.p2.supports", "MSFT.p1.supports", "AAPL.p1.supports",
        "NVDA.new1", "MSFT.new1", "AMZN.new1",
    ]
