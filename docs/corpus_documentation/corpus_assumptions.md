# Assumptions

This document contains all the assumptions I identified when designing the synthetic email corpus.


## 1. What "relevant" means

| # | Assumption | Source | What to check |
|---|---|---|---|
| 1.1 | Labels are written for an informed analyst tasked with deep understanding of all firms. 
| 1.2 | "A reasonable investment thesis" means anything that can materially impact the performance of a given asset.
| 1.3 | "Consensus" is the colloquial sense of what the industry as a whole thinks.
| 1.4 | Emails come in random intervals and that when or the order in which emails arrive are not relevent.
| 1.5 | The labels do not say which thesis pillar or model driver an email bears on. 
| 1.6 | The relevence of an email should pertain to its factual information about an asset or a market and be independent of any individual thesis or position the firm already holds.

## 2. Volume and label mix

| # | Assumption | Source | What to check |
|---|---|---|---|
| 2.1 | The desk receives 300 emails in the day. 
| 2.2 | Labels split 10% thesis_relevant, 15% monitor, 10% redundant, 35% low_value, 30% irrelevant. These values are fabricated based on the vagueness of the casestudy prompt and tuned to create a demonstrative prototype more so that anythign else.
| 2.3 | 25% of the day is signal. This number is inflated in order to provide more examples for positive classifications or agentic analysis examples.
| 2.4 | Each ticker gets about the same number of signal emails, about six thesis_relevant each. 
| 2.5 | No more than 15% of noise emails name a target company. This was made for simpler evaluation of the synthetic data set.
| 2.6 | Meetings, newsletters and events are at least 20% of emails. 
| 2.7 | human_attention is true on 15 to 25 emails. 
| 2.8 | Macro, sector and government labels appear on about 10% of emails, and that relevent emails may actually contain information on the above instead of just individual tickers.
| 2.9 | Emails that affect several tickers at once are under 10%. 
| 2.10 | Positive and negative information about each company appears in roughly equal measure. This is done to demonstrate model behavior in both scenarios.

## 3. Label definitions

| # | Assumption | Source | What to check |
|---|---|---|---|
| 3.1 | Every email fits exactly one of five triage labels for simplicity. 
| 3.2 | human_attention is a separate true or false flag, emails either require a human response to read, or include information that is best parsed for investment based relevance before being presented to an analyst.
| 3.3 | Repeating consensus counts as redundant, as does repeating an earlier email that day. And that redundant emails both exist and are common.
| 3.4 | All sales invitations are noise for the pusposes of this desk.
| 3.5 | GOOGL is the only Alphabet ticker.

## 4. Sources and content

| # | Assumption | Source | What to check |
|---|---|---|---|
| 4.1 | Every person, broker, vendor, outlet and expert is fictional; the companies are real. 
| 4.2 | Sender prestige, writing quality, format and length carry no information about relevance. In real life this would be the case, but as all emails are fake this is not included. Sender relevency ratings and block/allows lists would be a core feature of a production version of this system.
| 4.3 | No email passes on confidential company information, production versions would considered privacy, data security, and regulatory compliance.
| 4.4 | No email contains instructions aimed at an AI system. 
| 4.5 | Emails are text only, in English, with no attachments, images or tables as files. Multi-modal handling would be a necessary part of the production version of this system.
| 4.6 | There are no internal emails from the portfolio manager or colleagues. 
| 4.7 | There are no reply threads, CC lists or distribution-list metadata for this demo.

## 5. Timing

| # | Assumption | Source | What to check |
|---|---|---|---|
| 5.1 | All emails arrive on one trading day, 05:30 to 19:00 US Eastern, heaviest before the open. 
| 5.2 | The date in which these synthetic emails were written and the received has no real significance and is just like any other trading day.
| 5.3 | The day is an ordinary day, not an earnings day for any of the five. 
| 5.4 | Nothing is remembered from before this day except what is already consensus. 
| 5.5 | All information received in the inbox is assumed to be accurate and only to be judged on its relevency, not accuracy.
| 5.6 | Urgent trading information (confirmations, margin calls etc) are not going to be in this inbox and nothing is critically time sensitive.


