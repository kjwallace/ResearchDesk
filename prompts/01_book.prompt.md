# Prompt 1: generate the synthetic numbers in the book

**Produces:** `data/seed/models_draft.json`, which a script merges with base figures from filings into `data/seed/models.json`
**Run:** once, before the pipeline is built.
**Model:** a large generative model. Browsing is not needed.

The spec fixes the book's stances, sizes, pillars, driver IDs and links. Copy those into `data/seed/theses.json` and `data/seed/links.json` by hand or by script. This prompt writes only what the spec leaves open: the desk's value and an illustrative consensus for each driver, sanity bounds, and a target multiple for each company.

To try a different book, edit the "Fixed inputs" tables below and the spec together.

Paste everything below the line into the model.

---

## Role

You are helping build a software prototype for a technology desk at a long/short equity fund. The prototype compares incoming emails with the desk's "book" and recommends thesis changes to an analyst. Your task is to write the illustrative numbers for a fictional example book covering five companies.

The book is invented for a demo. It is not a real fund's view, not a forecast and not investment advice. Write numbers that a knowledgeable reader finds plausible in magnitude, and present none of them as a real estimate.

## Fixed inputs

Use these exactly. Do not change tickers, stances, pillar wording or driver IDs.

### Positions

| Ticker | Company | Stance | Size (bps) | Conviction (1 to 5) |
|--------|---------|--------|-----------|---------------------|
| NVDA | Nvidia | long | 300 | 4 |
| MSFT | Microsoft | long | 250 | 3 |
| AMZN | Amazon | long | 200 | 3 |
| AAPL | Apple | short | 200 | 3 |
| GOOGL | Alphabet | short | 150 | 2 |

### Pillars and their linked drivers

| ID | Pillar | Linked drivers |
|----|--------|----------------|
| NVDA.p1 | AI infrastructure spending by cloud and sovereign buyers keeps Data Center growth above consensus through the next fiscal year. | `NVDA.data_center_growth` |
| NVDA.p2 | Supply of advanced packaging and high-bandwidth memory is sufficient to ship the newest platform on schedule. | `NVDA.data_center_growth` |
| NVDA.p3 | In-house chips at large customers grow alongside Nvidia instead of replacing it, so pricing and margin hold. | `NVDA.operating_margin`, `NVDA.data_center_growth` |
| MSFT.p1 | Azure growth stays above consensus as data-center capacity comes online. | `MSFT.intelligent_cloud_growth` |
| MSFT.p2 | Paid AI assistants raise revenue per seat in the productivity suite. | `MSFT.productivity_growth` |
| MSFT.p3 | Capital intensity peaks within the model year and operating margin holds. | `MSFT.capex`, `MSFT.operating_margin` |
| AMZN.p1 | AWS growth re-accelerates as power and chip capacity is added. | `AMZN.aws_growth` |
| AMZN.p2 | Retail operating margin keeps expanding through fulfillment efficiency and advertising. | `AMZN.operating_margin`, `AMZN.north_america_growth` |
| AMZN.p3 | Capital expenditure converts into AWS backlog instead of a lasting drag on free cash flow. | `AMZN.capex`, `AMZN.aws_growth` |
| AAPL.p1 | The iPhone upgrade cycle disappoints: AI features do not pull upgrades forward, and share in China stays under pressure. | `AAPL.iphone_growth` |
| AAPL.p2 | Services growth slows as regulation and litigation pressure App Store fees and search distribution payments. | `AAPL.services_growth` |
| AAPL.p3 | Operating margin is at risk from tariffs and component costs. | `AAPL.operating_margin` |
| GOOGL.p1 | AI answers reduce clicks on commercial queries, so Search revenue growth falls below consensus. | `GOOGL.services_growth` |
| GOOGL.p2 | Rising capital expenditure and depreciation compress operating margin. | `GOOGL.operating_margin`, `GOOGL.capex`, `GOOGL.cloud_growth` |
| GOOGL.p3 | Regulatory remedies in search and advertising technology restrict distribution or the ad stack. | `GOOGL.services_growth` |

### Drivers and the desk's direction against consensus

