"""Stage 1 Parse: data/corpus/<set>/emails.jsonl -> raw.json, parsed.json.

Owned by work package 2 (Corpus and parse). See SPEC.md: Data flow; Corpus.

The parsed body is the text of record: every model reads it and every quote is checked
against it, so cleaning is conservative. It fixes line endings and invisible characters
and trims blank space; it never rewords or drops content. Labels never leave the loader.
"""

import re
from pathlib import Path

from triage_app.corpus import load
from triage_app.pipeline.context import RunContext
from triage_app.pipeline.io import write_list
from triage_app.schema import Email

STAGE = "parse"

_ZERO_WIDTH = re.compile("[​‌‍⁠﻿]")
_NBSP = re.compile("[  ]")
_TRAILING = re.compile(r"[ \t]+$", re.MULTILINE)
_BLANK_RUN = re.compile(r"\n{4,}")  # three or more blank lines


def clean_body(body: str) -> str:
    text = body.replace("\r\n", "\n").replace("\r", "\n")
    text = _ZERO_WIDTH.sub("", text)
    text = _NBSP.sub(" ", text)
    text = _TRAILING.sub("", text)
    text = _BLANK_RUN.sub("\n\n\n", text)
    return text.strip()


def run(in_dir: Path, out_dir: Path, ctx: RunContext) -> None:
    emails, _ = load(in_dir / "emails.jsonl", ctx.corpus_set)
    parsed: list[Email] = []
    for email in emails:
        with ctx.recorder.stage(STAGE, email.email_id):
            parsed.append(process(email))
    write_list(out_dir / "raw.json", emails)
    write_list(out_dir / "parsed.json", parsed)


def process(email: Email) -> Email:
    """The email with its body cleaned: the text of record every model reads."""
    return email.model_copy(update={"body": clean_body(email.body)})
