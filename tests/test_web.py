"""The web app on the fixtures, with fakes standing in for other packages' modules."""

import html
import json
import re
import shutil
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any, TypeVar

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from fakes import FIXTURE_EMAILS, FakeChat, FakeEmbedder, fixture_emails

from markupsafe import escape
from pydantic import BaseModel

from triage_app import config, thresholds
from triage_app.llm import Message
from triage_app.monitoring import Recorder
from triage_app.pipeline.context import RunContext
from triage_app.pipeline.io import read_list
from triage_app.schema import (
    AnalysisRecord, AttentionNote, Claim, Email, EmailResult, ExistingThesis, LinkedSection, ProjectionChange, RedundancyRecord, Suggestion, TriageRecord,
    VerifyResult,
)
from triage_app.state.compute import compute
from triage_app.state.fold import load_seed
from triage_app.web import labels, runner
from triage_app.web.main import create_app

OUT = Path(__file__).parent / "fixtures" / "out"
HX = {"HX-Request": "true"}
BANNER = "Synthetic data."
CORPUS = {e.email_id: e for e in fixture_emails()}   # the emails as the app reads them
RESULTS = {r.email_id: r for r in read_list(OUT / "results.json", EmailResult)}
QUARANTINED = [i for i, r in RESULTS.items() if r.gate == "quarantine"]
SECRET = "ZEBRA-QUARANTINE-BODY do not show this sentence anywhere at all"


def app_of(client: TestClient) -> FastAPI:
    """The FastAPI app behind a test client (TestClient types it as a bare ASGI app)."""
    assert isinstance(client.app, FastAPI)
    return client.app


def fake_ctx(recorder: Recorder) -> RunContext:
    return RunContext(None, recorder=recorder, use_cache=False, chat=FakeChat("{}"), embedder=FakeEmbedder(), emails_path=FIXTURE_EMAILS)


@pytest.fixture
def presets(tmp_path: Path) -> Path:
    d = tmp_path / "presets"
    d.mkdir()
    e = CORPUS["fixture_001"].model_copy(update={"email_id": "preset_01"})
    (d / "preset_01.json").write_text(e.model_dump_json())
    return d


@pytest.fixture
def client(presets: Path) -> Iterator[TestClient]:
    with TestClient(create_app(OUT, make_ctx=fake_ctx, presets_dir=presets)) as c:
        yield c


def eps_text(ticker: str, values: dict[str, float] | None = None) -> str:
    model = next(m for m in load_seed().models if m.ticker == ticker)
    if values:
        model = model.model_copy(deep=True)
        for d in model.drivers:
            d.analyst = values.get(d.id, d.analyst)
    return f"{compute(model)['analyst'].eps:,.2f}"


def eps_cells(page: str) -> list[str]:
    return re.findall(r'<td class="num eps">([^<]+)</td>', page)


# ---- Fakes for other packages' stage functions ----

M = TypeVar("M", bound=BaseModel)


def _swap(email_id: str, obj: M) -> M:
    return type(obj).model_validate_json(obj.model_dump_json().replace("fixture_001", email_id))


@pytest.fixture
def fake_stages(monkeypatch: pytest.MonkeyPatch) -> dict[str, bool]:
    """Stage functions that echo the fixture_001 records under the live email's ID.

    Set `quarantine` in the returned options to make the gate quarantine every email.
    """
    opts: dict[str, Any] = {"quarantine": False}
    triage = {t.email_id: t for t in read_list(OUT / "triage.json", TriageRecord)}["fixture_001"]
    claims = [c for c in read_list(OUT / "claims.json", Claim) if c.email_id == "fixture_001"]
    sugg = {s.id: s for s in read_list(OUT / "suggestions.json", Suggestion)}["MSFT.p1.supports"]
    mods = {name: __import__(f"triage_app.pipeline.{name}", fromlist=["process"])
            for name in ("redundancy", "classify", "gate", "human_attention", "extract", "analyze",
                         "validate", "merge")}

    def classify(email: Email, ctx: RunContext) -> TriageRecord:
        ctx.chat.complete(model="fake-jev", messages=[Message(role="user", content="x")])
        return _swap(email.email_id, triage)

    def gate(t: TriageRecord, red: RedundancyRecord, th: Any) -> EmailResult:
        if opts["quarantine"]:
            return RESULTS["fixture_003"].model_copy(update={"email_id": t.email_id})
        return _swap(t.email_id, RESULTS["fixture_001"])

    def analyze(email_id: str, cs: list[Claim], result: EmailResult, ctx: RunContext, **_: Any) -> Any:
        ctx.chat.complete(model="fake-analysis", messages=[Message(role="user", content="y")])
        s = _swap(email_id, sugg).model_copy(update={"id": f"{email_id}.s1"})
        return AnalysisRecord(email_id=email_id, skills_called=["existing_thesis"], suggestion_ids=[s.id]), [s]

    monkeypatch.setattr(runner, "day_cache", lambda data, ctx: None)
    monkeypatch.setattr(mods["redundancy"], "process", lambda e, day, ctx: RedundancyRecord(
        email_id=e.email_id, nearest=None, content_similarity=None, subject_score=None, flagged=False))
    monkeypatch.setattr(mods["classify"], "process", classify)
    monkeypatch.setattr(mods["gate"], "process", gate)
    monkeypatch.setattr(mods["extract"], "process", lambda e, r, earlier, ctx: [_swap(e.email_id, c) for c in claims])
    monkeypatch.setattr(mods["analyze"], "process", analyze)
    def inputs(*args: Any) -> None:
        opts["validate_seed"] = args[3]

    monkeypatch.setattr(mods["validate"], "ValidationInputs", inputs)
    monkeypatch.setattr(mods["validate"], "process", lambda s, ctx, inputs: s)
    def merge(ss: list[Suggestion], ctx: RunContext, results: list[EmailResult], seed: Any) -> list[Suggestion]:
        opts["merge_seed"], opts["merge_results"] = seed, results
        return [s.model_copy(update={"id": "MSFT.p1.supports"}) for s in ss]

    monkeypatch.setattr(mods["merge"], "process", merge)
    return opts


