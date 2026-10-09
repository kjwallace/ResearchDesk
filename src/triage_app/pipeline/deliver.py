"""Stage 9 Deliver: results.json, notes.json, analysis.json, suggestions.json -> brief.json.

Owned by work package 7 (State and app). See SPEC.md: Where each email appears; Order and alerts.

`run` is the fixed interface run.py calls. Inside it, wrap each email's `process` call in
`with ctx.recorder.stage(STAGE, email_id):` so monitoring times it per email.
"""

from pathlib import Path

from triage_app.pipeline.context import RunContext
from triage_app.schema import Brief

STAGE = "deliver"


def run(in_dir: Path, out_dir: Path, ctx: RunContext) -> None:
    raise NotImplementedError(f"stage {STAGE} is not built yet")


def process(out_dir: Path, ctx: RunContext) -> Brief:
    """Deterministic assembly of the brief from the stage files."""
    raise NotImplementedError(f"stage {STAGE} is not built yet")
