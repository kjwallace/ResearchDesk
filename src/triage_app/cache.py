"""On-disk cache for model calls and embeddings, committed under data/cache/.

Keys hash the program version, the criteria version and the input, so a rerun on the
same inputs costs nothing and the demo is deterministic.
"""

import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any

from triage_app.config import CACHE_DIR

PROGRAM_VERSION = "0.1.0"


def cache_key(namespace: str, payload: Any, criteria_version: str = "") -> str:
    blob = json.dumps(
        {"program": PROGRAM_VERSION, "criteria": criteria_version, "ns": namespace, "in": payload},
        sort_keys=True, default=str, ensure_ascii=False,
    )
    return hashlib.sha256(blob.encode()).hexdigest()


TRACE_ENV = "TRIAGE_CACHE_TRACE"  # a file path: every entry read or written is appended to it


class DiskCache:
    """One JSON file per entry: {"value": ..., "input_tokens": n, "output_tokens": n, "estimated": b}.

    With TRIAGE_CACHE_TRACE set to a file, each entry used (read or written) is logged there as
    "<namespace>/<key>", so `scripts/prune_cache.py` can keep exactly the entries runs need.
    """

    def __init__(self, root: Path = CACHE_DIR, overlay: Path | None = None) -> None:
        # `root` is the committed cache, which may be read-only (a serverless bundle). New entries
        # that cannot be written there go to `overlay` (a temp folder), which is read first.
        self.root = root
        self.overlay = overlay or Path(tempfile.gettempdir()) / "triage_cache"

    def _path(self, namespace: str, key: str, root: Path | None = None) -> Path:
        return (root or self.root) / namespace / key[:2] / f"{key}.json"

    def _trace(self, namespace: str, key: str) -> None:
        trace = os.environ.get(TRACE_ENV)
        if trace:
            with open(trace, "a") as f:
                f.write(f"{namespace}/{key}\n")

    def get(self, namespace: str, key: str) -> dict[str, Any] | None:
        self._trace(namespace, key)
        for root in (self.root, self.overlay):
            path = self._path(namespace, key, root)
            if path.exists():
                entry: dict[str, Any] = json.loads(path.read_text())
                return entry
        return None

    def put(self, namespace: str, key: str, entry: dict[str, Any]) -> None:
        self._trace(namespace, key)
        text = json.dumps(entry, ensure_ascii=False, sort_keys=True)
        for root in (self.root, self.overlay):
            path = self._path(namespace, key, root)
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(text)
                return
            except OSError:   # read-only filesystem: fall through to the temp overlay
                if root is self.overlay:
                    return   # nowhere to write; the call still succeeded, it just is not remembered
