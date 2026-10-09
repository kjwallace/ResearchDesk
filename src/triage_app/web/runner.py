"""Calls from the app into other packages' code: the live route, "this mattered" and verify.

Each stage function is imported when it is called, so the app answers before every package
has landed: a stage that raises NotImplementedError shows as "not available yet" in the
trace. A failed step shows only the exception's type, never its message, so no email text
(and never a quarantined body) can reach the page through an error.

Every step runs inside `recorder.stage(name, email_id)` on a fresh Recorder, so the trace
shows the tokens and latency of each stage.
"""

import importlib
import json
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from triage_app import config
from triage_app.monitoring import Recorder, recording
from triage_app.pipeline.context import RunContext
from triage_app.schema import (
    AnalysisRecord, AttentionNote, Claim, Email, EmailResult, LogEntry, RedundancyRecord, Suggestion,
    TriageRecord, VerifyResult,
)
from triage_app.state.fold import Seed, fold
from triage_app.web.data import DayData

StepStatus = Literal["ok", "skipped", "unavailable", "failed"]
ContextFactory = Callable[[Recorder], RunContext]


def _count(n: int, noun: str) -> str:
    return f"{n} {noun}{'' if n == 1 else 's'}"


class NotAvailable(Exception):
    """The other package's function is not built yet."""


def default_context(recorder: Recorder) -> RunContext:
    return RunContext(None, recorder=recorder)


def stage_fn(module: str, name: str = "process") -> Callable[..., Any]:
    """Look up a function at call time: `triage_app.pipeline.<module>.<name>` or a dotted module path."""
    path = module if "." in module else f"triage_app.pipeline.{module}"
    fn: Callable[..., Any] = getattr(importlib.import_module(path), name)
    return fn


@dataclass
class Step:
    name: str
    status: StepStatus
    detail: str = ""
    calls: int = 0
    cache_hits: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: float = 0.0


@dataclass
class Trace:
    email_id: str
    sender: str
    subject: str
    steps: list[Step] = field(default_factory=list)
    triage: TriageRecord | None = None
    result: EmailResult | None = None
    note: AttentionNote | None = None
    claims: list[Claim] = field(default_factory=list)
    analysis: AnalysisRecord | None = None
    suggestions: list[Suggestion] = field(default_factory=list)
    rejected: list[Suggestion] = field(default_factory=list)

    @property
    def quarantined(self) -> bool:
        return self.result is not None and self.result.gate == "quarantine"

    @property
    def totals(self) -> Step:
        return Step(
            name="total", status="ok", calls=sum(s.calls for s in self.steps),
            cache_hits=sum(s.cache_hits for s in self.steps),
            input_tokens=sum(s.input_tokens for s in self.steps),
            output_tokens=sum(s.output_tokens for s in self.steps),
            latency_ms=sum(s.latency_ms for s in self.steps),
        )


class _Runner:
    def __init__(self, trace: Trace, recorder: Recorder) -> None:
        self.trace, self.rec = trace, recorder

    def step(self, name: str, fn: Callable[[], Any], describe: Callable[[Any], str] = lambda _: "") -> Any:
        """Run one stage on the email; returns its value, or None when it did not run."""
        first_call = len(self.rec.calls)
        value: Any = None
        status: StepStatus = "ok"
        detail = ""
        try:
            with self.rec.stage(name, self.trace.email_id):
                value = fn()
        except NotImplementedError:
            status, detail = "unavailable", "Not available yet: this stage is not built"
        except Exception as e:  # noqa: BLE001  (shown by type only; see module docstring)
            status, detail = "failed", f"Failed ({type(e).__name__})"
        calls = self.rec.calls[first_call:]
        timing = self.rec.timings[-1].latency_ms if self.rec.timings else 0.0
        if status == "ok":
            detail = describe(value)
        self.trace.steps.append(Step(
            name=name, status=status, detail=detail, calls=len(calls),
            cache_hits=sum(c.cache_hit for c in calls), input_tokens=sum(c.input_tokens for c in calls),
            output_tokens=sum(c.output_tokens for c in calls), latency_ms=timing,
        ))
        return value if status == "ok" else None

    def skip(self, name: str, why: str) -> None:
        self.trace.steps.append(Step(name=name, status="skipped", detail=why))


