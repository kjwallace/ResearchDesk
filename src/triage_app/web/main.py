"""The web app: FastAPI + Jinja + HTMX, rendered on the server.

    TRIAGE_DATA_DIR=tests/fixtures/out uv run uvicorn triage_app.web.main:app

Every page is a GET that returns HTML. Every action is a POST that returns an HTMX fragment
and changes only the visitor's session (a POST without HTMX redirects back). Stage files are
read from `TRIAGE_DATA_DIR` (default `data/out/day_1`); the book is the seed plus the
session's change log, folded on every request and never stored. Every page carries the
synthetic-data banner. A quarantined email shows its sender and subject only, everywhere.
The app never sends mail and never writes to the book on disk.
"""

import hashlib
import itertools
import os
import secrets
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from collections.abc import Callable
from typing import Any, Literal

from fastapi import FastAPI, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.sessions import SessionMiddleware

from triage_app import config, thresholds
from triage_app.criteria import CriteriaError, parse_file, read_files
from triage_app.pipeline import deliver
from triage_app.schema import (
    AttentionNote, Brief, CompanyModel, LogEntry, ConvictionReview, Email, EmailResult, ExistingThesis, NewThesis,
    Suggestion, Thesis, TriageRecord,
)
from triage_app.state import apply
from triage_app.state.compute import Projection, compute, driver_values, project
from triage_app.state.fold import BookState, Seed, fold, load_seed, ticker_of
from triage_app.web import labels, runner
from triage_app.web.data import DataStore, DayData, data_dir_from_env, highlight, safe_sections
from triage_app.web.session import SESSION_KEY, GlobalRuns, SessionState, SessionStore

WEB_DIR = Path(__file__).resolve().parent
HTMX_URL = "https://unpkg.com/htmx.org@2.0.4/dist/htmx.min.js"
REVIEW_KEYS = ("note_review", "suggestion_review", "new_thesis_review")


@dataclass
class View:
    """Everything a page needs about one request: the set, the session and the folded book."""

    data: DayData
    sess: SessionState
    seed: Seed
    state: BookState

    # -- emails and results: the set's, plus what this session added --
    def email(self, email_id: str) -> Email | None:
        return self.data.emails.get(email_id) or self.sess.emails.get(email_id)

    def result(self, email_id: str) -> EmailResult | None:
        return self.data.results.get(email_id) or self.sess.results.get(email_id)

    def quarantined(self, email_id: str) -> bool:
        r = self.result(email_id)
        return r is not None and r.gate == "quarantine"

    # -- suggestions --
    def reviews(self) -> list[Suggestion]:
        return apply.conviction_reviews(self.seed, self.sess.log, self.sess.dismissed)

    def suggestions(self) -> dict[str, Suggestion]:
        out = {s.id: s for s in self.data.checked if s.status == "rejected"}
        out.update(self.data.suggestions)
        out.update(self.sess.suggestions)
        out.update({s.id: s for s in self.reviews()})
        return out

    def status(self, s: Suggestion) -> str:
        return apply.status_of(s, self.sess.log, self.sess.dismissed)

    def sections(self, s: Suggestion) -> list[Any]:
        return [x for x in safe_sections(s.sections, self.data) if not self.quarantined(x.email_id)]

    def all_monitor(self, s: Suggestion) -> bool:
        labels = {r.triage if (r := self.result(x.email_id)) else None for x in s.sections}
        return labels == {"monitor"}

    def ticker_of(self, s: Suggestion) -> str:
        b = s.body
        if isinstance(b, ExistingThesis):
            return b.pillar_id.split(".")[0]
        return b.ticker

    def pillar(self, pillar_id: str) -> Any:
        return next((p for t in self.state.theses.values() for p in t.pillars if p.id == pillar_id), None)

    def thesis(self, ticker: str) -> Thesis | None:
        return next((t for k, t in self.state.theses.items() if k == ticker), None)

    def model(self, ticker: str) -> CompanyModel | None:
        return next((m for k, m in self.state.models.items() if k == ticker), None)

    def driver(self, driver_id: str) -> Any:
        m = self.model(driver_id.split(".")[0])
        return next((d for d in m.drivers if d.id == driver_id), None) if m else None

    def seed_driver(self, driver_id: str) -> Any:
        return next((d for m in self.seed.models for d in m.drivers if d.id == driver_id), None)

    def effect(self, driver_id: str, value: float) -> dict[str, Projection] | None:
        """EPS and target price now, and if `driver_id` took `value`."""
        m = self.model(driver_id.split(".")[0])
        if m is None:
            return None
        now = driver_values(m, "analyst")
        return {"now": project(m, now), "if": project(m, {**now, driver_id: value})}

    def alerts(self, brief: Brief) -> list[dict[str, str]]:
        """Conviction reviews first, then the brief's alerts, within the day's budget."""
        out = [{"kind": "conviction_review", "ref_id": r.id} for r in self.reviews()]
        out += [{"kind": a.kind, "ref_id": a.ref_id} for a in brief.alerts]
        return out[:thresholds.ALERTS_PER_DAY]


