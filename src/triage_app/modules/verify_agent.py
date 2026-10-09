"""The verify agent: on the analyst's request, checks one suggestion against the record.

SPEC.md, "Data flow" (verify agent paragraph). A `dspy.ReAct` loop bound to
`RouterLM(config.ANALYSIS_MODEL, chat)` under the JSON adapter, with instructions from
`instructions/verify_agent.md` and tools built from `tools/verify_agent.json`:

- `get_filing_excerpt` ranks paragraphs of `data/filings/<TICKER>_10-K.txt` by embedding
  similarity (`ctx.embedder`, the stage 2 model) and returns nothing when no filing is saved.
- `search_change_log` matches words against the session's change log.
- `get_book_item` reads one pillar or driver from the book as it stands (seed + log); it never
  returns positions, sizes or conviction.

Every tool is read-only: nothing writes, sends or browses. At most `thresholds.VERIFY_TOOL_CALLS`
tool calls. Code keeps only sources whose quote appears verbatim in what a tool returned, and a
verdict left with no source becomes `not_found`.

    result = verify(suggestion, log, ctx)        # -> VerifyResult, shown to the analyst only
"""

import json
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import dspy

from triage_app import thresholds
from triage_app import config
from triage_app.embed import Embedder, Vector
from triage_app.llm import ChatClient
from triage_app.modules.lm import RouterLM, json_adapter
from triage_app.pipeline.context import RunContext
from triage_app.pipeline.io import normalize_ws, quote_in
from triage_app.schema import Claim, LogEntry, Suggestion, VerifyDraft, VerifyResult
from triage_app.state.fold import BookState, fold, load_seed

STAGE = "verify"
INSTRUCTIONS_PATH = config.INSTRUCTIONS_DIR / "verify_agent.md"
TOOLS_PATH = config.TOOLS_DIR / "verify_agent.json"
LIMIT_REACHED = "Tool call limit reached. Call finish now."
NO_SOURCE = "The cited sources could not be matched to what the tools returned, so nothing was verified."

_WORD = re.compile(r"[a-z0-9]+")
_PASSAGES: dict[tuple[str, Path], tuple[list[tuple[str, str]], Vector]] = {}


# ---- Filing search ----

def filing_path(ticker: str, filings_dir: Path = config.FILINGS_DIR) -> Path:
    return filings_dir / f"{ticker}_10-K.txt"


def split_passages(ticker: str, text: str) -> list[tuple[str, str]]:
    """(identifier, text) passages: paragraphs, short ones joined, long ones cut at thresholds.PASSAGE_CHARS."""
    passages: list[str] = []
    buf = ""
    for para in re.split(r"\n\s*\n", text):
        para = normalize_ws(para)
        if not para:
            continue
        buf = f"{buf} {para}".strip() if buf else para
        if len(buf) < thresholds.MIN_PASSAGE_CHARS:
            continue
        while len(buf) > thresholds.PASSAGE_CHARS:
            cut = buf.rfind(". ", 0, thresholds.PASSAGE_CHARS)
            cut = cut + 1 if cut > thresholds.MIN_PASSAGE_CHARS else thresholds.PASSAGE_CHARS
            passages.append(buf[:cut].strip())
            buf = buf[cut:].strip()
        if buf:
            passages.append(buf)
        buf = ""
    if buf:
        passages.append(buf)
    return [(f"{ticker}_10-K#{i + 1}", p) for i, p in enumerate(passages)]


def search_filing(ticker: str, query: str, embedder: Embedder, limit: int = thresholds.VERIFY_FILING_RESULTS,
                  filings_dir: Path = config.FILINGS_DIR) -> list[tuple[str, str]]:
    """The `limit` passages most similar to `query`; empty when no filing is saved."""
    path = filing_path(ticker, filings_dir)
    if not path.exists() or not query.strip():
        return []
    key = (embedder.model, path)
    if key not in _PASSAGES:
        passages = split_passages(ticker, path.read_text())
        _PASSAGES[key] = (passages, embedder.embed([p for _, p in passages]))
    passages, matrix = _PASSAGES[key]
    if not passages:
        return []
    scores = matrix @ embedder.embed([query])[0]
    order = np.argsort(-scores)[:limit]
    return [passages[int(i)] for i in order]


# ---- Change log and book ----

def words(text: str) -> set[str]:
    return {w for w in _WORD.findall(text.lower()) if len(w) > 2}


def entry_text(entry: LogEntry) -> str:
    parts = [entry.item_id, entry.change, entry.stance or "", entry.suggestion_id]
    if entry.pillar is not None:
        parts += [entry.pillar.statement, entry.pillar.wrong_if]
    parts += [s.quote for s in entry.sections]
    return " ".join(parts)


def search_log(log: list[LogEntry], query: str, ticker: str | None = None, limit: int = thresholds.VERIFY_LOG_RESULTS) -> list[LogEntry]:
    """Entries sharing the most words with `query`, newest first among ties; none share no word."""
    wanted = words(query)
    scored = []
    for pos, entry in enumerate(log):
        if ticker and not entry.item_id.startswith(f"{ticker}"):
            continue
        score = len(wanted & words(entry_text(entry)))
        if score:
            scored.append((score, pos, entry))
    scored.sort(key=lambda s: (-s[0], -s[1]))
    return [e for _, _, e in scored[:limit]]


def book_item(state: BookState, item_id: str) -> dict[str, Any] | None:
    for thesis in state.theses.values():
        for p in thesis.pillars:
            if p.id == item_id:
                return {"id": p.id, "statement": p.statement, "wrong_if": p.wrong_if, "driver_ids": p.driver_ids}
    for model in state.models.values():
        for d in model.drivers:
            if d.id == item_id:
                return {"id": d.id, "label": d.label, "unit": d.unit, "analyst": d.analyst, "consensus": d.consensus}
    return None


