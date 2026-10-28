"""The Vercel deployment: hosted embeddings, a read-only cache, the slim dependency set and the bundle."""

import ast
import json
import os
import re
import stat
import subprocess
import sys
from pathlib import Path
from typing import Any

import httpx
import numpy as np
import pytest

from triage_app import config, thresholds
from triage_app.cache import DiskCache
from triage_app.embed import RemoteEmbedder
from triage_app.monitoring import Recorder
from triage_app.pipeline.context import RunContext

ROOT = Path(__file__).parent.parent


class FakeEmbeddings:
    """Stands in for httpx.post against the embeddings endpoint, with vectors of known length."""

    def __init__(self, replies: list[Any] | None = None) -> None:
        self.calls: list[dict[str, Any]] = []
        self.replies = replies or []

    def __call__(self, url: str, *, json: dict[str, Any], headers: dict[str, str], timeout: float) -> httpx.Response:
        self.calls.append({"url": url, "json": json, "auth": headers["Authorization"]})
        if self.replies:
            reply: httpx.Response = self.replies.pop(0)
            return reply
        data = [{"index": i, "embedding": [float(len(t)), 1.0, 2.0]} for i, t in enumerate(json["input"])]
        return httpx.Response(200, json={"data": list(reversed(data))})   # out of order on purpose


@pytest.fixture
def post(monkeypatch: pytest.MonkeyPatch) -> FakeEmbeddings:
    fake = FakeEmbeddings()
    monkeypatch.setattr(httpx, "post", fake)
    monkeypatch.setattr("time.sleep", lambda _s: None)
    return fake


def embedder(tmp_path: Path, **kw: Any) -> RemoteEmbedder:
    return RemoteEmbedder("test/model", api_key="sk-test", cache=DiskCache(tmp_path / "c", tmp_path / "o"), **kw)


def test_remote_embedder_batches_normalises_and_orders(post: FakeEmbeddings, tmp_path: Path) -> None:
    vecs = embedder(tmp_path).embed(["a", "bbb", "a"])
    assert len(post.calls) == 1 and post.calls[0]["json"]["input"] == ["a", "bbb"]   # one request, duplicates folded
    assert post.calls[0]["auth"] == "Bearer sk-test" and post.calls[0]["url"].endswith("/embeddings")
    assert np.allclose(np.linalg.norm(vecs, axis=1), 1.0)
    assert np.allclose(vecs[0], vecs[2]) and not np.allclose(vecs[0], vecs[1])         # each text got its own vector


def test_remote_embedder_uses_the_cache_and_records_hits(post: FakeEmbeddings, tmp_path: Path) -> None:
    rec = Recorder()
    e = embedder(tmp_path, recorder=rec)
    e.embed(["hello"])
    e.embed(["hello"])
    assert len(post.calls) == 1
    assert [c.cache_hit for c in rec.calls] == [False, True]


def test_remote_embedder_splits_batches(post: FakeEmbeddings, tmp_path: Path) -> None:
    texts = [f"t{i}" for i in range(thresholds.REMOTE_EMBED_BATCH + 5)]
    embedder(tmp_path).embed(texts)
    assert [len(c["json"]["input"]) for c in post.calls] == [thresholds.REMOTE_EMBED_BATCH, 5]


def test_remote_embedder_retries_rate_limits_and_reports_errors(post: FakeEmbeddings, tmp_path: Path) -> None:
    post.replies = [httpx.Response(429, json={}), httpx.Response(200, json={"data": [{"index": 0, "embedding": [3.0, 4.0]}]})]
    assert np.allclose(embedder(tmp_path).embed(["x"])[0], [0.6, 0.8])
    post.replies = [httpx.Response(401, text="bad key")]
    with pytest.raises(RuntimeError, match="401"):
        embedder(tmp_path).embed(["y"])


def test_remote_embedder_needs_a_key_and_trims_overlong_chunks(post: FakeEmbeddings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="OPENROUTER_API_KEY"):
        RemoteEmbedder("m", cache=None, use_cache=False).embed(["x"])
    too_long = httpx.Response(400, text='{"error":{"message":"the model\'s context length is only 512 tokens"}}')
    post.replies = [too_long, too_long, httpx.Response(200, json={"data": [{"index": 0, "embedding": [1.0, 0.0]}]})]
    embedder(tmp_path).embed(["z" * 1000])
    assert len(post.calls[-1]["json"]["input"][0]) < len(post.calls[0]["json"]["input"][0])


def test_chunk_size_estimate_stays_under_the_model_limit(tmp_path: Path) -> None:
    e = embedder(tmp_path)
    assert e.max_tokens == thresholds.REMOTE_EMBED_MAX_TOKENS
    assert e.count_tokens("x" * 1000) >= 500   # a dense text is counted generously, so chunks stay under 512


def test_context_picks_the_hosted_embedder_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EMBEDDING_BACKEND", "openrouter")
    monkeypatch.setenv("EMBEDDING_MODEL", "baai/bge-base-en-v1.5")
    ctx = RunContext("day_1", use_cache=False)
    assert isinstance(ctx.embedder, RemoteEmbedder) and ctx.embedder.model == "baai/bge-base-en-v1.5"


