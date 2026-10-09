# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project state: read this first

This repo is a **build-from-spec case study**. `SPEC.md` is the source of truth: an email triage and thesis-suggestion prototype (package `src/triage_app/`) for a fictional long/short tech desk covering AMZN, NVDA, MSFT, AAPL, GOOGL. **Almost none of it is built yet.** There is no `src/` or `tests/` code and no commits.

An earlier, unrelated prototype ("finresearch") is archived in `legacy/finresearch/`. It holds its README, pyproject, uv.lock, .env.example, main.py and `data/skills/`. Ignore it and do not build on it. A fresh `pyproject.toml`, `README.md` and `.env.example` still need writing to the spec. Python is 3.14 (`.python-version`). The `LLM_*` and `EMBEDDING_*` variables in `.env` are also leftovers. The spec does not use them.

Start with `KICKOFF.md`, then read `SPEC.md` **in full** (about 1,370 lines; do not work from a summary), then `prompts/README.md`. Follow the spec's "Build order" (steps 0–7, each with a "done when" test). If you use subagents, follow "Work packages for subagents".

## Commands (as the spec defines them, to implement under these exact names)

```bash
uv sync                                                     # locked env; no test needs keys or network
uv run pytest                                               # all tests
uv run pytest tests/test_gate.py::test_name                 # single test
uv run python -m triage_app.corpus --set day_1              # load + normalize + distribution report (sets: day_1, day_2, tuning)
uv run python -m triage_app.pipeline.run --set day_1        # all stages -> data/out/day_1/; --stage classify reruns one; --from extract reruns from a stage
uv run python -m triage_app.evals.tune                      # fit thresholds -> tuned/thresholds.json (needs tuning set)
uv run python -m triage_app.evals.criteria_check            # rerun Jev on tuning set, before/after scores
uv run python -m triage_app.evals.score --set day_1         # writes data/out/day_1/eval.json
uv run uvicorn triage_app.web.main:app                      # FastAPI + Jinja + HTMX, server-rendered
docker build -t triage-app . && docker run -p 8000:8000 --env-file .env triage-app
```

Corpus generation scripts (already run, they produced the existing corpus): `scripts/generate_email_plan.py`, `scripts/generate_emails_llm.py` (Anthropic API), `scripts/build_email_jsonl.py`. See each script's docstring for usage.

## Architecture (big picture)

**Pipeline = stage functions from files to files.** Each `pipeline/<stage>.py` exposes `run(in_dir, out_dir)` and `process(...)` for one email. Stages: parse → redundancy → classify → gate → (attention ∥ extract → analyze → validate → merge) → deliver. Each set (`day_1`, `day_2`, `tuning`) is run separately. Each stage reads earlier stage JSON in `data/out/<set>/` and writes its own. The spec's "Stage files" table is the interface contract. Emails are processed in **arrival order**, because the redundancy day-cache holds only earlier emails.

- **Stage 2 redundancy:** local embedding (e.g. bge-small via fastembed), chunked mean vector, cosine against earlier emails of the same day, plus subject token-set similarity (rapidfuzz). It produces a *hint* flag only. The corpus has no `redundant_of` labels, so the thresholds are fixed (not swept) and repeat eval reports only the flag count and precision against `triage == redundant`.
- **Stage 3 classify (Jev via TypeSafe):** one request per email with all 14 questions. It receives **only** the email and the criteria text from `criteria/*.md`. It never sees the book, other emails or the redundancy flag. There are two routes (DSPy `TypeSafe` vs `typesafe_sdk`); step 0's spike picks one and records it in `DECISIONS.md`.
- **Stage 4 gate:** pure code. Order: quarantine → label → tickers/topics → attention → gate on signal score (P(thesis_relevant)+P(monitor)). Reason strings are composed by code, never by a model.
- **Stages 5–8:** claim extraction, then the analysis agent (tool loop over two skills: alter existing thesis, spawn new thesis; max 3 calls), then code validation (IDs, verbatim quotes, bounds, duplicates), then merge per pillar+stance.
- **State layer** (`state/`): seed files in `data/seed/` plus an append-only per-session change log. Current state = fold(seed, log) and is never stored. `compute.py` is a pure function for revenue → EPS → target price.
- **Contracts:** all Pydantic models live in `schema.py` (copied from the spec's "Data contracts"). Model output is parsed into `*Draft` models and code builds the stored models. **Code assigns every ID** (`<email_id>.c<n>`, `<email_id>.s<n>`, `<pillar_id>.<stance>`, `<ticker>.new<n>`).
- **Thresholds:** every threshold, limit and tunable number is defined once, in `src/triage_app/thresholds.py`, and read everywhere as `thresholds.NAME` (aliased `limits` in `gate.py` and `tune.py`, where `thresholds` names a `Thresholds` value). Never write such a number anywhere else. `tuned/thresholds.json` overrides the swept ones at run time via `thresholds.load_thresholds()`. `config.py` holds paths, sets and labels; model IDs live only in `.env`.
- **Caching:** every model call and embedding is cached on disk under `data/cache/`, keyed by program version + criteria version + input hash, and committed. Every module takes its client as an argument, and tests use fakes or cache replay.
- **Monitoring** (`monitoring.py`): wraps every client handed to a module and records a `CallRecord` per call (tokens, cache hit, latency). `run.py` records a `StageTiming` per stage per email. Output goes to `data/out/<set>/usage.json` and `metrics.json` (`UsageReport`), shown on `/monitor`. Records hold IDs, counts and times only, never prompt or email text.

## Invariants that must not be broken

- Loader splits each row into `Email` + `EmailLabel`. **Only the loader, evals and tuning code may read labels.** No corpus label (including `reason`) ever reaches a model prompt.
- Models recommend, never decide: no trades, sizes, numbers of their own, writes to the book or invented IDs. Every quote is verified verbatim (after whitespace collapse) against the parsed body.
- A quarantined email's body reaches no later model and no screen (sender and subject only).
- Criteria files: label definitions are fixed (from the corpus prompt). Add rules only, at most 12 per file, one sentence each. No pillar or driver IDs and no views (the loader must fail if one appears).
- Tune only on the tuning set and never on test. Never edit the corpus or the corpus prompt to make a score pass.
- Every generated draft (seed numbers, criteria, skills, instructions, tools) is committed and listed in `REVIEW.md`. Spec-silent choices go in `DECISIONS.md`. Session and subagent transcripts go in `transcripts/` (they are a deliverable).
- Every screen is labeled synthetic. The system never sends mail. Never commit or log API keys.

## Corpus and keys

- Test corpus: `data/corpus/day_1/emails.jsonl` and `data/corpus/day_2/emails.jsonl` (300 each), each with an `email_plan.jsonl` beside it. Tuning corpus: `data/corpus/tuning/emails.jsonl`. It is **being generated outside the build**, so don't generate or edit it. Until it exists, tuning is pending and the pipeline runs at starting values.
- Rows have no `received_at` (the loader assigns one in file order) and no `redundant_of`. Generation fields (`email_type`, `systemic`, `angle`, `day`) are label-side and never reach a model.
- Corpus prompt: `docs/corpus_documentation/synthetic_data_prompt.md`. Use only the text above its cut line.
- **All generative model calls go through OpenRouter** (`OPENROUTER_API_KEY`), via `triage_app/llm.py` (`OpenRouterClient`). Never call the Anthropic API directly. Jev uses the TypeSafe SDK (`TYPESAFE_API_KEY`) because OpenRouter does not serve it.
- **Never generate emails.** The corpus, including the tuning set, is produced elsewhere.
