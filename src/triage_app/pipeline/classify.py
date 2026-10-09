"""Stage 3 Classify: the corpus emails -> triage.json.

Owned by work package 4 (Classify and gate). See SPEC.md: Classification with Jev; Relevance criteria; Calling Jev.

One Jev request per email with all 14 questions. Jev gets the email's four input fields
and the criteria only (modules/classify.py builds the request).
"""

from pathlib import Path

from triage_app.modules.classify import classify
from triage_app.pipeline.context import RunContext
from triage_app.pipeline.io import write_list
from triage_app.schema import Email, TriageRecord

STAGE = "classify"


def run(in_dir: Path, out_dir: Path, ctx: RunContext) -> None:
    emails = ctx.emails
    records: list[TriageRecord] = []
    for email in emails:
        with ctx.recorder.stage(STAGE, email.email_id):
            records.append(process(email, ctx))
    write_list(out_dir / "triage.json", records)


def process(email: Email, ctx: RunContext) -> TriageRecord:
    """One Jev request with all 14 questions; the email and the criteria only."""
    return classify(email, ctx.criteria, ctx.jev, cache=ctx.cache, recorder=ctx.recorder)
