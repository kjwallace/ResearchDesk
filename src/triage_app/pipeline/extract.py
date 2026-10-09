"""Stage 5 Extract: parsed.json, results.json, redundancy.json -> claims.json.

Owned by work package 6 (Analysis). See SPEC.md: Data flow; Analysis agent.

`run` is the fixed interface run.py calls. Inside it, wrap each email's `process` call in
`with ctx.recorder.stage(STAGE, email_id):` so monitoring times it per email.
"""

from pathlib import Path

from triage_app.pipeline.context import RunContext
from triage_app.schema import Claim, Email, EmailResult

STAGE = "extract"


def run(in_dir: Path, out_dir: Path, ctx: RunContext) -> None:
    raise NotImplementedError(f"stage {STAGE} is not built yet")


def process(email: Email, result: EmailResult, earlier: Email | None, ctx: RunContext) -> list[Claim]:
    """Claims from one passed email; with `earlier`, only claims the earlier email did not make."""
    raise NotImplementedError(f"stage {STAGE} is not built yet")
