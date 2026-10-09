import json
from pathlib import Path

import pytest

from triage_app import config, corpus
from triage_app.schema import Email

FIXTURE = config.FIXTURES_DIR / "emails.jsonl"


def row(email_id: str = "synthetic_000001", **over: object) -> dict[str, object]:
    base: dict[str, object] = {
        "email_id": email_id, "sender": "A Person, Firm", "sender_email": "a@firm.example",
        "subject": f"Subject {email_id}", "body": f"Body of {email_id}.", "triage": "monitor",
        "additional_labels": [], "affected_tickers": [], "human_attention": False, "reason": "r",
        "email_type": "news", "systemic": False, "angle": "a", "day": 1,
    }
    base.update(over)
    return base


def write(tmp_path: Path, rows: list[dict[str, object]]) -> Path:
    p = tmp_path / "day_1" / "emails.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("".join(json.dumps(r) + "\n" for r in rows))
    return p


def load_one(tmp_path: Path, **over: object) -> corpus.LoadResult:
    return corpus.load_with_report(write(tmp_path, [row("synthetic_000001", **over)]))


# ---- The fixtures ----

def test_fixtures_load_and_match_labels_file() -> None:
    emails, labels = corpus.load(FIXTURE)
    assert [e.email_id for e in emails] == [f"fixture_{i:03d}" for i in range(1, 11)]
    expected = [json.loads(line) for line in (config.FIXTURES_DIR / "labels.jsonl").read_text().splitlines()]
    assert [lb.model_dump() for lb in labels] == expected


def test_fixture_arrival_times_match_fixture_stage_files() -> None:
    emails, _ = corpus.load(FIXTURE)
    raw = json.loads((config.FIXTURES_DIR / "out" / "raw.json").read_text())
    assert [e.received_at.isoformat() for e in emails] == [r["received_at"] for r in raw]


def test_generation_fields_never_reach_email() -> None:
    emails, _ = corpus.load(FIXTURE)
    for field in (*corpus.GENERATION_FIELDS, *corpus.LABEL_FIELDS):
        assert field not in Email.model_fields
    assert set(emails[0].model_dump()) == {*corpus.EMAIL_FIELDS, "received_at"}


def test_arrival_times_span_the_window() -> None:
    times = corpus.arrival_times("day_2", 300)
    assert times[0].isoformat() == "2026-10-14T05:30:00-04:00"
    assert times == sorted(times) and times[-1].hour < 19


def test_set_is_inferred_from_folder(tmp_path: Path) -> None:
    p = tmp_path / "tuning" / "emails.jsonl"
    p.parent.mkdir()
    p.write_text(json.dumps(row()) + "\n")
    emails, _ = corpus.load(p)
    assert emails[0].received_at.date().isoformat() == config.SET_DATES["tuning"]


# ---- One test per normalization row ----

@pytest.mark.parametrize("value", ["relevent", "relevant", "Relevant"])
def test_relevant_spellings_read_as_thesis_relevant(tmp_path: Path, value: str) -> None:
    r = load_one(tmp_path, triage=value)
    assert r.labels[0].triage == "thesis_relevant"


def test_macro_government_splits(tmp_path: Path) -> None:
    r = load_one(tmp_path, additional_labels=["macro_government", "sector"])
    assert r.labels[0].additional_labels == ["macro", "government", "sector"]


def test_human_attention_in_additional_labels_sets_flag(tmp_path: Path) -> None:
    r = load_one(tmp_path, additional_labels=["human_attention", "macro"], human_attention=False)
    assert r.labels[0].human_attention is True and r.labels[0].additional_labels == ["macro"]
    assert not r.warnings


def test_human_attention_as_triage_is_listed_for_hand_fixing(tmp_path: Path) -> None:
    r = load_one(tmp_path, triage="human_attention")
    assert not r.labels and r.hand_fix and "human_attention" in r.hand_fix[0][1]


def test_lower_case_ticker_and_goog(tmp_path: Path) -> None:
    r = load_one(tmp_path, affected_tickers=["aapl", "GOOG", "goog", "GOOGL"])
    assert r.labels[0].affected_tickers == ["AAPL", "GOOGL"]


