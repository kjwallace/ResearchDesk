"""Stage 8 Merge and rank: suggestions_checked.json -> suggestions.json.

Pure code. See SPEC.md: Merging in stage 8; Order and alerts (ordering only; alerts are
stage 9's). Only open suggestions are kept; rejected ones stay in suggestions_checked.json.

- Existing-thesis suggestions on the same pillar and stance merge into one, with ID
  `<pillar_id>.<stance>`: the highest strength (ties go to the email with the higher
  signal score, then the earlier suggestion), its rationale, `wrong_if_met` if any had it,
  assumptions pooled one per driver and stated value, and every claim and section kept.
  Opposite stances on one pillar stay two suggestions.
- New-thesis candidates for one company merge when a statement's cosine with a group's
  first statement reaches `thresholds.NEW_THESIS_MERGE`. The first candidate's statement,
  "wrong if" test and rationale are kept; drivers, claims and sections are pooled. IDs
  are `<ticker>.new<n>`, numbered per company in arrival order.
- Projection changes merge when ticker, metric, period and stated value all match; claims
  and sections are pooled and the suggestion from the email with the highest signal score
  (then the earlier one) leads. Different stated values for one metric stay separate. IDs
  are `<ticker>.<metric>.proj<n>`, numbered per company and metric in arrival order; a
  driver metric already starts with its ticker, so it is not repeated
  (`MSFT.intelligent_cloud_growth.proj1`, `MSFT.eps.proj1`).
- Second look is recomputed from the merged emails.
- Order: existing pillars by position size, then strength, then the highest signal score
  among the linked emails; then projection changes by position size, then signal score;
  then new-thesis candidates by position size, then signal score.
"""

from collections import defaultdict
from pathlib import Path
from typing import Any

from triage_app import thresholds
from triage_app import config
from triage_app.pipeline.context import RunContext
from triage_app.pipeline.io import read_list, write_list
from triage_app.pipeline.validate import linked_emails, needs_second_look
from triage_app.schema import (
    EmailResult,
    ExistingThesis,
    LinkedAssumption,
    LinkedSection,
    NewThesis,
    ProjectionChange,
    Suggestion,
)
from triage_app.state.fold import Seed, load_seed

STAGE = "merge"


def _signal(s: Suggestion, results: dict[str, EmailResult]) -> float:
    return max((results[e].signal_score for e in linked_emails(s) if e in results), default=0.0)


def _pool(group: list[Suggestion]) -> dict[str, Any]:
    """Every claim and every distinct section of the group, in first-seen order."""
    sections: dict[tuple[str, str], LinkedSection] = {}
    for s in group:
        for sec in s.sections:
            sections.setdefault((sec.email_id, sec.quote), sec)
    return {
        "claim_ids": list(dict.fromkeys(c for s in group for c in s.claim_ids)),
        "sections": list(sections.values()),
    }


def merge_existing(group: list[Suggestion], results: dict[str, EmailResult]) -> Suggestion:
    """One suggestion for one pillar and stance."""
    bodies = [s.body for s in group if isinstance(s.body, ExistingThesis)]
    strongest = max(range(len(group)),
                    key=lambda i: (bodies[i].strength, _signal(group[i], results), -i))
    pooled: dict[tuple[str, float], LinkedAssumption] = {}
    for b in bodies:
        for a in b.assumptions:
            pooled.setdefault((a.driver_id, a.stated_value), a)
    body = bodies[strongest].model_copy(update={
        "wrong_if_met": any(b.wrong_if_met for b in bodies),
        "assumptions": list(pooled.values()),
    })
    lead = bodies[strongest]
    return group[strongest].model_copy(update={
        "id": f"{lead.pillar_id}.{lead.stance}", "body": body, **_pool(group),
    })


def merge_new(group: list[Suggestion], ticker: str, n: int) -> Suggestion:
    """One candidate from similar new-thesis candidates for one company; the first is kept."""
    bodies = [s.body for s in group if isinstance(s.body, NewThesis)]
    drivers = list(dict.fromkeys(d for b in bodies for d in b.driver_ids))
    return group[0].model_copy(update={
        "id": f"{ticker}.new{n}", "body": bodies[0].model_copy(update={"driver_ids": drivers}),
        **_pool(group),
    })