# ---- Pages ----

GET_ROUTES = [
    "/", "/suggestion/MSFT.p1.supports", "/suggestion/AMZN.new1", "/suggestion/NVDA.p2.supports",
    "/suggestion/AAPL.p1.supports", "/suggestion/fixture_001.s2", *(f"/company/{t}" for t in config.TICKERS),
    "/criteria", *(f"/criteria/{label}" for label in config.CRITERIA_FILES), "/audit", "/inbox", "/attention",
    "/attention?view=calendar", "/book", "/review", "/review/MSFT.p1.supports", "/research-log/NVDA",
    *(f"/email/{i}" for i in CORPUS), "/live", "/eval", "/monitor",
]


def assert_no_quarantined_body(text: str) -> None:
    for eid in QUARANTINED:
        for body in (CORPUS[eid].body,):
            words = body.split()
            for i in range(0, max(1, len(words) - 6), 4):
                chunk = " ".join(words[i:i + 6])
                assert chunk not in text and html.escape(chunk) not in text, f"{eid} body leaked: {chunk!r}"
    assert SECRET not in text


def test_every_page_answers_with_banner_and_no_quarantined_body(client: TestClient) -> None:
    for url in GET_ROUTES:
        r = client.get(url)
        assert r.status_code == 200, url
        assert BANNER in r.text, url
        assert_no_quarantined_body(r.text)


def test_unknown_items_404_as_html_with_banner(client: TestClient) -> None:
    for url in ("/suggestion/NOPE", "/company/TSLA", "/criteria/nope", "/email/nope", "/no/such/page"):
        r = client.get(url)
        assert r.status_code == 404 and r.headers["content-type"].startswith("text/html"), url
        assert BANNER in r.text and "Not found" in r.text, url


def test_attention_tab_shows_requester_offer_deadline_and_tags(client: TestClient) -> None:
    text = client.get("/attention").text
    email = CORPUS["fixture_007"]
    note = next(n for n in read_list(OUT / "notes.json", AttentionNote) if n.email_id == "fixture_007")
    result = RESULTS["fixture_007"]
    card = text[text.index('id="req-fixture_007"'):]
    card = card[:card.index("</article>")]
    assert str(escape(email.sender.split(",")[0])) in card                       # who is asking
    assert str(escape(labels.split_summary(note.summary)[0])) in card            # the offer
    assert card.index("Reply by Today, 4:00 PM") < card.index("req-offer")       # due beside the name
    for t in result.affected_tickers:
        assert f'href="/company/{t}">{t}</a>' in card                            # relevance tags
    assert "/attention" in client.get("/").text                                  # reachable from the brief

def test_book_lists_every_position_with_open_suggestions(client: TestClient) -> None:
    text = client.get("/book").text
    for t in config.TICKERS:
        assert f'href="/company/{t}"' in text
    assert 'href="/review/MSFT.p1.supports"' in text   # an open suggestion, on its pillar


def test_review_queue_walks_open_suggestions_and_counts_decisions(client: TestClient) -> None:
    first = client.get("/review").text
    assert "0 of " in first and 'data-next-open="/review/' in first
    assert client.post("/suggestion/MSFT.p1.supports/accept", headers=HX).status_code == 200
    after = client.get("/review").text
    assert "1 of " in after and 'aria-current="true"' in after
    assert client.get("/review/NOPE").status_code == 404


def test_attention_calendar_puts_requests_on_their_due_day(client: TestClient) -> None:
    text = client.get("/attention?view=calendar").text
    assert 'class="cal-day today"' in text and 'href="/email/fixture_007"' in text and "Calendar" in text


def test_scores_sit_behind_view_scores_and_the_classifier_is_unnamed(client: TestClient) -> None:
    for url in GET_ROUTES:
        assert "Jev" not in client.get(url).text, url
    text = client.get("/email/fixture_001").text
    panel = text.index('<details class="scores')
    assert "View scores" in text[panel:]
    for score in ("Signal score", "Decision record", f"{RESULTS['fixture_001'].signal_score:.2f}"):
        assert score in text[panel:] and score not in text[:panel], score


