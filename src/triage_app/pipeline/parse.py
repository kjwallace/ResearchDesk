"""Stage 1 Parse: data/corpus/<set>/emails.jsonl -> raw.json, parsed.json.

Owned by work package 2 (Corpus and parse). See SPEC.md: Data flow; Corpus.

`run` is the fixed interface run.py calls. Inside it, wrap each email's `process` call in
`with ctx.recorder.stage(STAGE, email_id):` so monitoring times it per email.
"""

from pathlib import Path

from triage_app.pipeline.context import RunContext
from triage_app.schema import Email

STAGE = "parse"


def run(in_dir: Path, out_dir: Path, ctx: RunContext) -> None:
    raise NotImplementedError(f"stage {STAGE} is not built yet")


def process(email: Email) -> Email:
    """The email with its body cleaned: the text of record every model reads."""
    raise NotImplementedError(f"stage {STAGE} is not built yet")
