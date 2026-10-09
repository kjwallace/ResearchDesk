import json
from pathlib import Path

import pytest
from fakes import FIXTURE_EMAILS, FakeEmbedder, fixture_emails

from triage_app.config import FIXTURES_DIR
from triage_app.pipeline import validate
from triage_app.pipeline.context import RunContext
from triage_app.pipeline.io import read_list
from triage_app.schema import (
    Claim,
    Email,
    EmailResult,
    ExistingThesis,
    LinkedAssumption,
    LinkedSection,
    NewThesis,
    Suggestion,
)
from triage_app.state.fold import load_seed

OUT = FIXTURES_DIR / "out"


@pytest.fixture
def ctx() -> RunContext:
    return RunContext(embedder=FakeEmbedder(), use_cache=False, emails_path=FIXTURE_EMAILS)


@pytest.fixture
def inputs() -> validate.ValidationInputs:
    return validate.ValidationInputs(
        claims=read_list(OUT / "claims.json", Claim),
        emails=fixture_emails(),
        results=read_list(OUT / "results.json", EmailResult),
        seed=load_seed(),
    )


def raw() -> dict[str, Suggestion]:
    return {s.id: s for s in read_list(OUT / "suggestions_raw.json", Suggestion)}


def with_body(s: Suggestion, **update: object) -> Suggestion:
    return s.model_copy(update={"body": s.body.model_copy(update=update)})


def check(s: Suggestion, ctx: RunContext, inputs: validate.ValidationInputs) -> Suggestion:
    out = validate.process(s, ctx, inputs)
    Suggestion.model_validate(out.model_dump())
    return out


def test_run_reproduces_fixture(tmp_path: Path, ctx: RunContext) -> None:
    validate.run(OUT, tmp_path, ctx)
    written = json.loads((tmp_path / "suggestions_checked.json").read_text())
    assert written == json.loads((OUT / "suggestions_checked.json").read_text())
    read_list(tmp_path / "suggestions_checked.json", Suggestion)
    assert {t.email_id for t in ctx.recorder.timings if t.stage == "validate"} == {
        "fixture_001", "fixture_002", "fixture_008", "fixture_009"}


def test_valid_suggestion_kept_with_figure(ctx: RunContext, inputs: validate.ValidationInputs) -> None:
    out = check(raw()["fixture_001.s1"], ctx, inputs)
    assert out.status == "open" and out.reject_reason is None and not out.second_look
    assert isinstance(out.body, ExistingThesis) and len(out.body.assumptions) == 1


def test_unknown_claim_rejected(ctx: RunContext, inputs: validate.ValidationInputs) -> None:
    s = raw()["fixture_001.s1"].model_copy(update={"claim_ids": ["fixture_002.c1"]})
    out = check(s, ctx, inputs)
    assert out.status == "rejected" and out.reject_reason is not None
    assert out.reject_reason.startswith("unknown item: fixture_002.c1")


def test_unknown_pillar_rejected(ctx: RunContext, inputs: validate.ValidationInputs) -> None:
    # MSFT claims bring in NVDA.p1 by link, but not AAPL.p1.
    assert check(with_body(raw()["fixture_001.s1"], pillar_id="NVDA.p1", assumptions=[]),
                 ctx, inputs).status == "open"
    out = check(with_body(raw()["fixture_001.s1"], pillar_id="AAPL.p1"), ctx, inputs)
    assert out.status == "rejected" and "AAPL.p1" in (out.reject_reason or "")


def test_new_thesis_ticker_outside_claims_rejected(ctx: RunContext, inputs: validate.ValidationInputs) -> None:
    out = check(with_body(raw()["fixture_009.s1"], ticker="MSFT", driver_ids=[]), ctx, inputs)
    assert out.status == "rejected" and "MSFT" in (out.reject_reason or "")


def test_new_pillar_with_other_company_driver_rejected(ctx: RunContext, inputs: validate.ValidationInputs) -> None:
    out = check(with_body(raw()["fixture_009.s1"], driver_ids=["AMZN.aws_growth", "NVDA.data_center_growth"]),
                ctx, inputs)
    assert out.status == "rejected" and "NVDA.data_center_growth" in (out.reject_reason or "")


def test_section_from_another_email_rejected(ctx: RunContext, inputs: validate.ValidationInputs) -> None:
    s = raw()["fixture_001.s1"]
    other = LinkedSection(email_id="fixture_002", quote=raw()["fixture_002.s1"].sections[0].quote)
    out = check(s.model_copy(update={"sections": [*s.sections, other]}), ctx, inputs)
    assert out.status == "rejected" and (out.reject_reason or "").startswith("unknown item")


def test_quote_mismatch_rejected(ctx: RunContext, inputs: validate.ValidationInputs) -> None:
    out = check(raw()["fixture_001.s2"], ctx, inputs)
    assert out.status == "rejected"
    assert out.reject_reason == "quote mismatch: section not found in fixture_001"


def test_quote_matches_after_whitespace_collapse(ctx: RunContext, inputs: validate.ValidationInputs) -> None:
    s = raw()["fixture_001.s1"]
    spaced = [sec.model_copy(update={"quote": sec.quote.replace(" ", "  \n ")}) for sec in s.sections]
    assert check(s.model_copy(update={"sections": spaced}), ctx, inputs).status == "open"


