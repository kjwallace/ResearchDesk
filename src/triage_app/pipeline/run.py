"""Run the pipeline over one corpus set, writing every stage file to data/out/<set>/.

    uv run python -m triage_app.pipeline.run --set day_1
    uv run python -m triage_app.pipeline.run --set day_1 --stage classify   # one stage
    uv run python -m triage_app.pipeline.run --set day_1 --from extract     # a stage onward

Stages run in order. Stage A (attention) runs after the gate, beside 5 to 8. Each stage
is timed for the set, stages time each email themselves through the recorder, and the
run ends by writing usage.json and metrics.json and printing the monitoring summary.
"""

import argparse
import importlib
import json
from pathlib import Path
from types import ModuleType

from triage_app import config
from triage_app.config import CorpusSet
from triage_app.monitoring import format_summary, recording
from triage_app.pipeline.context import RunContext

STAGES = ("parse", "redundancy", "classify", "gate", "attention",
          "extract", "analyze", "validate", "merge", "deliver")


def stage_module(name: str) -> ModuleType:
    return importlib.import_module(f"triage_app.pipeline.{name}")


def select(stage: str | None, start: str | None) -> list[str]:
    if stage and start:
        raise SystemExit("use --stage or --from, not both")
    if stage:
        return [stage]
    if start:
        return list(STAGES[STAGES.index(start):])
    return list(STAGES)


def run_set(corpus_set: CorpusSet, stages: list[str], ctx: RunContext | None = None,
            corpus_dir: Path | None = None, out: Path | None = None) -> None:
    ctx = ctx or RunContext(corpus_set)
    corpus_dir = corpus_dir or config.CORPUS_DIR / corpus_set
    out = out or config.out_dir(corpus_set)
    out.mkdir(parents=True, exist_ok=True)
    with recording(ctx.recorder):
        for name in stages:
            in_dir = corpus_dir if name == "parse" else out
            print(f"[{corpus_set}] {name} ...", flush=True)
            with ctx.recorder.stage(name):
                stage_module(name).run(in_dir, out, ctx)
    parsed = out / "parsed.json"
    emails = len(json.loads(parsed.read_text())) if parsed.exists() else 0
    report = ctx.recorder.write(out, corpus_set, emails)
    print(format_summary(report))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--set", dest="corpus_set", required=True, choices=config.CORPUS_SETS)
    parser.add_argument("--stage", choices=STAGES)
    parser.add_argument("--from", dest="start", choices=STAGES)
    args = parser.parse_args()
    run_set(args.corpus_set, select(args.stage, args.start))


if __name__ == "__main__":
    main()
