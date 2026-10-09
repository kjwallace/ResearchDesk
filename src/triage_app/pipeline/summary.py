"""SUMMARY.md: a short Markdown summary of one run, written at the end of `pipeline/run.py`.

`render` is a pure function of the stage files' contents, the emails' header fields and the
run's UsageReport; `write` reads the stage files and writes `data/out/<set>/SUMMARY.md`.

It holds pipeline output only: never a corpus label, and never an email body (a quarantined
email shows its ID only; other emails are named by subject). A missing stage file reads as
empty, so a partial run still gets a summary.
"""

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

from pydantic import BaseModel

from triage_app import config
from triage_app import thresholds as limits
from triage_app.pipeline.io import read_list, read_one
from triage_app.schema import (
    AttentionNote, Brief, Email, EmailResult, ExistingThesis, NewThesis, RedundancyRecord, Suggestion,
    Thresholds, TriageRecord, UsageReport,
)

FILE = "SUMMARY.md"


@dataclass
class RunOutputs:
    """What the summary reads: the stage files, the run's report and the thresholds in force."""

    corpus_set: str
    emails: list[Email]
    tuned: bool
    criteria_version: str = ""
    results: list[EmailResult] = field(default_factory=list)
    redundancy: list[RedundancyRecord] = field(default_factory=list)
    notes: list[AttentionNote] = field(default_factory=list)
    suggestions: list[Suggestion] = field(default_factory=list)
    brief: Brief | None = None
    metrics: UsageReport | None = None


def _ms(value: float) -> str:
    return f"{value / 1000:.1f} s" if value >= 1000 else f"{value:.0f} ms"


