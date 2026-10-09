"""Score one set's pipeline output against its corpus labels.

    uv run python -m triage_app.evals.score --set day_1

Reads the set's stage files in data/out/<set>/ and its emails and labels from the corpus
file through the loader, and writes eval.json (an EvalReport with every
miss listed) and the two hand-review sheets, review_notes.csv and review_suggestions.csv.
A sheet is rewritten on each run until a person fills any check in it; from then on it is
kept and read for the three review keys. See SPEC.md, "Evaluation and guardrails".

Only evals and the corpus loader read EmailLabel.
"""

import argparse
import csv
from collections import Counter
from pathlib import Path

from pydantic import BaseModel

from triage_app import config
from triage_app.config import CorpusSet
from triage_app.evals import metric
from triage_app.pipeline.io import read_list, write_one
from triage_app.schema import (
    AttentionNote,
    Email,
    EmailLabel,
    EmailResult,
    EvalReport,
    RedundancyRecord,
    Suggestion,
    TriageRecord,
)

NOTES_SHEET = "review_notes.csv"
SUGGESTIONS_SHEET = "review_suggestions.csv"
NOTE_COLUMNS = ("id", "kind", *metric.NOTE_CHECKS, "comment")
SUGGESTION_COLUMNS = ("id", "kind", "right_pillar", "right_stance", "sections_support", "new_to_book",
                      "right_metric", "figure_stated", "comment")


# ---- Labels ----

def read_labels_file(path: Path) -> list[EmailLabel]:
    """Labels already in EmailLabel form, one JSON object per line (tests/fixtures/labels.jsonl)."""
    return [EmailLabel.model_validate_json(line) for line in path.read_text().splitlines() if line.strip()]


def load_corpus(corpus_set: CorpusSet) -> tuple[list[Email], list[EmailLabel]]:
    """Emails and labels of a set through the corpus loader, which normalizes them."""
    from triage_app import corpus
    return corpus.load(config.corpus_file(corpus_set))


def load_labels(corpus_set: CorpusSet, labels_path: Path | None = None) -> list[EmailLabel]:
    return read_labels_file(labels_path) if labels_path else load_corpus(corpus_set)[1]


# ---- Eval report ----

def _optional[M: BaseModel](path: Path, model: type[M]) -> list[M] | None:
    return read_list(path, model) if path.exists() else None


def criteria_version(triage: list[TriageRecord]) -> str:
    """The criteria version in force; the most common one if a run mixed versions."""
    counts = Counter(t.criteria_version for t in triage)
    return counts.most_common(1)[0][0] if counts else ""


def evaluate(corpus_set: CorpusSet, out_dir: Path, labels: list[EmailLabel], emails: list[Email]) -> EvalReport:
    """Every measure in the eval table, from the set's stage files. Review keys come from the sheets."""
    by_id = {lab.email_id: lab for lab in labels}
    results = {r.email_id: r for r in read_list(out_dir / "results.json", EmailResult)}
    triage = read_list(out_dir / "triage.json", TriageRecord)
    redundancy = read_list(out_dir / "redundancy.json", RedundancyRecord)  # flagged emails only
    bodies = {e.email_id: e.body for e in emails}
    notes = _optional(out_dir / "notes.json", AttentionNote)
    suggestions = _optional(out_dir / "suggestions.json", Suggestion)

    scores = metric.label_scores(results, by_id)
    scores["repeat_flagged"] = metric.repeat_flagged(redundancy)
    scores["repeat_precision"] = metric.repeat_precision(redundancy, by_id)
    scores["stray_suggestions"] = (metric.stray_suggestions(suggestions, by_id) if suggestions is not None
                                   else metric.Score(None))
    scores["quote_faithfulness"] = metric.quote_faithfulness(notes or [], suggestions or [], bodies)
    scores["meetings_share"] = metric.meetings_share(triage)
    scores["email_type_accuracy"] = metric.email_type_accuracy(triage, by_id, results)

    measures: dict[str, float | None] = {k: s.value for k, s in scores.items()}
    measures.update(read_reviews(out_dir))
    return EvalReport(
        corpus=corpus_set,
        criteria_version=criteria_version(triage),
        measures=measures,
        confusion=metric.confusion(results, by_id),
        misses=[m for s in scores.values() for m in s.misses],
    )


