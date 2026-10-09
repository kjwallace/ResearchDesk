# Day 1 corpus replacements

**The person asked for this edit to the test corpus:** in `data/corpus/day_1/`, replace **10 emails labeled `redundant`** with new emails in which analysts change financial projections (EPS, price targets, revenue or segment growth, margins, capex) or change their ratings (upgrades and downgrades). This gives the book's new projection-change and street-view analysis real examples. Also replace **1 more `redundant` email** with an email that should be **quarantined**. That makes 11 replacements; every other email stays byte-for-byte unchanged.

**You own only:** `data/corpus/day_1/emails.jsonl`, `data/corpus/day_1/email_plan.jsonl`, and the day 1 counts in `docs/corpus_documentation/synthetic_dataset_summary.md`.

Work in `/Users/kelvinwallace/Desktop/DE_Shaw_CaseStudy/.claude/worktrees/analysis-upgrade` (a git worktree), never in the main checkout. Other subagents edit other files there. Do not call any model API, and do not run the pipeline. Never print `.env`.

**Read first:**
- `docs/corpus_documentation/synthetic_data_prompt.md` above its cut line. It defines the labels and their meanings, the style, and the rules: fictional people and firms, no real analysts or banks, real names only for the five companies.
- `docs/corpus_documentation/synthetic_dataset_summary.md`.
- Five or six existing `day_1` emails of type `sell_side_research`, so yours match the house style: varied length, realistic sender signatures, some noise.

**Choosing the 11 to replace:**
- Choose 11 of the 30 `triage == "redundant"` rows in `day_1/emails.jsonl`, spread across the day.
- **Do not** pick `synthetic_000261`, `synthetic_000144` or `synthetic_000007`, or any email whose ID appears as the earlier email of another in `data/out/day_1/redundancy.json` (`nearest`).
- Keep each replaced row's `email_id`, `day` and position in the file. Arrival times come from file position, so order is preserved.

**The 10 projection and rating emails:**
- Senders are fictional sell-side analysts (invented firms), or occasionally a buy-side contact relaying a broker change.
- Cover all five companies (two each). Use a mix of:
  - EPS estimate changes;
  - price target changes;
  - segment growth, operating margin or capex estimate changes;
  - at least 3 rating changes (e.g. hold to buy, buy to hold), including at least one that moves *against* the desk's stance (the desk is long NVDA/MSFT/AMZN and short AAPL/GOOGL).
- **Every figure must be stated for the company's modeled fiscal year**, written exactly like this: NVDA **FY2027**, MSFT **FY2027**, AMZN **FY2026**, AAPL **FY2026**, GOOGL **FY2026**. You may mention other years too, but the key figure must carry that label.
- Each figure must sit within ±35% of the book's projection below, so it is plausible. Use the units shown: growth and margin in percent, revenue and capex in $bn, EPS and target price in $.

  | Company | EPS desk / consensus | Target price desk / cons | Revenue desk / cons | Drivers (desk / consensus) |
  |---|---|---|---|---|
  | NVDA FY2027 | 6.26 / 6.09 | 200 / 195 | 291.6bn / 283.8bn | Data Center growth 38 / 34; operating margin 62 / 62 |
  | MSFT FY2027 | 18.79 / 18.49 | 583 / 573 | 386.1bn / 379.9bn | Intelligent Cloud growth 24 / 21.5; Productivity growth 14 / 12; operating margin 45 / 45; capex 110bn / 110bn |
  | AMZN FY2026 | 8.02 / 7.09 | 241 / 213 | 799.8bn / 795.9bn | AWS growth 22 / 19; operating margin 13.5 / 12; capex 140bn / 140bn |
  | AAPL FY2026 | 7.27 / 7.95 | 196 / 215 | 431.0bn / 441.6bn | iPhone growth 1 / 4.5; Services growth 9 / 12; operating margin 30 / 32 |
  | GOOGL FY2026 | 9.06 / 10.23 | 190 / 215 | 443.6bn / 455.6bn | Services growth 7 / 10.5; Cloud growth 28 / 28; operating margin 30 / 33; capex 100bn / 93bn |
- **Labels** (follow the corpus prompt's definitions):
  - Most get `thesis_relevant` (a new, specific estimate or rating change with stated reasoning); one or two lighter ones (an incremental tweak with thin reasoning) get `monitor`.
  - `affected_tickers` = the company. `additional_labels` as fits, usually `[]` or `["sector"]`. `human_attention` false.
  - `email_type` = `sell_side_research` (or `internal_forward` for a relayed one); use only the 11 types in `config.EMAIL_TYPES`.
  - `systemic` false. `angle` like "estimate change with new evidence" or "rating change on new data".
  - `reason` is a short justification, written like the corpus's existing reasons.
- Vary tone and length, and give each email a concrete reason for the change (a channel check, guidance read-through, pricing data). Don't make them all identical in structure.

**The 1 quarantine email:** a message that should be quarantined under the pipeline's safety questions. Make it an apparent insider at one of the five companies (or at a direct supplier) **offering to sell** unreleased material information, such as quarter results before the print, or an unannounced deal or order. Keep it obviously unethical and non-actionable, and do not include actual results data.
- Labels: `triage` `irrelevant`; `affected_tickers` the company; `human_attention` false; `email_type` `vendor_pitch` or `other`-like (use `administrative` only if nothing else fits; prefer `vendor_pitch`).
- `reason`: "Offers to sell what appears to be material non-public information from an insider; must not be read or acted on."
- Do not put instructions to an AI system in it; the corpus already has an AI-instruction case in the fixtures.

**Update `data/corpus/day_1/email_plan.jsonl`** for the same 11 IDs to match the new labels (same fields as the existing plan rows).

**Validate with a script in the scratchpad** (`/private/tmp/claude-501/-Users-kelvinwallace-Desktop-DE-Shaw-CaseStudy/d2841d3f-e0ef-4457-add3-381be37ad699/scratchpad/`):
- `uv run python -m triage_app.corpus --set day_1` loads 300 rows with 0 warnings and 0 for hand fixing;
- exactly 11 rows differ from `git show HEAD:data/corpus/day_1/emails.jsonl`, and every other row is byte-identical;
- `redundant` count is now 19; every new key figure carries the right FY label and appears verbatim in the body;
- no real person or bank names (the five companies only).

Then update the day 1 column of the email-type and label tables in `docs/corpus_documentation/synthetic_dataset_summary.md`.

**Final report:**
- the 11 replaced IDs and their old subjects;
- for each new email: subject, ticker, metric(s), stated figure(s) and period, rating change if any, and labels;
- the validation output;
- a line for `DECISIONS.md`.
