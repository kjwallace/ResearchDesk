# Email triage and thesis suggestions

A prototype for a long/short technology desk covering **AMZN, NVDA, MSFT, AAPL and GOOGL**. An analyst receives 100 to 300 emails a day. Most are noise, a few bear on an investment thesis, and a few need a person to act. This system sorts every email by the attention it needs, then compares the relevant ones with the desk's book so the day collapses to a short list of recommendations and requests, each with its evidence. Everything else is provably safe to ignore: every email ends in exactly one label, with a written reason.

**All emails, brokers, positions, theses and estimates are synthetic. Nothing here is investment advice, and the system never sends mail.**

Related files: `SPEC.md` (the build spec), `DECISIONS.md` (choices the spec left open), `REVIEW.md` (generated drafts awaiting a person), `AI_transcripts/` (the AI sessions that built it).

## Principles that shape every stage

1. **Models recommend; the analyst decides.** No model makes an investment decision, writes to the book, does arithmetic or invents an ID. Code validates, computes and assigns every ID.
2. **Classification never sees the book.** The classifier reads one email and the desk's relevance criteria. It never sees positions, views, other emails or the repeat check.
3. **Every claim is quoted.** Any text a model attributes to an email must appear verbatim in that email's body (after collapsing whitespace), or it is dropped.
4. **Every change is traceable.** The book is a seed plus an append-only log of accepted changes, each tied to quoted email sections.
5. **Nothing is hidden silently.** Rejections, drops and stops all carry a reason that code composes; no model writes a reason.
6. **Untrusted input.** Email text is data. Models are told to ignore instructions inside it, and an email that tries to direct an AI or discloses inside information is quarantined before anything else reads it.

## How an email moves through the system

```
email ─► 2 repeat check ─► 3 classify (Jev) ─► 4 gate ─┬─► A attention note ─────────────┐
                                                       └─► 5 extract claims                │
                                                              ─► 6 analyze ─► 7 validate   ├─► 9 brief
                                                              ─► 8 merge and rank ─────────┘
```

Each stage is a function from files to files (`data/out/<set>/`, listed in `data/out/README.md`). Emails are processed in arrival order, because the repeat check only compares an email with earlier ones from the same day.

### Stage 2: repeat check (hint only, no generative model)

Each email body is embedded locally (chunked, mean-pooled, L2-normalised) and compared by cosine similarity with every earlier email of the day, together with a token-set similarity of the subjects. A pair is flagged as a potential repeat when content similarity reaches 0.85, or 0.75 when the subjects also match (similarity 0.6). The flag is a hint passed to the gate; it never decides a label on its own.

### Stage 3: classification by Jev, the heart of the triage

Jev is a typed question-answering classifier. For every email there is **one request carrying 14 questions**, and Jev returns a probability distribution for each, not just an answer:

| Question | Kind | What it produces |
|---|---|---|
| `triage` | choice over 5 labels | the label distribution (below) |
| `affects_AMZN`, `_NVDA`, `_MSFT`, `_AAPL`, `_GOOGL` | yes/no | probability the email meaningfully affects each company, in either direction |
| `human_attention` | yes/no | probability a person on the desk must act (reply, attend, decide) |
| `topic_macro`, `_sector`, `_government`, `_other` | yes/no | probability for each topic tag |
| `email_type` | choice over 11 types | display-only classification (research note, channel check, newsletter, meeting request, vendor pitch and so on); it never affects routing |
| `possible_mnpi`, `instructs_ai` | yes/no | the two **safety** questions: an insider disclosing or selling confidential facts, and text that tries to direct an AI |



**The five triage labels** are defined in the criteria files, whose definitions are fixed:

- `thesis_relevant`: new, specific information that would support, challenge or change a thesis on one of the five companies (a key actionable insight; specific, quantified evidence counts even before the company confirms it).
- `monitor`: credible but early, partial or unconfirmed signal about a target company, worth tracking but not enough to act on.
- `redundant`: careful analysis or news that only restates what is widely known.
- `low_value`: rumours, teasers, free samples, pitches and speculation with no evidence of their own.
- `irrelevant`: about companies outside the five unless the email states an effect on one of them.

Each criteria file may add at most 12 one-sentence rules to its definition. Rules never mention pillars, drivers or desk views, and the loader refuses a file that does. The criteria are versioned, and every cached model reply is keyed by that version, so editing a rule changes what runs.

Long emails are trimmed to the model's input limit; a truncated email that scores low is passed on its first chunk rather than silently stopped.

### Stage 4: label and gate (pure code)

The gate turns Jev's probabilities into decisions with fixed arithmetic. The order matters:

