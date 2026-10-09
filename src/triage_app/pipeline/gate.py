"""Stage 4 Label and gate: triage.json, redundancy.json -> results.json.

Owned by work package 4 (Classify and gate). See SPEC.md: Classification with Jev.

`run` is the fixed interface run.py calls. Inside it, wrap each email's `process` call in
`with ctx.recorder.stage(STAGE, email_id):` so monitoring times it per email.
"""

from pathlib import Path

from triage_app.pipeline.context import RunContext
from triage_app.schema import EmailResult, RedundancyRecord, Thresholds, TriageRecord

STAGE = "gate"


def run(in_dir: Path, out_dir: Path, ctx: RunContext) -> None:
    raise NotImplementedError(f"stage {STAGE} is not built yet")


def process(triage: TriageRecord, redundancy: RedundancyRecord, thresholds: Thresholds) -> EmailResult:
    """Quarantine, label, tickers and topics, attention, gate; reason composed by code."""
    raise NotImplementedError(f"stage {STAGE} is not built yet")
