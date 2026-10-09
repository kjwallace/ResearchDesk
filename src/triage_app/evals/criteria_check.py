"""Criteria check: rerun Jev on the tuning set with the current criteria files and compare.

    uv run python -m triage_app.evals.criteria_check

Reruns stage 3 (classify, through ctx.jev and the disk cache) and stage 4 (gate) on every
tuning email, refits the thresholds in memory on the fit split (never written to
tuned/thresholds.json), and prints the label measures before and after on the fit and
validation splits, with every email whose label changed. "Before" is the previous
criteria version's entry in data/out/criteria_history.json. The check then appends this
version's entry there (one entry per version: rerunning a version replaces its entry).

Each version's labels are kept beside the tuning output, in
data/out/tuning/criteria_check/<version>.json (EmailResult list), so the next version can
list the emails it relabeled. Nothing else is written. See SPEC.md, "Relevance criteria"
and the keep rule under "Tuning".
"""

import argparse
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from pathlib import Path

from pydantic import TypeAdapter

from triage_app import config
from triage_app import criteria as criteria_files
from triage_app.evals import metric, tune
from triage_app.evals.score import load_corpus
from triage_app.evals.tune import Split
from triage_app.pipeline import classify, gate
from triage_app.pipeline.context import RunContext
from triage_app.pipeline.io import read_list, write_list
from triage_app.schema import (
    CriteriaHistoryEntry,
    Email,
    EmailLabel,
    EmailResult,
    LabelChange,
    RedundancyRecord,
    Thresholds,
    TriageRecord,
)

PENDING = "criteria check pending: tuning set not available"
HISTORY = config.OUT_DIR / "criteria_history.json"
NEEDED = ("parsed.json", "redundancy.json")

Classify = Callable[[Email, RunContext], TriageRecord]
Gate = Callable[[TriageRecord, RedundancyRecord, Thresholds], EmailResult]
_HISTORY = TypeAdapter(list[CriteriaHistoryEntry])


def read_history(path: Path = HISTORY) -> list[CriteriaHistoryEntry]:
    return _HISTORY.validate_json(path.read_text()) if path.exists() else []


def write_history(path: Path, entries: list[CriteriaHistoryEntry]) -> None:
    write_list(path, entries)


def labels_file(out_dir: Path, version: str) -> Path:
    return out_dir / "criteria_check" / f"{version}.json"


def split_measures(results: Mapping[str, EmailResult], labels: Mapping[str, EmailLabel],
                   split: Mapping[str, Split], part: Split) -> dict[str, float]:
    return metric.label_measures(results, {i: lab for i, lab in labels.items() if split.get(i) == part})


def label_changes(before: Mapping[str, EmailResult], after: Mapping[str, EmailResult],
                  emails: Mapping[str, Email], labels: Mapping[str, EmailLabel],
                  split: Mapping[str, Split]) -> list[LabelChange]:
    """Tuning emails whose pipeline label differs between two versions."""
    changes = []
    for email_id, now in after.items():
        prev = before.get(email_id)
        if prev is None or prev.triage == now.triage or email_id not in split or email_id not in labels:
            continue
        changes.append(LabelChange(
            email_id=email_id, subject=emails[email_id].subject, before=prev.triage, after=now.triage,
            split=split[email_id], now_correct=now.triage == labels[email_id].triage,
        ))
    return changes


