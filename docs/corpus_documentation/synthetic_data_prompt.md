## Objective

Generate realistic synthetic emails for a technology-focused desk working at a buy side long-short hedge fund, receiving 300 emails daily. Emails may include notes from sell-side analysts, industry insiders, company contacts, vendor reports, news services, government bodies, and invitations.

The desk trades around information flow and needs to identify emails that could affect investment theses, expectations, positioning, risk, or require direct human engagement.

For this data set, we will only be focussing on information regarding these 5 target companies.
**Target companies:** Amazon (AMZN), Nvidia (NVDA), Microsoft (MSFT), Apple (AAPL), and Google/Alphabet (GOOGL).

Other companies and sectors may appear rarely, particularly in credible, informative examples. However, information about other companies can be relevant if it provides a clear read-through to a target company. But is mainly included as a potential source of noise.

---

## Label and Email Type Distribution — Projected Percentages, Amounts, and Weights

For the 300 synthetic emails in this dataset, target the following approximate proportions and amounts for each primary triage label and major email type. These projections are guidelines based on real observed flows and a realistic workflow.

| Primary Triage Label    | Target % | Projected Count (per 300) | Relative Weight | Description/Examples                                                                      |
|------------------------|----------|---------------------------|----------------|------------------------------------------------------------------------------------------|
| `thesis_relevant`      | 10%      | ~30                       | 1x             | Directly thesis-impacting, actionable, or meaningfully incremental info                   |
| `monitor`              | 15%      | ~45                       | 1.5x           | Emergent trend, signal, or ripple effect—plausible but unconfirmed                        |
| `redundant`            | 10%      | ~30                       | 1x             | Already known, well-disseminated, or duplicative                                          |
| `low_value`            | 35%      | ~105                      | 3.5x           | Marginal, tangential, or weakly supported; "soft noise"                                   |
| `irrelevant`           | 30%      | ~90                       | 3x             | Not relevant to the thesis or target companies                                            |

**Rules and Projections for Observed Distribution:**
- Distribution by label aligns with the above table; small batch-to-batch deviations are acceptable if justified by more realistic desk flow.
- Each of the five target tickers (AMZN, NVDA, MSFT, AAPL, GOOGL): Appear at an approximately equal rate across the `thesis_relevant` and `monitor` buckets. As a check, observe that roughly 6-8 emails per ticker per 300 are found in the `thesis_relevant` bucket when aggregating data over time.
- Among `low_value` and `irrelevant`, mention of a target ticker is less frequent—target no more than 15% of noise emails (collectively) that reference a target directly.
- Meeting requests, newsletters, and event announcements as email types: Comprise at least 20% of all items (~60 out of 300), but are not only assigned to `human_attention`—they can be labeled as `irrelevant`, `low_value`, or occasionally `monitor`.
- The `human_attention` label (as an additional label): Applied only to high-value, credible, or time-sensitive actionable meetings or requests (target ~15–25 total instances, which is ~5–7.5% of total emails). Not all invitations or calendar items should get this label.
- Macro, government, and sector labels: Present in about 10% of emails (25–35 total, across all triages), and always substantiated by content.
- Reports on companies outside the target list: Appear throughout, but mostly populate the `irrelevant`, `low_value`, and `redundant` buckets. Realistic informative detail is preserved, but without target-company implication.
- The observed flow favors noise: The majority of the daily volume is "noise" (`low_value`+`irrelevant`); only a minority is actionable or actionable-monitor.
- Systemic, regulatory, or "market moving" emails that cover multiple tickers in concert should be rare (under 10% of all emails combined).
- Over the course of a week, one expects to see similar proportions, confirming the strong prevalence of noise over signal.

---

## Labels

Assign one primary `triage` label and any applicable `additional_labels`.

### Primary triage label — exactly one

- `relevent`: New or meaningful information that supports, challenges, or changes an investment thesis, earnings expectations, competitive outlook, valuation, or trading decision.
- `monitor`: A credible emerging signal or developing trend that could affect a thesis, but whose implications remain uncertain or unconfirmed.
- `redundant`: Information already known or disseminated that adds no meaningful incremental insight.
- `low_value`: Some connection to a target company or investment thesis, but insufficient materiality, differentiation, or evidentiary support to merit attention.
- `irrelevant`: No meaningful investment-thesis connection to the target companies or desk's interests.
- `human_attention` : Information or meeting request that required direct human attention. Has to be from a valuable or credible source where taking the meeting is valuable. All sales invites are noise.

Judge relevance by incremental information value, not whether the news is positive or negative.

---

### Target Company Labels

If an email is relevant to any of the five target firms, use one or more of the following case-insensitive ticker labels in the `affected_tickers` field.
Label each affected company present in the email's content, using the company tickers:

- `AMZN` (Amazon)
- `NVDA` (Nvidia)
- `MSFT` (Microsoft)
- `AAPL` (Apple)
- `GOOGL` (Google/Alphabet)

If the email has a material implication for more than one of these companies, include all relevant tickers in the array.
If the email has relevance to all the companies for systemic reasons, select one of the following labels:

---

