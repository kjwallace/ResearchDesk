"""Fit the stage 4 thresholds on the tuning set's fit split, by code sweep.

    uv run python -m triage_app.evals.tune

Reads data/out/tuning/triage.json (Jev's answers) and the tuning labels, then writes
tuned/thresholds.json:

- pass threshold: the highest value that still passes every thesis_relevant email and at
  least 95% of monitor emails on the fit split;
- attention, ticker and topic thresholds: best F1 on the fit split (code sweep; ReAnchor
  is not used, DECISIONS #9);
- redundancy thresholds: copied from config.py unchanged (fixed, never swept);
- quarantine threshold: not tuned (config.py).

Quarantined emails never pass and truncated emails always pass, so neither constrains the
pass threshold, and quarantined emails are left out of every F1 sweep. Never run on test sets.
See SPEC.md, "Tuning".
"""

import math
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any, Literal

from triage_app import thresholds as limits  # the module; `thresholds` here is a Thresholds value
from triage_app import config
from triage_app.evals.score import load_corpus
from triage_app.pipeline.gate import signal_score
from triage_app.pipeline.io import read_list, write_one
from triage_app.schema import Email, EmailLabel, Thresholds, TriageRecord

Split = Literal["fit", "validation"]
PENDING = "tuning pending: tuning set not available"


def is_quarantined(t: TriageRecord, threshold: float = limits.QUARANTINE) -> bool:
    """Either safety probability reaches the quarantine threshold (DECISIONS #19)."""
    return max(t.safety.values(), default=0.0) >= threshold


def _floor4(x: float) -> float:
    scale = float(10 ** limits.PASS_THRESHOLD_DECIMALS)
    return math.floor(x * scale + 1e-9) / scale


# ---- Sweeps ----

def fit_pass_threshold(relevant: Sequence[float], monitor: Sequence[float], default: float,
                       monitor_share: float = limits.MONITOR_PASS_SHARE) -> float:
    """Highest threshold t with every relevant score >= t and at least `monitor_share` of monitor scores >= t."""
    bounds = []
    if relevant:
        bounds.append(min(relevant))
    if monitor:
        need = math.ceil(monitor_share * len(monitor) - 1e-9)
        bounds.append(sorted(monitor, reverse=True)[max(need, 1) - 1])
    return _floor4(min(bounds)) if bounds else default


def f1_at(probs: Sequence[float], truth: Sequence[bool], threshold: float) -> float | None:
    tp = sum(1 for p, y in zip(probs, truth) if p >= threshold and y)
    fp = sum(1 for p, y in zip(probs, truth) if p >= threshold and not y)
    fn = sum(1 for p, y in zip(probs, truth) if p < threshold and y)
    return 2 * tp / (2 * tp + fp + fn) if tp + fp + fn else None


def fit_f1_threshold(probs: Sequence[float], truth: Sequence[bool], default: float) -> float:
    """Threshold with the best F1. Candidates sit midway between neighbouring probabilities,
    plus the lowest one; ties go to the candidate nearest the starting value. With no
    positive example the starting value stays."""
    if not any(truth):
        return default
    values = sorted(set(probs))
    candidates = [values[0], *((a + b) / 2 for a, b in zip(values, values[1:]))]
    best = max(candidates, key=lambda t: (f1_at(probs, truth, t) or 0.0, -abs(t - default)))
    return round(best, 4)


# ---- Fitting ----

