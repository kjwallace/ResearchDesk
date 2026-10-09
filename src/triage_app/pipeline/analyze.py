"""Stage 6 Analyze: claims.json, results.json, seed -> analysis.json, suggestions_raw.json.

Owned by work package 6 (Analysis). See SPEC.md: Analysis agent; Read-through links.

`run` is the fixed interface run.py calls. Inside it, wrap each email's `process` call in
`with ctx.recorder.stage(STAGE, email_id):` so monitoring times it per email.
"""

from pathlib import Path

from triage_app.pipeline.context import RunContext
from triage_app.schema import AnalysisRecord, Claim, EmailResult, Suggestion

STAGE = "analyze"


def run(in_dir: Path, out_dir: Path, ctx: RunContext) -> None:
    raise NotImplementedError(f"stage {STAGE} is not built yet")


def process(email_id: str, claims: list[Claim], result: EmailResult, ctx: RunContext) -> tuple[AnalysisRecord, list[Suggestion]]:
    """Run the analysis agent (at most three skill calls) for one email."""
    raise NotImplementedError(f"stage {STAGE} is not built yet")
