from pathlib import Path

import pytest

from triage_app.criteria import CriteriaError, criteria_text, load, parse_file

GOOD = "# monitor\n\n## Definition\nSome definition.\n\n## Rules\n- R1: One rule.\n- R2: A rule that\n      wraps.\n"


def write(tmp: Path, name: str, text: str) -> Path:
    p = tmp / f"{name}.md"
    p.write_text(text)
    return p


def test_repo_criteria_load_and_hash() -> None:
    c = load()
    assert len(c.labels) == 11 and len(c.version) == 12
    assert load().version == c.version
    assert criteria_text(c, "monitor").startswith(c.labels["monitor"].definition)


def test_parse_wrapped_rule(tmp_path: Path) -> None:
    lc = parse_file(write(tmp_path, "monitor", GOOD))
    assert [r.id for r in lc.rules] == ["R1", "R2"] and lc.rules[1].text == "A rule that wraps."


@pytest.mark.parametrize("bad", [
    GOOD.replace("# monitor", "# other"),
    GOOD.replace("## Definition\nSome definition.\n", "## Definition\n"),
    GOOD.replace("- R2", "- R1"),
    GOOD + "- R3: Mentions NVDA.p1 directly.\n",
    GOOD + "- R3: Weighs MSFT.capex guidance.\n",
    GOOD + "".join(f"- R{i}: Rule.\n" for i in range(3, 14)),
])
def test_rejects(tmp_path: Path, bad: str) -> None:
    with pytest.raises(CriteriaError):
        parse_file(write(tmp_path, "monitor", bad))


def test_version_changes_with_text(tmp_path: Path) -> None:
    import shutil

    from triage_app.config import CRITERIA_DIR
    for f in CRITERIA_DIR.glob("*.md"):
        shutil.copy(f, tmp_path / f.name)
    v1 = load(tmp_path).version
    p = tmp_path / "monitor.md"
    p.write_text(p.read_text() + "- R9: An added rule.\n")
    assert load(tmp_path).version != v1