def test_manual_pillar_editing_from_the_company_page(client: TestClient) -> None:
    page = client.get("/company/AAPL").text
    assert 'action="/company/AAPL/pillars"' in page and 'action="/pillar/AAPL.p1/edit"' in page
    r = client.post("/company/AAPL/pillars", headers=HX,
                    data={"statement": "Enterprise demand grows on AI features.", "driver_ids": ["AAPL.other_products_growth"]})
    assert r.status_code == 200 and "Added AAPL pillar 4." in r.text
    r = client.post("/pillar/AAPL.p1/edit", headers=HX, data={"statement": "The upgrade cycle disappoints."})
    assert r.status_code == 200 and "Saved AAPL pillar 1." in r.text
    assert client.post("/pillar/AAPL.p2/evidence", headers=HX, data={"stance": "contradicts", "strength": "2"}).status_code == 200
    assert client.post("/pillar/AAPL.p3/remove", headers=HX).status_code == 200
    page = client.get("/company/AAPL").text
    assert "Enterprise demand grows on AI features." in page and "The upgrade cycle disappoints." in page
    assert "added by hand" in page and 'id="pillar-AAPL-p3"' not in page
    assert "Pillar removed" in page and "Pillar edited" in page
    bad = client.post("/company/AAPL/pillars", headers=HX, data={"statement": "  "})
    assert bad.status_code == 422
    p2 = next(p for t in load_seed().theses for p in t.pillars if p.id == "AAPL.p2")
    same = client.post("/pillar/AAPL.p2/edit", headers=HX, data={"statement": p2.statement, "driver_ids": p2.driver_ids})
    assert same.status_code == 200 and "No changes to save." in same.text and "HX-Refresh" not in same.headers


def test_book_shows_dollars_shares_logos_and_research_log(client: TestClient) -> None:
    text = client.get("/book").text
    assert "bps" not in text and 'class="num">Shares</th>' in text and "$30.0m" in text   # NVDA: 300 bps of $1bn
    assert "/static/logos/NVDA.svg" in text and 'href="/research-log/NVDA"' in text
    assert "Conviction</th>" not in text
    log = client.get("/research-log/NVDA").text
    assert "Full research log" in log and "Not connected yet" in log
    assert client.get("/research-log/TSLA").status_code == 404


def test_criteria_are_grouped_with_safety_separate_and_editing_marked_as_example(client: TestClient) -> None:
    text = client.get("/criteria").text
    for section in ("Email categories", "Attention required", "Topics and companies", "<b>Safety</b>"):
        assert section in text, section
    assert text.index("Email categories") < text.index('id="safety"')
    assert "not saved" in text and "Read-only" in text and "Possible MNPI" in text
    one = client.get("/criteria/thesis_relevant").text
    assert "data-crit-editor" in one and "Definition (fixed)" in one and "not saved" in one
    assert 'hx-post="/criteria' not in one   # editing never reaches the server


def test_requests_can_be_responded_to_or_rejected_and_restored(client: TestClient) -> None:
    assert 'action="/attention/fixture_007/respond"' in client.get("/attention").text
    r = client.post("/attention/fixture_007/respond", headers=HX)
    assert r.status_code == 200 and "Responded" in r.text and "no email was sent" in r.text
    page = client.get("/attention").text
    assert "Handled this session" in page and 'action="/attention/fixture_007/respond"' not in page
    assert "/email/fixture_007" not in client.get("/").text.split("Needs your attention")[1].split("</details>")[0]
    assert client.post("/attention/fixture_007/restore", headers=HX).status_code == 200
    assert 'action="/attention/fixture_007/respond"' in client.get("/attention").text
    assert client.post("/attention/fixture_007/reject", headers=HX).status_code == 200
    assert client.post("/attention/fixture_007/send", headers=HX).status_code == 404


def test_requests_order_by_time_or_relevance_and_filter_by_ticker(client: TestClient) -> None:
    for sort, heading in (("time", "Requests by deadline"), ("relevance", "Most relevant first")):
        text = client.get(f"/attention?sort={sort}").text
        assert heading in text and 'href="/attention?sort=relevance"' in text
        assert "Attention 0." not in text
    text = client.get("/attention").text
    assert "sort=tickers" not in text and 'aria-label="Filter by ticker"' in text
    tickers = " ".join(RESULTS["fixture_007"].affected_tickers)
    assert re.search(r'id="req-fixture_007"\s+data-keys="[a-z]+ ' + re.escape(tickers) + '"', text)   # filterable by ticker
    assert "Requested by" not in text and "Received " not in text


def test_inbox_tab_follows_the_brief_and_book_shows_street_view(client: TestClient) -> None:
    text = client.get("/").text
    nav = text[text.index('class="tabs"'):text.index("</nav>")]
    assert nav.index("Morning Brief") < nav.index("Inbox") < nav.index("Review")
    book = client.get("/book").text
    thesis = next(t for t in load_seed().theses if t.ticker == "MSFT")
    assert "Analyst rating</th>" in book and f'class="rating {thesis.street_view}"' in book
    assert "Street target</th>" in book
    if thesis.street_target_price is not None:
        assert f"${thesis.street_target_price:,.0f}" in book
    company = client.get("/company/MSFT").text
    assert "Suggested rating changes" in company and "Street target" in company
    if thesis.summary:
        assert str(escape(thesis.summary)) in company

def test_inbox_orders_by_time_or_relevance_and_filters_by_tags(client: TestClient) -> None:
    def ids(text: str) -> list[str]:
        return re.findall(r'id="row-(fixture_\d+)"', text)
    by_time = client.get("/inbox").text
    assert 'class="stat"' not in by_time and 'href="/inbox?sort=relevance"' in by_time
    assert "sort=ticker" not in by_time and "sort=topic" not in by_time
    received = sorted(CORPUS.values(), key=lambda e: e.received_at)
    assert ids(by_time) == [e.email_id for e in received]                           # time received
    relevance = ids(client.get("/inbox?sort=relevance").text)
    scores = [RESULTS[i].signal_score for i in relevance]
    assert scores == sorted(scores, reverse=True) and sorted(relevance) == sorted(CORPUS)
    assert "0.9" not in client.get("/inbox?sort=relevance").text.split('class="list"')[1].split("</section>")[0]
    # Tags: the search bar knows them, and each row carries its tickers and topics as filter keys.
    assert "data-taginput" in by_time and 'data-add-tag="AAPL"' in by_time and "Actionable" in by_time
    r = RESULTS["fixture_001"]
    row = by_time[by_time.index('id="row-fixture_001"') - 300:by_time.index('id="row-fixture_001"') + 200]
    for key in [*r.affected_tickers, *r.additional_labels]:
        assert key in row