def test_duplicate_thesis_rejected(ctx: RunContext, inputs: validate.ValidationInputs) -> None:
    statement = inputs.pillars["AMZN.p1"].statement
    out = check(with_body(raw()["fixture_009.s1"], statement=statement), ctx, inputs)
    assert out.status == "rejected"
    assert (out.reject_reason or "").startswith("duplicate thesis: statement matches AMZN.p1")


def test_monitor_only_caps_strength(ctx: RunContext, inputs: validate.ValidationInputs) -> None:
    s = raw()["fixture_002.s1"]
    assert isinstance(s.body, ExistingThesis) and s.body.strength == 2
    out = check(s, ctx, inputs)
    assert out.status == "open" and isinstance(out.body, ExistingThesis) and out.body.strength == 1
    assert not out.second_look


def test_monitor_only_rejects_new_thesis(ctx: RunContext, inputs: validate.ValidationInputs) -> None:
    inputs.results["fixture_009"] = inputs.results["fixture_009"].model_copy(update={"triage": "monitor"})
    out = check(raw()["fixture_009.s1"], ctx, inputs)
    assert out.status == "rejected" and (out.reject_reason or "").startswith("monitor only")


def figure(driver_id: str, value: float) -> LinkedAssumption:
    return LinkedAssumption(driver_id=driver_id, stated_value=value, book_value=24.0, consensus_value=21.5)


def test_out_of_bounds_figure_dropped(ctx: RunContext, inputs: validate.ValidationInputs) -> None:
    inputs.claims["fixture_001.c1"] = inputs.claims["fixture_001.c1"].model_copy(update={"value": 80.0})
    out = check(with_body(raw()["fixture_001.s1"], assumptions=[figure("MSFT.intelligent_cloud_growth", 80.0)]),
                ctx, inputs)
    assert out.status == "open" and isinstance(out.body, ExistingThesis) and out.body.assumptions == []


def test_driver_not_linked_to_pillar_dropped(ctx: RunContext, inputs: validate.ValidationInputs) -> None:
    inputs.claims["fixture_001.c1"] = inputs.claims["fixture_001.c1"].model_copy(update={"value": 40.0})
    out = check(with_body(raw()["fixture_001.s1"], assumptions=[figure("MSFT.operating_margin", 40.0)]),
                ctx, inputs)
    assert out.status == "open" and isinstance(out.body, ExistingThesis) and out.body.assumptions == []


@pytest.mark.parametrize("period", [None, "FY2026", "fy2027"])
def test_wrong_period_figure_dropped(period: str | None, ctx: RunContext,
                                     inputs: validate.ValidationInputs) -> None:
    inputs.claims["fixture_001.c1"] = inputs.claims["fixture_001.c1"].model_copy(update={"period": period})
    out = check(raw()["fixture_001.s1"], ctx, inputs)
    assert out.status == "open" and isinstance(out.body, ExistingThesis) and out.body.assumptions == []


def test_figure_no_claim_states_is_dropped(ctx: RunContext, inputs: validate.ValidationInputs) -> None:
    out = check(with_body(raw()["fixture_001.s1"], assumptions=[figure("MSFT.intelligent_cloud_growth", 30.0)]),
                ctx, inputs)
    assert isinstance(out.body, ExistingThesis) and out.body.assumptions == []


def test_second_look_marked(ctx: RunContext, inputs: validate.ValidationInputs) -> None:
    out = check(raw()["fixture_008.s1"], ctx, inputs)  # low_value email that cleared the gate
    assert out.status == "open" and out.second_look


def test_rules_run_in_order(ctx: RunContext, inputs: validate.ValidationInputs) -> None:
    # Unknown item is reported before a quote mismatch on the same suggestion.
    s = with_body(raw()["fixture_001.s2"], pillar_id="AAPL.p1")
    assert (check(s, ctx, inputs).reject_reason or "").startswith("unknown item")


def test_rejected_input_passes_through(ctx: RunContext, inputs: validate.ValidationInputs) -> None:
    s = raw()["fixture_001.s1"].model_copy(update={"status": "rejected", "reject_reason": "earlier"})
    assert validate.process(s, ctx, inputs) == s


def test_new_thesis_kept(ctx: RunContext, inputs: validate.ValidationInputs) -> None:
    out = check(raw()["fixture_009.s1"], ctx, inputs)
    assert out.status == "open" and isinstance(out.body, NewThesis)


def test_figure_whose_number_is_not_in_the_quote_is_dropped(ctx: RunContext,
                                                            inputs: validate.ValidationInputs) -> None:
    # The model wrote value 26 for the claim, but the quote states a different number.
    claim = inputs.claims["fixture_001.c1"]
    inputs.claims["fixture_001.c1"] = claim.model_copy(update={"quote": "Azure grew 31% y/y last quarter."})
    out = check(raw()["fixture_001.s1"], ctx, inputs)
    assert isinstance(out.body, ExistingThesis) and out.body.assumptions == []


def test_numbers_in_reads_separators_and_signs() -> None:
    assert validate.numbers_in("capex of $4,500m, up -2.5% to 31.0%") == [4500.0, 2.5, 31.0]
