"""Token use and latency for every model call and every stage.

See SPEC.md, "Monitoring: token use and latency".

- Every model and embedding call goes through `cached_call`, which checks the disk
  cache, times the call, reads token usage (or estimates it) and appends a CallRecord
  to the current Recorder. Modules never time themselves.
- `pipeline/run.py` wraps each stage in `recorder.stage(name, email_id)`, which appends a
  StageTiming and tells `cached_call` which stage and email a call belongs to.
- `build_report` turns the records into a UsageReport. It is a pure function.

The records stay in memory; a run writes only the run-level UsageReport (metrics.json).
Records hold IDs, counts and times only: never prompt text, email text or keys.
"""

import json
import time
from collections import defaultdict
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, TypeVar

from triage_app.cache import DiskCache, cache_key
from triage_app.thresholds import CHARS_PER_TOKEN
from triage_app.schema import CallRecord, StageTiming, StageUsage, UsageReport

T = TypeVar("T")
ReportCorpus = Literal["day_1", "day_2", "tuning", "live"]


def estimate_tokens(text: str) -> int:
    return max(1, len(text) // CHARS_PER_TOKEN) if text else 0


class Recorder:
    """Collects CallRecords and StageTimings for one run."""

    def __init__(self) -> None:
        self.calls: list[CallRecord] = []
        self.timings: list[StageTiming] = []
        self._where: ContextVar[tuple[str, str | None]] = ContextVar("where", default=("unknown", None))

    @property
    def where(self) -> tuple[str, str | None]:
        return self._where.get()

    @contextmanager
    def stage(self, stage: str, email_id: str | None = None) -> Iterator[None]:
        token = self._where.set((stage, email_id))
        start = time.perf_counter()
        try:
            yield
        finally:
            self.timings.append(StageTiming(
                stage=stage, email_id=email_id, latency_ms=(time.perf_counter() - start) * 1000,
            ))
            self._where.reset(token)

    def record(self, *, model: str, input_tokens: int, output_tokens: int, cache_hit: bool,
               latency_ms: float, estimated: bool = False, stage: str | None = None,
               email_id: str | None = None) -> CallRecord:
        cur_stage, cur_email = self.where
        rec = CallRecord(
            stage=stage or cur_stage, email_id=email_id if email_id is not None else cur_email,
            model=model, input_tokens=input_tokens, output_tokens=output_tokens,
            estimated=estimated, cache_hit=cache_hit, latency_ms=latency_ms, at=datetime.now(UTC),
        )
        self.calls.append(rec)
        return rec

    def report(self, corpus: ReportCorpus, emails: int) -> UsageReport:
        return build_report(corpus, self.calls, self.timings, emails)

    def write(self, out_dir: Path, corpus: ReportCorpus, emails: int) -> UsageReport:
        """Write metrics.json, the run-level report; per-call records are not written."""
        out_dir.mkdir(parents=True, exist_ok=True)
        report = self.report(corpus, emails)
        (out_dir / "metrics.json").write_text(report.model_dump_json(indent=2))
        return report


_current: ContextVar[Recorder | None] = ContextVar("recorder", default=None)


def current_recorder() -> Recorder | None:
    return _current.get()


@contextmanager
def recording(recorder: Recorder) -> Iterator[Recorder]:
    """Make `recorder` the one `cached_call` writes to, for the duration of the block."""
    token = _current.set(recorder)
    try:
        yield recorder
    finally:
        _current.reset(token)


def cached_call(
    *,
    namespace: str,
    model: str,
    payload: Any,
    call: Callable[[], T],
    dump: Callable[[T], Any],
    load: Callable[[Any], T],
    usage: Callable[[T], tuple[int | None, int | None] | None],
    input_text: str = "",
    criteria_version: str = "",
    cache: DiskCache | None = None,
    recorder: Recorder | None = None,
) -> T:
    """Run one model or embedding call through the cache, recording tokens and latency.

    `payload` is everything that determines the answer (it is hashed for the key).
    `usage` reads (input_tokens, output_tokens) from the response; when either is None,
    tokens are estimated from `input_text` and the dumped output, and marked estimated.
    """
    rec = recorder or current_recorder()
    key = cache_key(namespace, payload, criteria_version)
    start = time.perf_counter()
    if cache is not None:
        hit = cache.get(namespace, key)
        if hit is not None:
            value = load(hit["value"])
            if rec is not None:
                rec.record(model=model, input_tokens=hit["input_tokens"], output_tokens=hit["output_tokens"],
                           estimated=hit.get("estimated", False), cache_hit=True,
                           latency_ms=(time.perf_counter() - start) * 1000)
            return value

    start = time.perf_counter()
    result = call()
    latency_ms = (time.perf_counter() - start) * 1000
    dumped = dump(result)
    counts = usage(result)
    in_tok, out_tok = counts if counts is not None else (None, None)
    estimated = in_tok is None or out_tok is None
    if in_tok is None:
        in_tok = estimate_tokens(input_text)
    if out_tok is None:
        out_tok = estimate_tokens(json.dumps(dumped, default=str))
    if cache is not None:
        cache.put(namespace, key, {"value": dumped, "input_tokens": in_tok,
                                   "output_tokens": out_tok, "estimated": estimated})
    if rec is not None:
        rec.record(model=model, input_tokens=in_tok, output_tokens=out_tok, estimated=estimated,
                   cache_hit=False, latency_ms=latency_ms)
    return result


# ---- Report ----

def percentile(values: list[float], q: float) -> float:
    """Linear-interpolated percentile, q in [0, 100]; 0.0 for no values."""
    if not values:
        return 0.0
    xs = sorted(values)
    pos = (len(xs) - 1) * q / 100
    lo = int(pos)
    hi = min(lo + 1, len(xs) - 1)
    return xs[lo] + (xs[hi] - xs[lo]) * (pos - lo)


def _usage(calls: list[CallRecord], latencies: list[float]) -> StageUsage:
    misses = [c for c in calls if not c.cache_hit]
    return StageUsage(
        calls=len(calls),
        cache_hits=len(calls) - len(misses),
        input_tokens=sum(c.input_tokens for c in misses),
        output_tokens=sum(c.output_tokens for c in misses),
        uncached_input_tokens=sum(c.input_tokens for c in calls),
        uncached_output_tokens=sum(c.output_tokens for c in calls),
        latency_p50_ms=percentile(latencies, 50),
        latency_p95_ms=percentile(latencies, 95),
        latency_max_ms=max(latencies, default=0.0),
    )


def build_report(corpus: ReportCorpus, calls: list[CallRecord], timings: list[StageTiming],
                 emails: int) -> UsageReport:
    """Stage latency comes from per-email StageTimings; model latency from CallRecords."""
    calls_by_stage: dict[str, list[CallRecord]] = defaultdict(list)
    for c in calls:
        calls_by_stage[c.stage].append(c)
    per_email_by_stage: dict[str, list[float]] = defaultdict(list)
    per_email_total: dict[str, float] = defaultdict(float)
    set_level_total = 0.0
    for t in timings:
        if t.email_id is None:
            set_level_total += t.latency_ms
        else:
            per_email_by_stage[t.stage].append(t.latency_ms)
            per_email_total[t.email_id] += t.latency_ms

    stage_names = sorted(set(calls_by_stage) | set(per_email_by_stage))
    stages = {s: _usage(calls_by_stage.get(s, []), per_email_by_stage.get(s, [])) for s in stage_names}

    calls_by_model: dict[str, list[CallRecord]] = defaultdict(list)
    for c in calls:
        calls_by_model[c.model].append(c)
    by_model = {m: _usage(cs, [c.latency_ms for c in cs]) for m, cs in sorted(calls_by_model.items())}

    spent = sum(c.input_tokens + c.output_tokens for c in calls if not c.cache_hit)
    email_latencies = list(per_email_total.values())
    return UsageReport(
        corpus=corpus,
        run_at=datetime.now(UTC),
        emails=emails,
        stages=stages,
        by_model=by_model,
        tokens_per_email_mean=spent / emails if emails else 0.0,
        email_latency_p50_ms=percentile(email_latencies, 50),
        email_latency_p95_ms=percentile(email_latencies, 95),
        total_latency_ms=set_level_total or sum(email_latencies),
    )


def format_summary(report: UsageReport) -> str:
    """Plain-text table that run.py prints at the end of a run."""
    lines = [f"{'stage':<12}{'calls':>7}{'hits':>6}{'in tok':>10}{'out tok':>9}{'p50 ms':>9}{'p95 ms':>9}"]
    for name, u in report.stages.items():
        lines.append(f"{name:<12}{u.calls:>7}{u.cache_hits:>6}{u.input_tokens:>10}{u.output_tokens:>9}"
                     f"{u.latency_p50_ms:>9.1f}{u.latency_p95_ms:>9.1f}")
    lines.append(
        f"{report.emails} emails; {report.tokens_per_email_mean:.0f} tokens/email spent; "
        f"email latency p50 {report.email_latency_p50_ms:.0f} ms, p95 {report.email_latency_p95_ms:.0f} ms; "
        f"total {report.total_latency_ms / 1000:.1f} s"
    )
    return "\n".join(lines)