def test_projection_changes_render_and_accept(tmp_path: Path, presets: Path) -> None:
    """A projection change (an email's figure against the book's) shows in the brief, the review queue
    and the book, and accepting one on a driver updates that assumption."""
    out = tmp_path / "out"
    shutil.copytree(OUT, out)
    model = next(m for m in load_seed().models if m.ticker == "MSFT")
    driver = next(d for d in model.drivers if d.id == "MSFT.intelligent_cloud_growth")
    stated = min(driver.max, driver.analyst + 2.0)
    proj = Suggestion(
        id="MSFT.intelligent_cloud_growth.proj1",
        body=ProjectionChange(kind="projection_change", ticker="MSFT", metric=driver.id, period=model.fiscal_year,
                              stated_value=stated, book_value=driver.analyst, consensus_value=driver.consensus),
        rationale="Reseller checks put Azure growth above the book's assumption.", claim_ids=[],
        sections=[], status="open")
    suggestions = json.loads((out / "suggestions.json").read_text()) + [proj.model_dump(mode="json")]
    (out / "suggestions.json").write_text(json.dumps(suggestions))
    brief = json.loads((out / "brief.json").read_text())
    brief["projection_changes"] = [proj.id]
    (out / "brief.json").write_text(json.dumps(brief))
    with TestClient(create_app(out, make_ctx=fake_ctx, presets_dir=presets, emails_path=FIXTURE_EMAILS)) as c:
        assert "Projection changes" in c.get("/").text and f"/suggestion/{proj.id}" in c.get("/").text
        detail = c.get(f"/suggestion/{proj.id}").text
        assert f"Update MSFT {driver.label} to {stated:,.1f}%" in detail and "EPS and target price recompute" in detail
        assert "Consensus <b>" in detail and "Gap " in detail
        assert f'href="/review/{proj.id}"' in c.get("/book").text
        assert proj.id in c.get("/review").text
        r = c.post(f"/suggestion/{proj.id}/accept", headers=HX)
        assert r.status_code == 200 and "Accepted" in r.text
        assert f'value="{stated}"' in c.get("/company/MSFT").text   # the assumption took the stated figure


def test_suggestion_explains_impact_and_what_accepting_means(tmp_path: Path, presets: Path) -> None:
    if "assumption_impact" not in ExistingThesis.model_fields:
        pytest.skip("ExistingThesis.assumption_impact / if_accepted arrive with the analysis-upgrade merge")
    out = tmp_path / "out"
    shutil.copytree(OUT, out)
    rows = json.loads((out / "suggestions.json").read_text())
    row = next(r for r in rows if r["id"] == "MSFT.p1.supports")
    row["body"]["assumption_impact"] = "Reseller checks show Azure consumption running ahead of the book's assumption."
    row["body"]["if_accepted"] = "The evidence is logged against MSFT pillar 1 and the Azure view holds more firmly."
    (out / "suggestions.json").write_text(json.dumps(rows))
    with TestClient(create_app(out, make_ctx=fake_ctx, presets_dir=presets, emails_path=FIXTURE_EMAILS)) as c:
        page = c.get("/suggestion/MSFT.p1.supports").text
        assert "Reseller checks show Azure consumption" in page and "If you accept" in page
        assert "The evidence is logged against MSFT pillar 1" in page
        assert "Reseller checks show Azure consumption" in c.get("/").text   # on the brief's card too


def test_suggestion_states_the_change_plainly(client: TestClient) -> None:
    text = client.get("/suggestion/MSFT.p1.supports").text
    assert "Log supporting evidence on MSFT pillar 1" in text and "What changes if you accept" in text
    assert "strength" in text and "Reasoning" in text
    for gone in ("Suggested change", "Recommendation only", "Why the model suggests it", "Verify against filings"):
        assert gone not in text, gone
    new = client.get("/suggestion/AMZN.new1").text
    assert "Add a new pillar to AMZN" in new and "The pillar is added to the AMZN thesis" in new


def test_eval_explains_measures_collapses_detail_and_shows_example_feedback(client: TestClient) -> None:
    text = client.get("/eval").text
    assert 'Misses <span class="badge">' not in text and "<th>Expected</th>" not in text   # no misses list
    feedback = text.split("Analyst feedback on labels")[1]
    assert "/email/fixture_" in feedback or "No misclassified emails" in feedback
    assert labels.MEASURE_EXPLAINERS["gate_recall"] in text
    assert '<details class="panel collapsed-section">' in text and "All measures" in text and "Confusion table" in text
    assert "Analyst feedback on labels" in text and "Example" in text and "isn't connected yet" in text
    assert "Target " not in text   # targets colour the values; they are not printed
    assert "<details class=\"panel\" open>" not in client.get("/criteria").text


