# Kickoff brief for the lead coding agent

You are building the email triage prototype that `SPEC.md` specifies. Nothing is built yet.

1. Read `SPEC.md` whole, then `prompts/README.md`. Do not start from a summary.
2. Begin at "Start here" in the spec. Follow "Build order" step by step; each step has a test that proves it is done.
3. If you use subagents, follow "Work packages for subagents": build package 0 yourself, freeze the contracts, then brief each subagent from its row. A subagent has no memory of your session.
4. Keep to "Working rules for the coding agent" and the seven design rules. Where the spec is silent, choose the simpler option and record it in `DECISIONS.md`.
5. Save your session transcript and every subagent's brief, transcript and report under `transcripts/`. They are part of the submission.

## What is in this package

| Path | What it is |
| --- | --- |
| `SPEC.md` | The build spec. |
| `prompts/` | Six generation prompts and their README. |
| `docs/corpus_documentation/synthetic_data_prompt.md` | The corpus prompt. Use only the text above its cut line. |
| `data/corpus/day_1/`, `data/corpus/day_2/` | The test corpus: two days of 300 labeled emails each. |
| `.env` | API keys: `OPENROUTER_API_KEY` for every generative model call, `TYPESAFE_API_KEY` for Jev. Never call the Anthropic API directly. Never commit or print `.env`. |
| `legacy/finresearch/` | An archived earlier prototype. Not part of this build; do not build on it. |

## What a person still has to supply

The spec's "Where a person is needed" table says what to do while each of these is missing.

- The tuning corpus, at `data/corpus/tuning/emails.jsonl`. It is being generated elsewhere: never generate emails.
- A deploy host and its credentials.
