import json
import shutil
from pathlib import Path
from typing import Any

import pytest
from fakes import FIXTURE_EMAILS, FakeChat

from triage_app import thresholds
from triage_app import config
from triage_app.llm import Message
from triage_app.modules.analysis_agent import LIMIT_REACHED, candidate_pillars
from triage_app.pipeline import analyze
from triage_app.pipeline.context import RunContext
from triage_app.pipeline.io import read_list
from triage_app.schema import AnalysisRecord, Claim, EmailResult, ExistingThesis, NewThesis, Suggestion
from triage_app.state.fold import fold, load_seed

OUT = config.FIXTURES_DIR / "out"
BOOK = fold(load_seed(), [])
LABEL_KEYS = ('"additional_labels"', '"affected_tickers"', '"email_type"', '"systemic"', '"angle"',
              '"reason"', "signal_score", "decided_by")

MSFT_Q1 = ("Our checks with four Azure resellers point to Intelligent Cloud revenue growth of 26% "
           "in FY2027, versus the 21.5% the Street models.")


@pytest.fixture(autouse=True)
def analysis_model(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANALYSIS_MODEL", "fake/analysis-model")


def claims_of(email_id: str) -> list[Claim]:
    return [c for c in read_list(OUT / "claims.json", Claim) if c.email_id == email_id]


def result_of(email_id: str) -> EmailResult:
    return next(r for r in read_list(OUT / "results.json", EmailResult) if r.email_id == email_id)


def step(tool: str, **args: Any) -> dict[str, Any]:
    return {"next_thought": f"Call {tool}.", "next_tool_name": tool, "next_tool_args": args}


def existing(pillar: str, *claim_ids: str, email: str = "fixture_001", quote: str = MSFT_Q1,
             assumptions: list[dict[str, Any]] | None = None, strength: int = 2,
             relevance: float = 0.9, stance: str = "supports") -> dict[str, Any]:
    return {"kind": "existing_thesis", "pillar_id": pillar, "stance": stance, "strength": strength,
            "relevance": relevance, "wrong_if_met": False, "assumptions": assumptions or [],
            "rationale": f"Bears on {pillar}.", "claim_ids": list(claim_ids),
            "sections": [{"email_id": email, "quote": quote}]}


# Each skill is recognized by an input field only its signature has, never by its prompt file's wording.
SKILL_FIELDS = {"alter": "`theses`", "spawn": "`existing_pillars`", "project": "`companies`"}


class Script:
    """Routes each model call by its system prompt: agent steps, skill replies, final summary."""

    def __init__(self, steps: list[dict[str, Any]], alter: list[dict[str, Any]] | None = None,
                 spawn: list[dict[str, Any]] | None = None, summary: str = "Done.",
                 project: list[dict[str, Any]] | None = None) -> None:
        self.steps, self.summary = steps, summary
        self.replies = {"alter": alter or [], "spawn": spawn or [], "project": project or []}
        self.seen: dict[str, list[str]] = {"agent": [], "alter": [], "spawn": [], "project": [], "extract": []}

    def __call__(self, messages: list[Message]) -> str:
        system, full = messages[0].content, "\n".join(m.content for m in messages)
        if "next_tool_name" not in system:
            for skill, marker in SKILL_FIELDS.items():
                if marker in system:
                    self.seen[skill].append(full)
                    return json.dumps({"result": self.replies[skill].pop(0)})
        if "next_tool_name" in system:
            self.seen["agent"].append(full)
            return json.dumps(self.steps.pop(0) if self.steps else step("finish"))
        self.seen["extract"].append(full)
        return json.dumps({"reasoning": "Nothing applies.", "summary": self.summary})


def run_one(script: Script, email_id: str = "fixture_001") -> tuple[AnalysisRecord, list[Suggestion], FakeChat]:
    chat = FakeChat(script)
    ctx = RunContext(corpus_set="day_1", chat=chat, use_cache=False, emails_path=FIXTURE_EMAILS)
    record, made = analyze.process(email_id, claims_of(email_id), result_of(email_id), ctx, book=BOOK)
    return record, made, chat


# ---- Candidate pillars ----

def test_candidates_are_company_pillars_plus_linked_pillars() -> None:
    msft = claims_of("fixture_001")
    assert candidate_pillars(msft, BOOK) == ["MSFT.p1", "MSFT.p2", "MSFT.p3",
                                             "NVDA.p1", "NVDA.p3", "AMZN.p1", "GOOGL.p2"]
    aapl = claims_of("fixture_008")
    assert candidate_pillars(aapl, BOOK) == ["AAPL.p1", "AAPL.p2", "AAPL.p3", "GOOGL.p3"]
    both = [msft[0].model_copy(update={"tickers": ["MSFT", "AMZN"]})]
    got = candidate_pillars(both, BOOK)
    assert len(got) == len(set(got))
    assert set(got) == {"MSFT.p1", "MSFT.p2", "MSFT.p3", "AMZN.p1", "AMZN.p2", "AMZN.p3",
                        "NVDA.p1", "NVDA.p3", "GOOGL.p2"}


def test_existing_skill_sees_candidates_with_stance_and_drivers_never_size_or_conviction() -> None:
    script = Script([step("alter_existing_thesis", claim_ids=["fixture_001.c1"])],
                    alter=[{"suggestions": [], "no_change_reason": "Nothing bears."}])
    run_one(script)
    prompt = script.seen["alter"][0]
    for pid in ("MSFT.p1", "NVDA.p1", "GOOGL.p2"):
        assert pid in prompt
    assert "AAPL.p1" not in prompt and "MSFT.p1" in prompt
    assert '"stance": "long"' in prompt and '"consensus": 21.5' in prompt and '"analyst": 24.0' in prompt
    assert '"fixture_001": "thesis_relevant"' in prompt          # Jev's label, from results.json
    assert MSFT_Q1 in prompt
    assert "fixture_001.c2" not in prompt                        # only the claims the agent passed


# ---- The loop ----

def test_agent_never_exceeds_three_skill_calls() -> None:
    steps = [step("alter_existing_thesis", claim_ids=["fixture_001.c1"]) for _ in range(6)]
    alter = [{"suggestions": [], "no_change_reason": f"Reason {i}."} for i in range(6)]
    script = Script(steps, alter=alter)
    record, made, chat = run_one(script)
    assert record.skills_called == ["existing_thesis"] * thresholds.SKILL_CALLS_PER_EMAIL
    assert len(script.seen["alter"]) == thresholds.SKILL_CALLS_PER_EMAIL
    assert len(script.seen["agent"]) <= thresholds.SKILL_CALLS_PER_EMAIL
    assert record.no_change_reason == "Reason 2." and made == []


def test_call_limit_guard_refuses_a_fourth_skill_run() -> None:
    from triage_app.modules.analysis_agent import AnalysisAgent
    from triage_app.modules.skills import SkillContext

    steps = [step("alter_existing_thesis", claim_ids=["fixture_001.c1"]) for _ in range(5)]
    script = Script(steps, alter=[{"suggestions": [], "no_change_reason": "No."}] * 5)
    chat = FakeChat(script)
    agent = AnalysisAgent(chat, max_calls=2)
    claims = claims_of("fixture_001")
    ctx = SkillContext(book=BOOK, candidate_pillar_ids=candidate_pillars(claims, BOOK),
                       email_triage={"fixture_001": "thesis_relevant"})
    outcome = agent(claims, ctx)
    assert len(outcome.skills_called) == 2 and len(script.seen["alter"]) == 2
    # The tool itself refuses once the budget is spent.
    by_id = {c.id: c for c in claims}
    tool = agent._tool(agent.tool_defs[0], by_id, ctx, outcome)
    assert tool(claim_ids=["fixture_001.c1"]) == LIMIT_REACHED
    assert len(script.seen["alter"]) == 2


def test_suggestions_come_from_skill_results_not_final_text() -> None:
    fake = json.dumps({"suggestions": [existing("GOOGL.p3", "fixture_001.c1")]})
    steps = [step("alter_existing_thesis", claim_ids=["fixture_001.c1", "fixture_001.c2"]),
             {"next_thought": f"Also {fake}", "next_tool_name": "finish", "next_tool_args": {}}]
    alter = [{"suggestions": [existing("MSFT.p1", "fixture_001.c1")], "no_change_reason": None}]
    script = Script(steps, alter=alter, summary=fake)
    record, made, _ = run_one(script)
    assert [s.body.pillar_id for s in made if isinstance(s.body, ExistingThesis)] == ["MSFT.p1"]
    assert record.no_change_reason is None
    assert script.seen["extract"] == []       # with a skill result, the final-text call is skipped


def test_skill_drafts_of_the_wrong_kind_are_dropped() -> None:
    wrong = {"kind": "new_thesis", "ticker": "MSFT", "statement": "x", "wrong_if": "y", "driver_ids": [],
             "rationale": "r", "claim_ids": ["fixture_001.c1"], "sections": []}
    script = Script([step("alter_existing_thesis", claim_ids=["fixture_001.c1"])],
                    alter=[{"suggestions": [wrong, existing("MSFT.p1", "fixture_001.c1")]}])
    _, made, _ = run_one(script)
    assert [s.body.kind for s in made] == ["existing_thesis"]


# ---- No-change reasons ----

def test_no_claims_needs_no_model() -> None:
    script = Script([])
    record, made, chat = run_one(script, "fixture_007")
    assert record == AnalysisRecord(email_id="fixture_007", skills_called=[], suggestion_ids=[],
                                    no_change_reason="no claims extracted")
    assert made == [] and chat.calls == []


def test_no_change_reason_is_last_skills_reason() -> None:
    steps = [step("alter_existing_thesis", claim_ids=["fixture_009.c1", "fixture_009.c2"]),
             step("spawn_new_thesis", claim_ids=["fixture_009.c1"], ticker="AMZN")]
    script = Script(steps, alter=[{"suggestions": [], "no_change_reason": "First reason."}],
                    spawn=[{"suggestions": [], "no_change_reason": "Second reason."}],
                    summary="Agent text that must not be used.")
    record, made, _ = run_one(script, "fixture_009")
    assert record.skills_called == ["existing_thesis", "new_thesis"]
    assert record.no_change_reason == "Second reason." and made == []


def test_no_skill_called_uses_agent_final_text() -> None:
    script = Script([step("finish")], summary="No change: the claims concern no company in the book.")
    record, made, _ = run_one(script)
    assert record.skills_called == [] and made == []
    assert record.no_change_reason == "No change: the claims concern no company in the book."


def test_bad_tool_arguments_do_not_count_as_a_skill_call() -> None:
    steps = [step("spawn_new_thesis", claim_ids=["fixture_009.c1"], ticker="AAPL"),   # ticker not in claims
             step("alter_existing_thesis", claim_ids=["other_email.c1"]),             # not this email's claim
             step("finish")]
    script = Script(steps, summary="No change: the claims do not bear directly on any pillar or stated projection.")
    record, _, _ = run_one(script, "fixture_009")
    assert record.skills_called == [] and script.seen["spawn"] == [] and script.seen["alter"] == []
    assert record.no_change_reason == "No change: the claims do not bear directly on any pillar or stated projection."


# ---- Building suggestions ----

def test_code_fills_book_values_and_assigns_ids() -> None:
    assumptions = [{"driver_id": "MSFT.intelligent_cloud_growth", "stated_value": 26.0},
                   {"driver_id": "MSFT.no_such_driver", "stated_value": 3.0}]
    steps = [step("alter_existing_thesis", claim_ids=["fixture_009.c1", "fixture_009.c2"]),
             step("spawn_new_thesis", claim_ids=["fixture_009.c1", "fixture_009.c2"], ticker="AMZN")]
    q = "Amazon has moved roughly 40% of its internal model inference onto its own Trainium chips, up from under 15% a year ago."
    new = {"kind": "new_thesis", "ticker": "AMZN", "statement": "In-house chips lower AWS's AI cost.",
           "wrong_if": "Customers do not adopt in-house chip instances.", "driver_ids": ["AMZN.aws_growth"],
           "rationale": "No AMZN pillar covers it.", "claim_ids": ["fixture_009.c1"],
           "sections": [{"email_id": "fixture_009", "quote": q}]}
    script = Script(steps, alter=[{"suggestions": [
        existing("MSFT.p1", "fixture_009.c1", email="fixture_009", quote=q, assumptions=assumptions),
        existing("NVDA.p1", "fixture_009.c1", email="fixture_009", quote=q, strength=1)]}],
        spawn=[{"suggestions": [new]}])
    record, made, _ = run_one(script, "fixture_009")
    assert [s.id for s in made] == ["fixture_009.s1", "fixture_009.s2", "fixture_009.s3"]
    assert record.suggestion_ids == [s.id for s in made]
    assert all(s.status == "open" and s.reject_reason is None and not s.second_look for s in made)
    first = made[0].body
    assert isinstance(first, ExistingThesis)
    assert [(a.driver_id, a.stated_value, a.book_value, a.consensus_value) for a in first.assumptions] == [
        ("MSFT.intelligent_cloud_growth", 26.0, 24.0, 21.5)]
    assert isinstance(made[2].body, NewThesis) and made[2].body.driver_ids == ["AMZN.aws_growth"]
    spawn_prompt = script.seen["spawn"][0]
    assert "AMZN.p1" in spawn_prompt and "MSFT.p1" not in spawn_prompt
    assert '"analyst"' not in spawn_prompt and '"consensus"' not in spawn_prompt


# ---- The stage ----

def test_run_on_fixtures_writes_valid_files(tmp_path: Path) -> None:
    for name in ("claims.json", "results.json"):
        shutil.copy(OUT / name, tmp_path / name)

    def answer(messages: list[Message]) -> str:
        system, user = messages[0].content, messages[-1].content
        if "`theses`" in system and "next_tool_name" not in system:
            claims = json.loads(user.split("[[ ## claims ## ]]")[1].split("[[ ##")[0]) if "[[ ## claims" in user else []
            if claims:
                c = claims[0]
                return json.dumps({"result": {"suggestions": [existing(
                    f"{c['tickers'][0]}.p1", c["id"], email=c["email_id"], quote=c["quote"])]}})
            return json.dumps({"result": {"suggestions": [], "no_change_reason": "None."}})
        if "next_tool_name" in system:
            if "observation_0" in user:
                return json.dumps(step("finish"))
            ids = [c["id"] for c in json.loads(user.split("[[ ## claims ## ]]")[1].split("[[ ##")[0])]
            return json.dumps(step("alter_existing_thesis", claim_ids=ids))
        return json.dumps({"reasoning": "", "summary": "No change: nothing in the book is affected."})

    chat = FakeChat(answer)
    analyze.run(tmp_path, tmp_path, RunContext(corpus_set="day_1", chat=chat, use_cache=False, emails_path=FIXTURE_EMAILS))
    records = read_list(tmp_path / "analysis.json", AnalysisRecord)
    raw = read_list(tmp_path / "suggestions_raw.json", Suggestion)
    passed = [r.email_id for r in read_list(OUT / "results.json", EmailResult) if r.gate == "pass"]
    assert [r.email_id for r in records] == passed
    by_email = {r.email_id: r for r in records}
    assert by_email["fixture_007"].no_change_reason == "no claims extracted"
    assert {s.id for s in raw} == {i for r in records for i in r.suggestion_ids}
    assert raw and all(s.status == "open" for s in raw)
    assert len(raw) == sum(1 for r in records if r.skills_called)
    for r in records:
        assert (r.no_change_reason is None) == bool(r.suggestion_ids)


def test_prompts_hold_no_size_conviction_or_label_fields(tmp_path: Path) -> None:
    steps = [step("alter_existing_thesis", claim_ids=["fixture_009.c1", "fixture_009.c2"]),
             step("spawn_new_thesis", claim_ids=["fixture_009.c1"], ticker="AMZN")]
    script = Script(steps, alter=[{"suggestions": [], "no_change_reason": "No."}],
                    spawn=[{"suggestions": [], "no_change_reason": "No."}])
    _, _, chat = run_one(script, "fixture_009")
    sent = "\n".join("\n".join(m.content for m in c["messages"]) for c in chat.calls)
    assert chat.calls
    assert "size_bps" not in sent and "conviction" not in sent.lower()
    for key in LABEL_KEYS:
        assert key not in sent
    for row in (config.FIXTURES_DIR / "labels.jsonl").read_text().splitlines():
        assert json.loads(row)["reason"] not in sent


def test_one_failing_email_does_not_abort_the_stage(tmp_path: Path) -> None:
    for name in ("claims.json", "results.json"):
        shutil.copy(OUT / name, tmp_path / name)

    def answer(messages: list[Message]) -> str:
        if "fixture_001" in messages[-1].content:
            raise RuntimeError("provider error")
        if "next_tool_name" in messages[0].content:
            return json.dumps(step("finish"))
        return json.dumps({"reasoning": "", "summary": "No change: nothing in the book is affected."})

    analyze.run(tmp_path, tmp_path, RunContext(corpus_set="day_1", chat=FakeChat(answer), use_cache=False,
                                               emails_path=FIXTURE_EMAILS))
    records = {r.email_id: r for r in read_list(tmp_path / "analysis.json", AnalysisRecord)}
    assert records["fixture_001"].no_change_reason == "analysis failed: RuntimeError"
    assert len(records) == len({r.email_id for r in read_list(OUT / "results.json", EmailResult) if r.gate == "pass"})


# ---- Existing-thesis view, stance "none" and the per-email cap ----

def test_existing_skill_sees_street_view_pillar_summary_and_evidence() -> None:
    from triage_app.schema import PillarEvidence

    msft = BOOK.theses["MSFT"]
    pillars = [p.model_copy(update={"summary": "Azure takes share of AI workloads.",
                                    "evidence": [PillarEvidence(observation="Reseller checks up.", source="desk")]})
               if p.id == "MSFT.p1" else p for p in msft.pillars]
    thesis = msft.model_copy(update={"street_view": "buy", "street_view_note": "The street agrees.",
                                     "pillars": pillars})
    book = BOOK.model_copy(update={"theses": {**BOOK.theses, "MSFT": thesis}})
    script = Script([step("alter_existing_thesis", claim_ids=["fixture_001.c1"])],
                    alter=[{"suggestions": [], "no_change_reason": "Nothing bears."}])
    chat = FakeChat(script)
    ctx = RunContext(corpus_set="day_1", chat=chat, use_cache=False, emails_path=FIXTURE_EMAILS)
    analyze.process("fixture_001", claims_of("fixture_001"), result_of("fixture_001"), ctx, book=book)
    prompt = script.seen["alter"][0]
    assert '"street_view": "buy"' in prompt and "The street agrees." in prompt
    assert "Azure takes share of AI workloads." in prompt and "Reseller checks up." in prompt
    assert "size_bps" not in prompt and "conviction" not in prompt


def test_none_stance_drafts_are_dropped() -> None:
    script = Script([step("alter_existing_thesis", claim_ids=["fixture_001.c1"])],
                    alter=[{"suggestions": [existing("MSFT.p2", "fixture_001.c1", stance="none"),
                                            existing("NVDA.p1", "fixture_001.c1", stance="none")]}])
    dropped = analyze.Collected()
    chat = FakeChat(script)
    ctx = RunContext(corpus_set="day_1", chat=chat, use_cache=False, emails_path=FIXTURE_EMAILS)
    record, made = analyze.process("fixture_001", claims_of("fixture_001"), result_of("fixture_001"), ctx,
                                   book=BOOK, dropped=dropped)
    assert made == [] and dropped.no_bearing == 2
    assert record.no_change_reason == analyze.NO_BEARING


def test_per_email_cap_keeps_the_most_relevant() -> None:
    drafts = [existing("MSFT.p1", "fixture_001.c1", relevance=0.8),
              existing("MSFT.p2", "fixture_001.c1", relevance=0.95),
              existing("MSFT.p3", "fixture_001.c1", relevance=0.9, stance="contradicts"),
              existing("NVDA.p1", "fixture_001.c1", stance="none")]
    script = Script([step("alter_existing_thesis", claim_ids=["fixture_001.c1"])], alter=[{"suggestions": drafts}])
    _, made, _ = run_one(script)
    assert thresholds.MAX_THESIS_SUGGESTIONS_PER_EMAIL == 2
    bodies = [s.body for s in made]
    assert [(b.pillar_id, b.relevance) for b in bodies if isinstance(b, ExistingThesis)] == [
        ("MSFT.p2", 0.95), ("MSFT.p3", 0.9)]                     # call order kept among the kept
    assert [s.id for s in made] == ["fixture_001.s1", "fixture_001.s2"]


def test_relevance_and_street_view_shift_carried_into_the_suggestion() -> None:
    draft = existing("MSFT.p1", "fixture_001.c1", relevance=0.85)
    draft.update(street_view_shift="toward_buy", street_view_note="Analysts raised targets.",
                 assumption_impact="The email points above the desk's Intelligent Cloud growth assumption.",
                 if_accepted="Accepting logs strength-2 supporting evidence against MSFT.p1.")
    script = Script([step("alter_existing_thesis", claim_ids=["fixture_001.c1"])], alter=[{"suggestions": [draft]}])
    _, made, _ = run_one(script)
    body = made[0].body
    assert isinstance(body, ExistingThesis)
    assert (body.relevance, body.street_view_shift, body.street_view_note) == (
        0.85, "toward_buy", "Analysts raised targets.")
    assert body.assumption_impact.startswith("The email points above") and body.if_accepted.startswith("Accepting logs")
    Suggestion.model_validate(made[0].model_dump())


# ---- The third tool ----

def test_projection_tool_is_built_in_when_the_tools_file_lacks_it(tmp_path: Path) -> None:
    from triage_app.modules import analysis_agent

    two = [d for d in json.loads(analysis_agent.TOOLS_PATH.read_text()) if d["name"] != "revise_projections"]
    path = tmp_path / "analysis_agent.json"
    path.write_text(json.dumps(two))
    defs = analysis_agent.load_tool_defs(path)
    assert [d["name"] for d in defs] == ["alter_existing_thesis", "spawn_new_thesis", "revise_projections"]
    spec = defs[-1]
    assert set(spec["input_schema"]["properties"]) == {"claim_ids", "ticker"}
    assert spec["input_schema"]["required"] == ["claim_ids", "ticker"]


def test_projection_tool_counts_toward_the_call_limit() -> None:
    steps = [step("revise_projections", claim_ids=["fixture_001.c1"], ticker="MSFT") for _ in range(5)]
    script = Script(steps, project=[{"suggestions": [], "no_change_reason": f"Reason {i}."} for i in range(5)])
    record, made, _ = run_one(script)
    assert record.skills_called == ["projection_change"] * thresholds.SKILL_CALLS_PER_EMAIL
    assert len(script.seen["project"]) == thresholds.SKILL_CALLS_PER_EMAIL
    assert made == [] and record.no_change_reason == "Reason 2."


def test_mixed_skills_share_one_call_budget() -> None:
    steps = [step("alter_existing_thesis", claim_ids=["fixture_001.c1"]),
             step("revise_projections", claim_ids=["fixture_001.c1"], ticker="MSFT"),
             step("spawn_new_thesis", claim_ids=["fixture_001.c1"], ticker="MSFT"),
             step("revise_projections", claim_ids=["fixture_001.c1"], ticker="MSFT")]
    no = {"suggestions": [], "no_change_reason": "No."}
    script = Script(steps, alter=[no], spawn=[no], project=[no, no])
    record, _, _ = run_one(script)
    assert record.skills_called == ["existing_thesis", "projection_change", "new_thesis"]
    assert len(script.seen["project"]) == 1
