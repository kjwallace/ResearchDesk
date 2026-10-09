"""Stage 4 Label and gate: triage.json, redundancy.json -> results.json.

Owned by work package 4 (Classify and gate). See SPEC.md: Classification with Jev.

Pure code, in this order: quarantine, label, tickers and topics, attention, gate on the
signal score. The one-line reason is composed here from probabilities and thresholds
(wording in DECISIONS.md #21); no model writes it.
"""

from pathlib import Path

from triage_app import thresholds as limits  # the module; `thresholds` here is a Thresholds value
from triage_app import config
from triage_app.pipeline.context import RunContext
from triage_app.pipeline.io import read_list, write_list
from triage_app.schema import EmailResult, RedundancyRecord, Thresholds, TriageRecord

STAGE = "gate"


def run(in_dir: Path, out_dir: Path, ctx: RunContext) -> None:
    triage = read_list(in_dir / "triage.json", TriageRecord)
    redundancy = {r.email_id: r for r in read_list(in_dir / "redundancy.json", RedundancyRecord)}
    thresholds = ctx.thresholds
    results: list[EmailResult] = []
    for record in triage:
        with ctx.recorder.stage(STAGE, record.email_id):
            results.append(process(record, redundancy[record.email_id], thresholds))
    write_list(out_dir / "results.json", results)


def signal_score(triage: TriageRecord) -> float:
    """P(thesis_relevant) + P(monitor), rounded so float noise never moves the gate."""
    return round(triage.triage_probs.get("thesis_relevant", 0.0) + triage.triage_probs.get("monitor", 0.0), limits.SIGNAL_SCORE_DECIMALS)


def process(triage: TriageRecord, redundancy: RedundancyRecord, thresholds: Thresholds) -> EmailResult:
    """Quarantine, label, tickers and topics, attention, gate; reason composed by code."""
    signal = signal_score(triage)

    # 1. Quarantine on either safety question; nothing further runs.
    tripped = {q: p for q, p in triage.safety.items() if p >= limits.QUARANTINE}
    if tripped:
        question = max(tripped, key=lambda q: tripped[q])
        return EmailResult(
            email_id=triage.email_id, triage=None, decided_by="quarantine", redundant_of=None,
            affected_tickers=[], additional_labels=[], human_attention=False,
            signal_score=signal, gate="quarantine",
            reason=f"quarantined: {question} {tripped[question]:.2f} reaches {limits.QUARANTINE:.2f}",
        )

    # 2. Label: Jev's most probable label, unless the check flags a repeat below the gate.
    jev_label = max(config.TRIAGE_LABELS, key=lambda label: triage.triage_probs.get(label, 0.0))
    jev_part = f"{jev_label} {triage.triage_probs.get(jev_label, 0.0):.2f}"
    label, decided_by, redundant_of, label_part = jev_label, "jev", None, jev_part
    if (redundancy.flagged and signal < thresholds.pass_signal
            and jev_label != "redundant" and redundancy.nearest is not None):
        label, decided_by, redundant_of = "redundant", "redundancy_check", redundancy.nearest
        label_part = (f"redundant: repeat of {redundancy.nearest} "
                      f"(content {redundancy.content_similarity or 0.0:.2f}, "
                      f"subject {redundancy.subject_score or 0.0:.2f}); jev {jev_part}")

    # 3. Tickers and topics at their thresholds.
    tickers = [t for t in config.TICKERS
               if triage.ticker_probs.get(t, 0.0) >= thresholds.ticker.get(t, limits.TICKER_THRESHOLD)]
    topics = [t for t in config.TOPICS
              if triage.topic_probs.get(t, 0.0) >= thresholds.topic.get(t, limits.TOPIC_THRESHOLD)]

    # 4. Human attention.
    attention = triage.attention >= thresholds.attention

    # 5. Gate on the signal score, or pass a truncated email on its first chunk.
    if signal >= thresholds.pass_signal:
        gate, gate_part = "pass", f"signal score {signal:.2f} clears {thresholds.pass_signal:.2f}"
    elif triage.truncated:
        gate, gate_part = "pass", (f"signal score {signal:.2f} is below {thresholds.pass_signal:.2f}; "
                                   "truncated, passed on the first chunk")
    else:
        gate, gate_part = "stop", f"signal score {signal:.2f} is below {thresholds.pass_signal:.2f}"

    return EmailResult(
        email_id=triage.email_id, triage=label, decided_by=decided_by, redundant_of=redundant_of,
        affected_tickers=tickers, additional_labels=topics, human_attention=attention,
        signal_score=signal, gate=gate, reason=f"{label_part}; {gate_part}",
    )
