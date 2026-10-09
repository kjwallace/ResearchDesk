"""Corpus loader: split, normalize, check, report. Owned by work package 2.

Only this module, evals and tuning read EmailLabel. See SPEC.md, "Corpus".

The loader does five things, in order:
1. splits each row into an Email and an EmailLabel (generation fields are dropped);
2. normalizes label spellings with the table in SPEC.md, "The loader";
3. checks that IDs increase in file order and assigns `received_at` in that order;
4. validates every row against the schema and lists failures for hand fixing;
5. reports the distribution against the prompt's targets (`report`).

Usage:
    uv run python -m triage_app.corpus --set day_1
"""

import argparse
import hashlib
import json
import random
import re
import sys
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from triage_app import thresholds
from triage_app import config
from triage_app.config import CorpusSet
from triage_app.pipeline.io import normalize_ws
from triage_app.schema import Email, EmailLabel, Ticker, Topic, Triage

EMAIL_FIELDS = ("email_id", "sender", "sender_email", "subject", "body")
LABEL_FIELDS = ("triage", "additional_labels", "affected_tickers", "human_attention", "reason")
GENERATION_FIELDS = ("email_type", "systemic", "angle", "day")  # label-side; never kept


MACRO_SECTOR_GOVERNMENT: tuple[Topic, ...] = ("macro", "sector", "government")

_TRIAGE_ALIASES: dict[str, Triage] = {"relevent": "thesis_relevant", "relevant": "thesis_relevant"}
_TICKER_ALIASES: dict[str, Ticker] = {"GOOG": "GOOGL"}


@dataclass
class LoadResult:
    """What the loader keeps, and everything it found along the way."""

    emails: list[Email] = field(default_factory=list)
    labels: list[EmailLabel] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)          # dropped labels or tickers, ID order
    hand_fix: list[tuple[str, str]] = field(default_factory=list)  # (email_id or line, problem)
    duplicates: list[tuple[str, str]] = field(default_factory=list)  # (kept, dropped)
    rows: int = 0


def content_hash(subject: str, body: str) -> str:
    """Hash of subject and body after whitespace collapse: the duplicate and separation key."""
    return hashlib.sha256(f"{normalize_ws(subject)}\n{normalize_ws(body)}".encode()).hexdigest()


# ---- Step 2: normalization ----

def normalize_triage(value: Any) -> tuple[str | None, bool]:
    """The triage value read through the table, and whether it signalled human_attention.

    Returns None as the label when no primary label remains (the row needs hand fixing).
    """
    if not isinstance(value, str):
        return None, False
    v = re.sub(r"[\s-]+", "_", value.strip().lower())
    if v == "human_attention":
        return None, True
    return _TRIAGE_ALIASES.get(v, v), False


def normalize_topics(values: Any, email_id: str, warnings: list[str]) -> tuple[list[Topic], bool]:
    """Topics read through the table, and whether `human_attention` appeared among them."""
    topics: list[Topic] = []
    attention = False
    for raw in values if isinstance(values, list) else [values]:
        v = re.sub(r"[\s-]+", "_", str(raw).strip().lower())
        if v == "human_attention":
            attention = True
            continue
        found: list[str] = ["macro", "government"] if v == "macro_government" else [v]
        for t in found:
            if t in config.TOPICS:
                if t not in topics:
                    topics.append(t)
            else:
                warnings.append(f"{email_id}: dropped additional label {raw!r}")
    return topics, attention


def normalize_tickers(values: Any, email_id: str, warnings: list[str]) -> list[Ticker]:
    tickers: list[Ticker] = []
    for raw in values if isinstance(values, list) else [values]:
        v = str(raw).strip().upper()
        t = _TICKER_ALIASES.get(v, v)
        if t in config.TICKERS:
            if t not in tickers:
                tickers.append(t)
        else:
            warnings.append(f"{email_id}: dropped ticker {raw!r}")
    return tickers


def normalize_flag(value: Any) -> Any:
    """A boolean flag, accepting "true"/"false" strings; anything else is left for validation."""
    if isinstance(value, str) and value.strip().lower() in ("true", "false"):
        return value.strip().lower() == "true"
    return value


# ---- Step 3: arrival times ----

def arrival_times(corpus_set: CorpusSet, n: int) -> list[datetime]:
    """`n` times spread evenly across the set's window, the first at the window's start."""
    start_s, end_s = config.SET_WINDOW
    day = config.SET_DATES[corpus_set]
    start = datetime.fromisoformat(f"{day}T{start_s}:00{config.SET_TZ_OFFSET}")
    end = datetime.fromisoformat(f"{day}T{end_s}:00{config.SET_TZ_OFFSET}")
    step = (end - start) / n if n else timedelta(0)
    return [start + i * step for i in range(n)]


def _id_key(email_id: str) -> tuple[int, str]:
    m = re.search(r"(\d+)$", email_id)
    return (int(m.group(1)) if m else -1, email_id)


def infer_set(path: Path) -> CorpusSet:
    """The set a corpus file belongs to, from its folder; the fixtures use day_1's date."""
    name = path.parent.name
    for s in config.CORPUS_SETS:
        if s == name:
            return s
    return "day_1"


