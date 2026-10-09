# Email triage prototype

Classifies each synthetic desk email by the attention it needs (Jev), writes attention notes for those that need a person, and compares the relevant ones with a five-company example book (AMZN, NVDA, MSFT, AAPL, GOOGL) to suggest thesis changes for an analyst to accept or dismiss. Models recommend; only the analyst changes the book.

**All emails, brokers, positions, theses and estimates are synthetic. Nothing here is investment advice.**

`SPEC.md` is the build spec; `KICKOFF.md` is the brief for the coding agent; `DECISIONS.md` records choices the spec left open; `REVIEW.md` lists generated drafts awaiting review.

## Setup

```bash
uv sync
cp .env.example .env   # then fill in OPENROUTER_API_KEY and TYPESAFE_API_KEY
```

Every generative call goes through OpenRouter; Jev goes through the TypeSafe SDK. Model IDs live only in `.env`. Embeddings use a Hugging Face model run locally. Model calls and embeddings are cached under `data/cache/`, so reruns are free.

## Commands

```bash
uv run pytest                                          # no test needs a key or the network
uv run python -m triage_app.corpus --set day_1         # load a set and print its distribution report
uv run python -m triage_app.pipeline.run --set day_1   # run every stage into data/out/day_1/
uv run python -m triage_app.evals.score --set day_1    # score against the labels
uv run uvicorn triage_app.web.main:app                 # serve the app
```

Every run writes `usage.json` and `metrics.json` (tokens and latency per stage, model and email) beside its stage files and prints a summary.