def test_other_label_or_ticker_is_dropped_with_warning(tmp_path: Path) -> None:
    r = load_one(tmp_path, additional_labels=["crypto", "sector"], affected_tickers=["TSLA", "NVDA"])
    assert r.labels[0].additional_labels == ["sector"] and r.labels[0].affected_tickers == ["NVDA"]
    assert len(r.warnings) == 2 and "crypto" in r.warnings[0] and "TSLA" in r.warnings[1]


def test_duplicate_subject_and_body_keeps_first(tmp_path: Path) -> None:
    a = row("synthetic_000001", subject="Same", body="Same  body\n")
    b = row("synthetic_000002", subject="Same", body="Same body")
    r = corpus.load_with_report(write(tmp_path, [a, b, row("synthetic_000003")]))
    assert [e.email_id for e in r.emails] == ["synthetic_000001", "synthetic_000003"]
    assert r.duplicates == [("synthetic_000001", "synthetic_000002")]


# ---- Checks and validation ----

def test_ids_out_of_order_are_reported(tmp_path: Path) -> None:
    r = corpus.load_with_report(write(tmp_path, [row("synthetic_000002"), row("synthetic_000001")]))
    assert len(r.emails) == 2 and any("does not increase" in w for w in r.warnings)


def test_invalid_rows_are_listed_not_kept(tmp_path: Path) -> None:
    rows = [row("synthetic_000001", triage="maybe"), row("synthetic_000002", sender=None),
            row("synthetic_000003", human_attention="sometimes"), row("synthetic_000004")]
    p = write(tmp_path, rows)
    p.write_text(p.read_text() + "{not json\n")
    r = corpus.load_with_report(p)
    assert [e.email_id for e in r.emails] == ["synthetic_000004"]
    assert [w for w, _ in r.hand_fix] == ["synthetic_000001", "synthetic_000002", "synthetic_000003", "line 5"]


def test_string_flag_is_read(tmp_path: Path) -> None:
    assert load_one(tmp_path, human_attention="true").labels[0].human_attention is True


# ---- Report, split, separation, CLI ----

def test_report_prints_targets() -> None:
    text = corpus.report(corpus.load_with_report(FIXTURE), "fixtures")
    assert "human_attention true" in text and "macro, sector or government" in text
    assert "thesis_relevant per ticker" in text and "Rows for hand fixing: 0" in text
    assert "dropped" not in text  # aapl and GOOG normalize; no warning


def test_split_is_stratified_and_fixed() -> None:
    emails, labels = corpus.load(FIXTURE)
    s1 = corpus.split_tuning(emails, labels, seed=1)
    s2 = corpus.split_tuning(emails, labels, seed=1)
    assert [e.email_id for e in s1.fit_emails] == [e.email_id for e in s2.fit_emails]
    assert len(s1.fit_emails) + len(s1.val_emails) == 10
    assert {e.email_id for e in s1.fit_emails}.isdisjoint(e.email_id for e in s1.val_emails)
    assert [lb.email_id for lb in s1.fit_labels] == [e.email_id for e in s1.fit_emails]
    # fixtures: 3 thesis_relevant and 3 monitor -> 2 fit each; 2 irrelevant -> 1; 1 each of the rest -> 1
    fit = [lb.triage for lb in s1.fit_labels]
    assert fit.count("monitor") == 2 and fit.count("thesis_relevant") == 2 and fit.count("irrelevant") == 1


def test_check_separation_removes_overlaps() -> None:
    emails, _ = corpus.load(FIXTURE)
    copy = emails[2].model_copy(update={"email_id": "synthetic_000601", "body": emails[2].body + "  "})
    kept, overlaps = corpus.check_separation([copy, *emails[:2]], {"day_1": emails[2:]})
    assert [e.email_id for e in kept] == ["fixture_001", "fixture_002"]
    assert overlaps == [("synthetic_000601", "day_1", "fixture_003")]


def test_cli_missing_tuning_is_pending(monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
                                       capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setattr(config, "CORPUS_DIR", tmp_path)
    corpus.main(["--set", "tuning"])
    assert "pending" in capsys.readouterr().out