# ---- The loader ----

def load_with_report(path: Path, corpus_set: CorpusSet | None = None) -> LoadResult:
    """Run the loader's steps 1 to 4 on one file, keeping every finding."""
    corpus_set = corpus_set or infer_set(path)
    result = LoadResult()
    lines = [(i, line) for i, line in enumerate(path.read_text().splitlines(), 1) if line.strip()]
    result.rows = len(lines)
    times = arrival_times(corpus_set, len(lines))
    seen: dict[str, str] = {}
    last_id: str | None = None

    for (lineno, line), received_at in zip(lines, times):
        try:
            row = json.loads(line)
        except json.JSONDecodeError as e:
            result.hand_fix.append((f"line {lineno}", f"not valid JSON: {e.msg}"))
            continue
        if not isinstance(row, dict):
            result.hand_fix.append((f"line {lineno}", "row is not a JSON object"))
            continue
        email_id = str(row.get("email_id", f"line {lineno}"))

        # 1. Split: input fields to Email, label fields to EmailLabel; generation fields dropped.
        email_raw = {k: row.get(k) for k in EMAIL_FIELDS}
        label_raw: dict[str, Any] = {k: row.get(k) for k in LABEL_FIELDS}
        label_raw["email_id"] = row.get("email_id")

        # 2. Normalize label spellings.
        triage, attention_t = normalize_triage(label_raw["triage"])
        topics, attention_a = normalize_topics(label_raw["additional_labels"] or [], email_id, result.warnings)
        tickers = normalize_tickers(label_raw["affected_tickers"] or [], email_id, result.warnings)
        flag = normalize_flag(label_raw["human_attention"])
        if attention_t or attention_a:
            flag = True
        if triage is None:
            problem = ("human_attention was the triage value and no primary label remains"
                       if attention_t else f"no primary triage label ({label_raw['triage']!r})")
            result.hand_fix.append((email_id, problem))
            continue
        label_raw.update(triage=triage, additional_labels=topics, affected_tickers=tickers,
                         human_attention=flag)

        # 3. IDs increase in file order; received_at follows file order.
        if last_id is not None and _id_key(email_id) <= _id_key(last_id):
            result.warnings.append(f"{email_id}: ID does not increase after {last_id}")
        last_id = email_id
        email_raw["received_at"] = received_at

        # 4. Validate against the schema.
        try:
            email = Email.model_validate(email_raw)
            label = EmailLabel.model_validate(label_raw)
        except ValidationError as e:
            problems = "; ".join(f"{'.'.join(map(str, err['loc']))}: {err['msg']}" for err in e.errors())
            result.hand_fix.append((email_id, problems))
            continue

        # Duplicate subject and body: keep the first and report the pair.
        h = content_hash(email.subject, email.body)
        if h in seen:
            result.duplicates.append((seen[h], email.email_id))
            continue
        seen[h] = email.email_id
        result.emails.append(email)
        result.labels.append(label)
    return result


def load(path: Path, corpus_set: CorpusSet | None = None) -> tuple[list[Email], list[EmailLabel]]:
    """Split each row into an Email and an EmailLabel, normalized and checked."""
    result = load_with_report(path, corpus_set)
    return result.emails, result.labels


# ---- Step 5: distribution report ----

def _scaled(lo: int, hi: int, n: int) -> tuple[float, float]:
    return lo * n / thresholds.TARGET_BASE, hi * n / thresholds.TARGET_BASE


def report(result: LoadResult, corpus_set: str) -> str:
    """The loader's distribution report against the prompt's targets, plus its findings."""
    labels, n = result.labels, len(result.labels)
    out = [f"Corpus {corpus_set}: {result.rows} rows read, {n} kept"]

    out.append("\nTriage labels (target scaled to the set size):")
    counts = Counter(lb.triage for lb in labels)
    for t in config.TRIAGE_LABELS:
        target = thresholds.TARGET_SHARES[t] * n
        share = counts[t] / n if n else 0.0
        out.append(f"  {t:<16}{counts[t]:>5}  {share:6.1%}   target {target:5.1f} ({thresholds.TARGET_SHARES[t]:.0%})")

    def check(name: str, value: int, rng: tuple[int, int]) -> None:
        lo, hi = _scaled(*rng, n)
        ok = "ok" if lo <= value <= hi else "MISS"
        out.append(f"  {name:<34}{value:>5}   target {lo:g} to {hi:g}   {ok}")

    out.append("\nTargets the loader checks:")
    check("human_attention true", sum(lb.human_attention for lb in labels), thresholds.HUMAN_ATTENTION_RANGE)
    check("macro, sector or government", sum(any(t in MACRO_SECTOR_GOVERNMENT for t in lb.additional_labels)
                                             for lb in labels), thresholds.MACRO_SECTOR_GOVERNMENT_RANGE)
    relevant = [lb for lb in labels if lb.triage == "thesis_relevant"]
    per_ticker = Counter(t for lb in relevant for t in lb.affected_tickers)
    even = len(relevant) / len(config.TICKERS)
    out.append(f"  thesis_relevant per ticker (about {even:.1f} each if even):")
    for tk in config.TICKERS:
        out.append(f"    {tk:<6}{per_ticker[tk]:>3}")
    untagged = sum(1 for lb in relevant if not lb.affected_tickers)
    if untagged:
        out.append(f"    (no ticker: {untagged})")

    topic_counts = Counter(t for lb in labels for t in lb.additional_labels)
    out.append("\nAdditional labels: " + ", ".join(f"{t} {topic_counts[t]}" for t in config.TOPICS))
    ticker_counts = Counter(t for lb in labels for t in lb.affected_tickers)
    out.append("Affected tickers: " + ", ".join(f"{t} {ticker_counts[t]}" for t in config.TICKERS))

    out.append(f"\nNormalization warnings: {len(result.warnings)}")
    out += [f"  {w}" for w in result.warnings]
    out.append(f"Rows for hand fixing: {len(result.hand_fix)}")
    out += [f"  {where}: {problem}" for where, problem in result.hand_fix]
    out.append(f"Duplicate subject and body: {len(result.duplicates)}")
    out += [f"  kept {a}, dropped {b}" for a, b in result.duplicates]
    return "\n".join(out)


