"""Stage 6 Analyze: claims.json, results.json, seed -> analysis.json, suggestions_raw.json.

Owned by work package 6 (Analysis). See SPEC.md: Analysis agent; Read-through links.

One AnalysisRecord per passed email, in arrival order. Code picks the candidate pillars, runs
the agent, and builds every raw suggestion from the skills' parsed results: IDs
`<email_id>.s<n>`, status open, and each linked assumption's book and consensus values filled
from the book. Code also:

- drops existing-thesis drafts with stance "none" (the skill considered the pillar and found
  no direct bearing);
- keeps at most `thresholds.MAX_THESIS_SUGGESTIONS_PER_EMAIL` existing-thesis suggestions per
  email, the most relevant (ties go to the earlier draft);
- fills a projection's book and consensus values with `state.compute.metric_value`, and drops
  a projection whose metric is neither a driver of that company nor an output metric.

The no-change reason is "no claims extracted" when stage 5 found none, the last skill's own
reason when skills ran but suggested nothing, and the agent's final text only when it called
no skill.
"""

from dataclasses import dataclass, field
from pathlib import Path

from triage_app.llm import failure_note
from triage_app import thresholds
from triage_app.modules.analysis_agent import AgentOutcome, AnalysisAgent, candidate_pillars
from triage_app.modules.skills import SkillContext
from triage_app.pipeline.context import RunContext
from triage_app.pipeline.io import read_list, write_list
from triage_app.schema import (
    AnalysisRecord,
    Claim,
    EmailResult,
    ExistingThesis,
    ExistingThesisDraft,
    LinkedAssumption,
    NewThesis,
    NewThesisDraft,
    ProjectionChange,
    ProjectionDraft,
    Suggestion,
)
from triage_app.state.compute import metric_value
from triage_app.state.fold import BookState, fold, load_seed

STAGE = "analyze"
NO_CLAIMS = "no claims extracted"
NO_REASON = "no reason given"
NO_BEARING = "no claim bears directly on a candidate pillar"


@dataclass
class Collected:
    """One email's raw suggestions, and how many drafts code dropped and why."""

    suggestions: list[Suggestion] = field(default_factory=list)
    no_bearing: int = 0          # existing-thesis drafts with stance "none"
    over_cap: int = 0            # existing-thesis drafts beyond the per-email cap
    unknown_metric: int = 0      # projections on a metric the company's model lacks

    def add(self, other: "Collected") -> None:
        self.no_bearing += other.no_bearing
        self.over_cap += other.over_cap
        self.unknown_metric += other.unknown_metric


def run(in_dir: Path, out_dir: Path, ctx: RunContext) -> None:
    claims = read_list(in_dir / "claims.json", Claim)
    results = read_list(in_dir / "results.json", EmailResult)
    book = fold(load_seed(), [])
    agent = AnalysisAgent(ctx.chat)

    records: list[AnalysisRecord] = []
    suggestions: list[Suggestion] = []
    dropped = Collected()
    for result in results:  # results.json is in arrival order
        if result.gate != "pass":
            continue
        own = [c for c in claims if c.email_id == result.email_id]
        try:
            with ctx.recorder.stage(STAGE, result.email_id):
                record, made = process(result.email_id, own, result, ctx, book=book, agent=agent,
                                       dropped=dropped)
        except Exception as e:  # one bad model reply must not abort the stage
            record, made = AnalysisRecord(email_id=result.email_id, skills_called=[], suggestion_ids=[],
                                          no_change_reason=f"analysis failed: {type(e).__name__}"), []
            print(f"  {STAGE}: analysis failed for {result.email_id} ({failure_note(e)})", flush=True)
        records.append(record)
        suggestions.extend(made)
    print(f"  {STAGE}: dropped {dropped.no_bearing} no-bearing, {dropped.over_cap} over the per-email cap, "
          f"{dropped.unknown_metric} unknown-metric draft(s)", flush=True)
    write_list(out_dir / "analysis.json", records)
    write_list(out_dir / "suggestions_raw.json", suggestions)


