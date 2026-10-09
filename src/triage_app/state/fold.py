"""Current book state = seed + change log. Never stored; always recomputed.

See SPEC.md, "State: model, thesis and change log". An undo appends an entry whose
`reverses` names the entry it cancels; an undo of an undo restores the original.
"""

import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from triage_app.config import SEED_DIR, TICKERS
from triage_app.schema import CompanyModel, Link, LogEntry, Pillar, Thesis, Ticker

Conviction = Literal[1, 2, 3, 4, 5]
_TICKERS: dict[str, Ticker] = {t: t for t in TICKERS}
_CONVICTIONS: dict[int, Conviction] = {1: 1, 2: 2, 3: 3, 4: 4, 5: 5}


def ticker_of(item_id: str) -> Ticker:
    """The covered ticker an ID names: "AAPL", "AAPL.p4" or "AAPL.services_growth" give "AAPL"."""
    try:
        return _TICKERS[item_id.split(".")[0]]
    except KeyError:
        raise ValueError(f"{item_id!r} does not name a covered company") from None


def as_conviction(value: float) -> Conviction:
    """A conviction from 1 to 5; anything else is an error."""
    if value != int(value) or int(value) not in _CONVICTIONS:
        raise ValueError(f"conviction must be a whole number from 1 to 5, not {value}")
    return _CONVICTIONS[int(value)]


class Seed(BaseModel):
    theses: list[Thesis]
    models: list[CompanyModel]
    links: list[Link]


class BookState(BaseModel):
    theses: dict[Ticker, Thesis]
    models: dict[Ticker, CompanyModel]
    links: list[Link]
    evidence: dict[str, list[LogEntry]]   # pillar ID to accepted pillar_evidence entries
    applied: list[LogEntry]               # log entries in effect, in log order
    removed: dict[str, Pillar] = Field(default_factory=dict)  # pillars removed this session; their IDs are never reused
    projections: dict[str, list[LogEntry]] = Field(default_factory=dict)  # ticker to accepted projection notes


def load_seed(seed_dir: Path = SEED_DIR) -> Seed:
    def read(name: str) -> object:
        return json.loads((seed_dir / name).read_text())

    return Seed.model_validate({
        "theses": read("theses.json"),
        "models": read("models.json"),
        "links": read("links.json"),
    })


def effective_entries(log: list[LogEntry]) -> list[LogEntry]:
    """Entries still in effect: not cancelled by a later undo, and not undos themselves."""
    cancelled: set[str] = set()
    for entry in reversed(log):
        if entry.id in cancelled:
            continue
        if entry.reverses is not None:
            cancelled.add(entry.reverses)
    return [e for e in log if e.id not in cancelled and e.reverses is None]


def fold(seed: Seed, log: list[LogEntry]) -> BookState:
    theses = {t.ticker: t.model_copy(deep=True) for t in seed.theses}
    models = {m.ticker: m.model_copy(deep=True) for m in seed.models}
    evidence: dict[str, list[LogEntry]] = {p.id: [] for t in theses.values() for p in t.pillars}
    applied = effective_entries(log)
    removed: dict[str, Pillar] = {}
    projections: dict[str, list[LogEntry]] = {}

    for entry in applied:
        match entry.change:
            case "pillar_evidence":
                evidence.setdefault(entry.item_id, []).append(entry)
            case "pillar_added":
                if entry.pillar is None:
                    raise ValueError(f"{entry.id}: pillar_added without a pillar")
                theses[ticker_of(entry.item_id)].pillars.append(entry.pillar)
                evidence.setdefault(entry.pillar.id, [])
            case "driver_updated":
                if entry.after is None:
                    raise ValueError(f"{entry.id}: driver_updated without a value")
                model = models[ticker_of(entry.item_id)]
                for d in model.drivers:
                    if d.id == entry.item_id:
                        d.analyst = entry.after
                        break
                else:
                    raise ValueError(f"{entry.id}: unknown driver {entry.item_id}")
            case "conviction_changed":
                if entry.after is None:
                    raise ValueError(f"{entry.id}: conviction_changed without a value")
                theses[ticker_of(entry.item_id)].conviction = as_conviction(entry.after)
            case "pillar_edited":
                if entry.pillar is None:
                    raise ValueError(f"{entry.id}: pillar_edited without a pillar")
                pillars = theses[ticker_of(entry.item_id)].pillars
                at = next((i for i, p in enumerate(pillars) if p.id == entry.item_id), None)
                if at is None:
                    raise ValueError(f"{entry.id}: unknown pillar {entry.item_id}")
                pillars[at] = entry.pillar
            case "pillar_removed":
                thesis = theses[ticker_of(entry.item_id)]
                gone = next((p for p in thesis.pillars if p.id == entry.item_id), None)
                if gone is None:
                    raise ValueError(f"{entry.id}: unknown pillar {entry.item_id}")
                thesis.pillars = [p for p in thesis.pillars if p.id != entry.item_id]
                removed[gone.id] = gone
                evidence.pop(gone.id, None)
            case "projection_noted":
                projections.setdefault(ticker_of(entry.item_id), []).append(entry)

    return BookState(theses=theses, models=models, links=seed.links, evidence=evidence, applied=applied,
                     removed=removed, projections=projections)


def net_contradicting(state: BookState, pillar_id: str) -> int:
    """Summed strength of accepted contradicting evidence minus supporting evidence."""
    total = 0
    for e in state.evidence.get(pillar_id, []):
        strength = e.strength or 0
        total += strength if e.stance == "contradicts" else -strength
    return total


def next_pillar_id(state: BookState, ticker: Ticker) -> str:
    """The next free pillar ID for a company, such as AAPL.p4."""
    ids = [p.id for p in state.theses[ticker].pillars] + [i for i in state.removed if i.startswith(f"{ticker}.")]
    numbers = [int(i.split(".p")[1]) for i in ids]
    return f"{ticker}.p{max(numbers, default=0) + 1}"
