# Prompt 2: generate the Jev criteria files

**Produces:** the 11 files in `criteria/`
**Run:** once, to create the starter rules. After that, rules are added one at a time with prompt 3 or by hand.
**Model:** a large generative model.

Paste everything below the line into the model.

---

## Role

You are writing classification criteria for an email triage system used by a technology desk at a long/short equity fund. The desk follows five companies: Amazon (AMZN), Nvidia (NVDA), Microsoft (MSFT), Apple (AAPL) and Alphabet (GOOGL).

A fast decision model called Jev reads each email once and answers typed questions about it. Jev does not reason at length. It makes the kind of judgment a knowledgeable person makes in a second, and it is told only what the criteria files say. Your task is to write those files: one per label, each with a fixed definition and a short list of rules.

## How the files are used

- Code loads each file and passes its definition and rules to Jev as the criteria for one answer option or one yes/no question.
- Jev sees one email at a time: sender, sender address, subject and body. It sees no other email, no earlier day and nothing about the desk's positions.
- People on the desk read these files to audit why an email got its label, and add rules over time. Clarity matters more than coverage.

## The labels and their definitions

Copy each definition into its file word for word. Do not edit, shorten or extend a definition.

**Triage labels (one question with five options)**

- `thesis_relevant`: New, specific information that would support, challenge or change a reasonable investment thesis on a target company: its earnings expectations, competitive outlook, valuation or a trading decision.
- `monitor`: A credible emerging signal or developing trend that could affect a thesis on a target company, but whose implications remain uncertain or unconfirmed.
- `redundant`: Information already known that adds no meaningful incremental insight. This includes later emails that repeat an earlier email in the same day.
- `low_value`: Some connection to a target company, but insufficient materiality, differentiation or evidentiary support to merit attention.
- `irrelevant`: No meaningful investment connection to the target companies.

**Human attention (one yes/no question)**

- `human_attention`: The email contains a request, meeting or opportunity that needs a person on the desk to act, from a credible and valuable source: for example a small-group meeting with company management, a call offered by a differentiated analyst or industry expert, or a time-sensitive question from a trusted contact. All sales invitations, generic networking requests and mass conference promotions do not qualify.

**Topic labels (four yes/no questions)**

- `macro`: Broader macroeconomic events, data or trends, such as inflation, rates, currency or global demand.
- `sector`: Developments that affect the sector or industry and are not limited to one target company.
- `government`: Actions by government, policy or regulatory bodies, or legal rulings, with implications beyond a single firm.
- `other`: Any other material driver that fits none of the above.

**Affected tickers (five yes/no questions, one file)**

- `affected_tickers`: A target company is listed when it is meaningfully affected by the email's content. A company mentioned only in passing is not affected. Use GOOGL for Alphabet and Google.

## What a rule is

A rule is one sentence that helps Jev apply a definition to a borderline email. Write **three or four rules per file**, numbered R1, R2 and so on.

Every rule must be:

- **Judgeable from one email.** Jev cannot compare emails or look anything up. A rule may refer to what is widely known or consensus, but never to "an earlier email".
- **About a kind of information.** For example: company guidance, a reported figure, a channel check, a ruling, an invitation type. Never about a view. Do not say or imply that the desk is long or short anything, expects any outcome, or prefers good or bad news.
- **Neutral on direction.** Positive and negative information are treated alike.
- **Blind to presentation.** No rule may reward sender prestige, writing quality, length, formatting or a dramatic subject line. At least one rule in `thesis_relevant.md` and one in `low_value.md` must say so explicitly.
- **One sentence, plain words, under 30 words.**

Rules across the five triage files must draw the boundaries between neighbors, because those are where Jev will err:

- `thesis_relevant` versus `monitor`: specific and confirmed, versus early or unconfirmed.
- `thesis_relevant` versus `redundant`: new information, versus careful analysis that restates what is already consensus.
- `monitor` versus `low_value`: a credible signal with a plausible path to mattering, versus a weak or unsupported one.
- `low_value` versus `irrelevant`: some real connection to one of the five, versus none.

Cover these known traps at least once across the files:

1. Excellent research on a company outside the five with no stated read-through.
2. Detailed, data-heavy reports that reach no conclusion about a target company.
3. A short, informal email that contains one material first-hand fact.
4. Prestigious conferences and routine analyst meetings that offer no differentiated access.
5. Credible macro or legal commentary with no plausible effect on the five.
6. An email that mixes one useful item with promotional material.
7. A target company named in passing in an email about something else.

## What a rule must not contain

- A stance, a position, an estimate, a price target or a thesis.
- An ID of the form `TICKER.p1` or `TICKER.something_growth`.
- The name of a real person, broker, publication or fund.
- An instruction addressed to an AI system, or anything about prompts or models.

## Output format

Return 11 files and nothing else. Start each with a line `=== criteria/<name>.md ===`. Use exactly this layout:

```text
# <label>

## Definition
<the definition, word for word>

## Rules
- R1: <one sentence>
- R2: <one sentence>
- R3: <one sentence>
```

File names: `thesis_relevant.md`, `monitor.md`, `redundant.md`, `low_value.md`, `irrelevant.md`, `human_attention.md`, `macro.md`, `sector.md`, `government.md`, `other.md`, `affected_tickers.md`.

## Checks before you answer

1. Eleven files, each with the definition unchanged and three or four rules.
2. Every rule can be applied to a single email with no outside lookup.
3. No rule states or implies a view, a direction or a position.
4. No rule rewards prestige, polish or length.
5. Each of the seven traps is covered by at least one rule.
6. No two rules in one file say the same thing.
