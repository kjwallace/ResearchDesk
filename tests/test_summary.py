"""SUMMARY.md (pipeline/summary.py) and the end of a run (pipeline/run.py), on the fixtures."""

from pathlib import Path

from fakes import FIXTURE_EMAILS, FakeEmbedder, fixture_emails

from triage_app import config, thresholds
from triage_app.pipeline import run, summary
from triage_app.pipeline.context import RunContext
from triage_app.pipeline.io import read_list
from triage_app.schema import EmailLabel, EmailResult, RedundancyRecord

OUT = config.FIXTURES_DIR / "out"


def fixture_summary() -> str:
    return summary.render(summary.read(OUT, "day_1", fixture_emails(), None, thresholds.starting_thresholds()))


def test_fixture_summary_is_what_the_function_writes() -> None:
    assert fixture_summary() == (OUT / summary.FILE).read_text()


def test_summary_holds_no_body_and_no_label() -> None:
    text = fixture_summary()
    results = read_list(OUT / "results.json", EmailResult)
    bodies = {e.email_id: e.body for e in fixture_emails()}
    for r in results:
        if r.gate == "quarantine":
            words = bodies[r.email_id].split()
            assert all(" ".join(words[i:i + 6]) not in text for i in range(0, len(words) - 6, 3))
    for line in (config.FIXTURES_DIR / "labels.jsonl").read_text().splitlines():
        assert EmailLabel.model_validate_json(line).reason not in text
    for heading in ("Flagged repeats (1)", "Attention notes (1)", "Thesis changes", "Alerts (1)", "Monitoring",
                    "starting values", "fixture0000", "Gate: 6 pass, 2 stop, 2 quarantine"):
        assert heading in text
    assert "`MSFT.p1.supports`" in text and "`AMZN.new1`" in text


def test_tuned_thresholds_are_named() -> None:
    tuned = thresholds.starting_thresholds().model_copy(update={"pass_signal": 0.9})
    text = summary.render(summary.read(OUT, "day_1", fixture_emails(), None, tuned))
    assert "tuned (tuned/thresholds.json)" in text


def test_partial_run_still_summarizes(tmp_path: Path) -> None:
    text = summary.render(summary.read(tmp_path, "day_2", [], None, thresholds.starting_thresholds()))
    assert "day_2" in text and "No metrics for this run." in text


def test_run_reads_the_corpus_file_and_writes_only_its_outputs(tmp_path: Path) -> None:
    assert "parse" not in run.STAGES and "human_attention" in run.STAGES
    ctx = RunContext("day_1", embedder=FakeEmbedder(), use_cache=False)  # type: ignore[arg-type]
    run.run_set("day_1", ["redundancy"], ctx, emails_path=FIXTURE_EMAILS, out=tmp_path)
    assert ctx.emails_path == FIXTURE_EMAILS
    assert sorted(p.name for p in tmp_path.iterdir()) == ["SUMMARY.md", "metrics.json", "redundancy.json"]
    assert [r.email_id for r in read_list(tmp_path / "redundancy.json", RedundancyRecord)] == ["fixture_006"]
    assert "10 emails" in (tmp_path / "SUMMARY.md").read_text()
