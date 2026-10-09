"""Pure functions for every measure in SPEC.md, "Evaluation and guardrails".

Each measure takes pipeline output and corpus labels keyed by email ID and returns a
`Score`: the value (None when undefined, e.g. no positives) and the misses behind it.

A quarantined email counts as a miss on every label measure: its label is "quarantined",
it does not pass the gate, and it predicts no ticker, topic or attention flag. Labels are
the universe: an email with a label but no result is treated as quarantined.

Only evals and the corpus loader read EmailLabel.
"""

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field

from triage_app import config
from triage_app.config import TICKERS, TOPICS
from triage_app.pipeline.io import quote_in
from triage_app.schema import (
    AttentionNote,
    EmailLabel,
    EmailResult,
    LinkedSection,
    Miss,
    RedundancyRecord,
    Suggestion,
    TriageRecord,
)

QUARANTINED = "quarantined"
SIGNAL_CLASS = {
    "thesis_relevant": "signal", "monitor": "signal", "redundant": "redundant",
    "low_value": "noise", "irrelevant": "noise",
}
NOISE_LABELS = frozenset({"redundant", "low_value", "irrelevant"})

# The measures reported per split by the criteria check (all label measures with a value).
LABEL_MEASURES = ("gate_recall", "monitor_gate_recall", "signal_accuracy", "triage_accuracy",
                  "ticker_f1", "topic_f1", "human_attention_precision", "human_attention_recall")

Results = Mapping[str, EmailResult]
Labels = Mapping[str, EmailLabel]


@dataclass
class Score:
    value: float | None
    misses: list[Miss] = field(default_factory=list)


def _ratio(num: int, den: int) -> float | None:
    return round(num / den, 4) if den else None


def _get(results: Results, email_id: str) -> EmailResult | None:
    """The result for an email, or None when it is quarantined or missing."""
    r = results.get(email_id)
    return None if r is None or r.gate == "quarantine" else r


def pipeline_label(results: Results, email_id: str) -> str:
    r = _get(results, email_id)
    return QUARANTINED if r is None or r.triage is None else r.triage


def _gate(results: Results, email_id: str) -> str:
    r = results.get(email_id)
    return "missing" if r is None else r.gate


def _joined(items: Iterable[str], order: tuple[str, ...]) -> str:
    s = set(items)
    return ",".join(x for x in order if x in s) or "none"


# ---- Gate ----

def _gate_recall_for(label: str, measure: str, results: Results, labels: Labels) -> Score:
    ids = [i for i, lab in labels.items() if lab.triage == label]
    misses = [Miss(email_id=i, measure=measure, expected="pass", got=_gate(results, i))
              for i in ids if _gate(results, i) != "pass"]
    return Score(_ratio(len(ids) - len(misses), len(ids)), misses)


def gate_recall(results: Results, labels: Labels) -> Score:
    """Share of corpus thesis_relevant emails that pass the gate."""
    return _gate_recall_for("thesis_relevant", "gate_recall", results, labels)


def monitor_gate_recall(results: Results, labels: Labels) -> Score:
    """Share of corpus monitor emails that pass the gate."""
    return _gate_recall_for("monitor", "monitor_gate_recall", results, labels)


def gate_reduction(results: Results, labels: Labels) -> Score:
    """Share of emails stopped (or quarantined) before the analysis model."""
    stopped = sum(1 for i in labels if _gate(results, i) != "pass")
    return Score(_ratio(stopped, len(labels)))


# ---- Labels ----

def signal_accuracy(results: Results, labels: Labels) -> Score:
    """Label correct on three classes: signal, redundant, noise."""
    misses = []
    for i, lab in labels.items():
        expected = SIGNAL_CLASS[lab.triage]
        got = SIGNAL_CLASS.get(pipeline_label(results, i), QUARANTINED)
        if got != expected:
            misses.append(Miss(email_id=i, measure="signal_accuracy", expected=expected, got=got))
    return Score(_ratio(len(labels) - len(misses), len(labels)), misses)


def triage_accuracy(results: Results, labels: Labels) -> Score:
    """Label equals the corpus label exactly, on all five."""
    misses = [Miss(email_id=i, measure="triage_accuracy", expected=lab.triage, got=pipeline_label(results, i))
              for i, lab in labels.items() if pipeline_label(results, i) != lab.triage]
    return Score(_ratio(len(labels) - len(misses), len(labels)), misses)


