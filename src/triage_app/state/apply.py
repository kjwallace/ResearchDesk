"""Analyst actions to change-log entries. Pure functions over (seed, log).

See SPEC.md, "What the analyst can do" and "The change log". Each function reads the
current state as fold(seed, log) and returns the new LogEntry to append; it never mutates
the seed or the log, and never writes a file. Code fills every before/after value and
assigns every ID.

- Accept on an existing thesis logs `pillar_evidence` against the pillar.
- Accept on a new thesis logs `pillar_added` with the next free pillar ID.
- Update a linked assumption logs `driver_updated` with the current value as `before`.
- Set conviction logs `conviction_changed`; the value is the analyst's, never proposed.
- Undo appends a reversing entry for the last change still in effect.
- Dismiss changes only the suggestion's status in the session; it writes no entry.

A conviction review is raised by code when accepted contradicting evidence on one pillar
reaches `thresholds.CONVICTION_REVIEW_STRENGTH`. It is open until the analyst sets conviction
against it (a log entry whose `suggestion_id` is the review's ID) or dismisses it.
"""

from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Literal

from triage_app import thresholds
from triage_app.schema import (
    ConvictionReview, ExistingThesis, LinkedSection, LogEntry, NewThesis, Pillar, ProjectionChange, Stance,
    Suggestion, Ticker,
)
from triage_app.state.compute import metric_value
from triage_app.state.fold import (
    BookState, Seed, effective_entries, fold, net_contradicting, next_pillar_id, ticker_of,
)

Strength = Literal[1, 2, 3]
Status = Literal["open", "accepted", "dismissed", "rejected"]

REVIEW_SUFFIX = ".review"


class ActionError(ValueError):
    """An action the current state does not allow; the message is shown to the analyst."""


def _now(at: datetime | None) -> datetime:
    return at or datetime.now(UTC)


def next_entry_id(log: list[LogEntry]) -> str:
    return f"log{len(log) + 1}"


def accepted_ids(log: list[LogEntry]) -> set[str]:
    """Suggestion IDs with an accept still in effect."""
    return {e.suggestion_id for e in effective_entries(log)
            if e.suggestion_id and e.change in ("pillar_evidence", "pillar_added", "driver_updated", "projection_noted")}


def status_of(suggestion: Suggestion, log: list[LogEntry], dismissed: Iterable[str]) -> Status:
    """A suggestion's status in the session: accepted from the log, dismissed from the session."""
    if suggestion.status == "rejected":
        return "rejected"
    if suggestion.id in accepted_ids(log):
        return "accepted"
    if suggestion.id in set(dismissed):
        return "dismissed"
    return "open"


# ---- Accept ----

def accept(seed: Seed, log: list[LogEntry], suggestion: Suggestion, *, strength: Strength | None = None,
           statement: str | None = None, wrong_if: str | None = None, at: datetime | None = None) -> LogEntry:
    """Accept one suggestion, optionally edited: a new strength, or new wording for a new pillar."""
    if suggestion.status == "rejected":
        raise ActionError(f"{suggestion.id} was rejected in validation and cannot be accepted")
    if suggestion.id in accepted_ids(log):
        raise ActionError(f"{suggestion.id} is already accepted")
    body = suggestion.body
    if isinstance(body, ExistingThesis):
        return accept_existing(seed, log, suggestion, body, strength=strength, at=at)
    if isinstance(body, NewThesis):
        return accept_new(seed, log, suggestion, body, statement=statement, wrong_if=wrong_if, at=at)
    if isinstance(body, ProjectionChange):
        return accept_projection(seed, log, suggestion, body, at=at)
    raise ActionError("a conviction review is answered by setting conviction, not by accepting it")


def accept_projection(seed: Seed, log: list[LogEntry], suggestion: Suggestion, body: ProjectionChange, *,
                      at: datetime | None = None) -> LogEntry:
    """A projection on a driver updates that assumption; one on an output metric is logged as evidence."""
    state = fold(seed, log)
    model = state.models.get(body.ticker)
    if model is None:
        raise ActionError(f"unknown ticker {body.ticker}")
    if any(d.id == body.metric for d in model.drivers):
        return update_driver(seed, log, body.metric, body.stated_value, suggestion_id=suggestion.id,
                             sections=list(suggestion.sections), at=at)
    current = metric_value(model, body.metric, "analyst")
    if current is None:
        raise ActionError(f"unknown projection metric {body.metric}")
    return LogEntry(
        id=next_entry_id(log), at=_now(at), suggestion_id=suggestion.id, change="projection_noted",
        item_id=f"{body.ticker}.{body.metric}", before=current, after=body.stated_value,
        sections=list(suggestion.sections),
    )


