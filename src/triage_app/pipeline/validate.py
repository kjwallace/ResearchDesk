"""Stage 7 Validate: suggestions_raw.json, claims.json, parsed.json, results.json -> suggestions_checked.json.

Owned by work package 6 (Analysis). See SPEC.md: Validation in stage 7.

`run` is the fixed interface run.py calls. Inside it, wrap each email's `process` call in
`with ctx.recorder.stage(STAGE, email_id):` so monitoring times it per email.
"""

from pathlib import Path

from triage_app.pipeline.context import RunContext
from triage_app.schema import Suggestion

STAGE = "validate"


def run(in_dir: Path, out_dir: Path, ctx: RunContext) -> None:
    raise NotImplementedError(f"stage {STAGE} is not built yet")


def process(suggestion: Suggestion, ctx: RunContext) -> Suggestion:
    """Valid, adjusted (figure dropped, strength capped, second look), or rejected with a reason."""
    raise NotImplementedError(f"stage {STAGE} is not built yet")