1. **Quarantine.** If either safety probability reaches 0.65, the email is quarantined and nothing further runs. Its body reaches no later model and no screen; only sender and subject are shown.
2. **Label.** The label is Jev's most probable one, with two adjustments: `monitor` needs P ≥ 0.70 to keep the label (otherwise the next most probable label is used), and if the repeat check flagged the email and the signal score is below the gate, the label becomes `redundant`, linked to the earlier email.
3. **Companies and topics.** A company or topic is listed when its probability reaches its own threshold (each is tuned separately).
4. **Human attention.** Flagged when the attention probability reaches its threshold.
5. **Gate.** The *signal score* is `P(thesis_relevant) + P(monitor)`. At or above the pass threshold the email goes on to analysis; below it, the email is stopped (and still carries its label and reason).

The reason string, for example `monitor 0.74; signal score 0.96 is below 0.97`, is assembled by code from those numbers.

**Thresholds** are defined once, in `src/triage_app/thresholds.py`. Starting values are overridden at run time by `tuned/thresholds.json`, which is fitted only on a separate tuning set (never on the test days): the pass threshold is the highest value that still passes every known thesis_relevant email and at least 95% of known-monitor emails (so the gate removes as much as it safely can), and the attention, company and topic thresholds are each swept for the best F1 on a fit split and checked on a held-out validation split.

### Stage A: attention notes (in parallel with 5 to 8)

Every email flagged for human attention gets one short note written by a model: which company it bears on, what opportunity it offers the desk, why it needs a person, the action (`reply`, `attend`, `decide`, `read`, `other`), a follow-up and any deadline the email states. A note explains the flag; it cannot remove it and never touches the book. Quotes are string-matched against the body, and a quote that fails is dropped (the note stays). Deadlines are only filled when the email states them.

### Stage 5: claim extraction

For emails that passed the gate, a model extracts atomic claims: company, metric, direction, value, period, whether the source is first-hand, and a verbatim quote. Claims failing the quote check are dropped and counted. If the email was flagged as a repeat, the earlier email goes along as context and only claims it did not already make are kept.

### Stage 6: the analysis agent

A tool-using agent decides what to do with one email's claims. It is given the claims and the statements of the candidate pillars (the pillars of the companies in the claims, plus pillars the read-through links connect to them), and it may call at most three skills:

