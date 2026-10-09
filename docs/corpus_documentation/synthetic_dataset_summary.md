# Synthetic Desk Email Dataset

Two days of synthetic inbound email (300 per day, 600 total) plus a 100-email tuning set for the technology desk of a fictional long/short hedge fund, Larchmont Ridge Capital. The emails follow the instructions in [`synthetic_data_prompt.md`](synthetic_data_prompt.md). Every email carries the labels it was generated from, so the dataset can be used to grade a triage model.

All people, firms, research, datasets and figures are fictional. Real company names appear only for the five target companies and for well-known public companies used as context.

> **Day 1 after hand edits (2026-10-09).** Day 1 now holds **288 emails in shuffled arrival order**. Eleven redundant emails were replaced: ten became analyst estimate or rating changes, and one became an insider offering non-public results, which should be quarantined. Then seven thesis_relevant and five monitor emails were removed without replacement. Triage counts are now: thesis_relevant 30, monitor 45, redundant 19, low_value 105, irrelevant 89; human_attention 19. Email IDs are unchanged and no longer follow arrival order. Where the per-day tables below differ, these counts are current for day 1.

## Files

| Path | Contents |
| --- | --- |
| `data/corpus/day 1/emails.jsonl` | All 300 emails for day 1 (Tuesday, Oct 13, 2026): `synthetic_000001`–`synthetic_000300` |
| `data/corpus/day 2/emails.jsonl` | All 300 emails for day 2 (Wednesday, Oct 14, 2026): `synthetic_000301`–`synthetic_000600` |
| `data/corpus/tuning/emails.jsonl` | 100-email tuning set (Thursday, Oct 15, 2026): `synthetic_000601`–`synthetic_000700` |
| `data/corpus/<split>/email_plan.jsonl` | The randomly generated label plan each email was written against |

## Record schema

Each line of `emails.jsonl` is one JSON object with 14 fields: the 10 fields from the prompt's output schema, followed by the 4 generation labels.

| Field | Type | Description |
| --- | --- | --- |
| `email_id` | string | `synthetic_000001` … `synthetic_000700`, unique across all splits |
| `sender` | string | Sender name, title and firm |
| `sender_email` | string | Sender address |
| `subject` | string | Subject line |
| `body` | string | Full email text |
| `triage` | string | Primary label: `thesis_relevant`, `monitor`, `redundant`, `low_value`, `irrelevant` |
| `additional_labels` | array | Any of `macro`, `government`, `sector`, `other`, `human_attention` |
| `affected_tickers` | array | Any of `AMZN`, `NVDA`, `MSFT`, `AAPL`, `GOOGL`; empty when no target is affected |
| `human_attention` | bool | True for credible, time-sensitive meetings or calls worth taking |
| `reason` | string | Short justification for the triage label, based on the email's content |
| `email_type` | string | Format of the email, one of 11 types, e.g. `sell_side_research`, `primary_research`, `meeting_request`, `newsletter` |
| `systemic` | bool | True when one development affects all five targets together |
| `angle` | string | How the email earns its label, e.g. "contradicts consensus with new evidence" |
| `day` | int or string | `1`, `2`, or `"tuning"` |

## Distribution

| Measure | Day 1 | Day 2 | Tuning (100) | Target from prompt |
| --- | --- | --- | --- | --- |
| `thesis_relevant` | 37 (12%) | 27 (9%) | 9 (9%) | ~10% |
| `monitor` | 50 (17%) | 48 (16%) | 15 (15%) | ~15% |
| `redundant` | 19 (6%) | 33 (11%) | 9 (9%) | ~10% |
| `low_value` | 105 (35%) | 99 (33%) | 34 (34%) | ~35% |
| `irrelevant` | 89 (30%) | 93 (31%) | 33 (33%) | ~30% |
| `human_attention` | 19 | 20 | 7 | 15–25 per 300 (~5–8 per 100) |
| Emails with `macro` / `government` / `sector` | 29 | 28 | 10 | 25–35 per 300 (~8–12 per 100) |
| Emails with `other` | 7 | 4 | 2 | — |
| Systemic (all five tickers) | 4 | 4 | 2 | under 10% |
| Meetings, newsletters and events | 77 (26%) | 90 (30%) | 33 (33%) | at least 20% |
| Noise (`low_value` + `irrelevant`) naming a target | 29 of 194 (15%) | 28 of 192 (15%) | 10 of 67 (15%) | at most 15% |

The triage counts are jittered by a few emails around the targets, so the splits differ slightly, as the prompt allows. Day 1 is further off target on purpose: 11 of its `redundant` emails were later rewritten by hand, 10 as analyst estimate or rating changes (8 `thesis_relevant`, 2 `monitor`) and 1 as an insider offering to sell non-public results, which should be quarantined (`irrelevant`). See `DECISIONS.md`. Tuning-set counts are scaled from the 300-email day.

### Additional labels

| Label | Day 1 | Day 2 | Tuning |
| --- | --- | --- | --- |
| `macro` | 10 | 16 | 2 |
| `government` | 9 | 5 | 5 |
| `sector` | 13 | 10 | 5 |
| `other` | 7 | 4 | 2 |
| `human_attention` | 19 | 20 | 7 |

All `human_attention` emails are `thesis_relevant` or `monitor` meeting requests, expert-call offers or event invitations (day 1: 9 and 10; day 2: 8 and 12; tuning: 2 and 5). Meeting-type emails without `human_attention` are written as noise: sales pitches, generic networking, and routine events with little access.

### Ticker coverage