def confusion(results: Results, labels: Labels) -> dict[str, dict[str, int]]:
    """Corpus label, then pipeline label ("quarantined" when quarantined)."""
    table: dict[str, dict[str, int]] = {}
    for i, lab in labels.items():
        row = table.setdefault(lab.triage, {})
        got = pipeline_label(results, i)
        row[got] = row.get(got, 0) + 1
    return table


def _micro_f1(measure: str, order: tuple[str, ...], labels: Labels,
              predicted: Callable[[str], set[str]], expected: Callable[[EmailLabel], set[str]]) -> Score:
    tp = fp = fn = 0
    misses = []
    for i, lab in labels.items():
        want, got = expected(lab), predicted(i)
        tp += len(want & got)
        fp += len(got - want)
        fn += len(want - got)
        if want != got:
            misses.append(Miss(email_id=i, measure=measure, expected=_joined(want, order), got=_joined(got, order)))
    return Score(_ratio(2 * tp, 2 * tp + fp + fn), misses)


def ticker_f1(results: Results, labels: Labels) -> Score:
    """Micro-averaged F1 on affected_tickers."""
    def predicted(i: str) -> set[str]:
        r = _get(results, i)
        return set(r.affected_tickers) if r else set()
    return _micro_f1("ticker_f1", TICKERS, labels, predicted, lambda lab: set(lab.affected_tickers))


def topic_f1(results: Results, labels: Labels) -> Score:
    """Micro-averaged F1 on macro, sector, government and other."""
    def predicted(i: str) -> set[str]:
        r = _get(results, i)
        return set(r.additional_labels) if r else set()
    return _micro_f1("topic_f1", TOPICS, labels, predicted, lambda lab: set(lab.additional_labels))


def _attention(results: Results, email_id: str) -> bool:
    r = _get(results, email_id)
    return bool(r and r.human_attention)


def human_attention_precision(results: Results, labels: Labels) -> Score:
    flagged = [i for i in labels if _attention(results, i)]
    misses = [Miss(email_id=i, measure="human_attention_precision", expected="false", got="true")
              for i in flagged if not labels[i].human_attention]
    return Score(_ratio(len(flagged) - len(misses), len(flagged)), misses)


def human_attention_recall(results: Results, labels: Labels) -> Score:
    wanted = [i for i, lab in labels.items() if lab.human_attention]
    misses = [Miss(email_id=i, measure="human_attention_recall", expected="true", got="false")
              for i in wanted if not _attention(results, i)]
    return Score(_ratio(len(wanted) - len(misses), len(wanted)), misses)


# ---- Repeats ----

def repeat_flagged(redundancy: Iterable[RedundancyRecord]) -> Score:
    """Count of emails the redundancy check flags; an email absent from redundancy.json is not flagged."""
    return Score(float(sum(1 for r in redundancy if r.flagged)))


def repeat_precision(redundancy: Iterable[RedundancyRecord], labels: Labels) -> Score:
    """Share of flagged emails the corpus labels redundant."""
    flagged = [r for r in redundancy if r.flagged and r.email_id in labels]
    misses = [Miss(email_id=r.email_id, measure="repeat_precision", expected=labels[r.email_id].triage,
                   got=f"flagged, nearest {r.nearest}")
              for r in flagged if labels[r.email_id].triage != "redundant"]
    return Score(_ratio(len(flagged) - len(misses), len(flagged)), misses)


# ---- Suggestions and quotes ----

def linked_emails(s: Suggestion) -> set[str]:
    """Every email a suggestion links to: its sections' emails and its claims' emails."""
    return {sec.email_id for sec in s.sections} | {c.rsplit(".c", 1)[0] for c in s.claim_ids}


def stray_suggestions(suggestions: Iterable[Suggestion], labels: Labels) -> Score:
    """Count of suggestions whose only linked emails the corpus labels redundant, low_value or irrelevant."""
    misses = []
    for s in suggestions:
        linked = sorted(i for i in linked_emails(s) if i in labels)
        if linked and all(labels[i].triage in NOISE_LABELS for i in linked):
            misses.append(Miss(email_id=",".join(linked), measure="stray_suggestions",
                               expected="a signal email", got=f"{s.id}: {','.join(labels[i].triage for i in linked)}"))
    return Score(float(len(misses)), misses)


