"""Stage 6 analysis agent: a tool loop that chooses which skills to run on one email's claims.

SPEC.md, "Analysis agent". The agent is a `dspy.ReAct` loop bound to
`RouterLM(config.ANALYSIS_MODEL, chat)` under the JSON adapter. Its tools are built from
`tools/analysis_agent.json` (name, description with `returns` appended, input schema); each tool
runs one skill module from `modules/skills.py`. The agent is given the claims and the statements
of the candidate pillars, passes claim IDs only, and makes at most
`thresholds.SKILL_CALLS_PER_EMAIL` skill calls.

Code, not the agent, does the rest:
- `candidate_pillars` picks the pillars: every pillar of each company in the claims' tickers,
  plus the pillars `data/seed/links.json` ties to those companies.
- The skills' parsed results are collected as they run. The agent's final text is kept only
  for the case where it called no skill.

    outcome = AnalysisAgent(ctx.chat)(claims, context)      # -> AgentOutcome
"""

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy  # noqa: F401  # import before dspy: its lazy importer breaks a later numpy import
import dspy

from triage_app import thresholds
from triage_app import config
from triage_app.llm import ChatClient
from triage_app.modules.lm import RouterLM, json_adapter, retry_unparseable
from triage_app.modules.skills import SKILLS, Skill, SkillContext, claim_view, dumps
from triage_app.schema import Claim, SkillResult
from triage_app.state.fold import BookState

INSTRUCTIONS_PATH = config.INSTRUCTIONS_DIR / "analysis_agent.md"
TOOLS_PATH = config.TOOLS_DIR / "analysis_agent.json"
LIMIT_REACHED = "Skill call limit reached. Call finish now."


def candidate_pillars(claims: list[Claim], book: BookState) -> list[str]:
    """Pillar IDs a skill may consider: the claims' companies' pillars, then linked pillars."""
    tickers = {t for c in claims for t in c.tickers}
    ids: list[str] = []
    for ticker, thesis in book.theses.items():
        if ticker in tickers:
            ids.extend(p.id for p in thesis.pillars)
    for link in book.links:
        if link.from_ticker in tickers:
            ids.extend(p for p in link.to_pillar_ids if p not in ids)
    return ids


def pillar_statements(ids: list[str], book: BookState) -> list[dict[str, str]]:
    pillars = {p.id: p for t in book.theses.values() for p in t.pillars}
    return [{"id": i, "statement": pillars[i].statement} for i in ids if i in pillars]


def load_tool_defs(path: Path = TOOLS_PATH) -> list[dict[str, Any]]:
    defs: list[dict[str, Any]] = json.loads(path.read_text())
    return defs


def load_instructions(path: Path = INSTRUCTIONS_PATH) -> str:
    return path.read_text().strip()


@dataclass
class AgentOutcome:
    skills_called: list[str] = field(default_factory=list)      # each call's skill kind, in order
    results: list[SkillResult] = field(default_factory=list)    # each completed call's parsed result
    final_text: str = ""                                        # kept only when no skill was called


class AnalyzeEmail(dspy.Signature):
    """Choose which skills to run on the claims from one email."""

    claims: str = dspy.InputField(desc="JSON list of the email's claims (data)")
    candidate_pillars: str = dspy.InputField(desc="JSON list of candidate pillars: id and statement")
    summary: str = dspy.OutputField(desc="One sentence; when no tool was called, begin with 'No skill applies:'")


