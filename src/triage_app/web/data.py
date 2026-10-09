"""Read-only view of one set's stage files for the app.

The directory comes from `TRIAGE_DATA_DIR` (default `data/out/day_1`). The emails are not a
stage file: they are read from the set's corpus file through the corpus loader (label-free,
bodies exactly as in the corpus). `data/out/<set>` maps to `data/corpus/<set>/emails.jsonl`,
any other directory to the `emails.jsonl` beside it (the fixtures: `tests/fixtures/out` ->
`tests/fixtures/emails.jsonl`), and `TRIAGE_EMAILS_FILE` overrides both. Files are read once
and reloaded when any of them changes on disk. A missing file reads as empty, so the app
answers before every stage has run. Nothing here writes.
"""

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from markupsafe import Markup, escape
from pydantic import BaseModel

from triage_app import config
from triage_app.pipeline.io import normalize_ws, read_list, read_one
from triage_app.schema import (
    AnalysisRecord, AttentionNote, Brief, Claim, CriteriaHistoryEntry, Email, EmailResult,
    EvalReport, LinkedSection, RedundancyRecord, Suggestion, TriageRecord, UsageReport,
)

DEFAULT_DATA_DIR = config.OUT_DIR / "day_1"


def data_dir_from_env() -> Path:
    raw = os.environ.get("TRIAGE_DATA_DIR", "").strip()
    if not raw:
        return DEFAULT_DATA_DIR
    path = Path(raw)
    return path if path.is_absolute() else config.ROOT / path


def emails_file_for(data_dir: Path) -> Path:
    """The corpus file holding the emails of the set whose stage files are in `data_dir`."""
    raw = os.environ.get("TRIAGE_EMAILS_FILE", "").strip()
    if raw:
        path = Path(raw)
        return path if path.is_absolute() else config.ROOT / path
    for corpus_set in config.CORPUS_SETS:
        if data_dir.name == corpus_set:
            return config.corpus_file(corpus_set)
    return data_dir.parent / "emails.jsonl"


def load_emails(path: Path) -> list[Email]:
    """Label-free emails from a corpus file, in arrival order; empty when the file is missing."""
    if not path.exists():
        return []
    from triage_app.corpus import load as load_corpus
    return load_corpus(path)[0]


@dataclass
class DayData:
    """Every stage file of one set, with lookups by ID."""

    directory: Path
    inbox: list[Email] = field(default_factory=list)                    # from the corpus file
    redundancy: dict[str, RedundancyRecord] = field(default_factory=dict)  # flagged emails only
    triage: dict[str, TriageRecord] = field(default_factory=dict)
    results: dict[str, EmailResult] = field(default_factory=dict)
    notes: dict[str, AttentionNote] = field(default_factory=dict)
    claims: list[Claim] = field(default_factory=list)
    analysis: dict[str, AnalysisRecord] = field(default_factory=dict)
    checked: list[Suggestion] = field(default_factory=list)
    suggestions: dict[str, Suggestion] = field(default_factory=dict)
    brief: Brief | None = None
    eval: EvalReport | None = None
    metrics: UsageReport | None = None
    history: list[CriteriaHistoryEntry] = field(default_factory=list)
    day_cache: Any = None   # stage 2's day cache, built by the live route on first use

    @property
    def emails(self) -> dict[str, Email]:
        return {e.email_id: e for e in self.inbox}

    def quarantined(self, email_id: str) -> bool:
        r = self.results.get(email_id)
        return r is not None and r.gate == "quarantine"

    def rejected(self) -> list[Suggestion]:
        return [s for s in self.checked if s.status == "rejected"]

    def no_change_reason(self, email_id: str) -> str | None:
        """The analysis record's reason, or the code-written one when every suggestion was rejected."""
        a = self.analysis.get(email_id)
        if a is None:
            return None
        if a.no_change_reason:
            return a.no_change_reason
        mine = [s for s in self.checked if s.id in a.suggestion_ids]
        if mine and all(s.status == "rejected" for s in mine):
            return "all suggestions rejected in validation"
        return None

    def quotes_for(self, email_id: str) -> list[str]:
        """Every quoted section of one email shown anywhere: notes, claims and valid suggestions."""
        out: list[str] = []
        note = self.notes.get(email_id)
        if note:
            out += [s.quote for s in note.sections]
        out += [c.quote for c in self.claims if c.email_id == email_id]
        for s in self.suggestions.values():
            out += [x.quote for x in s.sections if x.email_id == email_id]
        return out