def check(emails: list[Email], redundancy: Mapping[str, RedundancyRecord], labels: Mapping[str, EmailLabel],
          split: Mapping[str, Split], ctx: RunContext, *, criteria_dir: Path, out_dir: Path,
          history_path: Path = HISTORY, classify_one: Classify = classify.process,
          gate_one: Gate = gate.process) -> tuple[CriteriaHistoryEntry, CriteriaHistoryEntry | None, Thresholds]:
    """Rerun stages 3 and 4 with ctx.criteria; return this version's entry, the previous one and the refit thresholds.

    Appends the entry to the history file and keeps this version's labels for the next check.
    """
    version = ctx.criteria.version
    triage = []
    for email in emails:
        with ctx.recorder.stage(classify.STAGE, email.email_id):
            triage.append(classify_one(email, ctx))
    thresholds = tune.fit_thresholds(triage, labels, {i for i, s in split.items() if s == "fit"})
    results = {t.email_id: gate_one(t, redundancy[t.email_id], thresholds) for t in triage}

    history = read_history(history_path)
    previous = next((h for h in reversed(history) if h.criteria_version != version), None)
    before: dict[str, EmailResult] = {}
    if previous is not None and labels_file(out_dir, previous.criteria_version).exists():
        before = {r.email_id: r for r in read_list(labels_file(out_dir, previous.criteria_version), EmailResult)}

    entry = CriteriaHistoryEntry(
        criteria_version=version,
        at=datetime.now(UTC),
        files=criteria_files.read_files(criteria_dir),
        fit=split_measures(results, labels, split, "fit"),
        validation=split_measures(results, labels, split, "validation"),
        changed=label_changes(before, results, {e.email_id: e for e in emails}, labels, split),
    )
    write_history(history_path, [h for h in history if h.criteria_version != version] + [entry])
    write_list(labels_file(out_dir, version), list(results.values()))
    return entry, previous, thresholds


def format_check(entry: CriteriaHistoryEntry, previous: CriteriaHistoryEntry | None, thresholds: Thresholds,
                 labels: Mapping[str, EmailLabel]) -> str:
    def cell(scores: dict[str, float] | None, key: str) -> str:
        v = None if scores is None else scores.get(key)
        return f"{'-' if v is None else f'{v:.3f}':>7}"

    before = previous.criteria_version if previous else "none"
    lines = [f"criteria {entry.criteria_version} (before: {before}); refit pass threshold "
             f"{thresholds.pass_signal:.4f}, not written",
             f"  {'measure':<20} {'fit':>7} {'':>7}   {'valid':>7}",
             f"  {'':<20} {'before':>7} {'after':>7}   {'before':>7} {'after':>7}"]
    for key in metric.LABEL_MEASURES:
        lines.append(f"  {key:<20}"
                     f" {cell(previous.fit if previous else None, key)} {cell(entry.fit, key)}  "
                     f" {cell(previous.validation if previous else None, key)} {cell(entry.validation, key)}")
    lines.append(f"label changes: {len(entry.changed)}")
    for c in entry.changed:
        mark = "now right" if c.now_correct else "now wrong"
        lines.append(f"  {c.email_id} [{c.split}] {c.before} -> {c.after} ({mark})  {c.subject}")
    fixed = sum(1 for c in entry.changed if c.split == "fit" and c.now_correct)
    broke = sum(1 for c in entry.changed if c.split == "fit" and c.before == labels[c.email_id].triage)
    lines.append(f"keep rule: fixes {fixed} fit emails (need 2+), breaks {broke} (need 0), validation signal accuracy "
                 f"{cell(previous.validation if previous else None, 'signal_accuracy').strip()} -> "
                 f"{cell(entry.validation, 'signal_accuracy').strip()} (must not fall)")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--criteria", type=Path, default=config.CRITERIA_DIR, help="criteria directory")
    args = parser.parse_args()
    out_dir = config.out_dir("tuning")
    if not tune.tuning_available(out_dir, NEEDED):
        print(PENDING)
        return
    corpus_emails, label_list = load_corpus("tuning")
    split = tune.split_ids(corpus_emails, label_list)
    emails = read_list(out_dir / "parsed.json", Email)
    redundancy = {r.email_id: r for r in read_list(out_dir / "redundancy.json", RedundancyRecord)}
    ctx = RunContext("tuning", criteria=criteria_files.load(args.criteria))
    entry, previous, thresholds = check(emails, redundancy, {lab.email_id: lab for lab in label_list}, split, ctx,
                                        criteria_dir=args.criteria, out_dir=out_dir)
    print(format_check(entry, previous, thresholds, {lab.email_id: lab for lab in label_list}))


if __name__ == "__main__":
    main()