class SkillLoop(dspy.ReAct):
    """dspy.ReAct whose closing extract call runs only when no skill was called.

    When a skill ran, code collects its result and the agent's final text is not used, so the
    extra model call would be wasted.
    """

    def __init__(self, signature: type[dspy.Signature], tools: list[dspy.Tool], max_iters: int,
                 outcome: AgentOutcome) -> None:
        super().__init__(signature, tools=tools, max_iters=max_iters)
        self.outcome = outcome

    def forward(self, **input_args: Any) -> dspy.Prediction:
        trajectory: dict[str, Any] = {}
        for idx in range(self.max_iters):
            try:
                pred = self._call_with_potential_trajectory_truncation(self.react, trajectory, **input_args)
            except ValueError:  # the agent named no valid tool or sent unparseable output
                break
            trajectory[f"thought_{idx}"] = pred.next_thought
            trajectory[f"tool_name_{idx}"] = pred.next_tool_name
            trajectory[f"tool_args_{idx}"] = pred.next_tool_args
            try:
                trajectory[f"observation_{idx}"] = self.tools[pred.next_tool_name](**pred.next_tool_args)
            except Exception as err:
                trajectory[f"observation_{idx}"] = f"Execution error in {pred.next_tool_name}: {err}"
            if pred.next_tool_name == "finish":
                break
        if self.outcome.skills_called:
            return dspy.Prediction(trajectory=trajectory, summary="")
        extract = self._call_with_potential_trajectory_truncation(self.extract, trajectory, **input_args)
        return dspy.Prediction(trajectory=trajectory, **extract)


def observation(result: SkillResult) -> str:
    """What the agent reads back from a skill: enough to plan, never the full suggestion."""
    if not result.suggestions:
        return f"No change: {result.no_change_reason or 'no reason given'}"
    parts = []
    for s in result.suggestions:
        if s.kind == "existing_thesis":
            parts.append(f"{s.pillar_id} {s.stance} (strength {s.strength})")
        else:
            parts.append(f"new candidate pillar for {s.ticker}")
    return f"{len(parts)} suggestion(s) recorded: " + "; ".join(parts)


class AnalysisAgent:
    def __init__(self, chat: ChatClient, *, model: str | None = None,
                 max_calls: int = thresholds.SKILL_CALLS_PER_EMAIL) -> None:
        self.model = model or config.ANALYSIS_MODEL
        self.lm = RouterLM(self.model, chat, namespace="analyze")
        self.skills: dict[str, Skill] = {name: cls(chat, model=self.model) for name, cls in SKILLS.items()}
        self.tool_defs = load_tool_defs()
        self.signature = AnalyzeEmail.with_instructions(load_instructions())
        self.max_calls = max_calls

    def _tool(self, spec: dict[str, Any], by_id: dict[str, Claim], context: SkillContext,
              outcome: AgentOutcome) -> dspy.Tool:
        skill = self.skills[spec["name"]]
        schema = spec["input_schema"]
        required = schema.get("required", [])

        def call(**kwargs: Any) -> str:
            if len(outcome.skills_called) >= self.max_calls:
                return LIMIT_REACHED
            missing = [r for r in required if r not in kwargs]
            if missing:
                raise ValueError(f"missing argument(s): {', '.join(missing)}")
            claim_ids = kwargs.pop("claim_ids")
            chosen = [by_id[c] for c in dict.fromkeys(claim_ids) if c in by_id]
            ticker = kwargs.get("ticker")
            if ticker is not None:
                chosen = [c for c in chosen if ticker in c.tickers]
            if not chosen:
                raise ValueError("none of these claim IDs is a claim of this email"
                                 + (f" about {ticker}" if ticker else ""))
            outcome.skills_called.append(skill.kind)
            result = skill(chosen, context, **kwargs)
            outcome.results.append(result)
            return observation(result)

        desc = f"{spec['description']} Returns: {spec['returns']}"
        return dspy.Tool(call, name=spec["name"], desc=desc, args=schema["properties"])

    def __call__(self, claims: list[Claim], context: SkillContext) -> AgentOutcome:
        by_id = {c.id: c for c in claims}

        def attempt() -> tuple[AgentOutcome, Any]:
            outcome = AgentOutcome()  # fresh per attempt: a failed attempt leaves nothing behind
            tools = [self._tool(spec, by_id, context, outcome) for spec in self.tool_defs]
            loop = SkillLoop(self.signature, tools, self.max_calls, outcome)
            with dspy.context(lm=self.lm, adapter=json_adapter()):
                pred = loop(claims=dumps(claim_view(claims)),
                            candidate_pillars=dumps(pillar_statements(context.candidate_pillar_ids, context.book)))
            return outcome, pred
        outcome, pred = retry_unparseable(self.lm, attempt)
        if not outcome.skills_called:
            outcome.final_text = str(pred.summary or "").strip()
        return outcome