@dataclass
class AttentionItem:
    """One email that needs a person, with what the Needs attention screen shows about it."""

    email: Email
    note: AttentionNote | None
    result: EmailResult | None
    triage: TriageRecord | None
    deadline: datetime | None
    kind: str          # meeting, event or other (labels.REQUEST_KINDS)
    bucket: str        # today, tomorrow, later or none (labels.DUE_BUCKETS)
    probability: float  # the classifier's human-attention probability (sorts; never shown)


def create_app(data_dir: Path | None = None, *, make_ctx: runner.ContextFactory | None = None,
               presets_dir: Path | None = None, emails_path: Path | None = None) -> FastAPI:
    app = FastAPI(title="Email triage (synthetic)", docs_url=None, redoc_url=None, openapi_url=None)
    app.add_middleware(
        SessionMiddleware, secret_key=os.environ.get("TRIAGE_SESSION_SECRET") or secrets.token_hex(32),
        session_cookie="triage_session", same_site="lax", max_age=None,
    )
    app.mount("/static", StaticFiles(directory=WEB_DIR / "static"), name="static")
    templates = Jinja2Templates(directory=WEB_DIR / "templates")
    templates.env.globals.update(HTMX_URL=HTMX_URL, highlight=highlight, config=config, thresholds=thresholds,
                                 ASSET_V=_asset_version())
    templates.env.filters["num"] = lambda v, d=1: "" if v is None else f"{v:,.{d}f}"
    templates.env.filters["pct"] = lambda v: "N/A" if v is None else f"{v * 100:.1f}%"
    templates.env.globals.update(labels=labels, position=labels.position)
    templates.env.filters.update(due=labels.due, human=labels.human, stage=labels.stage, measure=labels.measure,
                                 sentence=labels.sentence, prose=labels.prose, verdict=labels.verdict,
                                 ref=labels.pretty_id, money=labels.money)
    templates.env.filters["clock"] = _clock
    templates.env.filters["initials"] = _initials
    templates.env.filters["person"] = lambda s: s.split(",")[0].strip()
    templates.env.filters["org"] = lambda s: ", ".join(p.strip() for p in s.split(",")[1:])
    templates.env.filters["tone"] = lambda s: f"t{sum(map(ord, s)) % 4}"

    store = DataStore(data_dir or data_dir_from_env(), emails_path)
    sessions = SessionStore()
    seed = load_seed()
    ctx_factory = make_ctx or runner.default_context
    live_ids = itertools.count(1)
    global_runs = GlobalRuns()
    warm_presets: set[str] = set()  # presets whose last run was served wholly from the cache
    app.state.global_runs = global_runs
    app.state.store, app.state.sessions, app.state.seed = store, sessions, seed
    app.state.presets_dir = presets_dir or config.LIVE_PRESETS_DIR

    @app.exception_handler(StarletteHTTPException)
    def http_error(request: Request, exc: StarletteHTTPException) -> Response:
        """Errors render as a page with the synthetic banner, not as JSON."""
        return templates.TemplateResponse(request, "error.html", {"status": exc.status_code, "detail": exc.detail},
                                          status_code=exc.status_code)

    def view(request: Request) -> View:
        sid = request.session.get(SESSION_KEY)
        if not isinstance(sid, str):
            sid = sessions.new_id()
            request.session[SESSION_KEY] = sid
        sess = sessions.get(sid)
        return View(data=store.get(), sess=sess, seed=seed, state=fold(seed, sess.log))

    def page(request: Request, name: str, v: View, **ctx: Any) -> HTMLResponse:
        return templates.TemplateResponse(request, name, {"v": v, "now": datetime.now(UTC), **ctx})

    def fragment(request: Request, name: str, v: View, status_code: int = 200, **ctx: Any) -> Response:
        if request.headers.get("HX-Request") != "true":
            back = request.headers.get("referer") or "/"
            return RedirectResponse(back, status_code=303)
        return templates.TemplateResponse(request, name, {"v": v, **ctx}, status_code=status_code)

    def message(request: Request, v: View, text: str, *, ok: bool = True, refresh: bool = False,
                status_code: int = 200) -> Response:
        resp = fragment(request, "fragments/message.html", v, status_code=status_code, text=text, ok=ok)
        resp.headers["HX-Retarget"] = "#flash"
        resp.headers["HX-Reswap"] = "innerHTML"
        if refresh:
            resp.headers["HX-Refresh"] = "true"
        return resp

    def spend(v: View) -> str | None:
        """Take one live run from the session's and the process's hourly allowance; the reason when refused."""
        if v.sess.runs_left() <= 0:
            return f"This session has used its {thresholds.LIVE_RUNS_PER_HOUR} live runs for the hour."
        if not global_runs.take():
            return (f"The app has used its {thresholds.LIVE_RUNS_PER_HOUR_GLOBAL} live runs for the hour "
                    "across all visitors. Try again later.")
        v.sess.take_run()
        return None

    def refund(v: View) -> None:
        if v.sess.live_runs:
            v.sess.live_runs.pop()
        global_runs.refund()

    def brief_of(v: View) -> Brief:
        if v.data.brief is not None:
            return v.data.brief
        d = v.data
        day = d.inbox[0].received_at.date() if d.inbox else datetime.now(UTC).date()
        return deliver.assemble(day, d.inbox, list(d.results.values()), d.triage, list(d.notes.values()),
                                list(d.suggestions.values()), d.checked,
                                sizes={t.ticker: t.size_bps for t in seed.theses})

    def get_suggestion(v: View, sid: str) -> Suggestion:
        s = v.suggestions().get(sid)
        if s is None:
            raise HTTPException(404, f"There is no suggestion {sid}.")
        return s

    # ---------------- Pages ----------------

    @app.get("/", response_class=HTMLResponse)
    def brief_page(request: Request) -> HTMLResponse:
        v = view(request)
        brief = brief_of(v)
        sugg = v.suggestions()

        def grouped(ids: list[str]) -> list[list[Suggestion]]:
            """Opposite stances on one pillar show together as one card."""
            groups: dict[str, list[Suggestion]] = {}
            for i in ids:
                if i not in sugg:
                    continue
                s = sugg[i]
                key = s.body.pillar_id if isinstance(s.body, ExistingThesis) else s.id
                groups.setdefault(key, []).append(s)
            return list(groups.values())

        extras = list(v.sess.suggestions.values())
        return page(
            request, "brief.html", v, brief=brief, alerts=v.alerts(brief), reviews=v.reviews(),
            thesis_changes=grouped(brief.thesis_changes), new_theses=grouped(brief.new_theses),
            worth_watching=grouped(brief.worth_watching),
            extras=extras, sizes={t.ticker: t.size_bps for t in v.state.theses.values()},
        )

    def suggestion_context(v: View, s: Suggestion) -> dict[str, Any]:
        """What the suggestion detail needs: status, the opposite stance, linked quotes, verify."""
        b = s.body
        siblings = []
        if isinstance(b, ExistingThesis):
            other = f"{b.pillar_id}.{'contradicts' if b.stance == 'supports' else 'supports'}"
            siblings = [x for x in v.suggestions().values() if x.id == other]
        linked: dict[str, list[str]] = defaultdict(list)
        for x in v.sections(s):
            linked[x.email_id].append(x.quote)
        return {"s": s, "status": v.status(s), "siblings": siblings, "linked": dict(linked),
                "verify": v.sess.verify.get(s.id),
                "ticker": b.ticker if isinstance(b, (NewThesis, ConvictionReview)) else v.ticker_of(s)}

    @app.get("/suggestion/{sid}", response_class=HTMLResponse)
    def suggestion_page(request: Request, sid: str) -> HTMLResponse:
        v = view(request)
        return page(request, "suggestion.html", v, **suggestion_context(v, get_suggestion(v, sid)))

    def review_queue(v: View) -> list[Suggestion]:
        """Every suggestion for the analyst, in brief order: conviction reviews, thesis changes,
        new theses, worth watching, then what this session's live runs added."""
        brief = brief_of(v)
        sugg = v.suggestions()
        ids = [r.id for r in v.reviews()] + brief.thesis_changes + brief.new_theses + brief.worth_watching
        ids += [i for i in v.sess.suggestions if i not in ids]
        return [sugg[i] for i in dict.fromkeys(ids) if i in sugg]

    def review_page(request: Request, v: View, current: Suggestion | None) -> HTMLResponse:
        queue = review_queue(v)
        statuses = {s.id: v.status(s) for s in queue}
        ctx: dict[str, Any] = suggestion_context(v, current) if current else {}
        pos = next((i for i, s in enumerate(queue) if current and s.id == current.id), -1)
        after = queue[pos + 1:] + queue[:max(pos, 0)]
        nxt = next((s for s in after if statuses[s.id] == "open" and (current is None or s.id != current.id)), None)
        return page(request, "review.html", v, queue=queue, statuses=statuses, current=current,
                    prev=queue[pos - 1] if pos > 0 else None,
                    following=queue[pos + 1] if 0 <= pos < len(queue) - 1 else None, next_open=nxt,
                    decided=sum(st != "open" for st in statuses.values()),
                    sizes={t.ticker: t.size_bps for t in v.state.theses.values()}, **ctx)

    @app.get("/review", response_class=HTMLResponse)
    def review_start(request: Request) -> HTMLResponse:
        """The first open suggestion in brief order, or the summary when every one is decided."""
        v = view(request)
        first = next((s for s in review_queue(v) if v.status(s) == "open"), None)
        return review_page(request, v, first)

    @app.get("/review/{sid}", response_class=HTMLResponse)
    def review_item(request: Request, sid: str) -> HTMLResponse:
        v = view(request)
        return review_page(request, v, get_suggestion(v, sid))

    @app.get("/research-log/{ticker}", response_class=HTMLResponse)
    def research_log_page(request: Request, ticker: str) -> HTMLResponse:
        """A placeholder for the desk's full research log; it is not connected to anything."""
        v = view(request)
        if v.thesis(ticker) is None:
            raise HTTPException(404, f"There is no company {ticker} in the book.")
        return page(request, "research_log.html", v, ticker=ticker)

    @app.get("/book", response_class=HTMLResponse)
    def book_page(request: Request) -> HTMLResponse:
        """All five positions on one screen: stance, size, conviction, projections against
        consensus, accepted evidence and the open suggestions on each pillar."""
        v = view(request)
        open_by_pillar: dict[str, list[Suggestion]] = defaultdict(list)
        new_by_ticker: dict[str, list[Suggestion]] = defaultdict(list)
        for s in review_queue(v):
            if v.status(s) != "open":
                continue
            if isinstance(s.body, ExistingThesis):
                open_by_pillar[s.body.pillar_id].append(s)
            elif isinstance(s.body, NewThesis):
                new_by_ticker[s.body.ticker].append(s)
        rows = []
        for ticker in config.TICKERS:
            thesis, model = v.thesis(ticker), v.model(ticker)
            if thesis is None or model is None:
                continue
            rows.append({"ticker": ticker, "thesis": thesis, "model": model, "proj": compute(model),
                         "open": sum(len(open_by_pillar[p.id]) for p in thesis.pillars) + len(new_by_ticker[ticker])})
        return page(request, "book.html", v, rows=rows, open_by_pillar=dict(open_by_pillar),
                    new_by_ticker=dict(new_by_ticker), changes=len(v.sess.log))

    @app.get("/company/{ticker}", response_class=HTMLResponse)
    def company_page(request: Request, ticker: str) -> HTMLResponse:
        v = view(request)
        thesis, model = v.thesis(ticker), v.model(ticker)
        if thesis is None or model is None:
            raise HTTPException(404, f"There is no company {ticker} in the book.")
        seed_model = next(m for m in seed.models if m.ticker == ticker)
        history = [e for e in v.sess.log if (e.item_id == ticker or e.item_id.startswith(f"{ticker}."))
                   and e.change != "conviction_changed"]
        mine = [s for s in v.suggestions().values() if v.ticker_of(s) == ticker]
        return page(
            request, "company.html", v, ticker=ticker, thesis=thesis, model=model,
            projections={**compute(model), "seed": compute(seed_model)["analyst"]},
            history=list(reversed(history)), reviews=[r for r in v.reviews() if v.ticker_of(r) == ticker],
            dismissed=[s for s in mine if v.status(s) == "dismissed"],
            accepted=[s for s in mine if v.status(s) == "accepted"],
        )

    def criteria_context(label: str | None) -> dict[str, Any]:
        """Every criteria file parsed for the grouped overview, plus the fixed safety questions."""
        parsed: dict[str, Any] = {}
        errors: dict[str, str] = {}
        for name in config.CRITERIA_FILES:
            try:
                parsed[name] = parse_file(config.CRITERIA_DIR / f"{name}.md")
            except (CriteriaError, FileNotFoundError) as e:
                errors[name] = str(e)
        return {"files": _criteria_files(), "parsed_all": parsed, "errors": errors, "label": label,
                "parsed": parsed.get(label) if label else None, "error": errors.get(label) if label else None,
                "groups": labels.CRITERIA_GROUPS, "safety": _safety_questions(),
                "group_of": {n: g for g, _, _, names in labels.CRITERIA_GROUPS for n in names}}

    @app.get("/criteria", response_class=HTMLResponse)
    def criteria_page(request: Request) -> HTMLResponse:
        v = view(request)
        return page(request, "criteria.html", v, history=v.data.history, **criteria_context(None))

    @app.get("/criteria/{label}", response_class=HTMLResponse)
    def criteria_label(request: Request, label: str) -> HTMLResponse:
        v = view(request)
        if label not in config.CRITERIA_FILES:
            raise HTTPException(404, f"There is no criteria file named {label}.")
        return page(request, "criteria.html", v, history=v.data.history, **criteria_context(label))

    @app.get("/audit", response_class=HTMLResponse)
    def audit_page(request: Request) -> HTMLResponse:
        v = view(request)
        brief = brief_of(v)
        groups: dict[str, list[EmailResult]] = defaultdict(list)
        for eid in brief.audit:
            r = v.data.results.get(eid)
            if r is not None:
                groups[r.triage or "unlabeled"].append(r)
        by_earlier: dict[str, list[str]] = defaultdict(list)
        for r in v.data.results.values():
            if r.redundant_of:
                by_earlier[r.redundant_of].append(r.email_id)
        rejected: dict[str, list[Suggestion]] = defaultdict(list)
        for s in v.data.rejected():
            for eid in {x.email_id for x in s.sections}:
                if not v.quarantined(eid):
                    rejected[eid].append(s)
        quarantined = [v.data.results[e] for e in brief.quarantined if e in v.data.results]
        return page(request, "audit.html", v, groups=dict(groups), rejected=dict(rejected),
                    quarantined=quarantined, by_earlier=dict(by_earlier))

    @app.get("/attention", response_class=HTMLResponse)
    def attention_page(request: Request, view_mode: str = Query("list", alias="view"),
                       sort: str = Query("time")) -> HTMLResponse:
        """The brief's "needs your attention" list on its own screen: who is asking, what they
        offer, when a reply is due and what it bears on. Read-only; it adds no action."""
        v = view(request)
        brief = brief_of(v)
        ids = list(brief.needs_attention) + [e for e in v.sess.notes if e not in brief.needs_attention]
        items = []
        for eid in ids:
            email = v.email(eid)
            if email is None or v.quarantined(eid):
                continue
            note = v.data.notes.get(eid) or v.sess.notes.get(eid)
            triage = v.data.triage.get(eid)
            deadline = note.deadline.replace(tzinfo=None) if note and note.deadline else None
            items.append(AttentionItem(
                email=email, note=note, result=v.result(eid), triage=triage, deadline=deadline,
                kind=labels.request_kind(triage.email_type if triage else None),
                bucket=labels.due_bucket(deadline, brief.day),
                probability=triage.human_attention if triage else 0.0,
            ))
        # Time: soonest deadline first. Relevance: the classifier's attention score, which orders the
        # list and is never shown. A ticker filter on the page narrows either order.
        sort = sort if sort in ("time", "relevance") else "time"
        def by_time(i: AttentionItem) -> tuple[bool, datetime, float]:
            return (i.deadline is None, i.deadline or datetime.max, -i.probability)

        if sort == "relevance":
            items.sort(key=lambda i: (-i.probability, *by_time(i)))
        else:
            items.sort(key=by_time)
        handled = [i for i in items if i.email.email_id in v.sess.handled]
        items = [i for i in items if i.email.email_id not in v.sess.handled]
        # Calendar columns: the brief's day, then every day a reply is due, in order.
        days = sorted({brief.day} | {i.deadline.date() for i in items if i.deadline})
        return page(request, "attention.html", v, brief=brief, items=items, days=days, sort=sort, handled=handled,
                    mode="calendar" if view_mode == "calendar" else "list")

    @app.post("/attention/{email_id}/{outcome}")
    def handle_request(request: Request, email_id: str, outcome: str) -> Response:
        """Clear a request from the queue as responded or rejected. Nothing is sent: the app never sends mail."""
        v = view(request)
        if outcome not in ("respond", "reject", "restore"):
            raise HTTPException(404, f"There is no action {outcome}.")
        if v.email(email_id) is None:
            raise HTTPException(404, f"There is no email {email_id}.")
        if outcome == "restore":
            v.sess.handled.pop(email_id, None)
            return message(request, v, f"{labels.pretty_id(email_id)} is back in the queue.", refresh=True)
        v.sess.handled[email_id] = "responded" if outcome == "respond" else "rejected"
        return fragment(request, "fragments/handled.html", v, email=v.email(email_id),
                        outcome=v.sess.handled[email_id])

    @app.get("/inbox", response_class=HTMLResponse)
    def inbox_page(request: Request) -> HTMLResponse:
        v = view(request)
        return page(request, "inbox.html", v, emails=v.data.inbox)

    @app.get("/email/{email_id}", response_class=HTMLResponse)
    def email_page(request: Request, email_id: str) -> HTMLResponse:
        v = view(request)
        email = v.email(email_id)
        if email is None:
            raise HTTPException(404, f"There is no email {email_id}.")
        quarantined = v.quarantined(email_id)
        quotes: list[str] = [] if quarantined else v.data.quotes_for(email_id)
        if not quarantined:
            for s in v.sess.suggestions.values():
                quotes += [x.quote for x in s.sections if x.email_id == email_id]
            if (n := v.sess.notes.get(email_id)) is not None:
                quotes += [x.quote for x in n.sections]
        linked = [s for s in v.suggestions().values() if any(x.email_id == email_id for x in s.sections)]
        return page(
            request, "email.html", v, email=email, quarantined=quarantined, quotes=quotes,
            result=v.result(email_id), triage=v.data.triage.get(email_id),
            redundancy=v.data.redundancy.get(email_id), note=v.data.notes.get(email_id) or v.sess.notes.get(email_id),
            linked=linked, no_change=v.data.no_change_reason(email_id),
        )

    @app.get("/live", response_class=HTMLResponse)
    def live_page(request: Request) -> HTMLResponse:
        v = view(request)
        return page(request, "live.html", v, presets=runner.load_presets(app.state.presets_dir),
                    runs_left=v.sess.runs_left(), trace=None, error=None)

    @app.post("/live", response_class=HTMLResponse)
    def live_run(request: Request, preset: str = Form(""), sender: str = Form(""), sender_email: str = Form(""),
                 subject: str = Form(""), body: str = Form("")) -> Response:
        v = view(request)
        presets = {e.email_id: e for e in runner.load_presets(app.state.presets_dir)}

        def answer(trace: runner.Trace | None, error: str | None, code: int = 200) -> Response:
            ctx = {"trace": trace, "error": error, "runs_left": v.sess.runs_left()}
            if request.headers.get("HX-Request") == "true":
                return templates.TemplateResponse(request, "fragments/trace.html", {"v": v, **ctx}, status_code=code)
            return templates.TemplateResponse(
                request, "live.html", {"v": v, "now": datetime.now(UTC), "presets": list(presets.values()), **ctx},
                status_code=code)

        spent = False
        if preset:
            if preset not in presets:
                return answer(None, f"There is no preset {preset}.", 404)
            email = presets[preset]
            # A preset with a warm cache replays its results and is free; a cold one spends a run.
            if preset not in warm_presets:
                if (refused := spend(v)) is not None:
                    return answer(None, refused, 429)
                spent = True
        else:
            if not body.strip():
                return answer(None, "Paste an email body, or pick a preset.", 422)
            total = len(sender) + len(sender_email) + len(subject) + len(body)
            if total > thresholds.LIVE_INPUT_CAP_CHARS:
                return answer(None, f"The email is {total:,} characters; the cap is "
                                    f"{thresholds.LIVE_INPUT_CAP_CHARS:,}.", 413)
            if (refused := spend(v)) is not None:
                return answer(None, refused, 429)
            spent = True
            email = Email(email_id=f"live_{next(live_ids):03d}", received_at=datetime.now(UTC),
                          sender=sender.strip() or "Pasted email", sender_email=sender_email.strip() or "unknown",
                          subject=subject.strip() or "(no subject)", body=body)
        trace = runner.run_live(email, v.data, ctx_factory, seed, v.sess.log)
        totals = trace.totals
        if preset and totals.calls and totals.cache_hits == totals.calls:
            warm_presets.add(preset)
        if spent and (not totals.calls or (preset and preset in warm_presets)):
            refund(v)
        _join_session(v, email, trace)
        return answer(trace, None)

    @app.get("/eval", response_class=HTMLResponse)
    def eval_page(request: Request) -> HTMLResponse:
        v = view(request)
        ev = v.data.eval
        labels = sorted({k for row in ev.confusion.values() for k in row} | set(ev.confusion)) if ev else []
        return page(request, "eval.html", v, ev=ev, labels=labels, review_keys=REVIEW_KEYS)

    @app.get("/monitor", response_class=HTMLResponse)
    def monitor_page(request: Request) -> HTMLResponse:
        v = view(request)
        return page(request, "monitor.html", v, m=v.data.metrics)

    # ---------------- Actions ----------------

    def accept_and_report(request: Request, v: View, s: Suggestion, **edits: Any) -> Response:
        try:
            entry = apply.accept(seed, v.sess.log, s, **edits)
        except apply.ActionError as e:
            return message(request, v, str(e), ok=False, status_code=409)
        before = {r.id for r in v.reviews()}
        v.sess.log.append(entry)
        v.sess.dismissed.discard(s.id)
        raised = [r for r in apply.conviction_reviews(seed, v.sess.log, v.sess.dismissed) if r.id not in before]
        what = (f"Logged as evidence on {entry.item_id}" if entry.change == "pillar_evidence"
                else f"Added pillar {entry.item_id} to the book")
        return fragment(request, "fragments/status.html", v, s=s, status="accepted", text=what, raised=raised)

    @app.post("/suggestion/{sid}/accept")
    def accept_route(request: Request, sid: str) -> Response:
        v = view(request)
        return accept_and_report(request, v, get_suggestion(v, sid))

    @app.post("/suggestion/{sid}/edit")
    def edit_route(request: Request, sid: str, strength: int | None = Form(None),
                   statement: str = Form(""), wrong_if: str = Form("")) -> Response:
        v = view(request)
        s = get_suggestion(v, sid)
        edits: dict[str, Any] = {}
        if isinstance(s.body, ExistingThesis):
            if strength is not None:
                if strength not in (1, 2, 3):
                    return message(request, v, "Strength must be 1, 2 or 3.", ok=False, status_code=422)
                if v.all_monitor(s) and strength > 1:
                    return message(request, v, "Suggestions from monitor emails are capped at strength 1.",
                                   ok=False, status_code=422)
                edits["strength"] = strength
        elif isinstance(s.body, NewThesis):
            edits.update(statement=statement, wrong_if=wrong_if)
        return accept_and_report(request, v, s, **edits)

    @app.post("/suggestion/{sid}/dismiss")
    def dismiss_route(request: Request, sid: str) -> Response:
        v = view(request)
        s = get_suggestion(v, sid)
        if v.status(s) == "accepted":
            return message(request, v, "Already accepted. Use Undo to reverse it.", ok=False, status_code=409)
        v.sess.dismissed.add(s.id)
        return fragment(request, "fragments/status.html", v, s=s, status="dismissed",
                        text="Dismissed; it stays visible in the company's history", raised=[])

    @app.post("/suggestion/{sid}/verify")
    def verify_route(request: Request, sid: str) -> Response:
        v = view(request)
        s = get_suggestion(v, sid)
        if (refused := spend(v)) is not None:
            return message(request, v, refused, ok=False, status_code=429)
        try:
            cited = [c for c in [*v.data.claims, *v.sess.claims] if c.id in s.claim_ids]
            result = runner.run_verify(s, v.sess.log, cited, ctx_factory)
        except runner.NotAvailable:
            refund(v)
            return message(request, v, "Verify is not available yet.", ok=False)
        except Exception as e:  # noqa: BLE001  (type only; never the message)
            return message(request, v, f"Verify failed ({type(e).__name__}).", ok=False, status_code=502)
        v.sess.verify[s.id] = result
        return fragment(request, "fragments/verify.html", v, verify=result)

    @app.post("/driver/{driver_id}")
    def driver_route(request: Request, driver_id: str, value: float = Form(...),
                     suggestion_id: str = Form("")) -> Response:
        v = view(request)
        s = v.suggestions().get(suggestion_id)
        sections = v.sections(s) if s else []
        try:
            entry = apply.update_driver(seed, v.sess.log, driver_id, value, suggestion_id=suggestion_id,
                                        sections=sections)
        except apply.ActionError as e:
            return message(request, v, str(e), ok=False, status_code=422)
        v.sess.log.append(entry)
        v = view(request)
        ticker = driver_id.split(".")[0]
        model = v.model(ticker)
        assert model is not None
        a = None
        if s is not None and isinstance(s.body, ExistingThesis):
            a = next((x for x in s.body.assumptions if x.driver_id == driver_id), None)
        name = "fragments/assumption.html" if a is not None else "fragments/driver.html"
        return fragment(request, name, v, entry=entry, a=a, s=s, projections=compute(model), ticker=ticker)

    @app.post("/conviction/{ticker}")
    def conviction_route(request: Request, ticker: str, conviction: int = Form(...),
                         suggestion_id: str = Form("")) -> Response:
        v = view(request)
        if v.thesis(ticker) is None:
            raise HTTPException(404, f"There is no company {ticker} in the book.")
        try:
            entry = apply.set_conviction(seed, v.sess.log, ticker_of(ticker), conviction,
                                         suggestion_id=suggestion_id)
        except apply.ActionError as e:
            return message(request, v, str(e), ok=False, status_code=422)
        v.sess.log.append(entry)
        return message(request, v, f"{ticker} conviction set from {entry.before:g} to {entry.after:g}.",
                       refresh=True)

    @app.post("/audit/{email_id}/mattered")
    def mattered_route(request: Request, email_id: str) -> Response:
        v = view(request)
        email, result = v.data.emails.get(email_id), v.data.results.get(email_id)
        if email is None or result is None:
            raise HTTPException(404, f"There is no email {email_id}.")
        if result.gate == "quarantine":
            return message(request, v, "A quarantined email is held unsummarized and never sent to a model.",
                           ok=False, status_code=403)
        if result.gate != "stop":
            return message(request, v, "This email already passed the gate.", ok=False, status_code=409)
        if (refused := spend(v)) is not None:
            return message(request, v, refused, ok=False, status_code=429)
        trace = runner.run_mattered(email, result, v.data, ctx_factory, seed, v.sess.log)
        if not trace.totals.calls:
            refund(v)
        _join_session(v, email, trace, keep_email=False)
        n = len(trace.suggestions)
        v.sess.mattered[email_id] = (f"{n} suggestion{'s' if n != 1 else ''} added to your brief" if n
                                     else "No suggestion")
        return fragment(request, "fragments/trace.html", v, trace=trace, error=None,
                        runs_left=v.sess.runs_left())

    # ---- Manual edits to the book (no suggestion behind them) ----

    def record(request: Request, v: View, make: Callable[[], LogEntry], done: str) -> Response:
        try:
            entry = make()
        except apply.ActionError as e:
            return message(request, v, str(e), ok=False, status_code=422)
        v.sess.log.append(entry)
        return message(request, v, done.format(item=labels.pretty_id(entry.item_id)), refresh=True)

    @app.post("/company/{ticker}/pillars")
    def add_pillar_route(request: Request, ticker: str, statement: str = Form(""),
                         driver_ids: list[str] = Form([])) -> Response:
        v = view(request)
        if v.thesis(ticker) is None:
            raise HTTPException(404, f"There is no company {ticker} in the book.")
        return record(request, v, lambda: apply.add_pillar(seed, v.sess.log, ticker_of(ticker), statement,
                                                           driver_ids=driver_ids), "Added {item}.")

    @app.post("/pillar/{pillar_id}/edit")
    def edit_pillar_route(request: Request, pillar_id: str, statement: str = Form(""),
                          driver_ids: list[str] = Form([])) -> Response:
        v = view(request)
        current = v.pillar(pillar_id)
        if current is not None and (statement.strip() or current.statement) == current.statement \
                and set(driver_ids) == set(current.driver_ids):
            return message(request, v, "No changes to save.")
        return record(request, v, lambda: apply.edit_pillar(seed, v.sess.log, pillar_id, statement=statement,
                                                            driver_ids=driver_ids), "Saved {item}.")

    @app.post("/pillar/{pillar_id}/remove")
    def remove_pillar_route(request: Request, pillar_id: str) -> Response:
        v = view(request)
        return record(request, v, lambda: apply.remove_pillar(seed, v.sess.log, pillar_id),
                      "Removed {item}. Undo restores it.")

    @app.post("/pillar/{pillar_id}/evidence")
    def evidence_route(request: Request, pillar_id: str, stance: str = Form(...),
                       strength: int = Form(...)) -> Response:
        v = view(request)
        if stance not in ("supports", "contradicts") or strength not in (1, 2, 3):
            return message(request, v, "Pick a stance and a strength from 1 to 3.", ok=False, status_code=422)
        st: Literal["supports", "contradicts"] = "supports" if stance == "supports" else "contradicts"
        sg: Literal[1, 2, 3] = 1 if strength == 1 else (2 if strength == 2 else 3)
        return record(request, v, lambda: apply.log_evidence(seed, v.sess.log, pillar_id, st, sg),
                      "Logged evidence on {item}.")

    @app.post("/company/{ticker}/driver/{driver_id}")
    def company_driver_route(request: Request, ticker: str, driver_id: str, value: float = Form(...)) -> Response:
        v = view(request)
        return record(request, v, lambda: apply.update_driver(seed, v.sess.log, driver_id, value),
                      "Updated {item}; projections recomputed.")

    @app.post("/undo")
    def undo_route(request: Request) -> Response:
        v = view(request)
        entry = apply.undo(v.sess.log)
        if entry is None:
            return message(request, v, "Nothing to undo.", ok=False)
        v.sess.log.append(entry)
        return message(request, v, f"Reversed the last change to {entry.item_id}.", refresh=True)

    @app.post("/reset")
    def reset_route(request: Request) -> Response:
        v = view(request)
        v.sess.reset()
        return message(request, v, "Restored the seed state.", refresh=True)

    return app


