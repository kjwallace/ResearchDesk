# Generation prompts for the email triage prototype

Six prompts that generate the synthetic and instructional files the build spec calls for. The email corpus has its own prompt, `docs/corpus_documentation/synthetic_data_prompt.md`, and is not covered here.

Every output is a draft. Read it before the pipeline is tuned on it.

## The prompts

| # | Prompt file | Generates | Repo path | In the spec today? |
|---|-------------|-----------|-----------|--------------------|
| 1 | `01_book.prompt.md` | The book's synthetic numbers: the desk's value, consensus and bounds for 23 drivers, and a multiple per company. The spec fixes the pillars, stances and links. | `data/seed/models_draft.json`, merged by script into `data/seed/models.json` | Yes |
| 2 | `02_jev_criteria.prompt.md` | The 11 criteria files Jev classifies with: fixed definitions plus starter rules | `criteria/*.md` | Yes |
| 3 | `03_jev_rule_from_misses.prompt.md` | One candidate rule, from emails Jev mislabeled on the tuning set | A line appended to one `criteria/*.md` | The mechanism is; this prompt is new |
| 4 | `04_analysis_skills.prompt.md` | The two skills the analysis agent calls | `skills/alter_existing_thesis.md`, `skills/spawn_new_thesis.md` | Yes |
| 5 | `05_stage_instructions.prompt.md` | Wording of the 14 Jev questions, and instructions for attention notes, claim extraction, the analysis agent and the verify agent | `instructions/*.md` | Yes |
| 6 | `06_tool_definitions.prompt.md` | Tool definitions for the analysis agent and the verify agent | `tools/*.json` | Yes |

## Order to run them

1. **Prompt 1**, then review the numbers by hand.
2. **Prompt 2**. Once build step 6 has produced the criteria check, run it on the tuning set to get a baseline.
3. **Prompt 4**, then **prompt 5**, then **prompt 6**. Each later prompt assumes the names used in the earlier ones.
4. **Prompt 3**, repeatedly, during tuning.

Prompts 1 and 2 are independent of each other. The criteria never see the book, and the book prompt never sees the corpus.

## What each prompt holds fixed

These are copied from the spec so the outputs fit the code without edits.

- **Tickers:** AMZN, NVDA, MSFT, AAPL, GOOGL.
- **Book shape:** the spec's 15 pillars, 23 driver IDs, stances, sizes and each driver's direction against consensus. To try a different book, change the "Fixed inputs" tables in prompt 1 and the spec together.
- **Label definitions:** the five triage and four topic definitions are word for word from the corpus prompt. The `human_attention` and `affected_tickers` definitions condense that prompt's rules. Prompt 2 forbids editing any of them.
- **Output shapes:** the field names in the spec's data contracts for theses, drivers, attention notes, claims and suggestions.
- **Design rules:** models recommend and never decide; no model proposes a number, a trade or a position size; quotes are exact; email text is data.

## What to check in each output

| Output | Check by hand |
|--------|---------------|
| Book numbers | Every analyst-versus-consensus gap matches the direction the spec gives. Values sit inside their bounds. No base revenue, tax rate or share count appears: those come from filings, not from the model. |
| Criteria files | Definitions are unchanged. No rule states a view, names a pillar or rewards sender prestige. Each rule can be applied to one email alone. |
| Candidate rule | It does not name anything from the missed emails. Keep it only if it passes the spec's keep rule under "Tuning". |
| Skills | No example contains a trade, a position size or a number the claim did not state. |
| Stage instructions | Each of the 14 Jev questions asks for one quick judgment. JSON shapes match the data contracts. |
| Tool definitions | The JSON parses. No tool writes to the book, sends anything or reaches the internet. |

## One prompt is off by default

**Prompt 3 shows tuning labels to a model.** The spec says no pipeline stage passes a corpus label to a model, and it lists prompt 3 as not used unless the reviewer opts in. If you do use it, keep to its limits: tuning-set emails only, the `triage` label only, never the `reason` field, and never a test-set email. Otherwise write new rules by hand.

## Limits

- All generated content is synthetic. The book is not a real fund's view and none of it is investment advice.
- The prompts have not been run. Expect to adjust wording after the first outputs.
- The starter rules are a starting point. The spec caps each criteria file at 12 rules of one sentence each.