def test_brief_lists_every_section(client: TestClient) -> None:
    text = client.get("/").text
    for heading in ("Suggested thesis changes", "New thesis candidates", "Worth watching", "Needs your attention",
                    "Relevant with no link to your book", "Alerts"):
        assert heading in text
    for sid in ("MSFT.p1.supports", "AAPL.p1.supports", "AMZN.new1", "NVDA.p2.supports"):
        assert f"/suggestion/{sid}" in text
    assert "Second look" in text and "/email/fixture_007" in text


def test_audit_and_quarantine_list(client: TestClient) -> None:
    text = client.get("/audit").text
    for eid in ("fixture_006", "fixture_010"):
        assert f'id="audit-{eid}"' in text
    assert "Repeat of" in text and "fixture_005" in text
    assert "Quote mismatch" in text  # the rejected suggestion, under its email
    for eid in QUARANTINED:
        assert html.escape(CORPUS[eid].subject) in text and html.escape(CORPUS[eid].sender) in text


def test_email_view_highlights_quotes(client: TestClient) -> None:
    text = client.get("/email/fixture_001").text
    assert "<mark" in text and "Our checks with four Azure resellers" in text
    q = client.get("/email/fixture_003").text
    assert "Quarantined" in q and CORPUS["fixture_003"].subject in q


def test_suggestion_page_shows_figure_book_consensus_and_effect(client: TestClient) -> None:
    text = client.get("/suggestion/MSFT.p1.supports").text
    assert "26.0" in text and "21.5" in text and "24.0" in text
    assert "EPS" in text and "target price" in text
    assert eps_text("MSFT", {"MSFT.intelligent_cloud_growth": 26.0}) in text


def test_eval_shows_pending_reviews(client: TestClient) -> None:
    text = client.get("/eval").text
    assert text.count("Pending hand review") == 3 and "Gate recall" in text


def test_monitor_shows_stages_and_models_only(client: TestClient) -> None:
    text = client.get("/monitor").text
    metrics = json.loads((OUT / "metrics.json").read_text())
    for stage in metrics["stages"]:
        assert f"<td>{labels.stage(stage)}</td>" in text
    for model in metrics["by_model"]:
        assert model in text
    assert "Costliest emails" not in text and "Slowest emails" not in text and "/email/fixture_" not in text


# ---- Build step 5: accept, update, reset, undo ----

def test_accept_logs_evidence(client: TestClient) -> None:
    r = client.post("/suggestion/MSFT.p1.supports/accept", headers=HX)
    assert r.status_code == 200 and "Accepted" in r.text and "Logged as evidence on MSFT.p1" in r.text
    company = client.get("/company/MSFT").text
    assert "Supports</span> Strength 2" in company and "Evidence logged" in company
    assert client.post("/suggestion/MSFT.p1.supports/accept", headers=HX).status_code == 409


def test_accept_new_thesis_adds_pillar(client: TestClient) -> None:
    r = client.post("/suggestion/AMZN.new1/edit", headers=HX,
                    data={"statement": "Edited AMZN pillar statement.", "wrong_if": ""})
    assert r.status_code == 200 and "AMZN.p4" in r.text
    assert "Edited AMZN pillar statement." in client.get("/company/AMZN").text


def test_update_assumption_changes_eps_on_the_page(client: TestClient) -> None:
    before = eps_cells(client.get("/company/MSFT").text)
    assert before[0] == eps_text("MSFT")
    r = client.post("/driver/MSFT.intelligent_cloud_growth", headers=HX,
                    data={"value": "26", "suggestion_id": "MSFT.p1.supports"})
    new_eps = eps_text("MSFT", {"MSFT.intelligent_cloud_growth": 26.0})
    assert r.status_code == 200 and new_eps in r.text and new_eps != before[0]
    after = eps_cells(client.get("/company/MSFT").text)
    assert after[0] == new_eps and after[1] == before[1]  # consensus unchanged
    assert client.post("/driver/MSFT.intelligent_cloud_growth", headers=HX, data={"value": "9999"}).status_code == 422


def test_reset_restores_the_seed(client: TestClient) -> None:
    seed_page = client.get("/company/MSFT").text
    client.post("/suggestion/MSFT.p1.supports/accept", headers=HX)
    client.post("/driver/MSFT.intelligent_cloud_growth", headers=HX, data={"value": "26"})
    assert eps_cells(client.get("/company/MSFT").text) != eps_cells(seed_page)
    r = client.post("/reset", headers=HX)
    assert r.status_code == 200 and r.headers.get("HX-Refresh") == "true"
    page = client.get("/company/MSFT").text
    assert eps_cells(page) == eps_cells(seed_page) and "No changes in this session." in page


def test_undo_reverses_the_last_change(client: TestClient) -> None:
    seed_eps = eps_cells(client.get("/company/MSFT").text)
    client.post("/suggestion/MSFT.p1.supports/accept", headers=HX)
    client.post("/driver/MSFT.intelligent_cloud_growth", headers=HX, data={"value": "26"})
    assert client.post("/undo", headers=HX).status_code == 200
    page = client.get("/company/MSFT").text
    assert eps_cells(page) == seed_eps and "Supports</span> Strength 2" in page
    client.post("/undo", headers=HX)
    assert "No accepted evidence yet" in client.get("/company/MSFT").text
    assert "Nothing to undo" in client.post("/undo", headers=HX).text