def accept_existing(seed: Seed, log: list[LogEntry], suggestion: Suggestion, body: ExistingThesis, *,
                    strength: Strength | None = None, at: datetime | None = None) -> LogEntry:
    state = fold(seed, log)
    if body.pillar_id not in state.evidence:
        raise ActionError(f"unknown pillar {body.pillar_id}")
    return LogEntry(
        id=next_entry_id(log), at=_now(at), suggestion_id=suggestion.id, change="pillar_evidence",
        item_id=body.pillar_id, stance=body.stance, strength=strength or body.strength,
        sections=list(suggestion.sections),
    )


def accept_new(seed: Seed, log: list[LogEntry], suggestion: Suggestion, body: NewThesis, *,
               statement: str | None = None, wrong_if: str | None = None, at: datetime | None = None) -> LogEntry:
    state = fold(seed, log)
    pillar_id = next_pillar_id(state, body.ticker)
    statement = (statement or "").strip() or body.statement
    wrong_if = (wrong_if or "").strip() or body.wrong_if
    pillar = Pillar(id=pillar_id, statement=statement, wrong_if=wrong_if, driver_ids=list(body.driver_ids))
    return LogEntry(
        id=next_entry_id(log), at=_now(at), suggestion_id=suggestion.id, change="pillar_added",
        item_id=pillar_id, pillar=pillar, sections=list(suggestion.sections),
    )


# ---- Assumptions and conviction ----

def update_driver(seed: Seed, log: list[LogEntry], driver_id: str, value: float, *, suggestion_id: str = "",
                  sections: list[LinkedSection] | None = None, at: datetime | None = None) -> LogEntry:
    """Change one driver's analyst value. `before` is the current value, filled by code."""
    state = fold(seed, log)
    ticker = driver_id.split(".")[0]
    model = next((m for t, m in state.models.items() if t == ticker), None)
    driver = next((d for d in model.drivers if d.id == driver_id), None) if model else None
    if driver is None:
        raise ActionError(f"unknown driver {driver_id}")
    if not driver.min <= value <= driver.max:
        raise ActionError(f"{driver_id}: {value:g} is outside its bounds ({driver.min:g} to {driver.max:g})")
    if value == driver.analyst:
        raise ActionError(f"{driver_id} is already {value:g}")
    return LogEntry(
        id=next_entry_id(log), at=_now(at), suggestion_id=suggestion_id, change="driver_updated",
        item_id=driver_id, before=driver.analyst, after=value, sections=list(sections or []),
    )


def set_conviction(seed: Seed, log: list[LogEntry], ticker: Ticker, conviction: int, *,
                   suggestion_id: str = "", at: datetime | None = None) -> LogEntry:
    """Set a company's conviction to the analyst's chosen value, 1 to 5."""
    if conviction not in (1, 2, 3, 4, 5):
        raise ActionError("conviction must be a whole number from 1 to 5")
    state = fold(seed, log)
    if ticker not in state.theses:
        raise ActionError(f"unknown ticker {ticker}")
    sections = [s for e in state.evidence.get(_review_pillar(suggestion_id), []) for s in e.sections]
    return LogEntry(
        id=next_entry_id(log), at=_now(at), suggestion_id=suggestion_id, change="conviction_changed",
        item_id=ticker, before=float(state.theses[ticker].conviction), after=float(conviction),
        sections=sections,
    )


# ---- Manual changes to pillars (no suggestion behind them) ----

def _pillar(state: BookState, pillar_id: str) -> Pillar:
    pillar = next((p for t in state.theses.values() for p in t.pillars if p.id == pillar_id), None)
    if pillar is None:
        raise ActionError(f"unknown pillar {pillar_id}")
    return pillar


def _drivers(state: BookState, ticker: Ticker, driver_ids: Iterable[str]) -> list[str]:
    """The driver IDs, checked to belong to the company, in the model's order."""
    known = [d.id for d in state.models[ticker].drivers]
    wanted = set(driver_ids)
    if unknown := wanted - set(known):
        raise ActionError(f"not {ticker} assumptions: {', '.join(sorted(unknown))}")
    return [d for d in known if d in wanted]


def add_pillar(seed: Seed, log: list[LogEntry], ticker: Ticker, statement: str, *, driver_ids: Iterable[str] = (),
               wrong_if: str = "", at: datetime | None = None) -> LogEntry:
    """Add a pillar the analyst wrote; it gets the company's next free pillar ID."""
    state = fold(seed, log)
    if ticker not in state.theses:
        raise ActionError(f"unknown ticker {ticker}")
    if not statement.strip():
        raise ActionError("a pillar needs a statement")
    pillar_id = next_pillar_id(state, ticker)
    pillar = Pillar(id=pillar_id, statement=statement.strip(), wrong_if=wrong_if.strip(),
                    driver_ids=_drivers(state, ticker, driver_ids))
    return LogEntry(id=next_entry_id(log), at=_now(at), suggestion_id="", change="pillar_added",
                    item_id=pillar_id, pillar=pillar, sections=[])