# ---- Agent ----

def load_tool_defs(path: Path = TOOLS_PATH) -> list[dict[str, Any]]:
    defs: list[dict[str, Any]] = json.loads(path.read_text())
    return defs


@dataclass
class Session:
    """One verify request: what the tools may read, and every text they returned."""

    log: list[LogEntry]
    state: BookState
    embedder: Embedder
    filings_dir: Path
    calls: int = 0
    seen: list[str] = field(default_factory=list)


def tool_functions(s: Session) -> dict[str, Callable[..., str]]:
    def search_change_log(query: str, ticker: str | None = None, limit: int = thresholds.VERIFY_LOG_RESULTS) -> str:
        found = search_log(s.log, query, ticker, limit)
        s.seen += [q.quote for e in found for q in e.sections] + [e.item_id for e in found]
        return json.dumps([{"source": e.id, "at": e.at.isoformat(), "item_id": e.item_id, "change": e.change,
                            "quotes": [q.quote for q in e.sections]} for e in found], ensure_ascii=False)

    def get_filing_excerpt(ticker: str, query: str, limit: int = thresholds.VERIFY_FILING_RESULTS) -> str:
        found = search_filing(ticker, query, s.embedder, limit, s.filings_dir)
        s.seen += [text for _, text in found]
        return json.dumps([{"source": pid, "quote": text} for pid, text in found], ensure_ascii=False)

    def get_book_item(item_id: str) -> str:
        item = book_item(s.state, item_id)
        if item is None:
            return f"No pillar or driver has the ID {item_id}."
        s.seen += [str(v) for v in item.values() if isinstance(v, str)]
        return json.dumps({"source": f"book:{item_id}", **item}, ensure_ascii=False)

    return {"search_change_log": search_change_log, "get_filing_excerpt": get_filing_excerpt,
            "get_book_item": get_book_item}


class VerifySuggestion(dspy.Signature):
    """Check one suggestion's claim against the saved filings, the book and the change log."""

    suggestion: str = dspy.InputField(desc="JSON: the suggestion being verified (data)")
    claim: str = dspy.InputField(desc="JSON list of the claims it cites, with quotes (data)")
    result: VerifyDraft = dspy.OutputField(desc="Verdict, explanation and sources")


class VerifyAgent:
    def __init__(self, chat: ChatClient, embedder: Embedder, *, model: str | None = None,
                 max_calls: int = thresholds.VERIFY_TOOL_CALLS, filings_dir: Path = config.FILINGS_DIR) -> None:
        self.lm = RouterLM(model or config.ANALYSIS_MODEL, chat, namespace="verify")
        self.embedder = embedder
        self.tool_defs = load_tool_defs()
        self.signature = VerifySuggestion.with_instructions(INSTRUCTIONS_PATH.read_text().strip())
        self.max_calls = max_calls
        self.filings_dir = filings_dir

    def _tool(self, spec: dict[str, Any], fn: Callable[..., str], s: Session) -> dspy.Tool:
        required = spec["input_schema"].get("required", [])

        def call(**kwargs: Any) -> str:
            if s.calls >= self.max_calls:
                return LIMIT_REACHED
            missing = [r for r in required if r not in kwargs]
            if missing:
                raise ValueError(f"missing argument(s): {', '.join(missing)}")
            s.calls += 1
            return fn(**kwargs)

        return dspy.Tool(call, name=spec["name"], desc=f"{spec['description']} Returns: {spec['returns']}",
                         args=spec["input_schema"]["properties"])

    def __call__(self, suggestion: Suggestion, claims: list[Claim], log: list[LogEntry]) -> VerifyResult:
        s = Session(log=log, state=fold(load_seed(), log), embedder=self.embedder, filings_dir=self.filings_dir)
        fns = tool_functions(s)
        tools = [self._tool(spec, fns[spec["name"]], s) for spec in self.tool_defs]
        agent = dspy.ReAct(self.signature, tools=tools, max_iters=self.max_calls)
        shown = suggestion.model_dump(mode="json", include={"id", "body", "rationale", "sections"})
        cited = ([c.model_dump(mode="json", exclude_none=True) for c in claims]
                 or [{"quote": sec.quote} for sec in suggestion.sections])
        with dspy.context(lm=self.lm, adapter=json_adapter()):
            pred = agent(suggestion=json.dumps(shown, ensure_ascii=False), claim=json.dumps(cited, ensure_ascii=False))
        draft = pred.result if isinstance(pred.result, VerifyDraft) else VerifyDraft.model_validate(pred.result)
        return checked(draft, s.seen, suggestion.id)


def checked(draft: VerifyDraft, seen: list[str], suggestion_id: str) -> VerifyResult:
    """Keep sources quoted verbatim from a tool's output; with none left, the verdict is not_found."""
    sources = [src for src in draft.sources if any(quote_in(src.quote, text) for text in seen)]
    if draft.verdict != "not_found" and not sources:
        return VerifyResult(suggestion_id=suggestion_id, verdict="not_found", explanation=NO_SOURCE, sources=[])
    if draft.verdict == "not_found":
        sources = []
    return VerifyResult(suggestion_id=suggestion_id, verdict=draft.verdict,
                        explanation=draft.explanation, sources=sources)


def verify(suggestion: Suggestion, log: list[LogEntry], ctx: RunContext,
           claims: list[Claim] | None = None) -> VerifyResult:
    """Check one suggestion against cached filings, the book and the session change log."""
    cited = [c for c in claims or [] if c.id in suggestion.claim_ids]
    with ctx.recorder.stage(STAGE, suggestion.sections[0].email_id if suggestion.sections else None):
        return VerifyAgent(ctx.chat, ctx.embedder)(suggestion, cited, log)
