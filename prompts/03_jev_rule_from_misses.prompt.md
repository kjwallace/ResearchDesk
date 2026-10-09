# Prompt 3: propose one new Jev rule from tuning misses

**Produces:** one candidate rule line for one file in `criteria/`
**Run:** during tuning, each time the criteria check shows a pattern of misses on one label.
**Model:** a large generative model.

**Limits on what you may paste in**

- Use emails from the **tuning set only**. Never paste a test-set email.
- Paste each email's corpus `triage` label and Jev's label. Never paste the corpus `reason` field.
- A rule from this prompt is a candidate. Keep it only if it passes the spec's keep rule: it fixes at least two fit-split emails, breaks none that were right, and signal accuracy on the validation split does not fall.

Fill in the four blocks marked `[...]`, then paste everything below the line into the model.

---

## Role

You are tuning classification criteria for an email triage system used by a technology desk that follows Amazon (AMZN), Nvidia (NVDA), Microsoft (MSFT), Apple (AAPL) and Alphabet (GOOGL).

A fast decision model called Jev labels each email using a criteria file per label. Each file has a fixed definition and a list of one-sentence rules. Jev sees one email at a time and nothing else. Below are emails that Jev labeled differently from the reference label. Your task is to propose **one** new rule that would fix the pattern they share, without breaking emails Jev already gets right.

## The criteria file to improve

```text
[paste the current file, for example criteria/monitor.md]
```

## The neighboring file most often confused with it

```text
[paste that file, for example criteria/low_value.md]
```

## Misses

Each block is one tuning email. "Reference" is the label it should have. "Jev" is the label it got.

```text
[Email 1 — Reference: monitor — Jev: low_value
Subject: ...
Body: ...]

[Email 2 — ...]
```

## Emails Jev labeled correctly, for contrast

```text
[paste 3 to 5 tuning emails with this label that Jev got right]
```

## How to work

1. Read the misses and name, in one sentence, what they have in common that the current rules do not cover. If they have nothing in common, say so and propose no rule.
2. Write one rule that addresses that pattern.
3. Test it in your head against the correctly labeled emails. If it would flip any of them, narrow the rule.

## What the rule must be

- One sentence, plain words, under 30 words.
- About a kind of information that can be judged from a single email.
- Neutral on whether the news is positive or negative.
- Free of any view: no stance, position, estimate or expected outcome.
- Blind to sender prestige, writing quality, length and formatting.
- General. It must not name a company, person, broker or event from the misses, and must not quote them.
- Different from every existing rule in both files.

## Output format

Return exactly this, and nothing else:

```text
Pattern: <one sentence>
File: criteria/<name>.md
Rule: - R<next number>: <one sentence>
Should fix: <email numbers>
Might break: <one sentence on the kind of email this rule could mislabel, or "nothing obvious">
```

If no single rule fits, return:

```text
Pattern: none
Reason: <one sentence>
```