# ---- Live route ----

def load_presets(directory: Path = config.LIVE_PRESETS_DIR) -> list[Email]:
    """The preset emails: each JSON file holds one Email or a list of them."""
    out: list[Email] = []
    if not directory.exists():
        return out
    for path in sorted(directory.glob("*.json")):
        raw = json.loads(path.read_text())
        for item in raw if isinstance(raw, list) else [raw]:
            out.append(Email.model_validate(item))
    return out


def day_cache(data: DayData, ctx: RunContext) -> Any:
    """Stage 2's day cache over the set's emails, built at run time through `ctx.embedder`.

    Embeddings are disk-cached, so only the first build after a cold start embeds anything;
    the cache is then kept on the loaded set, and each run gets its own copy to add to.
    """
    if data.day_cache is None:
        red = importlib.import_module("triage_app.pipeline.redundancy")
        data.day_cache = red.build_day_cache(data.inbox, ctx)
    return data.day_cache.copy()


def run_live(email: Email, data: DayData, make_ctx: ContextFactory, seed: Seed, log: list[LogEntry]) -> Trace:
    """One email through every stage, against the day cache and the visitor's book (seed plus
    session log). Nothing is written to disk."""
    rec = Recorder()
    ctx = make_ctx(rec)
    trace = Trace(email_id=email.email_id, sender=email.sender, subject=email.subject)
    r = _Runner(trace, rec)
    with recording(rec):
        def redundancy() -> RedundancyRecord:
            record: RedundancyRecord = stage_fn("redundancy")(email, day_cache(data, ctx), ctx)
            return record

        red = r.step("redundancy", redundancy, lambda x: (
            f"Nearest earlier email {x.nearest} (content {x.content_similarity or 0:.2f}, subject {x.subject_score or 0:.2f})"
            + ("; flagged as a possible repeat" if x.flagged else "") if x.nearest else "no earlier email"))
        if red is None:
            red = RedundancyRecord(email_id=email.email_id, nearest=None, content_similarity=None,
                                   subject_score=None, flagged=False)
            trace.steps[-1].detail += "; treated as no repeat"

        trace.triage = r.step("classify", lambda: stage_fn("classify")(email, ctx),
                              lambda t: f"Top label: {max(t.triage_probs, key=t.triage_probs.get)}")
        if trace.triage is None:
            for name in ("gate", "human_attention", "extract", "analyze", "validate", "merge"):
                r.skip(name, "Needs a classification")
            return trace
        triage = trace.triage
        trace.result = r.step("gate", lambda: stage_fn("gate")(triage, red, ctx.thresholds),
                              lambda x: x.reason)
        if trace.result is None:
            for name in ("human_attention", "extract", "analyze", "validate", "merge"):
                r.skip(name, "Needs a gate decision")
            return trace
        result = trace.result
        if result.gate == "quarantine":
            for name in ("human_attention", "extract", "analyze", "validate", "merge"):
                r.skip(name, "Quarantined: held unsummarized")
            return trace
        if result.human_attention:
            trace.note = r.step("human_attention", lambda: stage_fn("human_attention")(email, result, ctx),
                                lambda n: f"Note written; action: {n.action}")
        else:
            r.skip("human_attention", "Not flagged for attention")
        if result.gate != "pass":
            for name in ("extract", "analyze", "validate", "merge"):
                r.skip(name, "Stopped at the gate")
            return trace
        _analyse(r, trace, email, result, earlier_email(red, data), ctx, seed, log)
    return trace


def earlier_email(record: RedundancyRecord | None, data: DayData) -> Email | None:
    """The nearest earlier email of a flagged repeat, as extraction context; never a quarantined one."""
    if record is None or not record.flagged or record.nearest is None or data.quarantined(record.nearest):
        return None
    return data.emails.get(record.nearest)


