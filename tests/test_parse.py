import json
from pathlib import Path

from triage_app import config
from triage_app.pipeline import parse
from triage_app.pipeline.context import RunContext
from triage_app.pipeline.io import normalize_ws, read_list
from triage_app.schema import Email


def email(body: str) -> Email:
    return Email(email_id="e1", received_at="2026-10-13T05:30:00-04:00", sender="s",
                 sender_email="s@x.example", subject="subj", body=body)


def test_line_endings() -> None:
    assert parse.process(email("a\r\nb\rc")).body == "a\nb\nc"


def test_zero_width_and_nbsp() -> None:
    assert parse.process(email("a​b﻿ c d e")).body == "ab c d e"


def test_trailing_spaces_stripped() -> None:
    assert parse.process(email("line one  \t\nline two ")).body == "line one\nline two"


def test_blank_runs_collapse_to_two() -> None:
    assert parse.process(email("a\n\n\n\n\n\nb\n\n\nc\n\nd")).body == "a\n\n\nb\n\n\nc\n\nd"


def test_ends_stripped_and_content_kept() -> None:
    body = "\n\n  Hi team,\n\n  Indented  double  spaces stay.\n\n"
    out = parse.process(email(body)).body
    assert out == "Hi team,\n\n  Indented  double  spaces stay."
    assert normalize_ws(out) == normalize_ws(body)


def test_process_keeps_header_fields() -> None:
    e = email("x ")
    assert parse.process(e).model_dump(exclude={"body"}) == e.model_dump(exclude={"body"})


def test_run_writes_raw_and_parsed(tmp_path: Path) -> None:
    ctx = RunContext("day_1", use_cache=False)
    parse.run(config.FIXTURES_DIR, tmp_path, ctx)
    raw = read_list(tmp_path / "raw.json", Email)
    parsed = read_list(tmp_path / "parsed.json", Email)
    rows = [json.loads(line) for line in (config.FIXTURES_DIR / "emails.jsonl").read_text().splitlines()]
    assert [e.email_id for e in raw] == [e.email_id for e in parsed] == [r["email_id"] for r in rows]
    for r, a, b in zip(rows, raw, parsed):
        assert a.body == r["body"]
        assert normalize_ws(b.body) == normalize_ws(a.body)  # no content lost or reworded
    for name in ("raw.json", "parsed.json"):
        text = (tmp_path / name).read_text()
        assert "reason" not in json.loads(text)[0] and "triage" not in json.loads(text)[0]
    assert {t.email_id for t in ctx.recorder.timings if t.stage == "parse"} == {e.email_id for e in raw}
