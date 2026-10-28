# AI transcripts

The record of the AI sessions that built this repository. All content is synthetic.

| Path | What it is |
|---|---|
| `00_data_set_generation_trace.txt` | Trace of how the synthetic email corpus was generated. |
| `01_build_out_from_spec.txt` | The lead session that built the pipeline, evals and first web app from `SPEC.md`. |
| `02_repository_specs_and_frontend_ui.txt` | The UI thread that took the app from the first version to the review, book and attention screens. |
| `03_ui_takeover_and_deploy.txt` | The session that reworked the brief, book, inbox and summaries, added the Live tab on Vercel, and began this cleanup. |
| `agent_transcripts/briefs/` | The brief given to each subagent (`_common.md` holds the shared rules). |
| `agent_transcripts/subagents/` | Each subagent's raw session log (JSON lines). |
| `agent_transcripts/generation/` | Requests, responses and metadata for the generation prompts (analysis skills, stage instructions, tool definitions). |

The `.txt` transcripts are text exports of the session logs: tool output is cut at 1,500 characters, and key-like values are replaced with `[REDACTED]`.
