## Working rules for every package (read before starting)

Repo: /Users/kelvinwallace/Desktop/DE_Shaw_CaseStudy. Python 3.14, uv. You have no memory of the lead's session: this brief, `SPEC.md`, and the code are your context. Other subagents are building other packages in parallel in the same working tree.

**Read first, whole:** `CLAUDE.md`, then the `SPEC.md` sections your package names, plus "Design rules to preserve", "Monitoring: token use and latency", "Data contracts", "Stage files" and "Working rules for the coding agent".

**Frozen foundation (lead-owned; never edit — if you need a change, stop and say so in your report):** `src/triage_app/schema.py` (every contract), `config.py` (starting values; model IDs resolve from `.env` via `config.ANALYSIS_MODEL` etc. — never write a model ID in code), `cache.py`, `monitoring.py` (`cached_call`, `Recorder`), `llm.py` (`OpenRouterClient`, `Message`, `Completion`), `embed.py` (`HFEmbedder`), `criteria.py`, `modules/lm.py` (`RouterLM`), `pipeline/context.py` (`RunContext`), `pipeline/io.py` (`read_list`, `write_list`, `read_one`, `write_one`, `normalize_ws`, `quote_in`), `pipeline/run.py`, `state/compute.py`, `state/fold.py`, `state/seed_merge.py`, `tests/fakes.py`, `tests/conftest.py`, `tests/fixtures/`, `pyproject.toml`, `uv.lock`, `SPEC.md`, `DECISIONS.md`, `REVIEW.md`. Do not run `uv add` or edit dependencies; if you need a package, say so in the report.

**One owner per file:** edit only the files your package owns, and add tests only for them as `tests/test_<module>.py`.

**How code talks to models:**
- Every generative call goes through OpenRouter: `ctx.chat.complete(...)` or, for DSPy modules, `RouterLM(config.NOTES_MODEL or config.ANALYSIS_MODEL, ctx.chat)` used as `with dspy.context(adapter=dspy.JSONAdapter()): predictor(..., lm=lm)`. Never call the Anthropic API or any provider SDK directly. Import `numpy` before `dspy` (a DSPy lazy-import bug on 3.14).
- Embeddings: `ctx.embedder.embed(texts)` → L2-normalized float32 rows; `ctx.embedder.count_tokens`, `ctx.embedder.max_tokens`.
- Jev (TypeSafe SDK): `ctx.jev.system_one(state=..., questions=...)`, wrapped in `monitoring.cached_call(namespace="jev", model=config.JEV_MODEL, ..., criteria_version=...)`.
- Every one of those already caches and records tokens/latency; do not time anything yourself. In each stage's `run`, wrap each email's `process` call in `with ctx.recorder.stage(STAGE, email_id):`.
- **No test calls a live model or the network.** Tests use `tests/fakes.py`: `FakeChat` (scripted replies; with JSONAdapter a reply is a JSON object keyed by the signature's output field names), `FakeEmbedder`, `FakeJev`, passed via `RunContext(..., chat=..., embedder=..., jev=..., use_cache=False)`. You may call live models only on the ten fixture emails, through the cache, and only if your done-when needs it; never on a full corpus set (only the lead runs a full corpus).

**Hard rules:** No pipeline stage passes a corpus label (including `reason` or the generation fields `email_type`, `systemic`, `angle`, `day`) to a model; only the corpus loader (package 2) and evals (package 8) read `EmailLabel` or `tests/fixtures/labels.jsonl`. Jev gets one email (sender, sender_email, subject, body) and the criteria only. Every quote is checked with `pipeline.io.quote_in` against the parsed body. A quarantined email's body reaches no later model and no screen. No tool writes to the book, sends anything, or browses. Code assigns every ID. Never generate corpus emails. Never print or log API keys or `.env`. Do not commit; the lead commits.

**Fixtures:** `tests/fixtures/emails.jsonl` (ten emails, corpus row format), `tests/fixtures/labels.jsonl`, `tests/fixtures/out/` (a valid example of every stage file), `tests/fixtures/README.md` (which email covers which case). Build and test against these; they stand in for upstream stages.

**Quality bar:** `uv run mypy src` stays clean for your files (strict); `uv run pytest tests/test_<yours>.py` passes; read like the surrounding code.

**Final report (your last message):** files changed; the exact test command(s) and their output; `uv run mypy src` output for your files; any line for `REVIEW.md` or choice for `DECISIONS.md`; anything left undone or any frozen-file change you need.