def run_mattered(email: Email, result: EmailResult, data: DayData, make_ctx: ContextFactory, seed: Seed,
                 log: list[LogEntry]) -> Trace:
    """Send one stopped email to extraction and the analysis agent ("this mattered").

    The analyst's request overrides the gate: the stages see a copy of the result with
    gate "pass", and keep its label, so validation still marks a suggestion "second look" when
    no linked email is labeled thesis_relevant or monitor. A quarantined email never runs.
    """
    if result.gate == "quarantine" or data.quarantined(email.email_id):
        raise ValueError("a quarantined email is never sent to a model")
    override = result.model_copy(update={"gate": "pass"})
    rec = Recorder()
    ctx = make_ctx(rec)
    trace = Trace(email_id=email.email_id, sender=email.sender, subject=email.subject, result=result)
    r = _Runner(trace, rec)
    with recording(rec):
        _analyse(r, trace, email, override, earlier_email(data.redundancy.get(email.email_id), data),
                 ctx, seed, log)
    return trace


def folded_seed(seed: Seed, log: list[LogEntry]) -> Seed:
    """The visitor's book as a Seed: theses and models folded with the session log, links unchanged."""
    state = fold(seed, log)
    return Seed(theses=list(state.theses.values()), models=list(state.models.values()), links=seed.links)


def _analyse(r: _Runner, trace: Trace, email: Email, result: EmailResult, earlier: Email | None,
             ctx: RunContext, seed: Seed, log: list[LogEntry]) -> None:
    claims = r.step("extract", lambda: stage_fn("extract")(email, result, earlier, ctx),
                    lambda cs: _count(len(cs), "claim"))
    if claims is None:
        for name in ("analyze", "validate", "merge"):
            r.skip(name, "Needs claims")
        return
    trace.claims = claims
    book = fold(seed, log)
    current = folded_seed(seed, log)
    out = r.step("analyze", lambda: stage_fn("analyze")(email.email_id, claims, result, ctx, book=book),
                 lambda o: _count(len(o[1]), "suggestion") if o[1] else (o[0].no_change_reason or "No suggestion"))
    if out is None:
        for name in ("validate", "merge"):
            r.skip(name, "Needs the analysis")
        return
    trace.analysis, raw = out
    if not raw:
        for name in ("validate", "merge"):
            r.skip(name, "No suggestions to check")
        return

    def validate() -> list[Suggestion]:
        inputs = stage_fn("validate", "ValidationInputs")(claims, [email], [result], current)
        check = stage_fn("validate")
        return [check(s, ctx, inputs) for s in raw]

    checked = r.step("validate", validate,
                     lambda xs: f"{sum(s.status == 'open' for s in xs)} valid, "
                                f"{sum(s.status == 'rejected' for s in xs)} rejected")
    if checked is None:
        r.skip("merge", "Needs validated suggestions")
        return
    trace.rejected = [s for s in checked if s.status == "rejected"]
    valid = [s for s in checked if s.status == "open"]
    if not valid:
        r.skip("merge", "All suggestions rejected in validation")
        return
    merged = r.step("merge", lambda: stage_fn("merge")(valid, ctx, [result], current), lambda xs: f"{len(xs)} after merging")
    trace.suggestions = merged or []


# ---- Verify ----

def run_verify(suggestion: Suggestion, log: list[LogEntry], claims: list[Claim],
               make_ctx: ContextFactory) -> VerifyResult:
    """The verify agent's cited verdict on one suggestion; raises NotAvailable before it is built."""
    rec = Recorder()
    ctx = make_ctx(rec)
    try:
        verify = stage_fn("triage_app.modules.verify_agent", "verify")
    except (ImportError, AttributeError) as e:
        raise NotAvailable("the verify agent is not built yet") from e
    with recording(rec), rec.stage("verify", None):
        try:
            result: VerifyResult = verify(suggestion, log, ctx, claims=claims)
        except NotImplementedError as e:
            raise NotAvailable("the verify agent is not built yet") from e
    return result