def projection_id(body: ProjectionChange, n: int) -> str:
    stem = body.metric if body.metric.startswith(f"{body.ticker}.") else f"{body.ticker}.{body.metric}"
    return f"{stem}.proj{n}"


def merge_projection(group: list[Suggestion], n: int, results: dict[str, EmailResult]) -> Suggestion:
    """One suggestion for one company, metric, period and stated value."""
    lead = max(range(len(group)), key=lambda i: (_signal(group[i], results), -i))
    body = group[lead].body
    assert isinstance(body, ProjectionChange)
    return group[lead].model_copy(update={"id": projection_id(body, n), **_pool(group)})


def group_new(candidates: list[Suggestion], ctx: RunContext) -> list[list[Suggestion]]:
    """Greedy grouping in arrival order against each group's first statement."""
    if not candidates:
        return []
    vectors = ctx.embedder.embed([s.body.statement for s in candidates if isinstance(s.body, NewThesis)])
    groups: list[list[int]] = []
    for i in range(len(candidates)):
        for g in groups:
            if float(vectors[g[0]] @ vectors[i]) >= thresholds.NEW_THESIS_MERGE:
                g.append(i)
                break
        else:
            groups.append([i])
    return [[candidates[i] for i in g] for g in groups]


def process(suggestions: list[Suggestion], ctx: RunContext, results: list[EmailResult],
            seed: Seed) -> list[Suggestion]:
    """One suggestion per pillar and stance, merged and ordered."""
    by_email = {r.email_id: r for r in results}
    size: dict[str, int] = {t.ticker: t.size_bps for t in seed.theses}
    existing: dict[tuple[str, str], list[Suggestion]] = defaultdict(list)
    new: dict[str, list[Suggestion]] = defaultdict(list)
    projections: dict[tuple[str, str, str, float], list[Suggestion]] = defaultdict(list)
    for s in suggestions:
        if s.status != "open":
            continue
        if isinstance(s.body, ExistingThesis):
            existing[(s.body.pillar_id, s.body.stance)].append(s)
        elif isinstance(s.body, NewThesis):
            new[s.body.ticker].append(s)
        elif isinstance(s.body, ProjectionChange):
            b = s.body
            projections[(b.ticker, b.metric, b.period, b.stated_value)].append(s)

    merged_existing = [merge_existing(g, by_email) for g in existing.values()]
    merged_new = [merge_new(g, ticker, n)
                  for ticker, candidates in new.items()
                  for n, g in enumerate(group_new(candidates, ctx), start=1)]
    seen: dict[tuple[str, str], int] = defaultdict(int)   # per company and metric, in arrival order
    merged_projections = []
    for (ticker, metric, _, _), group in projections.items():
        seen[(ticker, metric)] += 1
        merged_projections.append(merge_projection(group, seen[(ticker, metric)], by_email))
    merged = [m.model_copy(update={"second_look": needs_second_look(m, by_email)})
              for m in merged_existing + merged_projections + merged_new]

    def ticker_of(s: Suggestion) -> str:
        b = s.body
        return b.pillar_id.split(".")[0] if isinstance(b, ExistingThesis) else b.ticker

    def strength(s: Suggestion) -> int:
        return s.body.strength if isinstance(s.body, ExistingThesis) else 0

    def section(s: Suggestion) -> int:
        return 2 if isinstance(s.body, NewThesis) else 1 if isinstance(s.body, ProjectionChange) else 0

    return sorted(merged, key=lambda s: (
        section(s), -size.get(ticker_of(s), 0), -strength(s), -_signal(s, by_email), s.id,
    ))


def run(in_dir: Path, out_dir: Path, ctx: RunContext, seed: Seed | None = None) -> None:
    # Merging works across emails, so it is timed once for the set (by run.py), not per email.
    checked = read_list(in_dir / "suggestions_checked.json", Suggestion)
    results = read_list(in_dir / "results.json", EmailResult)
    write_list(out_dir / "suggestions.json", process(checked, ctx, results, seed or load_seed()))