- **alter existing thesis**: for each candidate pillar, say whether the claims support it, contradict it, or have no direct bearing; rate its relevance and strength (1 to 3); optionally propose a figure for a linked assumption that the email states. This skill also sees Jev's label for the email.
- **revise projections**: when a claim states a forward figure (EPS, revenue, operating income, target price, or a driver such as a segment's growth or the margin), compare it with the book.
- **spawn new thesis**: only when no existing pillar fits or the claims raise a debate no pillar mentions; proposes a new pillar and the drivers it would rest on.

A "skeptical reading" applies when every email behind a suggestion is labeled `monitor`: strength is capped at 1 and the relevance bar is raised. The agent never tells anyone to buy, sell or resize; it only says how information may alter a thesis, revise a projection or warrant a new one. Code, not the agent, collects the skills' results into suggestions and assigns their IDs.

### Stage 7: validation (pure code)

Every suggestion passes a fixed sequence of checks; the first failure rejects it with a one-line reason:

1. Unknown items: claim, pillar, company or driver IDs that do not exist or are out of scope.
2. Quote mismatch: a supporting section not found verbatim in the email.
3. Weak match: relevance to the pillar below the minimum.
4. Duplicate thesis: a "new" pillar whose embedding is too close to an existing one.
5. Projection checks: wrong fiscal period, a number that appears in none of the quotes, a stated value implausibly far from the book's, or a driver figure outside its bounds.

Softer outcomes keep the suggestion but change it: a monitor-only suggestion is capped at strength 1, a figure that cannot be tied to a quote or sits outside bounds is dropped, and a suggestion with no linked email labeled thesis_relevant or monitor is marked "second look". A number the email never states cannot reach the analyst.

### Stage 8: merge and rank (pure code)

Suggestions on the same pillar and stance merge into one (highest strength wins, evidence is pooled); opposite stances on one pillar stay separate and are shown as contradicting evidence. Near-identical new-thesis candidates merge, and projection changes merge when company, metric, period and value match. The list is ordered by position size, then strength, then signal score.

### Stage 9: the morning brief

Deterministic assembly: each email appears where it belongs (a suggestion card, "relevant with no link to the book", the audit list, or the quarantine list), requests needing a person are overlaid as "needs attention", and a small alert budget covers met "wrong if" tests on large positions and the most urgent attention flags.

## The book and the analyst's actions

The book is five company models plus theses. Each thesis has a stance, size, conviction, pillars (each with a "wrong if" condition and evidence) and linked drivers (growth rates, margins, capex) with desk and consensus values. Projections are computed by a pure function: revenue from line-by-line growth on the latest reported base, operating income from margin, EPS after tax and diluted shares, target price from a multiple.

**Current state is never stored.** It is always recomputed from the seed files plus an append-only change log for the session. The analyst can accept a suggestion (logging evidence on a pillar, adding a pillar, and applying the figures it links to linked assumptions, which recompute EPS and target price), dismiss it, edit it before accepting, set conviction, or undo. Accepting one side of a contradicting pair dismisses the other. Accepted and dismissed items leave the morning brief. Session changes reset when the session ends. Models never write to the book.

## The web app

Server-rendered (FastAPI, Jinja and HTMX) screens, all labeled synthetic:

- **Inbox:** every raw email with its label, company and topic tags, read/unread state, filter tabs, and a field-aware search (`from:`, `subject:`, `body:`, `company:`, `label:`, `topic:`, `is:`, `after:`, `before:`, quoted phrases, `-exclusions` and `OR`).
- **Morning Brief** and **Summaries:** the day's ranked suggestions and a per-company summary of the day's relevant emails.
- **Review:** work through suggestions one by one, with quoted evidence, what accepting would change, and side-by-side comparison for contradicting pairs.
- **Needs attention:** requests that need a person, ordered by deadline or relevance, with live counts.
- **Book** and company pages: positions, projections against consensus, accepted evidence, and editable pillars and assumptions.
- **Under the hood:** audit of every email not in the brief, the criteria, a live route that runs a pasted email through the whole pipeline, and a monitor of tokens and latency per stage.

## How the pipeline is evaluated and tuned (design, not results)

The corpus is synthetic and carries ground-truth labels beside each email (label, companies, topics, human attention, email type). The labels are the only reason the evaluation can exist, so the design is mostly about keeping them out of everything else.

- **Label isolation.** The corpus loader splits each row into an `Email` (what the pipeline sees) and an `EmailLabel`. Only the loader, the scoring code and the tuning code may read a label; no corpus field, including its free-text reason, can reach a prompt. Generation fields (`email_type`, `systemic`, `angle`, `day`) are label-side too.
- **Three sets, three jobs.** Two test days (`day_1`, `day_2`) are scored and never tuned on. A separate tuning set, generated outside the build, is the only data thresholds and criteria rules are fitted to. The tuning set is split once, by a fixed seed, into a fit share (two thirds of each label) and a validation share, so a threshold is chosen on one and checked on the other.
- **Thresholds are fitted by code, not by hand.** `evals/tune.py` sweeps each probability threshold against the fit split and writes `tuned/thresholds.json`. The objective for each is chosen to match its job: the pass threshold is a *recall constraint* (never lose a thesis-relevant email, lose at most 5% of monitor emails) maximised for reduction; attention, company and topic thresholds maximise F1. Quarantined emails never pass, and a truncated email always passes, so neither distorts the sweep. Repeat-check thresholds are deliberately not swept, because the corpus has no ground truth for "repeat of which email".
- **Criteria are edited against evidence.** `evals/criteria_check.py` reruns classification and the gate on the tuning set under the current criteria files, refits thresholds in memory only, and prints the label measures before and after on both splits with every email whose label changed. Each criteria version's labels are stored, so the next version can list exactly what it relabelled. A rule is added only if it helps validation, not just the fit split.
- **Measures follow the pipeline's decisions.** Gate recall and monitor recall at the gate measure the cost of stopping an email; gate reduction measures the saving; signal accuracy scores the three-way decision the gate actually makes (signal, redundant, noise) while triage accuracy scores the exact five-way label with a confusion table; company tagging uses micro F1; human attention is split into precision and recall because missing a request and flagging a pitch have different costs.
- **A quarantined email counts as a miss on every label measure**, so safety never improves a score by hiding failures.
- **Faithfulness is enforced, then measured.** Quote faithfulness is 100% by construction because code drops any quote that is not verbatim; the measure exists to prove the guard works end to end. Stray suggestions (a suggestion whose only linked emails are redundant, low-value or irrelevant) are listed individually for review.
- **Human review is built in.** The scorer writes review sheets for attention notes and suggestions, one row per item with yes/no checks. A person fills them, and the sheet is then frozen and read back, so model-written text is judged by a person, not by another model.
- **Honest about what it proves.** Labels and emails come from the same generator, so the scores show internal consistency, not performance on real mail. Targets are proposals and are shown beside each measure.

## Safeguards in one place

- Labels from the corpus never reach a model; only the loader and the scoring code read them.
- Quarantined email bodies reach no model and no screen.
- Every quote is verified against the email body; every ID is assigned by code.
- Model calls and embeddings are cached on disk (keyed by program version, criteria version and input), so reruns are free and reproducible.
- Models are called at temperature 0, with retries on rate limits and parse failures.
- Thresholds live in one file and are tuned only on the tuning set.
- Every generated draft (seed numbers, criteria, skills, instructions, tools) is committed and listed in `REVIEW.md`.