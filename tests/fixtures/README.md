# Test fixtures

Ten hand-written synthetic emails (day 1, 2026-10-13) and a valid, mutually consistent example of every stage file in `out/`, as the pipeline would write them at starting thresholds with criteria version `fixture0000`. People and firms are fictional; the five covered companies are real. No model wrote any of this.

Check everything with:

```
uv run python tests/fixtures/validate_fixtures.py
```

| Email | Case covered | Corpus label (normalized) | Pipeline label / gate | Where it lands in the brief |
| --- | --- | --- | --- | --- |
| fixture_001 | MSFT reseller check with a stated FY2027 Intelligent Cloud growth of 26%. Existing-thesis suggestion with a figure; a second suggestion (NVDA.p1) is rejected for a quote mismatch. Raw triage is `relevent`. | thesis_relevant, MSFT | thesis_relevant / pass (0.92) | thesis_changes: `MSFT.p1.supports` |
| fixture_002 | Unconfirmed supplier report on Nvidia memory supply. Monitor-only rule: raw strength 2 becomes 1. | monitor, sector, NVDA | monitor / pass (0.82) | worth_watching: `NVDA.p2.supports` |
| fixture_003 | Body tells an AI system to ignore its instructions. | irrelevant | none / quarantine (instructs_ai 0.97) | quarantined |
| fixture_004 | Appears to share inside information (an unannounced internal Apple figure). Raw ticker `aapl`. | thesis_relevant, AAPL | none / quarantine (possible_mnpi 0.91) | quarantined |
| fixture_005 | Alphabet power-deal report: the earlier email of the repeat pair. Passed with claims and no suggestion. Raw ticker `GOOG`. | monitor, sector, GOOGL | monitor / pass (0.71) | relevant_unlinked |
| fixture_006 | Same-day near-copy of fixture_005 (cosine 0.96, subject score 0.86). Jev's top label is monitor, and the redundancy check relabels it. | redundant, sector, GOOGL | redundant (redundancy_check, of fixture_005) / stop (0.52) | audit |
| fixture_007 | Expert-call offer with a same-day deadline (confirm by 4:00pm ET). Gets an attention note and an alert. No claims are extracted. Raw `additional_labels` holds `human_attention`. | monitor, NVDA, attention | monitor, attention / pass (0.72) | needs_attention and relevant_unlinked |
| fixture_008 | Promotional newsletter with one buried iPhone build-order datapoint. Labeled low_value, but the signal score clears the gate. | low_value, AAPL | low_value / pass (0.62) | thesis_changes: `AAPL.p1.supports`, second_look |
| fixture_009 | Amazon in-house chip adoption. New-thesis candidate. Jev also tags NVDA (0.55), a ticker false positive in eval. | thesis_relevant, AMZN | thesis_relevant / pass (0.90) | new_theses: `AMZN.new1` |
| fixture_010 | European banking conference invitation. | irrelevant | irrelevant / stop (0.04) | audit |

Placement rule used by the validator: every email appears exactly once across the suggestion lists (by linked email), `relevant_unlinked`, `audit` and `quarantined`. `needs_attention` is an overlay, so its emails also appear in one of those lists.
