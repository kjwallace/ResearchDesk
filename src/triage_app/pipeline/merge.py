"""Stage 8 Merge and rank: suggestions_checked.json -> suggestions.json.

Owned by work package 6 (Analysis). See SPEC.md: Merging in stage 8; Order and alerts.

`run` is the fixed interface run.py calls. Inside it, wrap each email's `process` call in
`with ctx.recorder.stage(STAGE, email_id):` so monitoring times it per email.
"""

from pathlib import Path

from triage_app.pipeline.context import RunContext
from triage_app.schema import Suggestion

STAGE = "merge"


def run(in_dir: Path, out_dir: Path, ctx: RunContext) -> None:
    raise NotImplementedError(f"stage {STAGE} is not built yet")


def process(suggestions: list[Suggestion], ctx: RunContext) -> list[Suggestion]:
    """One suggestion per pillar and stance, merged and ordered."""
    raise NotImplementedError(f"stage {STAGE} is not built yet")
