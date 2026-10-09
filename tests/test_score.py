import csv
import shutil
from pathlib import Path

import pytest
from fakes import fixture_emails

from triage_app import config
from triage_app.evals import score
from triage_app.pipeline.io import read_one
from triage_app.schema import EmailLabel, EvalReport

FIXTURES = config.FIXTURES_DIR


@pytest.fixture
def out_dir(tmp_path: Path) -> Path:
    out = tmp_path / "out"
    shutil.copytree(FIXTURES / "out", out)
    (out / "eval.json").unlink()
    return out


def labels() -> list[EmailLabel]:
    return score.read_labels_file(FIXTURES / "labels.jsonl")


def rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="") as f:
        return list(csv.DictReader(f))


def test_score_writes_valid_eval_and_sheets(out_dir: Path) -> None:
    score.score_set("day_1", out_dir, labels(), fixture_emails())
    report = read_one(out_dir / "eval.json", EvalReport)
    expected = read_one(FIXTURES / "out" / "eval.json", EvalReport)
    assert report.corpus == "day_1" and report.criteria_version == "fixture0000"
    assert report.measures == expected.measures
    assert report.confusion == expected.confusion
    assert {(m.email_id, m.measure) for m in expected.misses} <= {(m.email_id, m.measure) for m in report.misses}

    notes = rows(out_dir / score.NOTES_SHEET)
    assert [(r["id"], r["kind"]) for r in notes] == [("fixture_007", "note")]
    assert list(notes[0]) == list(score.NOTE_COLUMNS)
    suggestions = rows(out_dir / score.SUGGESTIONS_SHEET)
    assert {r["kind"] for r in suggestions} == {"existing_thesis", "new_thesis"}
    assert len(suggestions) == 4


def test_filled_sheets_are_kept_and_read(out_dir: Path) -> None:
    score.write_sheets(out_dir)
    path = out_dir / score.SUGGESTIONS_SHEET
    filled = rows(path)
    for r in filled:
        if r["kind"] == "existing_thesis":
            r.update(right_pillar="yes", right_stance="yes", sections_support="yes" if r["id"] != "AAPL.p1.supports" else "no")
        else:
            r.update(new_to_book="yes", sections_support="yes")
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=score.SUGGESTION_COLUMNS)
        writer.writeheader()
        writer.writerows(filled)

    written = score.write_sheets(out_dir)
    assert path not in written and rows(path) == filled
    report = score.score_set("day_1", out_dir, labels(), fixture_emails())
    assert report.measures["suggestion_review"] == pytest.approx(0.6667)
    assert report.measures["new_thesis_review"] == 1.0
    assert report.measures["note_review"] is None


def test_missing_suggestions_file_leaves_stray_empty(out_dir: Path) -> None:
    (out_dir / "suggestions.json").unlink()
    report = score.evaluate("day_1", out_dir, labels(), fixture_emails())
    assert report.measures["stray_suggestions"] is None
    assert report.measures["quote_faithfulness"] == 1.0
