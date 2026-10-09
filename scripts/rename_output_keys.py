"""Rewrite renamed keys in existing output files in place, leaving every value as it is.

    uv run python scripts/rename_output_keys.py                  # data/out and tuned/thresholds.json
    uv run python scripts/rename_output_keys.py --out tests/fixtures/out --tuned none

Idempotent: a file already using the new keys is left untouched. Renames:

- every `triage.json`:            kind -> email_type, kind_probs -> email_type_probs,
                                  attention -> human_attention
- `tuned/thresholds.json`:        attention -> human_attention
- every `eval.json`:              measures attention_precision / attention_recall ->
                                  human_attention_precision / human_attention_recall
- every `criteria_history.json`:  the same two measure keys in each entry's fit and validation
- every `metrics.json`:           stage key attention -> human_attention

Old email_type values (the earlier six options) stay until the next classify run refreshes them.
"""

import argparse
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
TRIAGE_KEYS = {"kind": "email_type", "kind_probs": "email_type_probs", "attention": "human_attention"}
MEASURE_KEYS = {"attention_precision": "human_attention_precision", "attention_recall": "human_attention_recall"}
STAGE_KEYS = {"attention": "human_attention"}


def rename(d: dict[str, Any], keys: dict[str, str]) -> dict[str, Any]:
    """`d` with old keys renamed, in the same order; a key whose new name exists is dropped."""
    out: dict[str, Any] = {}
    for k, v in d.items():
        new = keys.get(k, k)
        if new != k and new in d:
            continue
        out[new] = v
    return out


def rewrite(path: Path, fix: Any) -> bool:
    before = json.loads(path.read_text())
    after = fix(before)
    if json.dumps(after) == json.dumps(before):  # order-sensitive: a renamed key changes it
        return False
    path.write_text(json.dumps(after, indent=2, ensure_ascii=False) + "\n")
    return True


def fix_triage(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [rename(r, TRIAGE_KEYS) for r in rows]


def fix_eval(report: dict[str, Any]) -> dict[str, Any]:
    out = dict(report)
    out["measures"] = rename(report.get("measures", {}), MEASURE_KEYS)
    for m in out.get("misses", []):
        m["measure"] = MEASURE_KEYS.get(m.get("measure", ""), m.get("measure"))
    return out


def fix_history(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{**e, "fit": rename(e.get("fit", {}), MEASURE_KEYS),
             "validation": rename(e.get("validation", {}), MEASURE_KEYS)} for e in entries]


def fix_metrics(report: dict[str, Any]) -> dict[str, Any]:
    return {**report, "stages": rename(report.get("stages", {}), STAGE_KEYS)}


def fix_thresholds(th: dict[str, Any]) -> dict[str, Any]:
    return rename(th, {"attention": "human_attention"})


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", type=Path, default=ROOT / "data" / "out", help="output directory to walk")
    parser.add_argument("--tuned", default=str(ROOT / "tuned" / "thresholds.json"),
                        help="tuned thresholds file, or 'none'")
    args = parser.parse_args()
    fixes = {"triage.json": fix_triage, "eval.json": fix_eval, "criteria_history.json": fix_history,
             "metrics.json": fix_metrics}
    changed: list[Path] = []
    for name, fix in fixes.items():
        for path in sorted(args.out.rglob(name)):
            if rewrite(path, fix):
                changed.append(path)
    if args.tuned != "none" and Path(args.tuned).exists() and rewrite(Path(args.tuned), fix_thresholds):
        changed.append(Path(args.tuned))
    for path in changed:
        print(f"rewrote {path}")
    print(f"{len(changed)} file(s) changed")


if __name__ == "__main__":
    main()