def test_cache_falls_back_to_a_temp_overlay_when_the_bundle_is_read_only(tmp_path: Path) -> None:
    bundle = tmp_path / "bundle"
    (bundle / "chat").mkdir(parents=True)
    (bundle / "chat" / "ab").mkdir()
    (bundle / "chat" / "ab" / "abc.json").write_text(json.dumps({"value": "bundled"}))
    bundle.chmod(stat.S_IRUSR | stat.S_IXUSR)
    for d in bundle.rglob("*"):
        if d.is_dir():
            d.chmod(stat.S_IRUSR | stat.S_IXUSR)
    try:
        cache = DiskCache(bundle, tmp_path / "overlay")
        assert cache.get("chat", "abc") == {"value": "bundled"}            # reads the bundle
        cache.put("chat", "cd0", {"value": "new"})                           # cannot write there
        assert cache.get("chat", "cd0") == {"value": "new"}                  # served from the overlay
        assert (tmp_path / "overlay" / "chat" / "cd" / "cd0.json").exists()
    finally:
        for d in [bundle, *bundle.rglob("*")]:
            if d.is_dir():
                d.chmod(stat.S_IRWXU)


def test_requirements_cover_every_import_and_leave_out_the_local_embedding_model() -> None:
    names = {re.split(r"[\[=<>]", line.strip())[0].lower().replace("-", "_")
             for line in (ROOT / "requirements.txt").read_text().splitlines() if line.strip() and not line.startswith("#")}
    assert {"dspy", "typesafe_sdk", "rapidfuzz", "httpx", "numpy", "fastapi"} <= names
    assert not names & {"sentence_transformers", "torch", "huggingface_hub", "jupyter"}
    stdlib = set(sys.stdlib_module_names)
    provided = names | {"triage_app", "typesafe_sdk", "dotenv", "markupsafe", "starlette", "multipart"}
    lazy = {"sentence_transformers", "nbformat", "nbclient"}   # only the local embedder and the notebook builder
    imported: set[str] = set()
    for path in (ROOT / "src" / "triage_app").rglob("*.py"):
        if "evals" in path.parts:
            continue
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Import):
                imported |= {a.name.split(".")[0] for a in node.names}
            elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                imported.add(node.module.split(".")[0])
    missing = {m for m in imported - stdlib - provided - lazy if m.lower() not in names}
    assert not missing, f"not in requirements.txt: {sorted(missing)}"


def test_vercel_bundle_config() -> None:
    cfg = json.loads((ROOT / "vercel.json").read_text())["functions"]["app.py"]
    assert "data/cache_web/**" in cfg["includeFiles"] and "data/out/day_1/**" in cfg["includeFiles"]
    assert cfg["maxDuration"] >= 120
    ignore = (ROOT / ".vercelignore").read_text().split()
    assert {"pyproject.toml", "uv.lock", ".env", ".env.*"} <= set(ignore)
    entry = (ROOT / "app.py").read_text()
    assert "EMBEDDING_BACKEND" in entry and "TRIAGE_CACHE_DIR" in entry and "sk-" not in entry
    size_mb = sum(p.stat().st_size for p in (ROOT / "data" / "cache_web").rglob("*") if p.is_file()) / 1e6
    assert size_mb < 40   # the function's cache stays small


def test_presets_replay_from_the_shipped_cache_with_hosted_embeddings_and_no_network() -> None:
    try:
        for name in ("JEV_MODEL", "ANALYSIS_MODEL", "NOTES_MODEL"):
            config.model_id(name)
    except config.MissingModelError:
        pytest.skip("cache keys include the model IDs; set them in .env to replay the shipped cache")
    script = '''
import json, re, sys
from pathlib import Path
sys.path.insert(0, ".")
import app
import httpx
def no_network(*a, **k): raise AssertionError("network used")
httpx.post = no_network
from fastapi.testclient import TestClient
c = TestClient(app.app)
bad = []
for p in sorted(Path("data/live_presets").glob("*.json")):
    eid = json.loads(p.read_text())["email_id"]
    t = re.sub(r"\\s+", " ", re.sub(r"<[^>]+>", " ", c.post("/live", data={"preset": eid}, headers={"HX-Request": "true"}).text))
    m = re.search(r"(\\d+) model calls? \\((\\d+) cached\\)", t)
    if "Failed (" in t or (m and m.group(1) != m.group(2)): bad.append(eid)
print("BAD", bad)
'''
    env = {**os.environ, "OPENROUTER_API_KEY": "unused", "TYPESAFE_API_KEY": "unused"}
    for k in ("TRIAGE_DATA_DIR", "TRIAGE_CACHE_DIR", "EMBEDDING_BACKEND", "EMBEDDING_MODEL"):
        env.pop(k, None)   # the entrypoint must supply these itself
    out = subprocess.run([sys.executable, "-c", script], cwd=ROOT, env=env, capture_output=True, text=True, timeout=600)
    assert "BAD []" in out.stdout, out.stdout[-600:] + out.stderr[-600:]


def test_requirements_pins_match_the_locked_versions() -> None:
    """requirements.txt (Vercel) and uv.lock (local, Docker) are two lists; they must not drift apart."""
    import tomllib

    lock = tomllib.loads((ROOT / "uv.lock").read_text())
    locked = {p["name"].lower().replace("_", "-"): p["version"] for p in lock["package"]}
    for line in (ROOT / "requirements.txt").read_text().splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        m = re.match(r"([A-Za-z0-9_.\-]+)(?:\[[^\]]*\])?==(.+)", line.strip())
        assert m, f"requirements.txt line is not a pinned version: {line}"
        name = m.group(1).lower().replace("_", "-")
        assert locked.get(name) == m.group(2), f"{name}: requirements {m.group(2)} vs uv.lock {locked.get(name)}"