# ---- Review sheets ----

def _read_sheet(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(newline="") as f:
        return list(csv.DictReader(f))


def is_filled(path: Path) -> bool:
    """True when a person has filled in any check of the sheet."""
    checks = set(metric.NOTE_CHECKS) | {c for cs in metric.SUGGESTION_CHECKS.values() for c in cs}
    return any((row.get(c) or "").strip() for row in _read_sheet(path) for c in checks)


def _write_sheet(path: Path, columns: tuple[str, ...], rows: list[dict[str, str]]) -> None:
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def write_sheets(out_dir: Path) -> list[Path]:
    """Write a blank review sheet for notes and for suggestions, unless a filled one exists."""
    written = []
    notes_path, sugg_path = out_dir / NOTES_SHEET, out_dir / SUGGESTIONS_SHEET
    if not is_filled(notes_path):
        notes = _optional(out_dir / "notes.json", AttentionNote) or []
        _write_sheet(notes_path, NOTE_COLUMNS, [{"id": n.email_id, "kind": "note"} for n in notes])
        written.append(notes_path)
    if not is_filled(sugg_path):
        suggestions = _optional(out_dir / "suggestions.json", Suggestion) or []
        _write_sheet(sugg_path, SUGGESTION_COLUMNS, [{"id": s.id, "kind": s.body.kind} for s in suggestions
                                                     if s.body.kind in metric.SUGGESTION_CHECKS])
        written.append(sugg_path)
    return written


def read_reviews(out_dir: Path) -> dict[str, float | None]:
    """The three review keys; None until the sheets are filled."""
    notes = _read_sheet(out_dir / NOTES_SHEET)
    suggestions = _read_sheet(out_dir / SUGGESTIONS_SHEET)
    return {
        "note_review": metric.note_review(notes),
        "suggestion_review": metric.suggestion_review(suggestions),
        "new_thesis_review": metric.new_thesis_review(suggestions),
    }


# ---- Command ----

def score_set(corpus_set: CorpusSet, out_dir: Path, labels: list[EmailLabel], emails: list[Email]) -> EvalReport:
    write_sheets(out_dir)
    report = evaluate(corpus_set, out_dir, labels, emails)
    write_one(out_dir / "eval.json", report)
    return report


def format_report(report: EvalReport) -> str:
    lines = [f"eval {report.corpus} (criteria {report.criteria_version})"]
    lines += [f"  {k:<22} {'-' if v is None else f'{v:g}'}" for k, v in report.measures.items()]
    lines.append(f"  misses: {len(report.misses)}")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--set", dest="corpus_set", required=True, choices=config.CORPUS_SETS)
    parser.add_argument("--out", type=Path, help="stage-file directory (default data/out/<set>)")
    parser.add_argument("--emails", type=Path, help="corpus file (default data/corpus/<set>/emails.jsonl)")
    parser.add_argument("--labels", type=Path, help="labels already in EmailLabel form, instead of the corpus loader")
    args = parser.parse_args()
    out_dir = args.out or config.out_dir(args.corpus_set)
    if not (out_dir / "results.json").exists():
        print(f"no pipeline output in {out_dir}; run the pipeline on {args.corpus_set} first")
        return
    from triage_app import corpus
    emails, corpus_labels = corpus.load(args.emails or config.corpus_file(args.corpus_set), args.corpus_set)
    labels = read_labels_file(args.labels) if args.labels else corpus_labels
    report = score_set(args.corpus_set, out_dir, labels, emails)
    print(format_report(report))
    print(f"wrote {out_dir / 'eval.json'} and the review sheets")


if __name__ == "__main__":
    main()
