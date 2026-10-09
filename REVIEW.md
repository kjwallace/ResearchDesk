# Drafts awaiting review

Every generated file is committed as a draft and listed here before the pipeline is tuned on it. A person marks each one reviewed (with initials and date) or notes what to change. Checks for each kind are in `prompts/README.md`, "What to check in each output".

| File | Made by | What to look at | Reviewed |
|------|---------|-----------------|----------|
| `data/seed/models_draft.json` | Prompt 01, run in a Claude Code subagent (Claude Opus 5.5); its own check script passed | Each analyst-vs-consensus gap matches the spec's direction; bounds are wide enough; the multiples are plausible (NVDA 32, MSFT 31, AMZN 30, AAPL 27, GOOGL 21). Its fiscal-year labels are overridden by `seed_merge` (DECISIONS #14). | No |
| `data/seed/base_figures.json` | Extracted from each latest 10-K on SEC EDGAR by a subagent, cross-checked against XBRL companyfacts | Segment mapping per company (NVDA from the market-platform table; GOOGL excludes hedging); tax rate = provision / pre-tax income; diluted shares. Source URLs are in the file. | No |
| `data/seed/models.json` | `uv run python -m triage_app.state.seed_merge` from the two files above | Nothing is placeholder (`placeholder_base` false for all five). | No |
| `criteria/*.md` (11 files) | Prompt 02, run in a Claude Code subagent (Claude Opus 5.5); passes `triage_app.criteria.load` (version `f16e16cf314d`) | Definitions are word for word from the corpus prompt; no rule states a view, names a pillar, or rewards prestige; each rule applies to one email alone. | No |
| `skills/alter_existing_thesis.md` | Prompt 04 via OpenRouter (Sonnet 5.5) | The strength-3 example treats a relayed CFO quote as first-hand. Example claim IDs are written `c1`. Prose calls the other skill by a nickname. | No |
| `skills/spawn_new_thesis.md` | Prompt 04 via OpenRouter | The generator added its own rule: "at least one claim from another label must carry the candidate" (stricter than the spec). Example 1's health-subscription thesis must read clearly as an example. | No |
| `instructions/jev_questions.md` | Prompt 05 via OpenRouter; two lead edits (DECISIONS #22, #24) | The wording of all 14 questions, especially `possible_mnpi` (see the flag below). `topic_other` is defined by exclusion. | No |
| `instructions/attention_note.md` | Prompt 05 via OpenRouter | Example 2 adds facts the email does not state ("approaching the desk for the first time", a firm name), breaking its own rule. Added deadline defaults: a date alone means 23:59:59, with no time zone unless the email gives one. | No |
| `instructions/extract_claims.md` | Prompt 05 via OpenRouter | Added rules: `value` unsigned with the sign in `direction`; out-of-list units give a null value; a repeat definition. Example 1 marks a relayed supplier remark `first_hand: true`. | No |
| `instructions/analysis_agent.md` | Prompt 05 via OpenRouter | The fixed "No skill applies:" prefix when no skill is called. | No |
| `instructions/verify_agent.md` | Prompt 05 via OpenRouter | Requires `sources: []` for `not_found`; `confirmed` must match any figure and period. | No |
| `tools/analysis_agent.json` | Prompt 06 via OpenRouter; one lead edit (DECISIONS #23) | Descriptions say when not to call each tool. | No |
| `tools/verify_agent.json` | Prompt 06 via OpenRouter | Three read-only tools; the `item_id` pattern accepts every seed ID. | No |

## Flags for the reviewer

- **Quarantine on possible MNPI.** In the step 0 spike, a legitimate expert-network call invitation scored `possible_mnpi` 0.64 under provisional wording. The quarantine threshold is fixed at 0.4, so the final wording of the `possible_mnpi` question (from prompt 05) needs a careful look, or real expert-call invitations may be quarantined.