### Other (Non-Company) Labels

For emails that pertain to broader topics or drivers not exclusive to a single company, include one or more of the following non-company labels in the `additional_labels` field as appropriate:

- `macro`: Broader macroeconomic events, data, or trends (e.g., inflation, rates, currency, global demand) with relevance to the investment landscape.
- `sector`: Developments that predominantly affect the sector or industry level but are not limited to an individual target company.
- `government`: Actions by government, policy/regulatory bodies, or legal rulings that have material implications beyond a single firm.
- `other`: Any other material label describing the driver of the email that does not fit company or above categories.


---

Meeting requests are not automatically valuable. Include both important requests from credible insiders or analysts and noisy invitations, generic networking requests, low-value conference offers, and sales meetings.

## Email Content

Include realistic examples of:

- Earnings, guidance, estimates, and financial performance
- Details sell side analyst research pertaining to a target firm.
- Reporting and analysis on AI infrastructure, cloud spending, chips, and data centers
- Reporting and analysis on Product demand, pricing, supply chains, and competitive shifts
- Channel checks, expert calls, and differentiated sell-side research
- Regulatory, legal, macroeconomic, and government developments
- Industry events, meetings, analyst calls, and insider access
- Routine news, recurring reports, newsletters, and promotional outreach
- Sparse news pertaining to out of scope firms.

If allowed, do use the internet to find examples of the above to inform the generation of these artifacts.

Include emails that support and contradict existing theses, confirm expectations, introduce unexpected developments, or provide early but uncertain signals.

## Hard Negatives and Ambiguity

Noise must be as credible, detailed, and informative as useful content.

Include:
- Excellent research on unrelated companies with no clear target-company implications.
- Sophisticated analysis of target companies that merely repeats consensus.
- Detailed reports containing data but no thesis-changing conclusions.
- Routine analyst meetings that offer little differentiated access.
- Prestigious conference invitations that are irrelevant to the desk.
- Credible macro commentary with no plausible material effect on the target companies.
- Important-looking legal or government announcements that have little actual relevance.
- Emails that combine useful analysis with irrelevant material or promotional content.

Also include understated emails containing a single material insight, as well as relevant emails whose value depends on the desk's existing thesis or exposures.

Do not infer relevance from sender prestige, writing quality, email format, subject line, or length.

## Output Schema

Output valid JSONL: one JSON object per email, without surrounding commentary.

{
  "email_id": "synthetic_000001",
  "sender": "Fictional analyst at Example Securities",
  "sender_email" : "analyst@firm.com",
  "subject": "NVDA: Supplier checks indicate tightening capacity",
  "body": "Full realistic email content, including any research, bulletins, quoted material, or meeting details.",
  "triage": "thesis_relevant",
  "additional_labels": ["macro_government"],
  "affected_tickers": ["NVDA"],
  "human_attention" : bool,
  "reason": "Supplier constraints may limit shipments and challenge current revenue expectations."
}

### Field rules

- `triage`: Exactly one of the five primary labels.
- `additional_labels`: Any combination.
- `affected_tickers`: Any combination of `AMZN`, `NVDA`, `MSFT`, `AAPL`, and `GOOGL`. Use an empty array when no target company is meaningfully affected.
- `reason`: A few concise sentences for the classification based on the email's content. For emails with multiple labels, explain the primary triage decision; the additional labels should be evident from the content.
- Use fictional people, organizations, research, and data. Do not present fabricated information as real news or actual analyst research.
- Use real world examples as the basis for your generations.

Emails may contain complete articles, full analyst notes, multiple bulletins, forwarded messages, meeting invitations, or mixed content. Do not impose a body-length limit. Preserve enough detail to make the classification defensible.

A single email can contain multiple distinct items and qualify for multiple additional labels, but must have exactly one primary triage label.

## Dataset Distribution

For every 100 emails, target approximately:

- 10 `thesis_relevant`
- 15 `monitor`
- 10 `redundant`
- 35 `low_value`
- 30 `irrelevant`

These are approximate targets, not rigid quotas. Vary distributions across batches. Ensure that noisy meeting requests and valuable human-attention opportunities both appear.
Amongst relevent emails, make sure each target ticker is equally weighted and appear at roughly the saem rate.

## Quality Checks

Before emitting each example, verify:

1. The primary label reflects investment-thesis relevance and incremental information value.
2. `macro_government` is applied only when a systemic, legal, regulatory, political, or economic development has a plausible connection to the target companies or technology sector.
3. `human_attention` reflects a genuine need or opportunity for human engagement, not merely the presence of an invitation.
4. Relevant emails are not automatically classified as useful just because they mention a target company.
5. Unrelated-company research remains realistic and informative, even when classified as `irrelevant`.
6. `redundant` is used when information is already known and adds no meaningful insight, rather than as a catch-all for noise.
7. Multiple labels are applied when independently justified by the email content.
8. Tickers, reasons, and labels are consistent with the email body.
9. Examples are diverse and do not rely on superficial templates or keywords.

## Generation Task

Generate **[300] unique synthetic emails**. Output only the JSONL dataset.