| Driver ID | What it measures | Unit | Desk versus consensus |
|-----------|------------------|------|-----------------------|
| `NVDA.data_center_growth` | Data Center revenue growth | pct | Above |
| `NVDA.gaming_growth` | Gaming revenue growth | pct | In line |
| `NVDA.other_growth` | All other revenue growth | pct | In line |
| `NVDA.operating_margin` | Operating margin | pct | In line |
| `MSFT.intelligent_cloud_growth` | Intelligent Cloud revenue growth | pct | Above |
| `MSFT.productivity_growth` | Productivity and Business Processes revenue growth | pct | Above |
| `MSFT.personal_computing_growth` | More Personal Computing revenue growth | pct | In line |
| `MSFT.operating_margin` | Operating margin | pct | In line |
| `MSFT.capex` | Capital expenditure | usd_bn | In line |
| `AMZN.aws_growth` | AWS revenue growth | pct | Above |
| `AMZN.north_america_growth` | North America revenue growth | pct | In line |
| `AMZN.international_growth` | International revenue growth | pct | In line |
| `AMZN.operating_margin` | Operating margin | pct | Above |
| `AMZN.capex` | Capital expenditure | usd_bn | In line |
| `AAPL.iphone_growth` | iPhone revenue growth | pct | Below |
| `AAPL.services_growth` | Services revenue growth | pct | Below |
| `AAPL.other_products_growth` | Mac, iPad and wearables revenue growth | pct | In line |
| `AAPL.operating_margin` | Operating margin | pct | Below |
| `GOOGL.services_growth` | Google Services revenue growth | pct | Below |
| `GOOGL.cloud_growth` | Google Cloud revenue growth | pct | In line |
| `GOOGL.other_bets_growth` | Other Bets revenue growth | pct | In line |
| `GOOGL.operating_margin` | Operating margin | pct | Below |
| `GOOGL.capex` | Capital expenditure | usd_bn | Above |

## What to write

For each of the 23 drivers give:

- `id`, `label` (the "What it measures" text) and `unit`, copied from the table.
- `analyst`: the desk's value for the next fiscal year.
- `consensus`: an illustrative Street value.
- `min` and `max`: sanity bounds that any figure stated in an email should fall within.

For each company also give:

- `target_multiple`: an illustrative price-to-earnings multiple.
- `fiscal_year`: the forward fiscal year label, such as `FY2027`.

Requirements:

- **Units.** A `pct` value is in percentage points: 12.5 means 12.5%. A `usd_bn` value is in billions of US dollars.
- **Direction matches the table.** "Above" means `analyst` is higher than `consensus`; "Below" means lower; "In line" means the two are equal.
- **Gaps are meaningful but modest.** For growth and margin drivers, a gap of one to five points. For capex, a gap of 3% to 10% of the consensus figure.
- **Values are plausible in magnitude** for a company of that kind, but invented. Do not claim any number is a real estimate and do not cite a source.
- **Bounds are wide.** For growth drivers, at least 20 points either side of `analyst`. For margins, at least 10 points. For capex, from half to double the `analyst` figure.
- **Leave base figures out.** Base revenue by line, tax rate and diluted share count are real figures the build takes from each company's latest annual report. Do not write them.

## Output format

Return one JSON document and nothing else: an array of five objects in the order NVDA, MSFT, AMZN, AAPL, GOOGL.

```json
{
  "ticker": "NVDA",
  "synthetic": true,
  "fiscal_year": "FY2027",
  "target_multiple": 0,
  "drivers": [
    {"id": "NVDA.data_center_growth", "label": "Data Center revenue growth", "unit": "pct",
     "analyst": 0, "consensus": 0, "min": 0, "max": 0}
  ]
}
```

## Checks before you answer

1. Five companies and 23 drivers, with every ID copied from the table.
2. Every driver's gap matches its direction in the table, and "In line" drivers have equal values.
3. Every `analyst` and `consensus` value lies between `min` and `max`.
4. No base revenue, tax rate or share count appears.
5. Nothing is presented as a real estimate, a real fund's view or advice.
