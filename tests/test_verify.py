import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from fakes import FIXTURE_EMAILS, FakeChat, FakeEmbedder

from triage_app import thresholds
from triage_app import config
from triage_app.llm import Message
from triage_app.modules import verify_agent
from triage_app.modules.verify_agent import LIMIT_REACHED, NO_SOURCE, VerifyAgent, verify
from triage_app.pipeline.context import RunContext
from triage_app.pipeline.io import read_list
from triage_app.schema import Claim, LinkedSection, LogEntry, Suggestion, VerifyResult

OUT = config.FIXTURES_DIR / "out"
CLOUD = ("Intelligent Cloud revenue increased 21% driven by Azure and other cloud services, which grew 34% "
         "as consumption-based services expanded across every customer segment this year.")
FILING = "\n\n".join([
    "PART I",
    "Item 1. Business. We are a technology company whose mission is to empower every person and every "
    "organization on the planet to achieve more, across productivity and cloud platforms.",
    CLOUD,
    "Personal Computing revenue decreased as Windows OEM licensing declined with a weaker PC market and "
    "lower device sales through retail and commercial channels during the second half.",
])


@pytest.fixture(autouse=True)
def analysis_model(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANALYSIS_MODEL", "fake/analysis-model")


@pytest.fixture
def filings(tmp_path: Path) -> Path:
    (tmp_path / "MSFT_10-K.txt").write_text(FILING)
    return tmp_path


def suggestion() -> Suggestion:
    return read_list(OUT / "suggestions_raw.json", Suggestion)[0]   # fixture_001.s1, MSFT.p1


def claims() -> list[Claim]:
    return read_list(OUT / "claims.json", Claim)


def log_entry(i: int, item_id: str, quote: str) -> LogEntry:
    return LogEntry(id=f"log{i}", at=datetime(2026, 10, 13, 9, i, tzinfo=UTC), suggestion_id=f"x.s{i}",
                    change="pillar_evidence", item_id=item_id, stance="supports", strength=2,
                    sections=[LinkedSection(email_id="e1", quote=quote)])


def step(tool: str, **args: Any) -> dict[str, Any]:
    return {"next_thought": f"Use {tool}.", "next_tool_name": tool, "next_tool_args": args}


def script(steps: list[dict[str, Any]], result: dict[str, Any]) -> FakeChat:
    def answer(messages: list[Message]) -> str:
        if "next_tool_name" in messages[0].content:
            return json.dumps(steps.pop(0) if steps else step("finish"))
        return json.dumps({"reasoning": "Checked.", "result": result})
    return FakeChat(answer)


# ---- Tools ----

def test_filing_search_ranks_by_similarity_and_is_empty_without_a_filing(filings: Path) -> None:
    emb = FakeEmbedder()
    found = verify_agent.search_filing("MSFT", "Azure Intelligent Cloud revenue grew", emb, 1, filings)
    assert found == [("MSFT_10-K#2", CLOUD)]
    assert verify_agent.search_filing("NVDA", "data center", emb, 3, filings) == []


def test_passages_join_short_paragraphs_and_cut_long_ones() -> None:
    long = ". ".join(["Sentence number %d about revenue" % i for i in range(80)]) + "."
    passages = verify_agent.split_passages("MSFT", "PART I\n\nItem 1.\n\n" + long)
    assert passages[0][0] == "MSFT_10-K#1" and passages[0][1].startswith("PART I Item 1.")
    assert all(len(p) <= thresholds.PASSAGE_CHARS for _, p in passages)


def test_log_search_matches_words_and_filters_by_ticker() -> None:
    log = [log_entry(1, "MSFT.p1", "Azure resellers report growth"),
           log_entry(2, "NVDA.p2", "Memory supply is on schedule"),
           log_entry(3, "MSFT.p3", "Capex guidance raised for Azure")]
    assert [e.id for e in verify_agent.search_log(log, "azure growth")] == ["log1", "log3"]
    assert [e.id for e in verify_agent.search_log(log, "azure", ticker="NVDA")] == []
    assert verify_agent.search_log(log, "unrelated words") == []


def test_book_item_shows_no_size_or_conviction() -> None:
    from triage_app.state.fold import fold, load_seed
    state = fold(load_seed(), [])
    pillar = verify_agent.book_item(state, "MSFT.p1")
    driver = verify_agent.book_item(state, "MSFT.intelligent_cloud_growth")
    assert pillar is not None and set(pillar) == {"id", "statement", "wrong_if", "driver_ids"}
    assert driver is not None and driver["analyst"] == 24.0 and driver["consensus"] == 21.5
    assert verify_agent.book_item(state, "MSFT.p9") is None


def test_tool_definitions_are_read_only() -> None:
    names = {t["name"] for t in verify_agent.load_tool_defs()}
    assert names == {"search_change_log", "get_filing_excerpt", "get_book_item"}


# ---- The agent ----

def test_confirmed_with_a_source_quoted_from_a_tool(filings: Path) -> None:
    chat = script([step("get_filing_excerpt", ticker="MSFT", query="Azure Intelligent Cloud revenue", limit=1)],
                  {"verdict": "confirmed", "explanation": "The filing reports Intelligent Cloud growth.",
                   "sources": [{"source": "MSFT_10-K#2", "quote": "Intelligent Cloud revenue increased 21%"}]})
    agent = VerifyAgent(chat, FakeEmbedder(), filings_dir=filings)
    result = agent(suggestion(), claims()[:1], [])
    assert result.verdict == "confirmed" and result.suggestion_id == "fixture_001.s1"
    assert [s.source for s in result.sources] == ["MSFT_10-K#2"]
    VerifyResult.model_validate(result.model_dump())


def test_unmatched_source_makes_the_verdict_not_found(filings: Path) -> None:
    chat = script([step("get_filing_excerpt", ticker="MSFT", query="Azure")],
                  {"verdict": "contradicted", "explanation": "Invented.",
                   "sources": [{"source": "MSFT_10-K#9", "quote": "Azure revenue fell 50%."}]})
    result = VerifyAgent(chat, FakeEmbedder(), filings_dir=filings)(suggestion(), [], [])
    assert result.verdict == "not_found" and result.sources == [] and result.explanation == NO_SOURCE


def test_agent_makes_at_most_four_tool_calls(filings: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ran: list[str] = []
    real = verify_agent.search_log

    def counting(*a: Any, **k: Any) -> list[LogEntry]:
        ran.append("log")
        return real(*a, **k)

    monkeypatch.setattr(verify_agent, "search_log", counting)
    steps = [step("search_change_log", query=f"azure {i}") for i in range(8)]
    chat = script(steps, {"verdict": "not_found", "explanation": "Nothing came back.", "sources": []})
    result = VerifyAgent(chat, FakeEmbedder(), filings_dir=filings)(suggestion(), [], [])
    assert len(ran) == thresholds.VERIFY_TOOL_CALLS
    assert result.verdict == "not_found"


def test_guard_refuses_calls_past_the_budget(filings: Path) -> None:
    agent = VerifyAgent(FakeChat(), FakeEmbedder(), filings_dir=filings, max_calls=1)
    from triage_app.state.fold import fold, load_seed
    s = verify_agent.Session(log=[], state=fold(load_seed(), []), embedder=FakeEmbedder(), filings_dir=filings)
    fns = verify_agent.tool_functions(s)
    tool = agent._tool(agent.tool_defs[0], fns[agent.tool_defs[0]["name"]], s)
    assert tool(query="azure") == "[]"
    assert tool(query="azure") == LIMIT_REACHED


def test_verify_entry_point_uses_the_log_and_records_the_stage() -> None:
    log = [log_entry(1, "MSFT.p1", "Azure resellers report Intelligent Cloud growth ahead of plan")]
    chat = script([step("search_change_log", query="Azure Intelligent Cloud", ticker="MSFT")],
                  {"verdict": "confirmed", "explanation": "An accepted entry already logs this.",
                   "sources": [{"source": "log1", "quote": "Azure resellers report Intelligent Cloud growth"}]})
    ctx = RunContext(corpus_set="day_1", chat=chat, embedder=FakeEmbedder(), use_cache=False, emails_path=FIXTURE_EMAILS)
    result = verify(suggestion(), log, ctx, claims())
    assert result.verdict == "confirmed" and result.sources[0].source == "log1"
    assert any(t.stage == "verify" for t in ctx.recorder.timings)
    sent = "\n".join("\n".join(m.content for m in c["messages"]) for c in chat.calls)
    assert "size_bps" not in sent and "conviction" not in sent.lower()
    assert "fixture_001.c1" in sent          # the cited claim is shown, the uncited ones are not
    assert "fixture_009.c1" not in sent
