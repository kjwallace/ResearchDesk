import pytest

from triage_app import thresholds
from triage_app import config


def test_models_come_only_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANALYSIS_MODEL", "vendor/some-model")
    assert config.ANALYSIS_MODEL == "vendor/some-model"
    monkeypatch.delenv("ANALYSIS_MODEL")
    with pytest.raises(config.MissingModelError):
        _ = config.ANALYSIS_MODEL


def test_starting_thresholds_and_override(tmp_path: object) -> None:
    from pathlib import Path
    t = thresholds.starting_thresholds()
    assert t.pass_signal == 0.6 and t.subject_match == 0.6 and set(t.ticker) == set(config.TICKERS)
    p = Path(str(tmp_path)) / "thresholds.json"
    p.write_text(t.model_copy(update={"pass_signal": 0.3, "subject_match": 0.1}).model_dump_json())
    loaded = thresholds.load_thresholds(p)
    assert loaded.pass_signal == 0.3 and loaded.subject_match == 0.6  # redundancy stays fixed