def process(email_id: str, claims: list[Claim], result: EmailResult, ctx: RunContext,
            *, book: BookState | None = None,
            agent: AnalysisAgent | None = None,
            dropped: Collected | None = None) -> tuple[AnalysisRecord, list[Suggestion]]:
    """Run the analysis agent (at most three skill calls) for one email.

    `dropped`, when given, accumulates the counts of drafts code dropped.
    """
    if not claims:
        return AnalysisRecord(email_id=email_id, skills_called=[], suggestion_ids=[],
                              no_change_reason=NO_CLAIMS), []
    book = book or fold(load_seed(), [])
    context = SkillContext(book=book, candidate_pillar_ids=candidate_pillars(claims, book),
                           email_triage={email_id: result.triage or "unlabeled"})
    outcome = (agent or AnalysisAgent(ctx.chat))(claims, context)
    collected = collect(email_id, outcome, book)
    if dropped is not None:
        dropped.add(collected)
    suggestions = collected.suggestions
    return AnalysisRecord(
        email_id=email_id,
        skills_called=outcome.skills_called,
        suggestion_ids=[s.id for s in suggestions],
        no_change_reason=None if suggestions else no_change_reason(outcome, collected),
    ), suggestions


def no_change_reason(outcome: AgentOutcome, collected: Collected | None = None) -> str:
    if collected is not None and collected.no_bearing:
        return NO_BEARING
    if outcome.skills_called:
        last = outcome.results[-1].no_change_reason if outcome.results else None
        return last or NO_REASON
    return outcome.final_text or NO_REASON


def existing_body(draft: ExistingThesisDraft, book: BookState) -> ExistingThesis:
    drivers = {d.id: d for m in book.models.values() for d in m.drivers}
    assert draft.stance != "none"
    return ExistingThesis(
        kind="existing_thesis", pillar_id=draft.pillar_id, stance=draft.stance,
        strength=draft.strength, relevance=draft.relevance, wrong_if_met=draft.wrong_if_met,
        # An unknown driver has no book value to show; stage 7 handles unlinked ones.
        assumptions=[LinkedAssumption(driver_id=a.driver_id, stated_value=a.stated_value,
                                      book_value=drivers[a.driver_id].analyst,
                                      consensus_value=drivers[a.driver_id].consensus)
                     for a in draft.assumptions if a.driver_id in drivers],
        street_view_shift=draft.street_view_shift, street_view_note=draft.street_view_note,
    )


def projection_body(draft: ProjectionDraft, book: BookState) -> ProjectionChange | None:
    """The email's figure with the book's and consensus values filled by code; None for an unknown metric."""
    model = book.models.get(draft.ticker)
    if model is None:
        return None
    book_value = metric_value(model, draft.metric, "analyst")
    consensus_value = metric_value(model, draft.metric, "consensus")
    if book_value is None or consensus_value is None:
        return None
    return ProjectionChange(kind="projection_change", ticker=draft.ticker, metric=draft.metric,
                            period=draft.period, stated_value=draft.stated_value,
                            book_value=book_value, consensus_value=consensus_value)


def collect(email_id: str, outcome: AgentOutcome, book: BookState) -> Collected:
    """Raw suggestions from the skills' parsed drafts, in call order. Never from the agent's text."""
    collected = Collected()
    drafts: list[tuple[ExistingThesisDraft | NewThesisDraft | ProjectionDraft,
                       ExistingThesis | NewThesis | ProjectionChange]] = []
    for result in outcome.results:
        for draft in result.suggestions:
            body: ExistingThesis | NewThesis | ProjectionChange | None
            if isinstance(draft, ExistingThesisDraft):
                if draft.stance == "none":
                    collected.no_bearing += 1
                    continue
                body = existing_body(draft, book)
            elif isinstance(draft, ProjectionDraft):
                body = projection_body(draft, book)
                if body is None:
                    collected.unknown_metric += 1
                    continue
            else:
                body = NewThesis(kind="new_thesis", ticker=draft.ticker, statement=draft.statement,
                                 wrong_if=draft.wrong_if, driver_ids=draft.driver_ids)
            drafts.append((draft, body))

    # The per-email cap on existing-thesis suggestions: the most relevant, earlier first on ties.
    existing = [i for i, (_, b) in enumerate(drafts) if isinstance(b, ExistingThesis)]
    ranked = sorted(existing, key=lambda i: -_relevance(drafts[i][1]))
    over = set(ranked[thresholds.MAX_THESIS_SUGGESTIONS_PER_EMAIL:])
    collected.over_cap = len(over)

    for i, (draft, body) in enumerate(drafts):
        if i in over:
            continue
        collected.suggestions.append(Suggestion(
            id=f"{email_id}.s{len(collected.suggestions) + 1}", body=body, rationale=draft.rationale,
            claim_ids=draft.claim_ids, sections=draft.sections, status="open",
        ))
    return collected


def _relevance(body: ExistingThesis | NewThesis | ProjectionChange) -> float:
    return body.relevance if isinstance(body, ExistingThesis) else 0.0