def _list[M: BaseModel](path: Path, model: type[M]) -> list[M]:
    return read_list(path, model) if path.exists() else []


def _one[M: BaseModel](path: Path, model: type[M]) -> M | None:
    return read_one(path, model) if path.exists() else None


def load(directory: Path, emails_path: Path | None = None) -> DayData:
    d = directory
    history_path = d / "criteria_history.json"
    if not history_path.exists():
        history_path = d.parent / "criteria_history.json"
    return DayData(
        directory=d,
        inbox=load_emails(emails_path or emails_file_for(d)),
        redundancy={r.email_id: r for r in _list(d / "redundancy.json", RedundancyRecord)},
        triage={t.email_id: t for t in _list(d / "triage.json", TriageRecord)},
        results={r.email_id: r for r in _list(d / "results.json", EmailResult)},
        notes={n.email_id: n for n in _list(d / "notes.json", AttentionNote)},
        claims=_list(d / "claims.json", Claim),
        analysis={a.email_id: a for a in _list(d / "analysis.json", AnalysisRecord)},
        checked=_list(d / "suggestions_checked.json", Suggestion),
        suggestions={s.id: s for s in _list(d / "suggestions.json", Suggestion)},
        brief=_one(d / "brief.json", Brief),
        eval=_one(d / "eval.json", EvalReport),
        metrics=_one(d / "metrics.json", UsageReport),
        history=_list(history_path, CriteriaHistoryEntry),
    )


class DataStore:
    """Holds the loaded set and reloads it when a stage file changes."""

    def __init__(self, directory: Path, emails_path: Path | None = None) -> None:
        self.directory = directory
        self.emails_path = emails_path or emails_file_for(directory)
        self._stamp: tuple[float, ...] | None = None
        self._data: DayData | None = None

    def _mtimes(self) -> tuple[float, ...]:
        files = list(self.directory.glob("*.json")) if self.directory.exists() else []
        if self.emails_path.exists():
            files.append(self.emails_path)
        return tuple(sorted(p.stat().st_mtime for p in files))

    def get(self) -> DayData:
        stamp = self._mtimes()
        if self._data is None or stamp != self._stamp:
            self._data = load(self.directory, self.emails_path)
            self._stamp = stamp
        return self._data


# ---- Rendering helpers ----

def highlight(body: str, quotes: list[str]) -> Markup:
    """The email body as HTML, with each quoted section wrapped in <mark>.

    Quotes are matched after whitespace normalization, as the pipeline checks them.
    """
    text = normalize_ws(body)
    spans: list[tuple[int, int]] = []
    for q in {normalize_ws(q) for q in quotes if q.strip()}:
        start = text.find(q)
        while start != -1:
            spans.append((start, start + len(q)))
            start = text.find(q, start + 1)
    merged: list[list[int]] = []
    for a, b in sorted(spans):
        if merged and a <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], b)
        else:
            merged.append([a, b])
    parts: list[str] = []
    pos = 0
    for n, (a, b) in enumerate(merged, 1):
        parts.append(str(escape(text[pos:a])))
        parts.append(f'<mark id="q{n}">{escape(text[a:b])}</mark>')
        pos = b
    parts.append(str(escape(text[pos:])))
    return Markup("".join(parts))


def safe_sections(sections: list[LinkedSection], data: DayData) -> list[LinkedSection]:
    """Drop any section from a quarantined email: its body reaches no screen."""
    return [s for s in sections if not data.quarantined(s.email_id)]
