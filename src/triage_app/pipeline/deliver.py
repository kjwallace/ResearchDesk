"""Stage 9 Deliver: results.json, triage.json, notes.json, suggestions.json -> brief.json.

Owned by work package 7 (State and app). See SPEC.md: Where each email appears; Order and alerts.

Deterministic assembly, no model. Placement:

- quarantined: the quarantine list, by sender and subject only;
- a valid suggestion: its card, in thesis changes, new thesis candidates, or worth watching
  when every linked email is labeled monitor;
- passed, labeled thesis_relevant or monitor, with no valid suggestion: relevant_unlinked,
  by signal score;
- everything else: audit, in arrival order.

`needs_attention` is an overlay: every email with a note, by attention probability, whatever
else applies to it. Alerts: met "wrong if" tests on positions of at least
`thresholds.ALERT_WRONG_IF_MIN_BPS`, by size, then attention probabilities of at least
`thresholds.ALERT_HUMAN_ATTENTION`, up to `thresholds.ALERTS_PER_DAY`. Conviction reviews are raised in the
session and join the alerts in the app.
"""

from collections import Counter
from datetime import date
from pathlib import Path

from pydantic import BaseModel

from triage_app import config, thresholds
from triage_app.pipeline.context import RunContext
from triage_app.pipeline.io import read_list, write_one
from triage_app.schema import (
    Alert, AttentionNote, Brief, Email, EmailResult, ExistingThesis, NewThesis, ProjectionChange, Suggestion,
    TriageRecord,
)
from triage_app.state.fold import load_seed

STAGE = "deliver"
SIGNAL = ("thesis_relevant", "monitor")


def run(in_dir: Path, out_dir: Path, ctx: RunContext) -> None:
    with ctx.recorder.stage(STAGE, None):
        brief = process(in_dir, ctx)
    write_one(out_dir / "brief.json", brief)


def _optional_list[M: BaseModel](path: Path, model: type[M]) -> list[M]:
    return read_list(path, model) if path.exists() else []


def process(out_dir: Path, ctx: RunContext) -> Brief:
    """Deterministic assembly of the brief from the stage files in `out_dir`."""
    emails = ctx.emails
    results = read_list(out_dir / "results.json", EmailResult)
    triage = {t.email_id: t for t in _optional_list(out_dir / "triage.json", TriageRecord)}
    notes = _optional_list(out_dir / "notes.json", AttentionNote)
    suggestions = [s for s in _optional_list(out_dir / "suggestions.json", Suggestion) if s.status == "open"]
    checked = _optional_list(out_dir / "suggestions_checked.json", Suggestion)
    day = (date.fromisoformat(config.SET_DATES[ctx.corpus_set]) if ctx.corpus_set
           else emails[0].received_at.date() if emails else date.today())
    return assemble(day, emails, results, triage, notes, suggestions, checked, sizes=position_sizes())


def position_sizes() -> dict[str, int]:
    return {t.ticker: t.size_bps for t in load_seed().theses}


def suggestion_ticker(s: Suggestion) -> str:
    b = s.body
    return b.pillar_id.split(".")[0] if isinstance(b, ExistingThesis) else b.ticker


