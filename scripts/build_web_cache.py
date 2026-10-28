"""Rebuild data/cache_web/, the trimmed model cache the Vercel function ships.

    uv run python scripts/build_web_cache.py

Runs every Live preset against day_1 the way the deployed app does (hosted embeddings, the model
IDs in .env), records which cache entries the runs read or write (TRIAGE_CACHE_TRACE), and copies
exactly those entries from data/cache/ into a fresh data/cache_web/. Entries that are not in
data/cache/ yet are created by the run, so this needs OPENROUTER_API_KEY and TYPESAFE_API_KEY
the first time a preset or the day_1 repeat check is cold; a warm cache costs nothing.
"""

import json
import os
import shutil
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main() -> None:
    trace = Path(tempfile.mkdtemp()) / "trace.txt"
    os.environ.update({"EMBEDDING_BACKEND": "openrouter", "EMBEDDING_MODEL": "baai/bge-base-en-v1.5",
                       "TRIAGE_DATA_DIR": "data/out/day_1", "TRIAGE_CACHE_TRACE": str(trace)})
    os.environ.pop("TRIAGE_CACHE_DIR", None)   # read and write the full cache, not the trimmed one
    os.chdir(ROOT)

    from fastapi.testclient import TestClient

    from triage_app.web.main import app

    ids = [json.loads(p.read_text())["email_id"] for p in sorted((ROOT / "data" / "live_presets").glob("*.json"))]
    with TestClient(app) as client:
        for email_id in ids:
            r = client.post("/live", data={"preset": email_id}, headers={"HX-Request": "true"})
            print(f"{email_id}: HTTP {r.status_code}")

    target = ROOT / "data" / "cache_web"
    shutil.rmtree(target, ignore_errors=True)
    copied = missing = 0
    for line in sorted(set(trace.read_text().split())):
        namespace, key = line.split("/")
        src = ROOT / "data" / "cache" / namespace / key[:2] / f"{key}.json"
        if not src.exists():
            missing += 1
            continue
        dst = target / namespace / key[:2] / f"{key}.json"
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(src, dst)
        copied += 1
    print(f"copied {copied} entries to {target.relative_to(ROOT)} ({missing} read but not on disk)")


if __name__ == "__main__":
    main()
