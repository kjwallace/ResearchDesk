"""Projection changes: the revise_projections skill's view, collection, validation and merging."""

import json
from typing import Any

import pytest
from fakes import FIXTURE_EMAILS, FakeEmbedder, fixture_emails
from test_analyze import MSFT_Q1, Script, claims_of, run_one, step

from triage_app import thresholds
from triage_app.config import FIXTURES_DIR
from triage_app.evals import metric
from triage_app.pipeline import merge, validate
from triage_app.pipeline.context import RunContext
from triage_app.pipeline.io import read_list
from triage_app.schema import Claim, CompanyModel, EmailResult, LinkedSection, ProjectionChange, Suggestion
from triage_app.state.compute import metric_value
from triage_app.state.fold import load_seed

OUT = FIXTURES_DIR / "out"
SEED = load_seed()
MODELS: dict[str, CompanyModel] = {m.ticker: m for m in SEED.models}
MSFT = MODELS["MSFT"]
EPS_QUOTE = "We now see Microsoft earning EPS of $19.40 in FY2027."


@pytest.fixture(autouse=True)
def analysis_model(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANALYSIS_MODEL", "fake/analysis-model")


def draft(metric_id: str, value: float, *, ticker: str = "MSFT", period: str = "FY2027",
          claim_ids: tuple[str, ...] = ("fixture_001.c1",), quote: str = MSFT_Q1) -> dict[str, Any]:
    return {"kind": "projection_change", "ticker": ticker, "metric": metric_id, "period": period,
            "stated_value": value, "rationale": f"The email states {metric_id}.",
            "claim_ids": list(claim_ids), "sections": [{"email_id": "fixture_001", "quote": quote}]}


def project_once(*drafts: dict[str, Any]) -> tuple[list[Suggestion], Script]:
    script = Script([step("revise_projections", claim_ids=["fixture_001.c1"], ticker="MSFT")],
                    project=[{"suggestions": list(drafts)}])
    _, made, _ = run_one(script)
    for s in made:
        Suggestion.model_validate(s.model_dump())
    return made, script


# ---- The skill's view ----

def test_projection_skill_sees_fiscal_year_drivers_and_projections_never_size() -> None:
    _, script = project_once()
    prompt = script.seen["project"][0]
    assert '"fiscal_year": "FY2027"' in prompt
    assert '"id": "MSFT.intelligent_cloud_growth"' in prompt and '"consensus": 21.5' in prompt
    for m in ("revenue", "operating_income", "eps", "target_price"):
        value = metric_value(MSFT, m, "analyst")
        assert value is not None and f'"metric": "{m}"' in prompt and json.dumps(round(value, 2)) in prompt
    assert "size_bps" not in prompt and "conviction" not in prompt
    assert "NVDA.data_center_growth" not in prompt                  # only the company asked about


# ---- Collection: code fills book and consensus values ----

def test_code_fills_book_and_consensus_for_a_driver_and_for_eps() -> None:
    made, _ = project_once(draft("MSFT.intelligent_cloud_growth", 26.0), draft("eps", 19.4, quote=EPS_QUOTE))
    assert [s.id for s in made] == ["fixture_001.s1", "fixture_001.s2"]
    driver, eps = (s.body for s in made)
    assert isinstance(driver, ProjectionChange) and isinstance(eps, ProjectionChange)
    assert (driver.stated_value, driver.book_value, driver.consensus_value) == (26.0, 24.0, 21.5)
    assert eps.book_value == metric_value(MSFT, "eps", "analyst")
    assert eps.consensus_value == metric_value(MSFT, "eps", "consensus")
    assert eps.book_value != eps.consensus_value


def test_unknown_metric_or_other_companys_driver_is_dropped() -> None:
    made, _ = project_once(draft("free_cash_flow", 80.0), draft("NVDA.data_center_growth", 40.0),
                           draft("MSFT.capex", 120.0))
    assert [s.body.metric for s in made if isinstance(s.body, ProjectionChange)] == ["MSFT.capex"]
    assert [s.id for s in made] == ["fixture_001.s1"]


def test_projections_are_not_capped_with_existing_theses() -> None:
    made, _ = project_once(*(draft("MSFT.intelligent_cloud_growth", 26.0 + i) for i in range(3)))
    assert len(made) == 3 > thresholds.MAX_THESIS_SUGGESTIONS_PER_EMAIL


# ---- Validation ----

@pytest.fixture
def ctx() -> RunContext:
    return RunContext(embedder=FakeEmbedder(), use_cache=False, emails_path=FIXTURE_EMAILS)


@pytest.fixture
def inputs() -> validate.ValidationInputs:
    inp = validate.ValidationInputs(
        claims=read_list(OUT / "claims.json", Claim),
        emails=fixture_emails(),
        results=read_list(OUT / "results.json", EmailResult),
        seed=load_seed(),
    )
    # A second MSFT claim stating EPS, quoted in the email's body.
    inp.bodies["fixture_001"] += "\n\n" + EPS_QUOTE
    inp.claims["fixture_001.c9"] = inp.claims["fixture_001.c1"].model_copy(update={
        "id": "fixture_001.c9", "quote": EPS_QUOTE, "metric": "EPS", "value": 19.4, "unit": "usd"})
    return inp


def projection(metric_id: str, value: float, *, sid: str = "fixture_001.s1", ticker: str = "MSFT",
               period: str = "FY2027", claim: str = "fixture_001.c1", quote: str = MSFT_Q1,
               email: str = "fixture_001") -> Suggestion:
    model = MODELS.get(ticker)
    book = metric_value(model, metric_id, "analyst") if model else None
    return Suggestion(
        id=sid,
        body=ProjectionChange(kind="projection_change", ticker=ticker, metric=metric_id, period=period,
                              stated_value=value, book_value=book or 0.0, consensus_value=book or 0.0),
        rationale="r", claim_ids=[claim], sections=[LinkedSection(email_id=email, quote=quote)], status="open")


def checked(s: Suggestion, ctx: RunContext, inputs: validate.ValidationInputs) -> Suggestion:
    out = validate.process(s, ctx, inputs)
    Suggestion.model_validate(out.model_dump())
    return out


def reason(s: Suggestion, ctx: RunContext, inputs: validate.ValidationInputs) -> str:
    out = checked(s, ctx, inputs)
    assert out.status == "rejected"
    return out.reject_reason or ""


def test_valid_projections_kept(ctx: RunContext, inputs: validate.ValidationInputs) -> None:
    for s in (projection("MSFT.intelligent_cloud_growth", 26.0),
              projection("eps", 19.4, claim="fixture_001.c9", quote=EPS_QUOTE)):
        out = checked(s, ctx, inputs)
        assert out.status == "open" and not out.second_look and out.body == s.body


def test_unknown_metric_rejected(ctx: RunContext, inputs: validate.ValidationInputs) -> None:
    assert reason(projection("free_cash_flow", 26.0), ctx, inputs).startswith("unknown item: free_cash_flow")
    assert reason(projection("NVDA.data_center_growth", 26.0), ctx, inputs).startswith("unknown item")


def test_ticker_outside_claims_rejected(ctx: RunContext, inputs: validate.ValidationInputs) -> None:
    s = projection("NVDA.data_center_growth", 26.0, ticker="NVDA")
    assert reason(s, ctx, inputs) == "unknown item: projection on NVDA, outside the claims' tickers"


def test_projection_quote_mismatch_rejected(ctx: RunContext, inputs: validate.ValidationInputs) -> None:
    s = projection("MSFT.intelligent_cloud_growth", 26.0, quote="Intelligent Cloud growth of 30% in FY2027")
    assert reason(s, ctx, inputs) == "quote mismatch: section not found in fixture_001"


@pytest.mark.parametrize("period", ["FY2026", "fy2027", "FY2027E"])
def test_wrong_period_rejected(period: str, ctx: RunContext, inputs: validate.ValidationInputs) -> None:
    assert reason(projection("MSFT.intelligent_cloud_growth", 26.0, period=period), ctx, inputs).startswith(
        "wrong period")


def test_figure_not_in_quotes_rejected(ctx: RunContext, inputs: validate.ValidationInputs) -> None:
    assert reason(projection("MSFT.intelligent_cloud_growth", 27.0), ctx, inputs).startswith("figure not stated")


def test_implausible_gap_rejected(ctx: RunContext, inputs: validate.ValidationInputs) -> None:
    # The quote states 1.94 (a per-quarter figure, say); against an annual EPS near 18.8 it is implausible.
    quote = "Microsoft should earn EPS of $1.94 in FY2027."
    inputs.bodies["fixture_001"] += "\n\n" + quote
    inputs.claims["fixture_001.c9"] = inputs.claims["fixture_001.c9"].model_copy(update={"quote": quote})
    got = reason(projection("eps", 1.94, claim="fixture_001.c9", quote=quote), ctx, inputs)
    assert got.startswith("implausible: 1.94 is")
    book = metric_value(MSFT, "eps", "analyst")
    assert book is not None and abs(1.94 - book) / book > thresholds.PROJECTION_MAX_GAP


def test_driver_figure_out_of_bounds_rejected(ctx: RunContext, inputs: validate.ValidationInputs) -> None:
    # MSFT.operating_margin: book 45, bounds 30 to 60. A stated 61 is within the gap (36%) but out of bounds.
    quote = "We expect an operating margin of 61% in FY2027."
    inputs.bodies["fixture_001"] += "\n\n" + quote
    inputs.claims["fixture_001.c1"] = inputs.claims["fixture_001.c1"].model_copy(update={"quote": quote})
    got = reason(projection("MSFT.operating_margin", 61.0, quote=quote), ctx, inputs)
    assert got == "out of bounds: 61 is outside MSFT.operating_margin's bounds (30 to 60)"


def test_implausible_reported_before_bounds(ctx: RunContext, inputs: validate.ValidationInputs) -> None:
    quote = "Capex should reach $230 billion in FY2027."
    inputs.bodies["fixture_001"] += "\n\n" + quote
    inputs.claims["fixture_001.c1"] = inputs.claims["fixture_001.c1"].model_copy(update={"quote": quote})
    assert reason(projection("MSFT.capex", 230.0, quote=quote), ctx, inputs).startswith("implausible")


def test_monitor_only_and_second_look_apply(ctx: RunContext, inputs: validate.ValidationInputs) -> None:
    s = projection("MSFT.intelligent_cloud_growth", 26.0)
    inputs.results["fixture_001"] = inputs.results["fixture_001"].model_copy(update={"triage": "monitor"})
    out = checked(s, ctx, inputs)
    assert out.status == "open" and not out.second_look
    inputs.results["fixture_001"] = inputs.results["fixture_001"].model_copy(update={"triage": "low_value"})
    out = checked(s, ctx, inputs)
    assert out.status == "open" and out.second_look


# ---- Merging ----

def results() -> list[EmailResult]:
    return read_list(OUT / "results.json", EmailResult)


def made_in(email: str, sid: str, metric_id: str, value: float, ticker: str = "MSFT") -> Suggestion:
    return projection(metric_id, value, sid=sid, ticker=ticker, claim=f"{email}.c1",
                      quote=f"quote from {email}", email=email)


def test_same_figure_merges_and_different_figures_stay_apart(ctx: RunContext) -> None:
    items = [made_in("fixture_001", "fixture_001.s1", "MSFT.intelligent_cloud_growth", 26.0),
             made_in("fixture_002", "fixture_002.s1", "MSFT.intelligent_cloud_growth", 26.0),
             made_in("fixture_009", "fixture_009.s1", "MSFT.intelligent_cloud_growth", 28.0),
             made_in("fixture_002", "fixture_002.s2", "eps", 19.4)]
    out = merge.process(items, ctx, results(), SEED)
    for s in out:
        Suggestion.model_validate(s.model_dump())
    by_id = {s.id: s for s in out}
    assert set(by_id) == {"MSFT.intelligent_cloud_growth.proj1", "MSFT.intelligent_cloud_growth.proj2",
                          "MSFT.eps.proj1"}
    first = by_id["MSFT.intelligent_cloud_growth.proj1"]
    assert first.claim_ids == ["fixture_001.c1", "fixture_002.c1"]
    assert [sec.email_id for sec in first.sections] == ["fixture_001", "fixture_002"]
    second = by_id["MSFT.intelligent_cloud_growth.proj2"].body
    assert isinstance(second, ProjectionChange) and second.stated_value == 28.0


def test_projection_order_and_place(ctx: RunContext) -> None:
    from test_merge import existing, new

    items = [new("fixture_009.s9", "fixture_009", "A brand new idea about chips."),
             made_in("fixture_009", "fixture_009.s1", "AMZN.aws_growth", 26.0, ticker="AMZN"),
             made_in("fixture_001", "fixture_001.s1", "MSFT.intelligent_cloud_growth", 26.0),
             made_in("fixture_008", "fixture_008.s1", "eps", 19.0),
             existing("fixture_001.s2", "fixture_001")]
    out = merge.process(items, ctx, results(), SEED)
    kinds = [s.body.kind for s in out]
    assert kinds == ["existing_thesis", "projection_change", "projection_change", "projection_change", "new_thesis"]
    size = {t.ticker: t.size_bps for t in SEED.theses}
    signal = {r.email_id: r.signal_score for r in results()}
    keys = [(-size[s.body.ticker], -signal[s.sections[0].email_id]) for s in out
            if isinstance(s.body, ProjectionChange)]
    assert keys == sorted(keys)


def test_merge_validates_on_fixture_output(ctx: RunContext) -> None:
    out = merge.process(read_list(OUT / "suggestions_checked.json", Suggestion), ctx, results(), SEED)
    assert [s.id for s in out if isinstance(s.body, ProjectionChange)] == ["MSFT.intelligent_cloud_growth.proj1"]


# ---- Evals ----

def test_review_sheet_has_projection_checks() -> None:
    assert metric.SUGGESTION_CHECKS["projection_change"] == ("right_metric", "figure_stated", "sections_support")
    rows = [{"kind": "projection_change", "right_metric": "yes", "figure_stated": "yes", "sections_support": "yes"},
            {"kind": "projection_change", "right_metric": "yes", "figure_stated": "no", "sections_support": "yes"},
            {"kind": "projection_change", "right_metric": "", "figure_stated": "", "sections_support": ""}]
    assert metric.projection_review(rows) == 0.5
    assert metric.suggestion_review(rows) is None


def test_quote_faithfulness_and_stray_count_projections() -> None:
    s = projection("MSFT.intelligent_cloud_growth", 26.0, quote="not in the body")
    bodies = {e.email_id: e.body for e in fixture_emails()}
    assert metric.quote_faithfulness([], [s], bodies).value == 0.0
    assert metric.quote_faithfulness([], [projection("MSFT.intelligent_cloud_growth", 26.0)], bodies).value == 1.0
    from triage_app.evals.score import read_labels_file

    labels = {lab.email_id: lab for lab in read_labels_file(FIXTURES_DIR / "labels.jsonl")}
    noise = [i for i, lab in labels.items() if lab.triage in metric.NOISE_LABELS][0]
    stray = metric.stray_suggestions([made_in(noise, "x.s1", "eps", 19.0),
                                      made_in("fixture_001", "fixture_001.s1", "eps", 19.0)], labels)
    assert stray.value == 1.0 and stray.misses[0].got.startswith("x.s1:")

