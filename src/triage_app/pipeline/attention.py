"""Stage A Write attention notes: parsed.json, results.json -> notes.json.

Owned by work package 5 (Attention notes). See SPEC.md: Attention pathway.

`run` is the fixed interface run.py calls. Inside it, wrap each email's `process` call in
`with ctx.recorder.stage(STAGE, email_id):` so monitoring times it per email.
"""

from pathlib import Path

from triage_app.pipeline.context import RunContext
from triage_app.schema import AttentionNote, Email, EmailResult

STAGE = "attention"


def run(in_dir: Path, out_dir: Path, ctx: RunContext) -> None:
    raise NotImplementedError(f"stage {STAGE} is not built yet")


def process(email: Email, result: EmailResult, ctx: RunContext) -> AttentionNote:
    """A note for one flagged email; sections failing the string match are dropped and counted."""
    raise NotImplementedError(f"stage {STAGE} is not built yet")