Tickers are rotated evenly through the `thesis_relevant` and `monitor` emails. Counts below include the systemic emails, which list all five tickers.

| Ticker | Day 1 signal | Day 2 signal | Tuning signal | Day 1 all | Day 2 all | Tuning all |
| --- | --- | --- | --- | --- | --- | --- |
| AMZN | 20 | 22 | 5 | 35 | 37 | 9 |
| NVDA | 24 | 21 | 8 | 34 | 31 | 11 |
| MSFT | 22 | 21 | 7 | 30 | 34 | 10 |
| AAPL | 22 | 20 | 7 | 35 | 31 | 11 |
| GOOGL | 25 | 18 | 6 | 31 | 28 | 11 |

"Signal" means `thesis_relevant` + `monitor`. Within `thesis_relevant` alone, each ticker appears 5–8 times per 300-email day (7–10 on day 1 after the hand edits) (1–3 in the 100-email tuning set).

### Email types

The generator wrote 18 email types. They were consolidated in place to 11 (see `DECISIONS.md`): types that differ only by length or cadence from the same source were merged, as were the first-hand research formats and the meeting-like formats that ask for a call. The last column lists the generator types each one absorbed.

| Email type | Day 1 | Day 2 | Tuning | Generator types merged |
| --- | --- | --- | --- | --- |
| `sell_side_research` | 77 | 86 | 18 | sell_side_research, sell_side_morning_note, sell_side_sales_color, macro_strategy |
| `news_alert` | 46 | 33 | 15 | news_alert, government_regulatory |
| `meeting_request` | 32 | 34 | 17 | meeting_request, expert_call_offer |
| `primary_research` | 36 | 29 | 8 | channel_check, industry_contact, expert_network_transcript |
| `vendor_pitch` | 28 | 25 | 13 | vendor_sales_pitch |
| `newsletter` | 21 | 30 | 9 | newsletter |
| `event_invitation` | 24 | 26 | 7 | event_invitation |
| `data_report` | 17 | 16 | 8 | vendor_data_report |
| `administrative` | 14 | 12 | 1 | administrative |
| `internal_forward` | 4 | 4 | 4 | internal_forward |
| `company_release` | 1 | 5 | 0 | company_ir |

### Text statistics

| Measure | Day 1 | Day 2 | Tuning |
| --- | --- | --- | --- |
| Body length in words (min / average / max) | 83 / 250 / 400 | 164 / 263 / 429 | 177 / 249 / 376 |
| Distinct sender domains | 283 | 286 | 94 |
| Duplicate subjects | 0 | 0 (none across days either) | 0 |

## How it was generated

1. **Label plan** — `scripts/corpus_generation/generate_email_plan.py` turns the prompt's distribution section into a randomized plan (seed 1101 for day 1, 2202 for day 2, 3303 for tuning). Absolute counts in the prompt (human attention, macro/government/sector, systemic) scale with `--count`. Each slot fixes the triage label, email type, tickers, additional labels, `human_attention`, `systemic` flag and a content angle.
2. **Email writing** — `scripts/corpus_generation/generate_emails_llm.py` sends `docs/corpus_documentation/synthetic_data_prompt.md`, a scene-setting context block, and five hand-written style examples (`scripts/style_examples.json`) to Claude Sonnet 5.5 through the Anthropic API. The model writes only the sender, subject, body and reason for each slot. The plan's labels are attached in code afterwards, so the labels on every email are exactly the ones it was written for. The tuning set was given day 1 and day 2 subjects as already seen, so it does not repeat those scenarios.
3. **Checks before saving** — each response must return the right email IDs in order with no empty fields, and must name every ticker in `affected_tickers`. An email that names an untagged target company three or more times is rejected. Failed batches are retried up to five times.
4. **Diversity** — batches run in waves; each wave sees the subjects already written that day so scenarios aren't repeated. Day 2 also sees day 1's subjects as "yesterday's" inbox, so its redundant emails can rehash day 1 news.
5. **Assembly** — `scripts/corpus_generation/build_email_jsonl.py` merges the generator's temporary batch files into a single `emails.jsonl` per day, confirms all 300 slots are present, and prints the distribution above. The batch files are then removed so each day folder holds only the plan and the merged emails.

## Regenerating

From the repository root:

```bash
python3 scripts/corpus_generation/generate_email_plan.py --day 1 --seed 1101 --start-id 1
python3 scripts/corpus_generation/generate_emails_llm.py --day 1 --out-dir "data/corpus/day 1"
python3 scripts/corpus_generation/build_email_jsonl.py --dir "data/corpus/day 1"

python3 scripts/corpus_generation/generate_email_plan.py --day 2 --seed 2202 --start-id 301
python3 scripts/corpus_generation/generate_emails_llm.py --day 2 --out-dir "data/corpus/day 2" --prior-dir "data/corpus/day 1"
python3 scripts/corpus_generation/build_email_jsonl.py --dir "data/corpus/day 2"

python3 scripts/corpus_generation/generate_email_plan.py --day tuning --seed 3303 --start-id 601 --count 100 --out-dir data/corpus/tuning
python3 scripts/corpus_generation/generate_emails_llm.py --day tuning --out-dir data/corpus/tuning --prior-dir "data/corpus/day 1" --prior-dir "data/corpus/day 2"
python3 scripts/corpus_generation/build_email_jsonl.py --dir data/corpus/tuning
```

The generator reads `ANTHROPIC_API_KEY` from `.env`. After a successful run, each split folder should contain only `email_plan.jsonl` and `emails.jsonl`. Use `--dry-run` to print the request without calling the API.