def assemble(day: date, emails: list[Email], results: list[EmailResult], triage: dict[str, TriageRecord],
             notes: list[AttentionNote], suggestions: list[Suggestion], checked: list[Suggestion],
             sizes: dict[str, int]) -> Brief:
    res = {r.email_id: r for r in results}
    order = {e.email_id: i for i, e in enumerate(emails)}
    for r in results:
        order.setdefault(r.email_id, len(order))

    def signal(email_ids: set[str]) -> float:
        return max((res[e].signal_score for e in email_ids if e in res), default=0.0)

    def linked(s: Suggestion) -> set[str]:
        return {sec.email_id for sec in s.sections}

    def all_monitor(s: Suggestion) -> bool:
        labels = {res[e].triage if e in res else None for e in linked(s)}
        return labels == {"monitor"}

    def existing_key(s: Suggestion) -> tuple[int, int, float]:
        strength = s.body.strength if isinstance(s.body, ExistingThesis) else 0
        return (-sizes.get(suggestion_ticker(s), 0), -strength, -signal(linked(s)))

    def new_key(s: Suggestion) -> tuple[int, float]:
        return (-sizes.get(suggestion_ticker(s), 0), -signal(linked(s)))

    existing = [s for s in suggestions if isinstance(s.body, ExistingThesis)]
    new = [s for s in suggestions if isinstance(s.body, NewThesis)]
    projected = [s for s in suggestions if isinstance(s.body, ProjectionChange)]
    thesis_changes = [s.id for s in sorted(existing, key=existing_key) if not all_monitor(s)]
    new_theses = [s.id for s in sorted(new, key=new_key) if not all_monitor(s)]
    projection_changes = [s.id for s in sorted(projected, key=new_key) if not all_monitor(s)]
    watching = [s for s in suggestions if all_monitor(s)]
    worth_watching = [s.id for s in sorted(watching, key=existing_key)]

    quarantined = sorted((r.email_id for r in results if r.gate == "quarantine"), key=order.__getitem__)
    in_cards = {e for s in suggestions for e in linked(s)}
    unlinked = [r for r in results if r.gate == "pass" and r.triage in SIGNAL and r.email_id not in in_cards]
    relevant_unlinked = [r.email_id for r in sorted(unlinked, key=lambda r: (-r.signal_score, order[r.email_id]))]
    placed = set(quarantined) | in_cards | set(relevant_unlinked)
    audit = sorted((r.email_id for r in results if r.email_id not in placed), key=order.__getitem__)

    def attention(email_id: str) -> float:
        t = triage.get(email_id)
        return t.human_attention if t else 0.0

    noted = [n.email_id for n in notes if n.email_id not in quarantined]
    needs_attention = sorted(noted, key=lambda e: (-attention(e), order.get(e, 0)))

    alerts = brief_alerts(suggestions, res, triage, sizes)
    counts = Counter(r.triage for r in results if r.triage is not None)
    return Brief(
        day=day,
        counts={
            **{label: counts.get(label, 0) for label in config.TRIAGE_LABELS},
            "quarantined": len(quarantined),
            "passed": sum(r.gate == "pass" for r in results),
            "stopped": sum(r.gate == "stop" for r in results),
            "notes": len(needs_attention),
            "suggestions": len(suggestions),
            "rejected": sum(s.status == "rejected" for s in checked),
        },
        thesis_changes=thesis_changes,
        new_theses=new_theses,
        projection_changes=projection_changes,
        worth_watching=worth_watching,
        needs_attention=needs_attention,
        relevant_unlinked=relevant_unlinked,
        alerts=alerts,
        audit=audit,
        quarantined=quarantined,
    )


def brief_alerts(suggestions: list[Suggestion], res: dict[str, EmailResult], triage: dict[str, TriageRecord],
                 sizes: dict[str, int]) -> list[Alert]:
    """Met "wrong if" tests by position size, then attention items by probability; budget first-come."""
    met = [s for s in suggestions if isinstance(s.body, ExistingThesis) and s.body.wrong_if_met
           and sizes.get(suggestion_ticker(s), 0) >= thresholds.ALERT_WRONG_IF_MIN_BPS]
    met.sort(key=lambda s: -sizes.get(suggestion_ticker(s), 0))
    flagged = [t for t in triage.values()
               if t.human_attention >= thresholds.ALERT_HUMAN_ATTENTION and t.email_id in res
               and res[t.email_id].human_attention and res[t.email_id].gate != "quarantine"]
    flagged.sort(key=lambda t: -t.human_attention)
    alerts = [Alert(kind="wrong_if_met", ref_id=s.id) for s in met]
    alerts += [Alert(kind="human_attention", ref_id=t.email_id) for t in flagged]
    return alerts[:thresholds.ALERTS_PER_DAY]
