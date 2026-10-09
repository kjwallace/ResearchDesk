"""Move cache entries that no run uses to the Trash, keeping exactly the ones in a trace.

1. Record which entries runs use, by running every consumer with tracing on:
       TRIAGE_CACHE_TRACE=/tmp/cache.trace uv run python -m triage_app.pipeline.run --set day_1
       ... (each set, the notebook, the live presets)
2. Prune everything the trace does not name:
       uv run python scripts/prune_cache.py /tmp/cache.trace --dry-run
       uv run python scripts/prune_cache.py /tmp/cache.trace

Entries are moved to ~/.Trash/cache-prune-<time>/ (recoverable), not deleted.
"""

import argparse
import shutil
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from triage_app.config import CACHE_DIR  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("trace", type=Path)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    used = {line.strip() for line in args.trace.read_text().splitlines() if line.strip()}
    entries = sorted(CACHE_DIR.glob("*/*/*.json"))
    unused = [p for p in entries if f"{p.parent.parent.name}/{p.stem}" not in used]
    by_ns = Counter(p.parent.parent.name for p in unused)
    print(f"{len(entries)} entries; {len(entries) - len(unused)} used; {len(unused)} unused: {dict(by_ns)}")
    if args.dry_run or not unused:
        return
    dest = Path.home() / ".Trash" / f"cache-prune-{datetime.now():%Y%m%d-%H%M%S}"
    for p in unused:
        target = dest / p.relative_to(CACHE_DIR)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(p), str(target))
    for d in sorted(CACHE_DIR.glob("*/*"), reverse=True):
        if d.is_dir() and not any(d.iterdir()):
            d.rmdir()
    for d in sorted(CACHE_DIR.glob("*")):
        if d.is_dir() and not any(d.iterdir()):
            d.rmdir()
    print(f"moved {len(unused)} entries to {dest}")


if __name__ == "__main__":
    main()