def fit_thresholds(triage: Iterable[TriageRecord], labels: Mapping[str, EmailLabel],
                   fit_ids: set[str], start: Thresholds | None = None) -> Thresholds:
    """Every tuned threshold, fit on the emails in `fit_ids`; redundancy values from config."""
    start = start or limits.starting_thresholds()
    rows = [(t, labels[t.email_id]) for t in triage if t.email_id in fit_ids and t.email_id in labels]
    live = [(t, lab) for t, lab in rows if not is_quarantined(t)]
    gated = [(t, lab) for t, lab in live if not t.truncated]

    pass_signal = fit_pass_threshold(
        [signal_score(t) for t, lab in gated if lab.triage == "thesis_relevant"],
        [signal_score(t) for t, lab in gated if lab.triage == "monitor"],
        start.pass_signal)
    attention = fit_f1_threshold([t.attention for t, _ in live], [lab.human_attention for _, lab in live],
                                 start.attention)
    ticker = {k: fit_f1_threshold([t.ticker_probs.get(k, 0.0) for t, _ in live],
                                  [k in lab.affected_tickers for _, lab in live], start.ticker.get(k, limits.TICKER_THRESHOLD))
              for k in config.TICKERS}
    topic = {k: fit_f1_threshold([t.topic_probs.get(k, 0.0) for t, _ in live],
                                 [k in lab.additional_labels for _, lab in live], start.topic.get(k, limits.TOPIC_THRESHOLD))
             for k in config.TOPICS}
    return Thresholds(
        pass_signal=pass_signal, attention=attention, ticker=ticker, topic=topic,
        content_similarity=limits.CONTENT_SIMILARITY,
        content_similarity_with_subject=limits.CONTENT_SIMILARITY_WITH_SUBJECT,
        subject_match=limits.SUBJECT_MATCH,
    )


# ---- Tuning set ----

def split_ids(emails: list[Email], labels: list[EmailLabel]) -> dict[str, Split]:
    """Fit or validation for each tuning email, from the loader's stratified split."""
    from triage_app import corpus
    split = corpus.split_tuning(emails, labels)
    out: dict[str, Split] = {e.email_id: "fit" for e in split.fit_emails}
    out.update({e.email_id: "validation" for e in split.val_emails})
    return out


def tuning_available(out_dir: Path | None = None, needed: Sequence[str] = ("triage.json",)) -> bool:
    out_dir = out_dir or config.out_dir("tuning")
    return config.corpus_file("tuning").exists() and all((out_dir / n).exists() for n in needed)


def describe(th: Thresholds, triage: list[TriageRecord], labels: Mapping[str, EmailLabel],
             split: Mapping[str, Split]) -> str:
    """Each fitted threshold with its F1 on the fit and validation splits."""
    lines = [f"  pass_signal  {th.pass_signal:.4f}"]

    def row(name: str, value: float, prob: Any, truth: Any) -> str:
        cells = []
        for part in ("fit", "validation"):
            rows = [(t, labels[t.email_id]) for t in triage
                    if split.get(t.email_id) == part and t.email_id in labels and not is_quarantined(t)]
            f1 = f1_at([prob(t) for t, _ in rows], [truth(lab) for _, lab in rows], value)
            cells.append(f"{part} F1 {'-' if f1 is None else f'{f1:.3f}'}")
        return f"  {name:<12} {value:.4f}  " + "  ".join(cells)

    lines.append(row("attention", th.attention, lambda t: t.attention, lambda lab: lab.human_attention))
    for k, v in th.ticker.items():
        lines.append(row(k, v, lambda t, k=k: t.ticker_probs.get(k, 0.0), lambda lab, k=k: k in lab.affected_tickers))
    for k, v in th.topic.items():
        lines.append(row(k, v, lambda t, k=k: t.topic_probs.get(k, 0.0), lambda lab, k=k: k in lab.additional_labels))
    return "\n".join(lines)


def main() -> None:
    if not tuning_available():
        print(PENDING)
        return
    emails, labels = load_corpus("tuning")
    split = split_ids(emails, labels)
    by_id = {lab.email_id: lab for lab in labels}
    triage = read_list(config.out_dir("tuning") / "triage.json", TriageRecord)
    thresholds = fit_thresholds(triage, by_id, {i for i, s in split.items() if s == "fit"})
    write_one(config.TUNED_THRESHOLDS, thresholds)
    print(f"tuned on {sum(s == 'fit' for s in split.values())} fit emails; wrote {config.TUNED_THRESHOLDS}")
    print(describe(thresholds, triage, by_id, split))


if __name__ == "__main__":
    main()