def quote_faithfulness(notes: Iterable[AttentionNote], suggestions: Iterable[Suggestion],
                       bodies: Mapping[str, str]) -> Score:
    """Share of quoted sections, in notes and suggestions, found verbatim in the email body."""
    sections: list[tuple[str, LinkedSection]] = [(n.email_id, sec) for n in notes for sec in n.sections]
    sections += [(s.id, sec) for s in suggestions for sec in s.sections]
    misses = [Miss(email_id=sec.email_id, measure="quote_faithfulness", expected=f"verbatim quote in {owner}",
                   got=sec.quote[:80])
              for owner, sec in sections if not quote_in(sec.quote, bodies.get(sec.email_id, ""))]
    return Score(_ratio(len(sections) - len(misses), len(sections)), misses)


def meetings_share(triage: Iterable[TriageRecord]) -> Score:
    """Share of emails whose Jev email type is meeting-like (`config.MEETING_LIKE_TYPES`)."""
    records = list(triage)
    return Score(_ratio(sum(1 for t in records if t.email_type in config.MEETING_LIKE_TYPES), len(records)))


def email_type_accuracy(triage: Iterable[TriageRecord], labels: Labels, results: Results) -> Score:
    """Share of emails whose Jev email type (most probable option) equals the corpus `email_type`.

    A quarantined email counts as a miss; an email whose label has no email_type is left out.
    """
    by_id = {t.email_id: t for t in triage}
    ids = [i for i, lab in labels.items() if lab.email_type is not None and i in by_id]
    misses = []
    for i in ids:
        want = labels[i].email_type or ""
        quarantined = (r := results.get(i)) is not None and r.gate == "quarantine"
        got = "quarantined" if quarantined else by_id[i].email_type
        if got != want:
            misses.append(Miss(email_id=i, measure="email_type_accuracy", expected=want, got=got))
    return Score(_ratio(len(ids) - len(misses), len(ids)), misses)


# ---- Hand reviews, from the filled sheets ----

NOTE_CHECKS = ("summary_accurate", "reason_stated", "action_stated")
SUGGESTION_CHECKS: dict[str, tuple[str, ...]] = {
    "existing_thesis": ("right_pillar", "right_stance", "sections_support"),
    "new_thesis": ("new_to_book", "sections_support"),
}
YES = frozenset({"yes", "y", "true", "1"})


def review_share(rows: Iterable[Mapping[str, str]], kinds: Mapping[str, tuple[str, ...]]) -> float | None:
    """Share of reviewed rows of the given kinds whose every applicable check is yes.

    A row counts as reviewed once every applicable check is filled in; until any row of
    these kinds is reviewed the key is None.
    """
    reviewed = passed = 0
    for row in rows:
        checks = kinds.get(row.get("kind", "").strip())
        if not checks:
            continue
        values = [(row.get(c) or "").strip().lower() for c in checks]
        if any(not v for v in values):
            continue
        reviewed += 1
        passed += all(v in YES for v in values)
    return _ratio(passed, reviewed)


def note_review(rows: Iterable[Mapping[str, str]]) -> float | None:
    return review_share(rows, {"note": NOTE_CHECKS})


def suggestion_review(rows: Iterable[Mapping[str, str]]) -> float | None:
    return review_share(rows, {"existing_thesis": SUGGESTION_CHECKS["existing_thesis"]})


def new_thesis_review(rows: Iterable[Mapping[str, str]]) -> float | None:
    return review_share(rows, {"new_thesis": SUGGESTION_CHECKS["new_thesis"]})


# ---- All label measures at once ----

LABEL_FUNCTIONS: dict[str, Callable[[Results, Labels], Score]] = {
    "gate_recall": gate_recall,
    "monitor_gate_recall": monitor_gate_recall,
    "gate_reduction": gate_reduction,
    "signal_accuracy": signal_accuracy,
    "triage_accuracy": triage_accuracy,
    "ticker_f1": ticker_f1,
    "human_attention_precision": human_attention_precision,
    "human_attention_recall": human_attention_recall,
    "topic_f1": topic_f1,
}


def label_scores(results: Results, labels: Labels) -> dict[str, Score]:
    return {key: fn(results, labels) for key, fn in LABEL_FUNCTIONS.items()}


def label_measures(results: Results, labels: Labels) -> dict[str, float]:
    """The label measures that have a value, as the criteria check stores them per split."""
    scores = label_scores(results, labels)
    return {k: v for k in LABEL_MEASURES if (v := scores[k].value) is not None}