def render(run: RunOutputs) -> str:
    subject = {e.email_id: e.subject for e in run.emails}
    quarantined = {r.email_id for r in run.results if r.gate == "quarantine"}

    def name(email_id: str) -> str:
        if email_id in quarantined or email_id not in subject:
            return f"`{email_id}`"
        return f"`{email_id}` {subject[email_id]}"

    day = str(run.brief.day) if run.brief else config.SET_DATES.get(run.corpus_set, "")
    lines = [
        f"# Run summary: {run.corpus_set}",
        "",
        "Synthetic data. Pipeline output only; no corpus label appears here.",
        "",
        f"- Set: {run.corpus_set}, day {day}",
        f"- Criteria version: {run.criteria_version or 'unknown'}",
        f"- Thresholds: {'tuned (tuned/thresholds.json)' if run.tuned else 'starting values (thresholds.py)'}",
        "",
        "## Emails",
        "",
    ]
    labels = Counter(r.triage for r in run.results if r.triage is not None)
    gates = Counter(r.gate for r in run.results)
    lines.append(f"{len(run.emails)} emails; {len(run.results)} with a result.")
    lines.append("")
    lines.append("| Label | Emails |")
    lines.append("| --- | --- |")
    for label in config.TRIAGE_LABELS:
        lines.append(f"| {label} | {labels.get(label, 0)} |")
    lines.append("")
    lines.append(f"Gate: {gates.get('pass', 0)} pass, {gates.get('stop', 0)} stop, "
                 f"{gates.get('quarantine', 0)} quarantine.")
    if quarantined:
        lines.append(f"Quarantined (held unsummarized): {', '.join(f'`{i}`' for i in sorted(quarantined))}.")

    flagged = [r for r in run.redundancy if r.flagged]
    lines += ["", f"## Flagged repeats ({len(flagged)})", ""]
    for r in flagged:
        lines.append(f"- {name(r.email_id)}: repeats {name(r.nearest or '')} "
                     f"(content {r.content_similarity or 0.0:.2f}, subject {r.subject_score or 0.0:.2f})")
    if not flagged:
        lines.append("None.")

    lines += ["", f"## Attention notes ({len(run.notes)})", ""]
    for n in run.notes:
        deadline = f", by {n.deadline.strftime('%Y-%m-%d %H:%M')}" if n.deadline else ""
        lines.append(f"- {name(n.email_id)}: {n.action}{deadline}. {n.why_attention}")
    if not run.notes:
        lines.append("None.")

    by_id = {s.id: s for s in run.suggestions}
    lists = (("Thesis changes", run.brief.thesis_changes if run.brief else []),
             ("New thesis candidates", run.brief.new_theses if run.brief else []),
             ("Worth watching", run.brief.worth_watching if run.brief else []))
    lines += ["", f"## Suggestions ({len(run.suggestions)})", ""]
    for title, ids in lists:
        lines.append(f"**{title}** ({len(ids)})")
        lines.append("")
        for sid in ids:
            s = by_id.get(sid)
            if s is None:
                continue
            target = (f"{s.body.pillar_id} {s.body.stance}, strength {s.body.strength}"
                      if isinstance(s.body, ExistingThesis)
                      else f"new {s.body.ticker} thesis" if isinstance(s.body, NewThesis) else s.body.kind)
            mark = " (second look)" if s.second_look else ""
            lines.append(f"- `{sid}` ({target}){mark}: {s.rationale}")
        if not ids:
            lines.append("None.")
        lines.append("")

    alerts = run.brief.alerts if run.brief else []
    lines += [f"## Alerts ({len(alerts)})", ""]
    for a in alerts:
        lines.append(f"- {a.kind}: {name(a.ref_id) if a.kind == 'human_attention' else f'`{a.ref_id}`'}")
    if not alerts:
        lines.append("None.")

    lines += ["", "## Monitoring", ""]
    m = run.metrics
    if m is None:
        lines.append("No metrics for this run.")
    else:
        spent = sum(u.input_tokens + u.output_tokens for u in m.stages.values())
        uncached = sum(u.uncached_input_tokens + u.uncached_output_tokens for u in m.stages.values())
        calls = sum(u.calls for u in m.stages.values())
        hits = sum(u.cache_hits for u in m.stages.values())
        lines += [
            f"- Tokens spent: {spent:,} (uncached cost {uncached:,}); {m.tokens_per_email_mean:,.0f} per email",
            f"- Cache hits: {hits:,} of {calls:,} calls",
            f"- Email latency: p50 {_ms(m.email_latency_p50_ms)}, p95 {_ms(m.email_latency_p95_ms)}",
            f"- Total time: {_ms(m.total_latency_ms)}",
        ]
    return "\n".join(lines) + "\n"


def _list[M: BaseModel](path: Path, model: type[M]) -> list[M]:
    return read_list(path, model) if path.exists() else []


def _one[M: BaseModel](path: Path, model: type[M]) -> M | None:
    return read_one(path, model) if path.exists() else None


def criteria_version(triage: Sequence[TriageRecord]) -> str:
    counts = Counter(t.criteria_version for t in triage)
    return counts.most_common(1)[0][0] if counts else ""


def read(out_dir: Path, corpus_set: str, emails: list[Email], metrics: UsageReport | None,
         thresholds: Thresholds) -> RunOutputs:
    starting = limits.starting_thresholds()
    return RunOutputs(
        corpus_set=corpus_set,
        emails=emails,
        tuned=thresholds.model_dump() != starting.model_dump(),
        criteria_version=criteria_version(_list(out_dir / "triage.json", TriageRecord)),
        results=_list(out_dir / "results.json", EmailResult),
        redundancy=_list(out_dir / "redundancy.json", RedundancyRecord),
        notes=_list(out_dir / "notes.json", AttentionNote),
        suggestions=_list(out_dir / "suggestions.json", Suggestion),
        brief=_one(out_dir / "brief.json", Brief),
        metrics=metrics or _one(out_dir / "metrics.json", UsageReport),
    )


def write(out_dir: Path, corpus_set: str, emails: list[Email], metrics: UsageReport | None,
          thresholds: Thresholds) -> Path:
    path = out_dir / FILE
    path.write_text(render(read(out_dir, corpus_set, emails, metrics, thresholds)))
    return path
