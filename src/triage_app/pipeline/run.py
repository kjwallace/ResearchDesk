"""Run the pipeline over one corpus set, writing every stage file to data/out/<set>/.

    uv run python -m triage_app.pipeline.run --set day_1
    uv run python -m triage_app.pipeline.run --set day_1 --stage classify   # one stage
    uv run python -m triage_app.pipeline.run --set day_1 --from extract     # a stage onward

Every stage reads the set's emails from data/corpus/<set>/emails.jsonl through the corpus
loader (`ctx.emails`: label-free, bodies exactly as in the corpus); no stage writes them out.
Stages run in order. Stage A (human_attention: attention notes) runs after the gate, beside
5 to 8. Each stage is timed for the set, stages time each email themselves through the
recorder, and the run ends by writing metrics.json and SUMMARY.md and printing the
monitoring summary.
"""

import argparse
import importlib
from pathlib import Path
from types import ModuleType

from triage_app import config
from triage_app.config import CorpusSet
from triage_app.monitoring import format_summary, recording
from triage_app.pipeline import summary
from triage_app.pipeline.context import RunContext

STAGES = ("redundancy", "classify", "gate", "human_attention",
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
            emails_path: Path | None = None, out: Path | None = None) -> None:
    ctx = ctx or RunContext(corpus_set)
    if ctx.emails_path is None:
        ctx.emails_path = emails_path or config.corpus_file(corpus_set)
    out = out or config.out_dir(corpus_set)
    out.mkdir(parents=True, exist_ok=True)
    with recording(ctx.recorder):
        for name in stages:
            print(f"[{corpus_set}] {name} ...", flush=True)
            with ctx.recorder.stage(name):
                stage_module(name).run(out, out, ctx)
    report = ctx.recorder.write(out, corpus_set, len(ctx.emails))
    summary.write(out, corpus_set, ctx.emails, report, ctx.thresholds)
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