def test_dismiss_and_sessions_are_separate(client: TestClient, presets: Path) -> None:
    r = client.post("/suggestion/NVDA.p2.supports/dismiss", headers=HX)
    assert r.status_code == 200 and "Dismissed" in r.text
    assert "Dismissed suggestions" in client.get("/company/NVDA").text
    client.post("/suggestion/MSFT.p1.supports/accept", headers=HX)
    with TestClient(create_app(OUT, make_ctx=fake_ctx, presets_dir=presets)) as other:
        assert "No changes in this session." in other.get("/company/MSFT").text


def test_post_without_htmx_redirects(client: TestClient) -> None:
    r = client.post("/suggestion/NVDA.p2.supports/dismiss", follow_redirects=False,
                    headers={"referer": "/suggestion/NVDA.p2.supports"})
    assert r.status_code == 303 and r.headers["location"] == "/suggestion/NVDA.p2.supports"


def test_conviction_review_and_set_conviction(client: TestClient) -> None:
    app = app_of(client)
    # Two contradicting suggestions of strength 2 on one pillar cross the threshold of 4.
    sugg = {s.id: s for s in read_list(OUT / "suggestions.json", Suggestion)}
    base = sugg["MSFT.p1.supports"]
    store = app.state.store
    data = store.get()
    for n in (1, 2):
        s = base.model_copy(update={"id": f"MSFT.p1.contradicts{n}", "body": base.body.model_copy(
            update={"stance": "contradicts", "assumptions": []})})
        data.suggestions[s.id] = s
    client.post("/suggestion/MSFT.p1.contradicts1/accept", headers=HX)
    r = client.post("/suggestion/MSFT.p1.contradicts2/accept", headers=HX)
    assert "Conviction review raised" in r.text and "MSFT.p1.review" in r.text
    brief = client.get("/").text
    assert "Conviction review" in brief and brief.index("MSFT.p1.review") < brief.index("fixture_007")
    assert client.get("/suggestion/MSFT.p1.review").status_code == 200
    r = client.post("/conviction/MSFT", headers=HX, data={"conviction": "2", "suggestion_id": "MSFT.p1.review"})
    assert r.status_code == 200 and "from 3 to 2" in r.text
    for url in ("/company/MSFT", "/book"):   # no conviction in the book's UI (seed prose may mention it)
        page = client.get(url).text
        assert "Set conviction" not in page and ">Conviction<" not in page and "Conviction changed" not in page
        assert "Conviction " not in re.sub(r'<p class="(thesis-summary|small)[^"]*"[^>]*>.*?</p>', "", page, flags=re.S)
    assert "MSFT.p1.review" not in client.get("/").text
    assert client.post("/conviction/MSFT", headers=HX, data={"conviction": "9"}).status_code == 422


# ---- Verify, "this mattered" and live ----

def test_verify_not_available(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "triage_app.modules.verify_agent", None)
    r = client.post("/suggestion/MSFT.p1.supports/verify", headers=HX)
    assert r.status_code == 200 and "not available yet" in r.text


def test_verify_with_fake_agent(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, Any] = {}

    def verify(suggestion: Suggestion, log: list[Any], ctx: RunContext, claims: list[Claim]) -> VerifyResult:
        seen["id"], seen["log"], seen["claims"] = suggestion.id, list(log), [c.id for c in claims]
        return VerifyResult(suggestion_id=suggestion.id, verdict="not_found", explanation="No filing passage found.",
                            sources=[])

    from triage_app.modules import verify_agent
    monkeypatch.setattr(verify_agent, "verify", verify)
    client.post("/suggestion/MSFT.p1.supports/accept", headers=HX)
    r = client.post("/suggestion/MSFT.p1.supports/verify", headers=HX)
    assert r.status_code == 200 and "Not found" in r.text and "No filing passage found." in r.text
    assert seen["id"] == "MSFT.p1.supports" and len(seen["log"]) == 1
    assert seen["claims"] == ["fixture_001.c1", "fixture_001.c2"]
    assert "/verify" not in client.get("/suggestion/MSFT.p1.supports").text   # the button is no longer shown