# ---- Tuning set ----

@dataclass
class TuningSplit:
    fit_emails: list[Email]
    fit_labels: list[EmailLabel]
    val_emails: list[Email]
    val_labels: list[EmailLabel]


def split_tuning(emails: Sequence[Email], labels: Sequence[EmailLabel], seed: int = thresholds.SPLIT_SEED) -> TuningSplit:
    """Two-thirds to fit and one-third to validate, stratified by triage label, fixed seed.

    Both halves keep file (arrival) order.
    """
    by_id = {lb.email_id: lb for lb in labels}
    strata: dict[str, list[str]] = defaultdict(list)
    for e in emails:
        strata[by_id[e.email_id].triage].append(e.email_id)
    rng = random.Random(seed)
    fit: set[str] = set()
    for t in sorted(strata):
        ids = sorted(strata[t])
        rng.shuffle(ids)
        fit.update(ids[:round(len(ids) * thresholds.FIT_SHARE)])
    split = TuningSplit([], [], [], [])
    for e in emails:
        if e.email_id in fit:
            split.fit_emails.append(e)
            split.fit_labels.append(by_id[e.email_id])
        else:
            split.val_emails.append(e)
            split.val_labels.append(by_id[e.email_id])
    return split


def check_separation(tuning: Sequence[Email], test_sets: Mapping[str, Sequence[Email]]
                     ) -> tuple[list[Email], list[tuple[str, str, str]]]:
    """Tuning emails with no subject+body match in any test set, and each overlap removed.

    Overlaps are (tuning email_id, test set, test email_id).
    """
    test_hashes: dict[str, tuple[str, str]] = {}
    for name, emails in test_sets.items():
        for e in emails:
            test_hashes.setdefault(content_hash(e.subject, e.body), (name, e.email_id))
    kept: list[Email] = []
    overlaps: list[tuple[str, str, str]] = []
    for e in tuning:
        hit = test_hashes.get(content_hash(e.subject, e.body))
        if hit:
            overlaps.append((e.email_id, hit[0], hit[1]))
        else:
            kept.append(e)
    return kept, overlaps


def tuning_report(result: LoadResult) -> str:
    test_sets: dict[str, list[Email]] = {s: load(config.corpus_file(s), s)[0] for s in config.TEST_SETS if config.corpus_file(s).exists()}
    kept_emails, overlaps = check_separation(result.emails, test_sets)
    kept_ids = {e.email_id for e in kept_emails}
    split = split_tuning(kept_emails, [lb for lb in result.labels if lb.email_id in kept_ids])
    out = [f"\nSeparation from {', '.join(test_sets) or 'no test sets'}: {len(overlaps)} overlap(s) removed"]
    out += [f"  {a} matches {s} {b}" for a, s, b in overlaps]
    out.append(f"Split (seed {thresholds.SPLIT_SEED}): {len(split.fit_emails)} fit, {len(split.val_emails)} validate")
    fit_c, val_c = Counter(lb.triage for lb in split.fit_labels), Counter(lb.triage for lb in split.val_labels)
    for t in config.TRIAGE_LABELS:
        out.append(f"  {t:<16} fit {fit_c[t]:>3}   validate {val_c[t]:>3}")
    return "\n".join(out)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Load, normalize and report one corpus set.")
    parser.add_argument("--set", dest="corpus_set", required=True, choices=config.CORPUS_SETS)
    args = parser.parse_args(argv)
    corpus_set: CorpusSet = args.corpus_set
    path = config.corpus_file(corpus_set)
    if not path.exists():
        if corpus_set == "tuning":
            print(f"Tuning set pending: {path} does not exist yet. Tuning and the criteria check "
                  "are pending; the pipeline runs at starting values.")
            return
        sys.exit(f"corpus file not found: {path}")
    result = load_with_report(path, corpus_set)
    print(report(result, corpus_set))
    if corpus_set == "tuning":
        print(tuning_report(result))


if __name__ == "__main__":
    main()
