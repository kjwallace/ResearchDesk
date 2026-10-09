# Corpus generation (historical)

These scripts produced the synthetic corpus in `data/corpus/` and are kept as the record of how it was made. They are not part of the pipeline, and nothing in `src/` imports them.

| File | Role |
|---|---|
| `generate_email_plan.py` | Draws each day's label plan from the corpus prompt's target distribution. |
| `generate_emails_llm.py` | Writes the email text for each planned slot. It calls the Anthropic API directly, before the project moved every model call to OpenRouter. |
| `build_email_jsonl.py` | Merges the drafted batches with the plan into `emails.jsonl`. |
| `style_examples.json` | Style examples given to the generator. |

They describe the generator's original 18 email types. The corpus has since been consolidated to 11 types in place (DECISIONS #45) and edited by hand (#85, #87), so rerunning them would not reproduce the current files. See `docs/corpus_documentation/synthetic_dataset_summary.md` for the commands that were run.