def _asset_version() -> str:
    """A short hash of the static files, so a new deploy is never served a cached stylesheet."""
    digest = hashlib.sha256()
    for path in sorted((WEB_DIR / "static").rglob("*")):
        if path.is_file():
            digest.update(path.read_bytes())
    return digest.hexdigest()[:10]


def _clock(at: datetime) -> str:
    """9:18 AM: a 12-hour time without a leading zero, the same on every platform."""
    return at.strftime("%I:%M %p").lstrip("0")


def _initials(sender: str) -> str:
    """Up to two initials from the person's name, the part of the sender before the first comma."""
    words = [w for w in sender.split(",")[0].split() if w[:1].isalpha()]
    return "".join(w[0] for w in words[:2]).upper() or "?"


def _safety_questions() -> list[dict[str, str]]:
    """The two safety questions as the classifier is asked them, from instructions/jev_questions.md."""
    path = config.INSTRUCTIONS_DIR / "jev_questions.md"
    if not path.exists():
        return []
    out = []
    for line in path.read_text().splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) >= 3 and cells[0].strip("`") in config.SAFETY_QUESTIONS:
            out.append({"key": cells[0].strip("`"), "question": cells[-1].replace("`", "")})
    return out


def _criteria_files() -> dict[str, str]:
    try:
        return read_files()
    except FileNotFoundError:
        return {}


def _join_session(v: View, email: Email, trace: runner.Trace, *, keep_email: bool = True) -> None:
    """A live run's note and suggestions join this session's brief. A quarantined email keeps
    only its sender and subject."""
    if trace.result is not None:
        v.sess.results.setdefault(email.email_id, trace.result)
    if keep_email and email.email_id not in v.data.emails:
        body = "" if trace.quarantined else email.body
        v.sess.emails[email.email_id] = email.model_copy(update={"body": body})
    if trace.quarantined:
        return
    if trace.note is not None:
        v.sess.notes[email.email_id] = trace.note
    v.sess.claims.extend(c for c in trace.claims if c not in v.sess.claims)
    for s in trace.suggestions:
        new_id = f"{email.email_id}.{s.id}"
        v.sess.suggestions[new_id] = s.model_copy(update={"id": new_id})


app = create_app()
