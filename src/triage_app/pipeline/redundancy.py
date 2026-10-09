"""Stage 2 Check for repeats: parsed.json -> redundancy.json, vectors.npy.

Owned by work package 3 (Redundancy). See SPEC.md: Redundancy check; Starting values.

`run` is the fixed interface run.py calls. Inside it, wrap each email's `process` call in
`with ctx.recorder.stage(STAGE, email_id):` so monitoring times it per email.
"""

from pathlib import Path

from typing import Any

from triage_app.pipeline.context import RunContext
from triage_app.schema import Email, RedundancyRecord

STAGE = "redundancy"


def run(in_dir: Path, out_dir: Path, ctx: RunContext) -> None:
    raise NotImplementedError(f"stage {STAGE} is not built yet")


def process(email: Email, day: Any, ctx: RunContext) -> RedundancyRecord:
    """Compare one email with the earlier emails in `day` (the day cache), then add it to the cache."""
    raise NotImplementedError(f"stage {STAGE} is not built yet")
