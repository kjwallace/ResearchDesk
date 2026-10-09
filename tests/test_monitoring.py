import json
from pathlib import Path

import pytest

from fakes import FakeChat, FakeEmbedder
from triage_app.cache import DiskCache
from triage_app.llm import Message
from triage_app.monitoring import Recorder, build_report, cached_call, percentile, recording
from triage_app.schema import UsageReport


def test_percentile() -> None:
    assert percentile([], 50) == 0.0
    assert percentile([1, 2, 3, 4], 50) == pytest.approx(2.5)
    assert percentile([10], 95) == 10


def test_fake_calls_aggregate_into_report(tmp_path: Path) -> None:
    rec = Recorder()
    chat = FakeChat("ok", input_tokens=100, output_tokens=20)
    with recording(rec):
        for eid in ("e1", "e2"):
            with rec.stage("human_attention", eid):
                chat.complete(model="m", messages=[Message(role="user", content=eid)])
            with rec.stage("redundancy", eid):
                FakeEmbedder().embed([f"text {eid}"])
    report = rec.write(tmp_path, "day_1", emails=2)
    UsageReport.model_validate_json((tmp_path / "metrics.json").read_text())
    assert sorted(p.name for p in tmp_path.iterdir()) == ["metrics.json"]  # no per-call file
    assert len(rec.calls) == 4 and len(rec.timings) == 4
    att = report.stages["human_attention"]
    assert (att.calls, att.input_tokens, att.output_tokens) == (2, 200, 40)
    assert report.by_model["m"].calls == 2 and report.emails == 2
    assert report.tokens_per_email_mean == pytest.approx((240 + 4) / 2)


def test_cache_hit_counts_as_uncached_only(tmp_path: Path) -> None:
    rec, cache = Recorder(), DiskCache(tmp_path)
    calls = {"n": 0}

    def call() -> str:
        calls["n"] += 1
        return "answer"

    for _ in range(2):
        cached_call(namespace="t", model="m", payload={"x": 1}, call=call, dump=lambda v: v, load=str,
                    usage=lambda _v: (10, 5), cache=cache, recorder=rec)
    assert calls["n"] == 1 and [c.cache_hit for c in rec.calls] == [False, True]
    u = build_report("day_1", rec.calls, rec.timings, 1).by_model["m"]
    assert (u.input_tokens, u.uncached_input_tokens, u.cache_hits) == (10, 20, 1)


def test_missing_usage_is_estimated() -> None:
    rec = Recorder()
    cached_call(namespace="t", model="m", payload=1, call=lambda: "x" * 40, dump=lambda v: v, load=str,
                usage=lambda _v: None, input_text="y" * 400, recorder=rec)
    c = rec.calls[0]
    assert c.estimated and c.input_tokens == 100 and c.output_tokens > 0


def test_records_hold_no_text() -> None:
    rec = Recorder()
    with recording(rec), rec.stage("extract", "e1"):
        FakeChat("SECRET-OUTPUT").complete(model="m", messages=[Message(role="user", content="SECRET-INPUT")])
    dumped = json.dumps([c.model_dump(mode="json") for c in rec.calls] + [t.model_dump(mode="json") for t in rec.timings])
    assert "SECRET" not in dumped
    assert rec.calls[0].stage == "extract" and rec.calls[0].email_id == "e1"


def test_cost_estimates_use_the_price_table(monkeypatch: pytest.MonkeyPatch) -> None:
    from triage_app import thresholds
    monkeypatch.setattr(thresholds, "MODEL_PRICES", {"priced": (2.0, 10.0)})
    rec = Recorder()
    rec.record(model="priced", input_tokens=1_000_000, output_tokens=100_000, cache_hit=False, latency_ms=1)
    rec.record(model="priced", input_tokens=1_000_000, output_tokens=0, cache_hit=True, latency_ms=1)
    rec.record(model="jev", input_tokens=500, output_tokens=10, cache_hit=False, latency_ms=1)
    report = build_report("day_1", rec.calls, rec.timings, emails=2)
    assert report.cost_usd == pytest.approx(3.0)              # 2.00 input + 1.00 output, misses only
    assert report.uncached_cost_usd == pytest.approx(5.0)     # plus the cached call
    assert report.cost_per_email_usd == pytest.approx(1.5)
    assert report.unpriced_models == ["jev"]
    assert report.by_model["priced"].cost_usd == pytest.approx(3.0)
    assert report.by_model["jev"].cost_usd is None
