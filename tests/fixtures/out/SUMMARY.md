# Run summary: day_1

Synthetic data. Pipeline output only; no corpus label appears here.

- Set: day_1, day 2026-10-13
- Criteria version: fixture0000
- Thresholds: starting values (thresholds.py)

## Emails

10 emails; 10 with a result.

| Label | Emails |
| --- | --- |
| thesis_relevant | 2 |
| monitor | 3 |
| redundant | 1 |
| low_value | 1 |
| irrelevant | 1 |

Gate: 6 pass, 2 stop, 2 quarantine.
Quarantined (held unsummarized): `fixture_003`, `fixture_004`.

## Flagged repeats (1)

- `fixture_006` Alphabet near 1.2 GW power deal with Midwest utility for data centers: repeats `fixture_005` Alphabet nears 1.2 GW power deal with Midwest utility for data centers (content 0.96, subject 0.86)

## Attention notes (1)

- `fixture_007` Wed 8:00am ET call: former packaging engineer on Nvidia supply - confirm by 4pm today: reply, by 2026-10-13 16:00. Seats are released to other clients unless someone confirms by 4:00pm ET today, so a person must decide whether to take one.

## Suggestions (4)

**Thesis changes** (2)

- `MSFT.p1.supports` (MSFT.p1 supports, strength 2): Reseller checks put Azure growth above consensus and show capacity arriving early, which supports the Azure pillar.
- `AAPL.p1.supports` (AAPL.p1 supports, strength 1) (second look): A distributor report of trimmed iPhone build orders supports the view that the upgrade cycle disappoints.

**New thesis candidates** (1)

- `AMZN.new1` (new AMZN thesis): Partner checks show most new internal inference moving to Amazon's own chips at a steep price discount, which no AMZN pillar covers.

**Projection changes** (0)

None.

**Worth watching** (1)

- `NVDA.p2.supports` (NVDA.p2 supports, strength 1): A supplier report that memory for the next platform is booked and on schedule supports the supply pillar.

## Alerts (1)

- human_attention: `fixture_007` Wed 8:00am ET call: former packaging engineer on Nvidia supply - confirm by 4pm today

## Monitoring

- Tokens spent: 45,391 (uncached cost 51,433); 4,539 per email
- Cache hits: 6 of 39 calls
- Estimated cost: not priced spent this run, not priced if uncached, not priced per email
- Email latency: p50 5.7 s, p95 8.0 s
- Total time: 44.0 s