def edit_pillar(seed: Seed, log: list[LogEntry], pillar_id: str, *, statement: str | None = None,
                driver_ids: Iterable[str] | None = None, at: datetime | None = None) -> LogEntry:
    """Reword a pillar or change its linked assumptions; anything not given is kept."""
    state = fold(seed, log)
    before = _pillar(state, pillar_id)
    after = before.model_copy(update={
        "statement": (statement or "").strip() or before.statement,
        "driver_ids": before.driver_ids if driver_ids is None
                      else _drivers(state, ticker_of(pillar_id), driver_ids),
    })
    if after == before:
        raise ActionError(f"{pillar_id} is unchanged")
    return LogEntry(id=next_entry_id(log), at=_now(at), suggestion_id="", change="pillar_edited",
                    item_id=pillar_id, pillar=after, pillar_before=before, sections=[])


def remove_pillar(seed: Seed, log: list[LogEntry], pillar_id: str, *, at: datetime | None = None) -> LogEntry:
    """Take a pillar out of the thesis for this session; undo restores it with its evidence."""
    state = fold(seed, log)
    pillar = _pillar(state, pillar_id)
    return LogEntry(id=next_entry_id(log), at=_now(at), suggestion_id="", change="pillar_removed",
                    item_id=pillar_id, pillar=pillar, sections=[])


def log_evidence(seed: Seed, log: list[LogEntry], pillar_id: str, stance: Stance, strength: Strength, *,
                 at: datetime | None = None) -> LogEntry:
    """Evidence the analyst records by hand, counted like accepted evidence (and toward conviction reviews)."""
    state = fold(seed, log)
    _pillar(state, pillar_id)
    if stance not in ("supports", "contradicts"):
        raise ActionError("stance must be supports or contradicts")
    if strength not in (1, 2, 3):
        raise ActionError("strength must be 1, 2 or 3")
    return LogEntry(id=next_entry_id(log), at=_now(at), suggestion_id="", change="pillar_evidence",
                    item_id=pillar_id, stance=stance, strength=strength, sections=[])


# ---- Undo ----

def undo(log: list[LogEntry], *, at: datetime | None = None) -> LogEntry | None:
    """A reversing entry for the last change still in effect, or None when there is none."""
    live = effective_entries(log)
    if not live:
        return None
    last = live[-1]
    return LogEntry(
        id=next_entry_id(log), at=_now(at), suggestion_id=last.suggestion_id, change=last.change,
        item_id=last.item_id, before=last.after, after=last.before, stance=last.stance,
        strength=last.strength, pillar=last.pillar, pillar_before=last.pillar_before, reverses=last.id,
        sections=list(last.sections),
    )


# ---- Conviction reviews ----

def review_id(pillar_id: str) -> str:
    return f"{pillar_id}{REVIEW_SUFFIX}"


def _review_pillar(suggestion_id: str) -> str:
    return suggestion_id.removesuffix(REVIEW_SUFFIX) if suggestion_id.endswith(REVIEW_SUFFIX) else ""


def conviction_reviews(seed: Seed, log: list[LogEntry], dismissed: Iterable[str] = ()) -> list[Suggestion]:
    """Open conviction reviews: pillars whose net contradicting strength reaches the threshold,
    not yet answered by a conviction change on the review and not dismissed."""
    state = fold(seed, log)
    answered = {e.suggestion_id for e in state.applied if e.change == "conviction_changed"}
    gone = set(dismissed) | answered
    out: list[Suggestion] = []
    for ticker, thesis in state.theses.items():
        for pillar in thesis.pillars:
            net = net_contradicting(state, pillar.id)
            rid = review_id(pillar.id)
            if net < thresholds.CONVICTION_REVIEW_STRENGTH or rid in gone:
                continue
            out.append(review_suggestion(state, ticker, pillar.id, net))
    return out


def review_suggestion(state: BookState, ticker: Ticker, pillar_id: str, net: int) -> Suggestion:
    entries = state.evidence.get(pillar_id, [])
    return Suggestion(
        id=review_id(pillar_id),
        body=ConvictionReview(kind="conviction_review", ticker=ticker, pillar_id=pillar_id),
        rationale=(f"Accepted contradicting evidence on {pillar_id} reaches a net strength of {net}, "
                   f"at or above the review threshold of {thresholds.CONVICTION_REVIEW_STRENGTH}."),
        claim_ids=[],
        sections=[s for e in entries if e.stance == "contradicts" for s in e.sections],
        status="open",
    )
