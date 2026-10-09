"""Stage 3 Classify: parsed.json -> triage.json.

Owned by work package 4 (Classify and gate). See SPEC.md: Classification with Jev; Relevance criteria; Calling Jev.

`run` is the fixed interface run.py calls. Inside it, wrap each email's `process` call in
`with ctx.recorder.stage(STAGE, email_id):` so monitoring times it per email.
"""

from pathlib import Path

from triage_app.pipeline.context import RunContext
from triage_app.schema import Email, TriageRecord

STAGE = "classify"


def run(in_dir: Path, out_dir: Path, ctx: RunContext) -> None:
    raise NotImplementedError(f"stage {STAGE} is not built yet")


def process(email: Email, ctx: RunContext) -> TriageRecord:
    """One Jev request with all 14 questions; the email and the criteria only."""
    raise NotImplementedError(f"stage {STAGE} is not built yet")
