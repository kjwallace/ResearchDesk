"""Stage 5 Extract: parsed.json, results.json, redundancy.json -> claims.json.

Owned by work package 6 (Analysis). See SPEC.md: Data flow; Analysis agent.

Runs only for emails whose gate is "pass", in arrival order. When an email's redundancy record
is flagged, the nearest earlier email's parsed body goes along as context and only claims it
did not make are kept; that context is skipped when the earlier email was quarantined. Every
quote is checked verbatim (after whitespace collapse) against the parsed body; failures are
dropped and counted. Code assigns claim IDs `<email_id>.c<n>`.
"""

from dataclasses import dataclass, field
from pathlib import Path

from triage_app.modules.extract import ClaimExtractor
from triage_app.pipeline.context import RunContext
from triage_app.pipeline.io import quote_in, read_list, write_list
from triage_app.schema import Claim, Email, EmailResult, RedundancyRecord

STAGE = "extract"


@dataclass
class Extraction:
    claims: list[Claim] = field(default_factory=list)
    dropped_quotes: int = 0     # quote not found verbatim in the email body
    dropped_repeats: int = 0    # quote found verbatim in the earlier email: a claim it already made


def run(in_dir: Path, out_dir: Path, ctx: RunContext) -> None:
    emails = read_list(in_dir / "parsed.json", Email)
    results = {r.email_id: r for r in read_list(in_dir / "results.json", EmailResult)}
    redundancy = {r.email_id: r for r in read_list(in_dir / "redundancy.json", RedundancyRecord)}
    by_id = {e.email_id: e for e in emails}
    extractor = ClaimExtractor(ctx.chat)

    claims: list[Claim] = []
    passed = dropped_quotes = dropped_repeats = 0
    for email in emails:
        result = results.get(email.email_id)
        if result is None or result.gate != "pass":
            continue
        earlier = earlier_context(redundancy.get(email.email_id), by_id, results)
        with ctx.recorder.stage(STAGE, email.email_id):
            out = extract(email, result, earlier, ctx, extractor)
        passed += 1
        claims.extend(out.claims)
        dropped_quotes += out.dropped_quotes
        dropped_repeats += out.dropped_repeats
    write_list(out_dir / "claims.json", claims)
    print(f"  {STAGE}: {len(claims)} claims from {passed} passed emails; "
          f"{dropped_quotes} dropped for a quote mismatch, {dropped_repeats} as repeats", flush=True)


def earlier_context(record: RedundancyRecord | None, emails: dict[str, Email],
                    results: dict[str, EmailResult]) -> Email | None:
    """The nearest earlier email when this one is a flagged repeat, unless that one was quarantined."""
    if record is None or not record.flagged or record.nearest is None:
        return None
    nearest = results.get(record.nearest)
    if nearest is None or nearest.gate == "quarantine":
        return None
    return emails.get(record.nearest)


def process(email: Email, result: EmailResult, earlier: Email | None, ctx: RunContext) -> list[Claim]:
    """Claims from one passed email; with `earlier`, only claims the earlier email did not make."""
    return extract(email, result, earlier, ctx).claims


def extract(email: Email, result: EmailResult, earlier: Email | None, ctx: RunContext,
            extractor: ClaimExtractor | None = None) -> Extraction:
    if result.gate != "pass":
        return Extraction()
    drafts = (extractor or ClaimExtractor(ctx.chat))(email, earlier)
    out = Extraction()
    for draft in drafts:
        if not quote_in(draft.quote, email.body):
            out.dropped_quotes += 1
            continue
        if earlier is not None and quote_in(draft.quote, earlier.body):
            out.dropped_repeats += 1
            continue
        n = len(out.claims) + 1
        out.claims.append(Claim(**draft.model_dump(), id=f"{email.email_id}.c{n}", email_id=email.email_id))
    return out
