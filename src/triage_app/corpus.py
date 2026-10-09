"""Corpus loader: split, normalize, check, report. Owned by work package 2.

Only this module, evals and tuning read EmailLabel. See SPEC.md, "Corpus".

Usage:
    uv run python -m triage_app.corpus --set day_1
"""

from pathlib import Path

from triage_app.schema import Email, EmailLabel


def load(path: Path) -> tuple[list[Email], list[EmailLabel]]:
    """Split each row into an Email and an EmailLabel, normalized and checked."""
    raise NotImplementedError("corpus loader is not built yet")


def main() -> None:
    raise NotImplementedError("corpus loader is not built yet")


if __name__ == "__main__":
    main()
