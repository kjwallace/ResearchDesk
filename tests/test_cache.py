from pathlib import Path

import pytest

from triage_app.cache import TRACE_ENV, DiskCache


def test_trace_records_entries_read_and_written(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    trace = tmp_path / "trace.txt"
    monkeypatch.setenv(TRACE_ENV, str(trace))
    cache = DiskCache(tmp_path / "cache")
    cache.put("extract", "abc", {"value": 1})
    assert cache.get("extract", "abc") == {"value": 1}
    assert cache.get("analyze", "missing") is None
    assert trace.read_text().splitlines() == ["extract/abc", "extract/abc", "analyze/missing"]


def test_no_trace_without_the_variable(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(TRACE_ENV, raising=False)
    DiskCache(tmp_path).put("jev", "k", {"value": 0})
    assert not list(tmp_path.glob("*.txt"))