def test_mattered_not_available(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    from triage_app.pipeline import extract

    def unbuilt(*_: Any) -> Any:
        raise NotImplementedError

    monkeypatch.setattr(extract, "process", unbuilt)
    r = client.post("/audit/fixture_010/mattered", headers=HX)
    assert r.status_code == 200 and "Not available yet" in r.text


def test_mattered_with_fakes(client: TestClient, fake_stages: dict[str, Any]) -> None:
    r = client.post("/audit/fixture_010/mattered", headers=HX)
    assert r.status_code == 200 and "Extract claims" in r.text and "fixture_010.MSFT.p1.supports" in r.text
    assert "/suggestion/fixture_010.MSFT.p1.supports" in client.get("/").text
    assert client.post("/audit/fixture_003/mattered", headers=HX).status_code == 403
    assert client.post("/audit/fixture_001/mattered", headers=HX).status_code == 409


def test_live_with_fakes_traces_every_stage(client: TestClient, fake_stages: dict[str, Any]) -> None:
    body = CORPUS["fixture_001"].body
    r = client.post("/live", headers=HX, data={"sender": "A", "subject": "Live check", "body": body})
    assert r.status_code == 200
    for stage in ("redundancy", "classify", "gate", "human_attention", "extract", "analyze", "validate", "merge"):
        assert f'<span class="step-name">{labels.stage(stage)}</span>' in r.text
    assert "<td>parse</td>" not in r.text and "<td>Parse</td>" not in r.text
    assert "100" in r.text  # FakeChat's input tokens, shown beside a stage
    sid = re.search(r"/suggestion/(live_\d+\.MSFT\.p1\.supports)", r.text)
    assert sid is not None
    assert client.get(f"/suggestion/{sid.group(1)}").status_code == 200
    assert f"/suggestion/{sid.group(1)}" in client.get("/").text
    assert client.post(f"/suggestion/{sid.group(1)}/accept", headers=HX).status_code == 200
    full = client.post("/live", data={"preset": "preset_01"})
    assert full.status_code == 200 and BANNER in full.text and "Trace" in full.text


def test_live_unbuilt_stages_answer(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    from triage_app.pipeline import classify

    def unbuilt(*_: Any) -> Any:
        raise NotImplementedError

    monkeypatch.setattr(classify, "process", unbuilt)
    r = client.post("/live", headers=HX, data={"preset": "preset_01"})
    assert r.status_code == 200 and "Not available yet" in r.text


def test_live_quarantine_never_shows_body(client: TestClient, fake_stages: dict[str, Any]) -> None:
    fake_stages["quarantine"] = True
    r = client.post("/live", headers=HX, data={"sender": "B", "subject": "Odd note", "body": SECRET})
    assert r.status_code == 200 and "Quarantined" in r.text
    assert_no_quarantined_body(r.text)
    eid = re.search(r"(live_\d+)", r.text)
    assert eid is not None
    page = client.get(f"/email/{eid.group(1)}")
    assert page.status_code == 200 and "Odd note" in page.text
    for url in ("/", "/audit", "/inbox", f"/email/{eid.group(1)}"):
        assert_no_quarantined_body(client.get(url).text)


def test_live_input_cap_and_app_wide_limit(client: TestClient, fake_stages: dict[str, Any],
                                           monkeypatch: pytest.MonkeyPatch) -> None:
    big = "x" * (thresholds.LIVE_INPUT_CAP_CHARS + 1)
    assert client.post("/live", headers=HX, data={"body": big}).status_code == 413
    assert client.post("/live", headers=HX, data={"body": ""}).status_code == 422
    # No per-visitor limit: one session can run more than the old five an hour.
    codes = [client.post("/live", headers=HX, data={"body": f"note {i}"}).status_code for i in range(8)]
    assert codes == [200] * 8
    assert "left this hour" not in client.get("/live").text
    # The app-wide cap still applies, to pastes, cold presets and "this mattered" alike.
    monkeypatch.setattr(thresholds, "LIVE_RUNS_PER_HOUR_GLOBAL", 8)
    assert client.post("/live", headers=HX, data={"body": "again"}).status_code == 429
    assert client.post("/live", headers=HX, data={"preset": "preset_01"}).status_code == 429
    assert client.post("/audit/fixture_010/mattered", headers=HX).status_code == 429
    client.post("/reset", headers=HX)   # reset does not lift it
    assert client.post("/live", headers=HX, data={"body": "again"}).status_code == 429

def test_responses_never_hold_quarantined_bodies_after_actions(client: TestClient, fake_stages: dict[str, Any]) -> None:
    responses: list[Any] = [
        client.post("/suggestion/MSFT.p1.supports/accept", headers=HX),
        client.post("/audit/fixture_010/mattered", headers=HX),
        client.post("/live", headers=HX, data={"preset": "preset_01"}),
        *(client.get(u) for u in GET_ROUTES),
    ]
    for r in responses:
        assert_no_quarantined_body(r.text)


def test_sections_from_quarantined_emails_are_dropped(client: TestClient) -> None:
    data = app_of(client).state.store.get()
    s = data.suggestions["MSFT.p1.supports"]
    leak = LinkedSection(email_id="fixture_004", quote=" ".join(CORPUS["fixture_004"].body.split()[:8]))
    data.suggestions["MSFT.p1.supports"] = s.model_copy(update={"sections": [*s.sections, leak]})
    for url in ("/", "/suggestion/MSFT.p1.supports", "/email/fixture_004"):
        assert_no_quarantined_body(client.get(url).text)


# ---- Review fixes: mattered override, global limit, sessions, folded book, audit repeats ----

def test_mattered_extracts_claims_from_a_stopped_email(presets: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """No stage is faked: the stopped email reaches the real extraction with the analyst's override."""
    monkeypatch.setenv("ANALYSIS_MODEL", "fake/analysis-model")
    quote = ("Sessions cover the final Basel standards, deposit insurance reform and the outlook for "
             "European bank consolidation.")
    replies = iter([json.dumps({"claims": [{"quote": quote, "tickers": [], "entities": ["European banks"],
                                            "kind": "reported_fact", "first_hand": True}]})])
    chat = FakeChat(lambda _messages: next(replies, "{}"))

    def ctx(recorder: Recorder) -> RunContext:
        return RunContext(None, recorder=recorder, use_cache=False, chat=chat, embedder=FakeEmbedder(), emails_path=FIXTURE_EMAILS)

    with TestClient(create_app(OUT, make_ctx=ctx, presets_dir=presets)) as c:
        assert RESULTS["fixture_010"].gate == "stop"
        r = c.post("/audit/fixture_010/mattered", headers=HX)
        assert r.status_code == 200
        assert re.search(r'data-step="extract">.*?<span class="step-name">Extract claims</span>\s*<span class="pill ok">Done</span>\s*<span class="step-detail">1 claim<', r.text, re.S)
        assert chat.calls and chat.calls[0]["namespace"] == "extract"
        step = r.text[r.text.index('data-step="extract"'):]
        step = step[:step.index("</li>")]
        assert str(escape(quote)) in step and "Model calls" in step and "First-hand" in step   # the claim, its call


def test_mattered_on_quarantined_spends_nothing(client: TestClient) -> None:
    assert client.post("/audit/fixture_003/mattered", headers=HX).status_code == 403
    assert app_of(client).state.global_runs.left() == thresholds.LIVE_RUNS_PER_HOUR_GLOBAL
    with pytest.raises(ValueError):
        runner.run_mattered(CORPUS["fixture_003"], RESULTS["fixture_003"], app_of(client).state.store.get(),
                            fake_ctx, load_seed(), [])


def test_day_cache_is_built_through_the_embedder_once(client: TestClient) -> None:
    data = app_of(client).state.store.get()
    embedder = FakeEmbedder()
    ctx = RunContext(None, use_cache=False, embedder=embedder)
    first = runner.day_cache(data, ctx)
    assert first.ids == [e.email_id for e in data.inbox] and len(first.ids) == 10
    first.add("live_001", "x", first.vectors[0])  # a run's own copy; the kept cache is unchanged
    again = runner.day_cache(data, RunContext(None, use_cache=False, embedder=FakeEmbedder()))
    assert len(again.ids) == 10


def test_emails_come_from_the_corpus_file(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from triage_app.web import data as web_data
    assert web_data.emails_file_for(config.OUT_DIR / "day_2") == config.corpus_file("day_2")
    assert web_data.emails_file_for(OUT) == FIXTURE_EMAILS
    monkeypatch.setenv("TRIAGE_EMAILS_FILE", str(tmp_path / "x.jsonl"))
    assert web_data.emails_file_for(OUT) == tmp_path / "x.jsonl"
    assert web_data.load_emails(tmp_path / "x.jsonl") == []


def test_email_page_shows_email_type(client: TestClient) -> None:
    assert "Primary research" in client.get("/email/fixture_001").text
    assert "Email type: News alert" in client.get("/audit").text  # fixture_006, in the audit view


def test_earlier_email_is_never_quarantined(client: TestClient) -> None:
    data = app_of(client).state.store.get()

    def record(nearest: str) -> RedundancyRecord:
        return RedundancyRecord(email_id="x", nearest=nearest, content_similarity=0.99, subject_score=0.9,
                                flagged=True)

    assert runner.earlier_email(record("fixture_004"), data) is None
    assert runner.earlier_email(record("fixture_005"), data) == CORPUS["fixture_005"]
    assert runner.earlier_email(record("fixture_005").model_copy(update={"flagged": False}), data) is None


def test_global_live_limit_ignores_cookies(client: TestClient, fake_stages: dict[str, Any],
                                           monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(thresholds, "LIVE_RUNS_PER_HOUR_GLOBAL", 2)
    codes = []
    for i in range(3):
        client.cookies.clear()  # a new visitor each time
        codes.append(client.post("/live", headers=HX, data={"body": f"note {i}"}).status_code)
    assert codes == [200, 200, 429]
    client.cookies.clear()
    r = client.post("/suggestion/MSFT.p1.supports/verify", headers=HX)
    assert r.status_code == 429 and "across all visitors" in r.text


def test_warm_preset_is_free(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    def cached_run(email: Email, *_: Any) -> runner.Trace:
        return runner.Trace(email_id=email.email_id, sender=email.sender, subject=email.subject,
                            steps=[runner.Step(name="classify", status="ok", calls=1, cache_hits=1)])

    monkeypatch.setattr(runner, "run_live", cached_run)
    for _ in range(7):
        assert client.post("/live", headers=HX, data={"preset": "preset_01"}).status_code == 200
    assert app_of(client).state.global_runs.left() == thresholds.LIVE_RUNS_PER_HOUR_GLOBAL


def test_sessions_are_evicted(monkeypatch: pytest.MonkeyPatch) -> None:
    from triage_app.web.session import SessionStore

    monkeypatch.setattr(thresholds, "MAX_SESSIONS", 2)
    store = SessionStore()
    a = store.get("a", now=0.0)
    store.get("b", now=1.0)
    assert store.get("a", now=2.0) is a  # touching "a" makes "b" the least recently used
    store.get("c", now=3.0)
    assert "b" not in store and "a" in store and len(store) == 2
    store.get("d", now=3.0 + thresholds.SESSION_IDLE_TTL_S + 1)
    assert list(("a" in store, "c" in store, "d" in store)) == [False, False, True]


def test_live_validates_against_the_visitors_book(client: TestClient, fake_stages: dict[str, Any]) -> None:
    client.post("/suggestion/AMZN.new1/accept", headers=HX)
    client.post("/audit/fixture_010/mattered", headers=HX)
    for key in ("validate_seed", "merge_seed"):
        pillars = [p.id for t in fake_stages[key].theses for p in t.pillars]
        assert "AMZN.p4" in pillars, key
    assert [r.gate for r in fake_stages["merge_results"]] == ["pass"]  # the analyst's override


def test_audit_shows_every_flagged_repeat(client: TestClient) -> None:
    data = app_of(client).state.store.get()
    data.redundancy["fixture_010"] = RedundancyRecord(
        email_id="fixture_010", nearest="fixture_004", content_similarity=0.81, subject_score=0.7, flagged=True)
    text = client.get("/audit").text
    assert "Flagged as a possible repeat of" in text and "0.81" in text and "0.70" in text
    assert html.escape(CORPUS["fixture_004"].subject) in text
    assert_no_quarantined_body(text)
