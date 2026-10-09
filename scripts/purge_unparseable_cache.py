"""Delete cached model replies that can never parse, so the next run retries those calls.

A malformed reply is cached like any other (the cache stores the raw completion before
DSPy parses it), and a rerun would replay the same failure. This removes cached chat
replies that are empty, runs of tool-call tags such as `<parameter_thought>` or
`<parametrize>` with placeholder text, or that contain no JSON object or array at all.
Only those entries are removed; every other call stays cached.

    uv run python scripts/purge_unparseable_cache.py            # list and delete
    uv run python scripts/purge_unparseable_cache.py --dry-run  # list only
"""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from triage_app.config import CACHE_DIR  # noqa: E402

CHAT_NAMESPACES = ("attention", "extract", "analyze", "skill", "verify", "chat", "dspy")
DEGENERATE_MARKERS = ("<parameter_", "<parametrize>", "Placeholder")


def unparseable(entry: dict[str, object]) -> bool:
    """Empty, tool-tag runs, or text with no JSON object or array anywhere in it."""
    value = entry.get("value")
    if not isinstance(value, dict):
        return False
    text = str(value.get("text", ""))
    return (not text.strip() or any(marker in text for marker in DEGENERATE_MARKERS)
            or ("{" not in text and "[" not in text))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    found = [p for ns in CHAT_NAMESPACES for p in sorted((CACHE_DIR / ns).glob("*/*.json"))
             if unparseable(json.loads(p.read_text()))]
    for p in found:
        print(p.relative_to(ROOT))
        if not args.dry_run:
            p.unlink()
    print(f"{len(found)} unparseable cached repl{'y' if len(found) == 1 else 'ies'} "
          f"{'found' if args.dry_run else 'deleted'}")


if __name__ == "__main__":
    main()
