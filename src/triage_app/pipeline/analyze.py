"""Stage 6 Analyze: claims.json, results.json, seed -> analysis.json, suggestions_raw.json.

Owned by work package 6 (Analysis). See SPEC.md: Analysis agent; Read-through links.

One AnalysisRecord per passed email, in arrival order. Code picks the candidate pillars, runs
the agent, and builds every raw suggestion from the skills' parsed results: IDs
`<email_id>.s<n>`, status open, and each linked assumption's book and consensus values filled
from the book. The no-change reason is "no claims extracted" when stage 5 found none, the last
skill's own reason when skills ran but suggested nothing, and the agent's final text only when
it called no skill.
"""

from pathlib import Path

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
    Suggestion,
)
from triage_app.state.fold import BookState, fold, load_seed

STAGE = "analyze"
NO_CLAIMS = "no claims extracted"
NO_REASON = "no reason given"


def run(in_dir: Path, out_dir: Path, ctx: RunContext) -> None:
    claims = read_list(in_dir / "claims.json", Claim)
    results = read_list(in_dir / "results.json", EmailResult)
    book = fold(load_seed(), [])
    agent = AnalysisAgent(ctx.chat)

    records: list[AnalysisRecord] = []
    suggestions: list[Suggestion] = []
    for result in results:  # results.json is in arrival order
        if result.gate != "pass":
            continue
        own = [c for c in claims if c.email_id == result.email_id]
        with ctx.recorder.stage(STAGE, result.email_id):
            record, made = process(result.email_id, own, result, ctx, book=book, agent=agent)
        records.append(record)
        suggestions.extend(made)
    write_list(out_dir / "analysis.json", records)
    write_list(out_dir / "suggestions_raw.json", suggestions)


def process(email_id: str, claims: list[Claim], result: EmailResult, ctx: RunContext,
            *, book: BookState | None = None,
            agent: AnalysisAgent | None = None) -> tuple[AnalysisRecord, list[Suggestion]]:
    """Run the analysis agent (at most three skill calls) for one email."""
    if not claims:
        return AnalysisRecord(email_id=email_id, skills_called=[], suggestion_ids=[],
                              no_change_reason=NO_CLAIMS), []
    book = book or fold(load_seed(), [])
    context = SkillContext(book=book, candidate_pillar_ids=candidate_pillars(claims, book),
                           email_triage={email_id: result.triage or "unlabeled"})
    outcome = (agent or AnalysisAgent(ctx.chat))(claims, context)
    suggestions = collect(email_id, outcome, book)
    return AnalysisRecord(
        email_id=email_id,
        skills_called=outcome.skills_called,
        suggestion_ids=[s.id for s in suggestions],
        no_change_reason=None if suggestions else no_change_reason(outcome),
    ), suggestions


def no_change_reason(outcome: AgentOutcome) -> str:
    if outcome.skills_called:
        last = outcome.results[-1].no_change_reason if outcome.results else None
        return last or NO_REASON
    return outcome.final_text or NO_REASON


def collect(email_id: str, outcome: AgentOutcome, book: BookState) -> list[Suggestion]:
    """Raw suggestions from the skills' parsed drafts, in call order. Never from the agent's text."""
    drivers = {d.id: d for m in book.models.values() for d in m.drivers}
    out: list[Suggestion] = []
    for result in outcome.results:
        for draft in result.suggestions:
            body: ExistingThesis | NewThesis
            if isinstance(draft, ExistingThesisDraft):
                body = ExistingThesis(
                    kind="existing_thesis", pillar_id=draft.pillar_id, stance=draft.stance,
                    strength=draft.strength, wrong_if_met=draft.wrong_if_met,
                    # An unknown driver has no book value to show; stage 7 handles unlinked ones.
                    assumptions=[LinkedAssumption(driver_id=a.driver_id, stated_value=a.stated_value,
                                                  book_value=drivers[a.driver_id].analyst,
                                                  consensus_value=drivers[a.driver_id].consensus)
                                 for a in draft.assumptions if a.driver_id in drivers],
                )
            else:
                assert isinstance(draft, NewThesisDraft)
                body = NewThesis(kind="new_thesis", ticker=draft.ticker, statement=draft.statement,
                                 wrong_if=draft.wrong_if, driver_ids=draft.driver_ids)
            out.append(Suggestion(
                id=f"{email_id}.s{len(out) + 1}", body=body, rationale=draft.rationale,
                claim_ids=draft.claim_ids, sections=draft.sections, status="open",
            ))
    return out
