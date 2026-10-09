# Email triage and newsflow redesign: plan

Oct 8, 2026 · @Kelvin

This is a build spec to be used by a coding agent. The prototype classifies each of 300 synthetic emails by how much attention it needs, then compares the relevant ones with a five-company book and suggests changes for an investment analyst to decide on.

## Overview

The design is settled and nothing is built yet. The hand-off is this spec, the corpus prompt and six generation prompts. The corpus, the seed files, the criteria files and all code are still to be produced.

### Method

&#91;embedded content: proposed method · corpus and book in, brief and evaluation out\]

Jev reads every email against the desk's relevance criteria and never sees the book. Two pathways follow the gate: attention notes for emails that need a person, and the analysis agent for emails that bear on a thesis. The analyst's decision is the only path by which the book changes.
The purpose of this is to automatically triage incoming emails for relevent research insights, identify those emails, and then parse research insights from the to be presented to an analyst.

## Start here

Build four things, in this order of importance:

1. **A pipeline** that reads 300 synthetic emails and emits redundancy flags, triage labels, attention notes and thesis suggestions.
2. **A state layer:** criteria text files that users can read and extend, plus a driver model and a thesis for each of five companies, changed only when the analyst accepts a suggestion. This layer will also analyze and provide insight based on the emails.
3. **A web app:** morning brief, suggestion review, company pages, criteria viewer, audit view, raw inbox and eval page. This is to be done last.


### Inputs and who provides them

| Input | Lands in | Provided by |
| --- | --- | --- |
| This spec | `SPEC.md` | Supplied: a Markdown export of this document. The agent reads it whole before step 0. |
| Corpus prompt | `docs/corpus_documentation/synthetic_data_prompt.md` | Supplied. Use only the text above its cut line; the appendix below it is for human reviewers. |
| Generation prompts | `prompts/` | Supplied: six prompts and a README that gives their order. |
| Test corpus: 600 emails, two days of 300 | `data/corpus/day_1/emails.jsonl`, `data/corpus/day_2/emails.jsonl` | Supplied, generated from the corpus prompt. The agent never generates or edits it. |
| Tuning corpus | `data/corpus/tuning/emails.jsonl` | Being generated separately from the corpus prompt. The agent never generates or edits it. |
| Book: stances, sizes, pillars, driver IDs, links | `data/seed/` | This spec, under "The book" and "State". Copy them exactly. |
| Book: driver values, consensus, bounds, multiples | `data/seed/models_draft.json` | The agent runs `prompts/01_book.prompt.md`; a person reviews the result. A script merges the draft into `models.json`. |
| Book: base revenue, tax rate, share count | `data/seed/models.json` | The agent takes them from each company's latest annual report. |
| Criteria starter rules | `criteria/*.md` | The agent runs `prompts/02_jev_criteria.prompt.md`; a person reviews the result. |
| Skills, stage instructions, tool definitions | `skills/`, `instructions/`, `tools/` | The agent runs prompts 04, 05 and 06; a person reviews the results. |
| API keys | `OPENROUTER_API_KEY` for every generative model call; `TYPESAFE_API_KEY` for Jev, which OpenRouter does not serve. The Anthropic API is never called directly. | Supplied in `.env`, which is never committed. Never printed or logged. |
| Deploy host | Outside the repo | Supplied by the reviewer, with its credentials. |

Every generated file is committed as a draft and listed in REVIEW.md before the pipeline is tuned on it.

### Where a person is needed

The agent never waits for a review. It stops only where this table says so.

| When | What the person does | If the person is absent |
| --- | --- | --- |
| After step 0 | Reads the drafts listed in `REVIEW.md`: book numbers, criteria, skills, instructions and tools. | Continue on the drafts. `REVIEW.md` records which were unreviewed when tuning ran. |
| Before tuning | Supplies the tuning corpus at `data/corpus/tuning/emails.jsonl`. | Build and test everything else on the fixtures and both test days at starting values, and report that tuning is pending. |
| After step 6 | Fills in and commits the two review sheets. | The eval page shows the three hand reviews as pending. |
| At step 7 | Supplies a host and its credentials. | Deliver the container and the command that runs it locally. |
| After step 7 | Records the screencast and writes the summary. | Nothing in the build waits on this. |

The final run is one pass of the pipeline and the eval script over each test day (`day_1`, then `day_2`), made after tuning is frozen.

Two failures have their own rule. If the TypeSafe packages do not install, move them to an optional dependency group so `uv sync` passes, and continue with a fake client. If both Jev routes fail with a valid key, stop and report.

Three more cases have a default. The lead runs each generation prompt with the analysis model through OpenRouter (`scripts/run_generation_prompt.py`), or in a fresh subagent, giving it only the text below the prompt's line, and notes the model in `REVIEW.md`. If DSPy itself does not install, call the model SDKs directly behind the same module interfaces. If the pages under "Read first" cannot be reached, follow the sketch under "Calling Jev".

### Fixed decisions

| Decision | Choice |
| --- | --- |
| Coverage | Amazon (AMZN), Nvidia (NVDA), Microsoft (MSFT), Apple (AAPL), Alphabet (GOOGL) |
| Corpus | Two days of 300 synthetic emails each from the corpus prompt, labeled without reference to any book |
| Book | A fictional example book in the seed files, kept separate from the corpus |
| Classification | Jev classifies every email by the attention it needs. It never sees the book. |
| Relevance criteria | Plain text files, one per label, hold the criteria Jev applies. Users can read, audit and add rules. They hold kinds of information, never views. |
| Redundancy | Every email is embedded and compared with every earlier email; a close match is flagged as potentially redundant |
| Attention pathway | Emails that need a person get a note with a summary, the reason and the action asked for |
| Analysis agent | A stronger model with two skills: how new information may alter an existing thesis, and whether it should spawn a new one |
| Who decides | Only the analyst. Models recommend and never make an investment decision. |
| Language | Python for everything, including a server-rendered UI; no TypeScript |
| Surface | Morning brief plus alerts; the inbox is untouched |
| Runtime | Pipeline output is precomputed and committed; one route runs live |
| Build time | 2–3 days |

### Definition of done

- From a clean clone, one command runs the pipeline over the corpus and writes its outputs.
- Every email has one triage label and a reason, and every flagged repeat points to the earlier email it resembles.
- Every email flagged for human attention has a note with a summary, a reason and the action asked for.
- Every suggestion shows its linked emails, and every quoted section exists verbatim in its source email.
- Accepting a thesis suggestion logs the evidence, and updating a linked assumption recomputes EPS and target price.
- Adding a rule to a criteria file and running the criteria check shows which emails changed label and how the scores moved.
- Every email not shown in the brief appears in the audit view with a reason.
- The eval page reports the pipeline's scores against the corpus labels.
- Every run writes run-level token use and latency per stage and per model, and a short summary of the run; the Monitor page shows the former.
- The deployed URL works from a clean browser, and reset restores the seed state.

## Why this exists

A technology analyst at a long/short equity fund receives 100 to 300 emails a day. Most are noise, a few bear on a thesis, and a few need a person to act. Today that sorting is done from subject lines, and what is learned rarely reaches the thesis record.

> How might we sort every inbound email by the attention it needs, then compare the relevant ones with the desk's book, so each day collapses to a few recommendations and requests, each with its evidence, and everything else is provably safe to ignore?

### Design rules to preserve

When the spec is silent, these seven rules decide.

1. **Recommendations, not summaries.** Reading a relevant email produces a suggestion about a named thesis, with the email sections that support it, or a stated reason for none.
2. **Models recommend; the analyst decides.** No model makes an investment decision, writes to the book, does arithmetic or invents an ID. Code validates and computes.
3. **Classification never sees the book.** Jev gets one email and the desk's relevance criteria. It never gets positions, views or other emails.
4. **Every change is traceable.** State is the seed plus a log of accepted changes, each tied to quoted sections of emails.
5. **Nothing is hidden silently.** Every email ends in exactly one triage label, with a reason.
6. **Read-only and draft-only.** The system never sends mail and never touches the inbox.
7. **Synthetic is labeled.** The companies are real; the emails, brokers, positions, theses and estimates are not, and every screen says so.

## Data flow

Each email passes through the stages below, shown in the flow chart under "Overview". Code checks for repeats and Jev classifies every email. Two separate pathways follow: attention notes for emails that need a person, and the analysis agent for emails that bear on a thesis.

### Stages

| # | Stage | Input to output | How | Model |
| --- | --- | --- | --- | --- |
| 1 | Load | Corpus file to emails | The corpus loader reads `data/corpus/<set>/emails.jsonl`, drops every label and keeps body, sender, subject and the other input fields exactly as written. No output file: every stage, the evals and the app read the emails this way. | None |
| 2 | Check for repeats | Email to a redundancy record, for flagged emails only | Embed every email and compare it with every earlier email by cosine similarity. Subject similarity is a second signal. | Embedding model |
| 3 | Classify | Email to a triage record | One Jev request per email with 14 typed questions, using the desk's relevance criteria. | Jev |
| 4 | Label and gate | Triage and redundancy records to a triage label and a gate decision | Thresholds and the redundancy flag, applied by code. | None |
| A | Write attention notes | Email flagged for human attention to an attention note | Summary, why it needs a person, the action asked for and any deadline. Quoted sections are checked by string match. | Small generative |
| 5 | Extract | Passed email to claims | Schema-constrained call. Each quoted section is checked by string match; failures are dropped and counted. | Analysis model |
| 6 | Analyze | Claims plus the candidate pillars, to suggestions or a no-change reason | The analysis agent calls a skill for each question: alter an existing thesis, or spawn a new one. | Analysis model |
| 7 | Validate | Suggestions to valid, or rejected with a reason | ID exists, quote matches, figure within bounds, new thesis is not a duplicate. | None |
| 8 | Merge and rank | Valid suggestions to one suggestion per thesis | Suggestions on the same pillar and stance merge, keeping every linked email and section. | None |
| 9 | Deliver | Labels, notes and suggestions to brief, alerts and audit view | Deterministic assembly. | None |

Stage A runs alongside stages 5 to 8 and never touches the book. An email can take both pathways.

After stage 9 the analyst accepts, edits or dismisses each suggestion. Only an accepted suggestion changes the book, through the change log.

A verify agent sits outside the main line. On request it checks one suggestion against cached filings and the change log, and returns a cited verdict.

The verify agent's tools are built from `tools/verify_agent.json`. Its filing search ranks paragraphs of the saved annual reports by embedding similarity, using the stage 2 model, and returns nothing when no report was saved. Its log search matches words in the session's change log.

### Redundancy check

Stage 2 runs before classification and keeps a cache of the day's subjects and vectors. For each email, in arrival order:

1. **Embed the email.** Split the body into chunks that fit the embedding model's input limit, embed each chunk, and take the normalized mean as the email's vector.
2. **Compare content with every earlier email.** Take the highest cosine similarity and the email it belongs to.
3. **Compare subjects.** Normalize this email's subject and that earlier email's subject, and score their token-set similarity from 0 to 1.
4. **Flag.** The email is flagged as potentially redundant when content similarity reaches the content threshold, or reaches a lower threshold with a matching subject. It points to the most similar earlier email.
5. **Add the subject and vector to the cache,** whether or not the email was flagged.

Four rules govern the check:

- **The flag is a hint, not a verdict.** Stage 4 turns it into a redundant label only when the email's signal score is below the pass threshold.
- **A flagged email whose signal score clears the gate still passes.** The earlier email travels with it, and the analysis model keeps only claims the earlier email did not make. A repeat that carries one new insight is not lost.
- **Thresholds are fixed at 0.85 for content alone, or 0.75 with a subject score of 0.6 or more.** The corpus carries no `redundant_of` labels, so the check runs at run time with these values and is not swept.
- **The check finds same-day repeats only.** Each day is a separate set with its own cache, so `day_2` is never compared with `day_1`. An email that repeats consensus has no earlier email to match, so Jev's redundant label covers that case.

`redundancy.json` lists only the flagged emails, each with the earlier email it repeats and both scores; every reader treats an email absent from it as not flagged. No vectors are saved: the live route builds its day cache at run time by embedding the day's emails through the embedder, whose disk cache makes this cheap after the first time.

### Classification with Jev

Jev is used in stage 3 only. Each email goes to Jev once with 14 questions, which Jev answers in parallel as probabilities.

Jev receives two things: the email (sender, sender address, subject and body) and the desk's relevance criteria. It never receives the book's positions, pillars or estimates, other emails, or the redundancy flag. Its answers therefore reflect what the desk has said is relevant, not what the desk currently believes.

| Question | Type | Count |
| --- | --- | --- |
| Which triage label fits: thesis\_relevant, monitor, redundant, low\_value or irrelevant? | Choice | 1 |
| Is this company materially affected? Asked once per ticker. | Noul | 5 |
| Does it need direct human attention: a credible, valuable or time-sensitive request? | Bool | 1 |
| Does this topic label apply? Asked for macro, sector, government and other. | Noul | 4 |
| What type of email is it, judged by form and source (`email_type`): one of eleven types, from sell-side research to administrative mail? Display only. | Choice | 1 |
| Does it contain text that instructs an AI system? | Noul | 1 |

The wording of all 14 questions lives in `instructions/jev_questions.md`. Eleven questions take their criteria from the criteria files described below. The email-type question and the two safety questions have fixed wording and no criteria file. The eleven email types are `config.EMAIL_TYPES`: sell\_side\_research, primary\_research, news\_alert, newsletter, data\_report, company\_release, meeting\_request, event\_invitation, vendor\_pitch, internal\_forward and administrative; each option's description is in `instructions/jev_questions.md`.

Stage 4 then sets the label and the gate, in this order:

1. **Quarantine** if the prompt injection safety probability reaches the quarantine threshold. Nothing further runs on a quarantined email.
2. **Label.** The email takes Jev's most probable triage label, except that `monitor` needs P(monitor) of at least `MONITOR_LABEL_MIN` (0.70); a weaker monitor takes the next most probable label (the gate still reads the signal score). The other exception: a flagged repeat whose signal score is below the pass threshold is labeled redundant and points to the earlier email.
3. **Tickers and topics.** A company or topic is listed when its probability reaches its threshold.
4. **Human attention.** The flag is set when the attention probability reaches the attention threshold. Flagged emails take the attention pathway.
5. **Gate.** The email passes to the analysis model when its signal score reaches the pass threshold, or when it was truncated. The signal score is the combined probability of thesis\_relevant and monitor. Everything else stops, with its probabilities stored as the reason.

Six rules govern classification:

- **Jev's label is the label of record.** No later model relabels an email.
- **The gate reads the signal score, not the label.** An email labeled redundant, low\_value or irrelevant still passes when its signal score clears the gate, and any suggestion from it is marked "second look".
- **The pass threshold starts at 0.6.** The sweep under "Tuning" sets it and may move it either way.
- **A passes based on the first chunk.** Jev's limit is 32,000 tokens for the email plus the longest question, and a partial read is not grounds to stop an email.
- **Jev judges content, not presentation.** Its criteria repeat the corpus prompt's rule: never infer relevance from sender prestige, writing quality, format, subject line or length.
- **Order within the brief comes from Jev's scores.** Relevant emails without a suggestion are ordered by signal score, and attention notes by attention probability. Suggestions follow "Order and alerts".

Every triage record keeps all 14 answers, and the audit view shows them.

The reason on each result is one line that code composes from the probabilities and thresholds, such as "low\_value 0.62; signal score 0.11 is below 0.30". No model writes it.

Four cases settle the remaining fields of a result:

- **Quarantined.** The label is empty, the ticker and topic lists are empty, and the attention flag is false. The signal score is still stored, and the reason names the safety question and its probability.
- **Redundant by Jev alone.** `redundant_of` is empty and `decided_by` is `jev`.
- **Redundant by the check.** `decided_by` is `redundancy_check` only when the check changed the label. `redundant_of` is then the nearest earlier email.
- **Passed.** The reason names the signal score and the threshold it cleared, or says the email was truncated.

A quarantined email's body reaches no model after stage 3 and no screen. Stage 5 leaves out an earlier email that was quarantined, and the Inbox shows only its sender and subject.

### Relevance criteria

The criteria Jev uses are plain text files, one per label. Anyone on the desk can read them, audit them and add a rule. The corpus labels never change: the files tune how Jev applies those labels, and every rule is measured against them.

| Files in `criteria/` | Feed this Jev question |
| --- | --- |
| `thesis_relevant.md`, `monitor.md`, `redundant.md`, `low_value.md`, `irrelevant.md` | The five options of the triage question |
| `human_attention.md` | The human-attention question |
| `macro.md`, `sector.md`, `government.md`, `other.md` | The four topic questions |
| `affected_tickers.md` | The five company questions |

Each file has a fixed definition and a list of rules. The rules below are illustrations.

```text
# thesis_relevant

## Definition
New, specific information that would support, challenge or change a reasonable
investment thesis on a target company: its earnings expectations, competitive
outlook, valuation or a trading decision.

## Rules
- R1: Company guidance or a reported figure that differs from consensus counts.
- R2: First-hand information, such as a channel check, counts even when the
      email is short or informal.
- R3: News on a company outside the five counts only when the email states the
      read-through to one of them.
- R4: Sender prestige, length and formatting are not evidence of relevance.
```

The files are used in five steps:

1. **Load.** Code reads every file, checks its format and computes one version hash for the set.
2. **Compose.** Each label's definition and rules become the criteria for that option or question in the Jev request. Nothing else is added.
3. **Record.** Every triage record stores the version hash, so any label can be traced to the exact text that produced it.
4. **Tune.** Add or reword a rule, then run the criteria check. It reruns Jev on the tuning set, refits the thresholds, and prints scores before and after for each label, with the emails whose label changed. "Before" is the previous version's entry in the history file. The check appends a new entry and never writes the tuned thresholds.
5. **Keep or revert.** A rule stays when it passes the keep rule under "Tuning". The files' history in git is the audit trail.

Five rules govern the files:

- **Labels are fixed.** Label names and definitions come from the corpus prompt and are not edited. Tuning happens only under "Rules".
- **Rules describe kinds of information, never views.** Stances, pillars and estimates belong to the book. The load fails if a file names a pillar or driver ID.
- **Rules are tuned on the tuning set only.** Test-set scores are reported for the committed files and are never used to choose a rule.
- **Files stay short:** at most 12 rules a label, one sentence each. Jev makes snap judgments, and long criteria blur them.
- **The app shows the files as written.** The Criteria screen displays each file and its history, and the audit view links every email to the version in force.

### Calling Jev

Stage 3 can reach Jev by two routes. Step 0 runs one email through both and records the choice in `DECISIONS.md`.

| Route | Call | Choose it when |
| --- | --- | --- |
| DSPy | `dspy.experimental.TypeSafe("jev-latest")` bound to one `dspy.Predict` signature with 14 top-level `Noul` and `Choice[...]` outputs | The criteria text can be set on the predictor's fields at run time. ReAnchor then fits the yes/no thresholds. |
| TypeSafe SDK | `TypeSafeClient().system_one(state=..., questions=...)` | The DSPy route cannot take criteria at run time. The code sweep then fits every threshold. |

The SDK route maps directly onto the criteria files. This sketch follows the TypeSafe documentation; confirm the names against the pinned SDK.

```python
from typesafe_sdk import Choice, Noul, TypeSafeClient

TRIAGE = ["thesis_relevant", "monitor", "redundant", "low_value", "irrelevant"]

def ask_jev(email: Email, criteria: CriteriaSet, wording: dict[str, str]):
    """wording maps a question ID to its sentence in instructions/jev_questions.md."""

    def text(label: str) -> str:          # definition plus rules, as written
        c = criteria.labels[label]
        return "\n".join([c.definition, *(f"{r.id}: {r.text}" for r in c.rules)])

    questions = {
        "triage": Choice(instructions=wording["triage"],
                         criteria={label: text(label) for label in TRIAGE}),
        "human_attention": Noul(instructions=wording["human_attention"],
                                criteria=text("human_attention")),
        "affects_NVDA": Noul(instructions=wording["affects_NVDA"],
                             criteria=text("affected_tickers")),
        # ...the other four tickers, topic_macro, topic_sector, topic_government,
        # topic_other, email_type, possible_mnpi and instructs_ai: 14 in all
    }
    state = {"sender": email.sender, "sender_email": email.sender_email,
             "subject": email.subject, "body": email.body}
    with TypeSafeClient() as client:
        answers = client.system_one(state=state, questions=questions).answers
    return answers    # answers["triage"].probabilities, answers["human_attention"].noul
```

Eight facts the build depends on:

- **Read first.** The DSPy 3.4.0 release notes and the TypeSafe Primitives page, both under "Sources".
- **Pins.** `dspy[typesafe]==3.4.0`, `typesafe-sdk>=0.6.0,<1.0.0`, and Pydantic 2.11 or later.
- **Answers.** The SDK returns `probabilities` for a Choice and `noul`, the probability of yes, for a Noul. DSPy exposes them as `.probabilities` and `.probability`.
- **Criteria.** A Choice takes a map from option to text. A Noul takes one optional text that says what yes and no mean. Each text is a file's definition and rules, as written.
- **One file, five questions.** `affected_tickers.md` supplies the criteria for all five company questions. The question wording names the company.
- **Thresholds stay local.** Jev returns probabilities and code applies the thresholds. In DSPy a threshold sits on the predictor, as in `predictor.fields["human_attention"] = {"threshold": 0.3}`.
- **ReAnchor.** `ReAnchor(metric=...).compile(program, trainset=fit, valset=validation)` returns a tuned copy and needs caching on.
- **Trimming.** When the email plus the longest question would exceed 32,000 tokens, stage 3 keeps the start of the body and sets `truncated`. Count four characters as one token unless the SDK offers a counter.

### Attention pathway

Emails that Jev flags for human attention take a separate pathway from the thesis analysis. A small generative model writes an attention note, so the analyst can act without reading the whole email.

Each note holds:

- a summary of the email in two sentences;
- the reason it needs a person, in one or two sentences;
- the action asked for, such as reply, attend or decide;
- the deadline, if the email states one;
- the quoted sections that support the note.

Three rules govern the pathway:

- **Jev alone decides which emails are flagged.** The note explains the flag and cannot remove it.
- **A note describes and explains.** It never recommends an investment action and never touches the book.
- **Every quoted section is checked against the email by code.**

### Analysis agent

Stage 6 is an analysis agent with a narrow job: say how new information may alter an existing thesis, or whether it should spawn a new one. It does nothing else. Each job is a separate skill the agent calls.

| Skill | Question it answers | What it is given | What it returns |
| --- | --- | --- | --- |
| Alter an existing thesis | Does this information support or contradict a pillar, or meet its "wrong if" test? | The claims, and the candidate pillars with their stance and linked drivers | A suggestion on one pillar: stance, strength, whether the test is met, and any figure the email states for a linked assumption |
| Spawn a new thesis | Does this information point to a thesis the book does not hold? | The claims, one ticker, and the statements of that company's pillars | A candidate pillar: statement, what would prove it wrong, and linked drivers |

Five rules govern the agent:

- **Each skill is its own prompt file and DSPy module.** Adding a skill means adding a file and registering it; the agent's own prompt does not grow.
- **The agent chooses which skills to call for each email,** with at most three calls.
- **The new-thesis skill is for information that fits no existing pillar.** Code rejects a candidate that restates one.
- **Skills recommend and never decide.** Every output is a suggestion for the analyst.
- **No skill proposes a number, a trade or a position size.** A figure appears only when the email states it.

Five mechanics make the agent buildable:

- **Code picks the candidate pillars.** They are every pillar of each company in the claims' `tickers`, plus the pillars the links file ties to those companies. The agent passes claim IDs only, and the new-thesis skill takes one ticker a call.
- **The existing-thesis skill sees stance, pillars and linked drivers.** Each driver shows its label, unit, desk value and consensus. A skill never sees size or conviction, and never copies a book value into its output. The new-thesis skill sees one company's pillar statements and its drivers' IDs, labels and units.
- **A skill sees Jev's label for each email.** This is the pipeline's own label from stage 4, never the corpus label.
- **The agent is a tool loop.** Its tools are built from `tools/analysis_agent.json`: name, description and input schema, with `returns` appended to the description. Each tool runs one skill module. The agent itself is given the claims and the statements of the candidate pillars.
- **Code collects the output.** Suggestions come from the skills' results, parsed with the draft contracts, never from the agent's final text. The no-change reason is the last skill's own reason, and the agent's final text is used only when no skill was called.

### Tuning

- **Stages 3, A, 5 and 6 are DSPy modules.** Stage 3 binds the TypeSafe backend; the others bind generative models.
- **A code sweep fits the gate.** It sets the pass threshold on the fit split, picking the highest value that still passes every thesis\_relevant email and at least 95% of monitor emails. The three redundancy thresholds are not swept: the corpus has no `redundant_of` labels to score them against.
- **ReAnchor fits the yes/no thresholds.** It sets the attention, ticker and topic thresholds for the best F1 on the fit split. ReAnchor is experimental; if it proves unreliable, the same code sweep replaces it.
- **The quarantine threshold is not tuned.** The corpus holds no positive examples, so it stays at its starting value and is covered by test fixtures.
- **Criteria rules are tuned by hand, in text.** Add a rule, run the criteria check, and apply the keep rule below.
- **Small samples are noisy.** The tuning set holds about 15 thesis\_relevant emails, so a change of one email is not evidence. The keep rule: a rule stays only when it fixes at least two fit-split emails, breaks none that were right, and signal accuracy on the validation split does not fall.
- **Prompt optimization is optional.** GEPA or MIPROv2 can tune the skill prompts; this is the first thing to cut.
- **Tuned settings are files.** Each is saved as JSON and loaded at run time, so thresholds stay readable and editable.
- **The 600 test emails in `day_1` and `day_2` are never used for tuning.**

### Starting values

Every number the pipeline depends on is listed here and is defined once, in `src/triage_app/thresholds.py`; all code reads it from there. Model IDs are not numbers and never live in code: each is read from `.env`, as `JEV_MODEL`, `ANALYSIS_MODEL`, `NOTES_MODEL` and `EMBEDDING_MODEL`, and a stage that needs an unset one fails with a clear error.

| Setting | Starting value | Set by |
| --- | --- | --- |
| Pass threshold on the signal score | 0.6 | Sweep |
| Human-attention threshold (`HUMAN_ATTENTION`) | 0.6 | ReAnchor |
| Ticker and topic thresholds | 0.5 each | ReAnchor |
| Quarantine threshold | 0.65 | Fixed |
| Minimum P(monitor) for the monitor label | 0.70 | Chosen on the tuning fit split |
| Relevance a thesis suggestion needs (monitor-only evidence) | 0.7 (0.85) | Fixed |
| Content similarity that flags a repeat | 0.85 | Fixed |
| Content similarity that flags a repeat when subjects match | 0.75 | Fixed |
| Subject similarity that counts as a match | 0.6 | Fixed |
| Similarity at which a new thesis duplicates a pillar | 0.8 | Fixed |
| Net contradicting strength that triggers a conviction review | 4 | Fixed |
| Human-attention probability that raises an alert (`ALERT_HUMAN_ATTENTION`) | 0.8 | Fixed |
| Position size at which a met "wrong if" test raises an alert | 150 bps | Fixed |
| Alerts per day | 3 | Fixed |
| Skill calls per email | 3 | Fixed |
| Rules per criteria file | 12 | Fixed |
| Live route input cap | 10,000 characters | Fixed |
| Similarity at which two new-thesis candidates merge | 0.8 | Fixed |
| Jev input limit for the email plus the longest question | 32,000 tokens | Fixed |
| Verify agent tool calls per request | 4 | Fixed |
| Live runs per visitor session per hour | 5 | Fixed |

### How to construct it

- **Each stage is a function from files to files.** Stage N reads the JSON that earlier stages wrote and writes its own. Any stage reruns alone. "Stage files" lists every file and its contract.
- **Emails are processed in arrival order.** The day cache makes stage 2 depend on what came before.
- **The corpus body is the text of record.** The emails are not cleaned or copied into the output: every stage reads them from the corpus file through the loader (`RunContext.emails`). Every model reads the body as written, every quote is checked against it after each run of whitespace is collapsed to one space, and the app highlights quotes in it. The Inbox shows the same emails.
- **Every model call and every embedding is cached on disk,** keyed by program version, criteria version and input hash. Reruns cost nothing and the demo is deterministic.
- **The cache is committed.** A clean clone reruns the pipeline without spending tokens. Only a cache miss needs the keys.
- **No test calls a live model.** Each module takes its client as an argument, and tests pass a fake client or replay the cache.
- **The live route calls the same stage functions** on one email, against the day cache and the visitor's session state.
- **Each skill sees only what it needs:** the claims, and the candidate pillars with their stance and linked drivers.
- **Read-throughs come from a links file,** not the model's memory. When a claim tags one company, linked pillars on other companies are added to the candidates.
- **Code fills the book's current value and consensus** wherever a suggestion shows a linked assumption. The model never restates them.

### Monitoring: token use and latency

Every run records how many tokens each stage and model used and how long each stage took, so the cost and speed of processing a day are visible and comparable across runs. Per-email usage is not kept as an output.

1. **Wrap every client.** `monitoring.py` wraps each model client and the embedder that a module receives as its argument. Each call appends one `CallRecord`: the stage, email ID, model ID, input and output tokens, whether it was a cache hit, and wall-clock latency. Modules do not time themselves.
2. **Time every stage.** `pipeline/run.py` times each stage's `process(...)` call per email and its `run(...)` call per set, and appends a `StageTiming`.
3. **Write one file per set.** The `CallRecord`s and `StageTiming`s stay in memory. `metrics.json` holds the run-level `UsageReport` that code computes from them: per stage and per model totals, cache hits, spent and uncached tokens, latency percentiles, mean tokens per email and total latency.
4. **Summarize.** At the end of a run, `run.py` prints tokens and latency per stage and totals for the set, and writes `SUMMARY.md` (`pipeline/summary.py`): set and date, criteria version, tuned or starting thresholds, emails by label and gate, flagged repeats, attention notes, suggestions by brief list with ID and rationale, alerts, and the monitoring headline. It holds pipeline output only: never an email body or a corpus label.

Five rules govern monitoring:

- **Counts come from the provider.** Token counts are read from each response's usage fields. Where a provider reports none, as Jev may not, code estimates them at four characters per token and marks the record `estimated`.
- **Cache hits are kept apart.** A cache hit records the original call's tokens with `cache_hit` true and its own lookup latency. The report shows tokens spent on this run (misses only) separately from tokens the run would have cost uncached.
- **No content is logged.** Records hold IDs, counts and times only. They never hold prompt text, email text or keys.
- **Fakes report too.** A fake client reports fixed token counts, so tests check aggregation without a live model.
- **Latency is wall-clock, per email and per stage,** with p50, p95 and max computed by code and reported per stage, per model and per email end to end. Stages that run per set, such as redundancy, are also timed per email.

The Monitor screen shows the latest `metrics.json` for the set, and the Live screen shows tokens and latency beside each stage of its trace.

## The book

The book is the desk's own state: positions, thesis pillars and model drivers. It lives in the app's seed files and is never shown to the corpus generator.

| Part of the book | In the example | What it is used for |
| --- | --- | --- |
| Positions | Stance and size for each company | Ordering suggestions and setting alerts |
| Thesis | Three pillars per company, each with a "wrong if" test | The subject of every suggestion: alter a pillar, or add a new one |
| Assumptions | The analyst's value for each of 23 drivers, beside consensus | Shown on a thesis suggestion when an email states a figure for a linked driver |
| Projections | Revenue, EPS and target price computed from the drivers | Showing what an updated assumption would do |
| Outlook | Conviction from 1 to 5 | A prompt to review conviction when accepted evidence accumulates |

### Why the book is separate from the corpus

- **Emails describe the world; the book describes the desk.** The corpus labels say whether an email is informative about a company. Only the analysis agent says whether it matters to this desk's theses.
- **The book enters at stage 6.** Jev classifies with the relevance criteria and never sees the book. The analysis agent then compares each relevant email's claims with the theses.
- **One inbox, many books.** Editing the seed files and rerunning stages 6 to 9 gives a different brief from the same emails.
- **Two things are measured separately.** Labels are scored against the corpus. Suggestions are reviewed by hand, because no label knows the book.

### Example book: positions

This example is the seed for the prototype. It is invented for the demo and is not a view on the real companies.

| Ticker | Stance | Size | Conviction (1 to 5) |
| --- | --- | --- | --- |
| NVDA | Long | 300 bps | 4 |
| MSFT | Long | 250 bps | 3 |
| AMZN | Long | 200 bps | 3 |
| AAPL | Short | 200 bps | 3 |
| GOOGL | Short | 150 bps | 2 |

### Example book: thesis pillars

| ID | Pillar | Wrong if | Linked drivers |
| --- | --- | --- | --- |
| NVDA.p1 | AI infrastructure spending by cloud and sovereign buyers keeps Data Center growth above consensus through the next fiscal year. | Two of MSFT, AMZN and GOOGL guide capital expenditure flat or lower. | `NVDA.data_center_growth` |
| NVDA.p2 | Supply of advanced packaging and high-bandwidth memory is sufficient to ship the newest platform on schedule. | Credible evidence of a delay of a quarter or more. | `NVDA.data_center_growth` |
| NVDA.p3 | In-house chips at large customers grow alongside Nvidia instead of replacing it, so pricing and margin hold. | A top customer moves most new capacity to in-house chips, or Nvidia cuts pricing to defend share. | `NVDA.operating_margin`, `NVDA.data_center_growth` |
| MSFT.p1 | Azure growth stays above consensus as data-center capacity comes online. | Capacity constraints persist for two more quarters, or Azure guidance falls below consensus. | `MSFT.intelligent_cloud_growth` |
| MSFT.p2 | Paid AI assistants raise revenue per seat in the productivity suite. | Seat adoption or renewal data show enterprises cutting back. | `MSFT.productivity_growth` |
| MSFT.p3 | Capital intensity peaks within the model year and operating margin holds. | Capex guidance is raised again without matching growth in backlog. | `MSFT.capex`, `MSFT.operating_margin` |
| AMZN.p1 | AWS growth re-accelerates as power and chip capacity is added. | AWS growth decelerates for two consecutive quarters, or large workloads move to rivals. | `AMZN.aws_growth` |
| AMZN.p2 | Retail operating margin keeps expanding through fulfillment efficiency and advertising. | Fulfillment costs rise faster than revenue, or advertising growth slows sharply. | `AMZN.operating_margin`, `AMZN.north_america_growth` |
| AMZN.p3 | Capital expenditure converts into AWS backlog instead of a lasting drag on free cash flow. | Capex rises while backlog growth stalls. | `AMZN.capex`, `AMZN.aws_growth` |
| AAPL.p1 | The iPhone upgrade cycle disappoints: AI features do not pull upgrades forward, and share in China stays under pressure. | Sell-through or lead-time data show a clearly stronger cycle than consensus expects. | `AAPL.iphone_growth` |
| AAPL.p2 | Services growth slows as regulation and litigation pressure App Store fees and search distribution payments. | Rulings or settlements leave fees and payments intact and Services growth holds. | `AAPL.services_growth` |
| AAPL.p3 | Operating margin is at risk from tariffs and component costs. | Costs are absorbed or passed through and margin is guided flat or up. | `AAPL.operating_margin` |
| GOOGL.p1 | AI answers reduce clicks on commercial queries, so Search revenue growth falls below consensus. | Paid-click and pricing data show monetization holding or improving. | `GOOGL.services_growth` |
| GOOGL.p2 | Rising capital expenditure and depreciation compress operating margin. | Cloud growth and Cloud margin offset the step-up in depreciation. | `GOOGL.operating_margin`, `GOOGL.capex`, `GOOGL.cloud_growth` |
| GOOGL.p3 | Regulatory remedies in search and advertising technology restrict distribution or the ad stack. | Remedies are narrow or delayed, with little operating effect. | `GOOGL.services_growth` |

A pillar's linked drivers are where a figure stated in an email can appear on a suggestion. The driver IDs, and the desk's direction against consensus on each, are listed under "The model".

### Pillar detail, evidence and the street's view

Each thesis and pillar in `data/seed/theses.json` carries detail beyond the table above. The `id`, statement, "wrong if" test and linked drivers stay as listed; the rest is synthetic boilerplate for the demo.

- **Thesis summary** (`Thesis.summary`): a short paragraph on the desk's view and how the three pillars fit together.
- **The street's view** (`Thesis.street_view`, `street_view_note`, `street_target_price`): the street's consensus rating (buy, hold or sell), one sentence on where the street sits versus the desk, and the street's consensus target price in USD per share. The existing-thesis skill compares an email's analyst views with this rating. A target price sits within about 10% of the target the book computes on consensus drivers, at or above it for a buy.
- **Pillar summary** (`Pillar.summary`): two to three sentences of reasoning behind the statement.
- **Evidence** (`Pillar.evidence`): three or four observations, each with a source. A source is either fictional desk work or a fictional sell-side note, marked "(synthetic)", or the company's latest 10-K. A figure cited from a 10-K matches `data/seed/base_figures.json` exactly; invented figures never contradict the drivers in `data/seed/models.json`. No real person, research firm or bank is named.

### How an email meets the book

These five cases are illustrations, not corpus emails. They show the two results an email can have: a label from Jev and a suggestion from the analysis agent.

| Email | Triage label | Skill called and result | What the analyst is shown |
| --- | --- | --- | --- |
| Microsoft raises its capital expenditure guidance. | thesis\_relevant | Existing thesis: supports NVDA.p1 and contradicts MSFT.p3. | Two suggestions with the quoted guidance. The stated capex figure appears beside the book's value for the linked driver. |
| A court narrows the search remedies. | thesis\_relevant | Existing thesis: meets the "wrong if" test on GOOGL.p3 and contradicts AAPL.p2, both short theses. | Two suggestions and an alert. |
| Apple's enterprise device sales accelerate on AI features. | thesis\_relevant | New thesis: no pillar covers enterprise demand. | A candidate pillar for AAPL with a proposed "wrong if" test. |
| A supplier hints at tighter packaging capacity. | monitor | Existing thesis: bears on NVDA.p2, unconfirmed. | One suggestion at strength 1, under "worth watching". |
| A broker reiterates its rating on Nvidia, citing AI demand. | redundant | None; it stops at the gate. | Audit view only. |

### Assumptions in the example book

- **Neutrality:** three longs and two shorts are not market neutral alone, so the five are treated as part of a larger book.
- **Sizes:** they only set which contradictions raise an alert.
- **Segment names:** the drivers use each company's reported segments and still need checking against the latest annual reports.
- **Balance:** the example has pillars that good news and bad news can each contradict, so the demo shows both.

## State: model, thesis and change log

State is a set of seed files plus one append-only log. Current state is always computed as seed plus log and is never stored.

### The model

Each company gets one small driver model for one forward fiscal year. There are 23 drivers in total. This table fixes each driver's ID and the desk's direction against consensus; the values themselves are synthetic and come from the book prompt.

| Driver ID | What it measures | Unit | Desk versus consensus |
| --- | --- | --- | --- |
| `NVDA.data_center_growth` | Data Center revenue growth | pct | Above |
| `NVDA.gaming_growth` | Gaming revenue growth | pct | In line |
| `NVDA.other_growth` | All other revenue growth | pct | In line |
| `NVDA.operating_margin` | Operating margin | pct | In line |
| `MSFT.intelligent_cloud_growth` | Intelligent Cloud revenue growth | pct | Above |
| `MSFT.productivity_growth` | Productivity and Business Processes revenue growth | pct | Above |
| `MSFT.personal_computing_growth` | More Personal Computing revenue growth | pct | In line |
| `MSFT.operating_margin` | Operating margin | pct | In line |
| `MSFT.capex` | Capital expenditure | usd\_bn | In line |
| `AMZN.aws_growth` | AWS revenue growth | pct | Above |
| `AMZN.north_america_growth` | North America revenue growth | pct | In line |
| `AMZN.international_growth` | International revenue growth | pct | In line |
| `AMZN.operating_margin` | Operating margin | pct | Above |
| `AMZN.capex` | Capital expenditure | usd\_bn | In line |
| `AAPL.iphone_growth` | iPhone revenue growth | pct | Below |
| `AAPL.services_growth` | Services revenue growth | pct | Below |
| `AAPL.other_products_growth` | Mac, iPad and wearables revenue growth | pct | In line |
| `AAPL.operating_margin` | Operating margin | pct | Below |
| `GOOGL.services_growth` | Google Services revenue growth | pct | Below |
| `GOOGL.cloud_growth` | Google Cloud revenue growth | pct | In line |
| `GOOGL.other_bets_growth` | Other Bets revenue growth | pct | In line |
| `GOOGL.operating_margin` | Operating margin | pct | Below |
| `GOOGL.capex` | Capital expenditure | usd\_bn | Above |

Each driver holds the analyst's value, a consensus value, a unit and bounds. Consensus is seed data: it shows where the analyst differs from the Street and gives stage 6 a reference point for each claim.

One pure function computes the outputs, once on analyst values and once on consensus:

- Revenue is the sum of each line's base revenue times one plus its growth.
- Operating income is revenue times operating margin.
- EPS is operating income, less tax, divided by diluted shares.
- Target price is EPS times the target multiple.

Base revenue, tax rate and share count come from each company's latest annual report on SEC EDGAR, with the source URL kept in the seed file. Analyst values, consensus values and multiples are synthetic. Confirm the revenue lines against each latest 10-K before seeding.

If the filings cannot be fetched during the build, use placeholder base figures, mark them as placeholders on the Company screen, and report it. Never present an invented figure as a reported one.

Three details complete the seed. A `pct` driver is in percentage points, so 12.5 means 12.5%, and the tax rate is a fraction. The book prompt writes `data/seed/models_draft.json`, and state/seed\_merge.py merges it with the base figures into `models.json`. When the annual reports are fetched, their text is saved as `data/filings/<TICKER>_10-K.txt` for the verify agent.

Capex does not feed EPS. It is tracked because it is the main read-through from the three cloud companies to NVDA.

### Read-through links

A link says that a claim about one company should also be weighed against pillars on another.

| A claim about | Also brings in | Why |
| --- | --- | --- |
| MSFT | NVDA.p1, NVDA.p3, AMZN.p1, GOOGL.p2 | Its capex and in-house chips bear on Nvidia; cloud share shifts between the three clouds. |
| AMZN | NVDA.p1, NVDA.p3, MSFT.p1, GOOGL.p2 | The same two reasons. |
| GOOGL | NVDA.p1, NVDA.p3, MSFT.p1, AMZN.p1, AAPL.p2 | The same two reasons, and search distribution payments reach Apple Services. |
| AAPL | GOOGL.p3 | Rulings on search distribution deals affect both companies. |
| NVDA | MSFT.p1, AMZN.p1 | Chip supply sets how fast cloud capacity comes online. |

A link only adds pillars to what a skill is shown. It never produces a suggestion by itself. News about a company outside the five reaches a pillar through the claim's own tickers, which stage 5 fills in when the email states the read-through.

### The thesis

Each company has a stance (long or short), a size in basis points, a conviction from 1 to 5, and three pillars. Each pillar has a statement, a "wrong if" test, linked driver IDs and a ledger of accepted evidence. All of it is synthetic.

The example book above is the seed for these records. The corpus generator never sees it.

A new pillar that the analyst accepts gets the next free ID for its company, such as AAPL.p4. Net contradicting strength on a pillar is the summed strength of accepted contradicting evidence minus the summed strength of accepted supporting evidence.

### The change log

Each entry records the book item, the value before and after, the quoted sections that supported the change, and a timestamp. An entry is written only when the analyst accepts a suggestion, and entries are held on the server for each visitor session. Reset clears the session log, and undo appends a reversing entry.

## Data contracts

These Pydantic models are the contract between the corpus, the pipeline and the UI. The first two mirror the corpus prompt's JSONL schema field for field. Define them once. Parse every model output with a draft model, and let code build the stored model from it.

```python
from datetime import date, datetime
from typing import Annotated, Literal
from pydantic import BaseModel, Field

Ticker = Literal["AMZN", "NVDA", "MSFT", "AAPL", "GOOGL"]
Triage = Literal["thesis_relevant", "monitor", "redundant",
                 "low_value", "irrelevant"]
Topic = Literal["macro", "sector", "government", "other"]
Stance = Literal["supports", "contradicts"]
StreetView = Literal["buy", "hold", "sell"]


# ---- Corpus ----

class Email(BaseModel):                 # input fields of one JSONL row
    email_id: str
    received_at: datetime
    sender: str
    sender_email: str
    subject: str
    body: str                           # exactly as in the corpus: the text of record

class EmailLabel(BaseModel):            # corpus label fields of the same row
    email_id: str                       # read only by the loader, evals and tuning
    triage: Triage
    additional_labels: list[Topic]
    affected_tickers: list[Ticker]
    human_attention: bool
    redundant_of: str | None = None     # absent from the corpus; always None today
    reason: str
    email_type: str | None = None       # generation field, for email_type_accuracy only


# ---- Criteria ----

class CriteriaRule(BaseModel):          # one line under "## Rules"
    id: str                             # e.g. "R3"
    text: str                           # a kind of information, never a view

class LabelCriteria(BaseModel):         # parsed from one file in criteria/
    label: str                          # the file's name without ".md"
    definition: str                     # from the corpus prompt; not edited
    rules: list[CriteriaRule]

class CriteriaSet(BaseModel):           # everything Jev is told about relevance
    version: str                        # hash of all criteria files
    labels: dict[str, LabelCriteria]


# ---- Stages 2 to 4 ----

class RedundancyRecord(BaseModel):      # stage 2 output; redundancy.json holds flagged emails only
    email_id: str
    nearest: str | None                 # email_id of the most similar earlier email
    content_similarity: float | None    # cosine; None for the first email
    subject_score: float | None         # token-set similarity with that email, 0 to 1
    flagged: bool                       # potentially redundant; an email absent from the file is not

class TriageRecord(BaseModel):          # stage 3 output: Jev's answers, unmodified
    email_id: str
    criteria_version: str               # hash of the criteria files in force
    triage_probs: dict[str, float]      # Choice over the five labels
    ticker_probs: dict[str, float]      # Noul per ticker
    human_attention: float              # Noul
    topic_probs: dict[str, float]       # Noul per topic label
    email_type: str                     # most probable option; display only
    email_type_probs: dict[str, float]  # Choice over the eleven email types
    safety: dict[str, float]            # keys: possible_mnpi, instructs_ai
    truncated: bool                     # set by stage 3 when it trims the body

class EmailResult(BaseModel):           # stage 4 output: label of record and gate
    email_id: str
    triage: Triage | None               # None only when quarantined
    decided_by: Literal["jev", "redundancy_check", "quarantine"]
    redundant_of: str | None
    affected_tickers: list[Ticker]
    additional_labels: list[Topic]
    human_attention: bool
    signal_score: float                 # P(thesis_relevant) + P(monitor)
    gate: Literal["pass", "stop", "quarantine"]
    reason: str                         # one line composed by code


# ---- Model outputs: parse with these; code then builds the stored models ----

class QuoteDraft(BaseModel):
    quote: str

class NoteFields(BaseModel):          # what a note says; shared by the draft and the stored note
    summary: str                        # two sentences
    why_attention: str                  # one or two sentences
    action: Literal["reply", "attend", "decide", "read", "other"]
    deadline: datetime | None = None    # only when the email states one

class NoteDraft(NoteFields):           # stage A model output
    sections: list[QuoteDraft]

class ClaimDraft(BaseModel):            # stage 5 model output, one per claim
    quote: str                          # verbatim section of the email
    tickers: list[Ticker]               # the covered companies the claim bears on
    entities: list[str]                 # companies outside coverage
    kind: Literal["reported_fact", "guidance", "estimate_change",
                  "rating_change", "channel_check", "management_comment",
                  "opinion"]
    metric: str | None = None
    period: str | None = None           # e.g. "FY2027"
    value: float | None = None
    unit: Literal["pct", "usd_bn", "usd", "multiple"] | None = None
    direction: Literal["up", "down", "flat"] | None = None
    first_hand: bool

class LinkedSection(BaseModel):
    email_id: str
    quote: str                          # verbatim; shown highlighted in the email

class AssumptionDraft(BaseModel):
    driver_id: str
    stated_value: float                 # the figure the email states

class ExistingThesisDraft(BaseModel):   # one suggestion from the existing-thesis skill
    kind: Literal["existing_thesis"]
    pillar_id: str
    stance: Stance
    strength: Literal[1, 2, 3]
    wrong_if_met: bool = False
    assumptions: list[AssumptionDraft] = []
    rationale: str
    claim_ids: list[str]
    sections: list[LinkedSection]

class NewThesisDraft(BaseModel):        # one candidate from the new-thesis skill
    kind: Literal["new_thesis"]
    ticker: Ticker
    statement: str
    wrong_if: str
    driver_ids: list[str] = []
    rationale: str
    claim_ids: list[str]
    sections: list[LinkedSection]

class SkillResult(BaseModel):           # what either skill returns
    suggestions: list[Annotated[ExistingThesisDraft | NewThesisDraft,
                                Field(discriminator="kind")]] = []
    no_change_reason: str | None = None # one sentence when suggestions is empty

class VerifySource(BaseModel):
    source: str                         # filing or log entry identifier
    quote: str

class VerifyDraft(BaseModel):           # verify agent output
    verdict: Literal["confirmed", "contradicted", "not_found"]
    explanation: str                    # two sentences at most
    sources: list[VerifySource]


# ---- Stored records for the attention pathway and analysis ----

class AttentionNote(NoteFields):        # stage A output
    email_id: str
    sections: list[LinkedSection]       # code adds the email_id to each quote

class Claim(ClaimDraft):                # stage 5 output
    id: str                             # "<email_id>.c<n>", assigned by code
    email_id: str

class LinkedAssumption(AssumptionDraft):  # detail on a thesis suggestion
    book_value: float                   # filled by code
    consensus_value: float              # filled by code

class ExistingThesis(BaseModel):        # skill: alter an existing thesis
    kind: Literal["existing_thesis"]
    pillar_id: str
    stance: Stance
    strength: Literal[1, 2, 3]
    wrong_if_met: bool = False
    assumptions: list[LinkedAssumption] = []

class NewThesis(BaseModel):             # skill: spawn a new thesis
    kind: Literal["new_thesis"]
    ticker: Ticker
    statement: str
    wrong_if: str
    driver_ids: list[str] = []

class ConvictionReview(BaseModel):      # raised by code in the session, not by a model
    kind: Literal["conviction_review"]
    ticker: Ticker
    pillar_id: str                      # the pillar whose evidence crossed the threshold

class Suggestion(BaseModel):            # stages 6 to 8
    id: str                             # assigned by code; see "Stage files"
    body: Annotated[
        ExistingThesis | NewThesis | ConvictionReview,
        Field(discriminator="kind"),
    ]
    rationale: str                      # one sentence
    claim_ids: list[str]                # the claims behind it; empty for a conviction review
    sections: list[LinkedSection]
    second_look: bool = False           # no linked email is labeled as signal
    status: Literal["open", "accepted", "dismissed", "rejected"]
    reject_reason: str | None = None    # set by stage 7

class AnalysisRecord(BaseModel):        # stage 6 output, one per passed email
    email_id: str
    skills_called: list[str]
    suggestion_ids: list[str]
    no_change_reason: str | None = None # one sentence when no suggestion was made

class VerifyResult(VerifyDraft):        # shown to the analyst; never stored in the book
    suggestion_id: str


# ---- Delivery, tuning and evaluation ----

class Alert(BaseModel):
    kind: Literal["wrong_if_met", "conviction_review", "human_attention"]
    ref_id: str                         # a suggestion ID or an email ID

class Brief(BaseModel):                 # stage 9 output; every list is in display order
    day: date
    counts: dict[str, int]              # emails by label, notes, suggestions
    thesis_changes: list[str]           # suggestion IDs
    new_theses: list[str]               # suggestion IDs
    worth_watching: list[str]           # suggestion IDs whose emails are all monitor
    needs_attention: list[str]          # email IDs that have a note
    relevant_unlinked: list[str]        # see "Where each email appears"
    alerts: list[Alert]                 # at most three; conviction reviews join in the session
    audit: list[str]                    # every other email ID
    quarantined: list[str]              # email IDs

class Thresholds(BaseModel):            # tuned/thresholds.json; overrides thresholds.py
    pass_signal: float
    human_attention: float
    ticker: dict[str, float]
    topic: dict[str, float]
    content_similarity: float
    content_similarity_with_subject: float
    subject_match: float

class Miss(BaseModel):
    email_id: str
    measure: str
    expected: str
    got: str

class EvalReport(BaseModel):            # data/out/<set>/eval.json
    corpus: Literal["day_1", "day_2", "tuning"]
    criteria_version: str
    measures: dict[str, float | None]   # keys are listed under "Evaluation"
    confusion: dict[str, dict[str, int]]  # corpus label, then pipeline label
    misses: list[Miss]

class CallRecord(BaseModel):            # one model or embedding call; in memory only
    stage: str                          # a stage name, or "live" / "verify"
    email_id: str | None                # None for set-level calls
    model: str                          # model ID from config.py
    input_tokens: int
    output_tokens: int
    estimated: bool = False             # true when the provider reported no usage
    cache_hit: bool
    latency_ms: float                   # wall clock
    at: datetime

class StageTiming(BaseModel):           # one stage over one email, or over the set; in memory only
    stage: str
    email_id: str | None                # None for the set-level total
    latency_ms: float

class StageUsage(BaseModel):
    calls: int
    cache_hits: int
    input_tokens: int                   # spent this run: cache misses only
    output_tokens: int
    uncached_input_tokens: int          # what the run would have cost uncached
    uncached_output_tokens: int
    latency_p50_ms: float
    latency_p95_ms: float
    latency_max_ms: float

class UsageReport(BaseModel):           # data/out/<set>/metrics.json, computed by code
    corpus: Literal["day_1", "day_2", "tuning", "live"]
    run_at: datetime
    emails: int
    stages: dict[str, StageUsage]       # stage name to its totals
    by_model: dict[str, StageUsage]     # model ID to its totals
    tokens_per_email_mean: float        # spent tokens, input plus output
    email_latency_p50_ms: float         # end to end, all stages for one email
    email_latency_p95_ms: float
    total_latency_ms: float

class LabelChange(BaseModel):
    email_id: str
    subject: str
    before: Triage | None
    after: Triage | None
    split: Literal["fit", "validation"]
    now_correct: bool                   # after equals the corpus label

class CriteriaHistoryEntry(BaseModel):  # data/out/criteria_history.json, one per version
    criteria_version: str
    at: datetime
    files: dict[str, str]               # criteria file name to its full text
    fit: dict[str, float]               # eval keys for label measures, on the fit split
    validation: dict[str, float]        # the same measures on the validation split
    changed: list[LabelChange]          # tuning emails relabeled since the previous entry


# ---- The book ----

class Driver(BaseModel):                # one assumption inside a CompanyModel
    id: str                             # e.g. "NVDA.data_center_growth"
    label: str
    unit: Literal["pct", "usd_bn"]      # pct is in percentage points
    analyst: float                      # synthetic
    consensus: float                    # synthetic
    min: float
    max: float

class RevenueLine(BaseModel):
    driver_id: str                      # the growth driver for this line
    base_revenue_usd_bn: float          # from the latest annual report

class CompanyModel(BaseModel):          # data/seed/models.json
    ticker: Ticker
    synthetic: bool = True
    fiscal_year: str                    # the forward year modeled, e.g. "FY2027"
    revenue_lines: list[RevenueLine]
    tax_rate: float                     # a fraction, from the latest annual report
    diluted_shares_bn: float            # from the latest annual report
    source_url: str | None = None
    placeholder_base: bool = False      # true when base figures are not from filings
    target_multiple: float              # synthetic
    drivers: list[Driver]

class PillarEvidence(BaseModel):        # synthetic boilerplate behind a pillar
    observation: str                    # a data point or observation
    source: str                         # where it comes from (fictional desk work or a filing)

class Pillar(BaseModel):
    id: str                             # e.g. "NVDA.p1"
    statement: str
    wrong_if: str
    driver_ids: list[str]
    summary: str = ""                   # a few sentences of reasoning behind the statement
    evidence: list[PillarEvidence] = []

class Thesis(BaseModel):                # data/seed/theses.json
    ticker: Ticker
    stance: Literal["long", "short"]    # the desk's view
    size_bps: int
    conviction: Literal[1, 2, 3, 4, 5]
    pillars: list[Pillar]
    summary: str = ""                   # the thesis in a short paragraph
    street_view: StreetView = "hold"    # the street's consensus rating
    street_view_note: str = ""          # one sentence: where the street sits versus the desk
    street_target_price: float | None = None  # the street's consensus target, USD per share (synthetic)

class Link(BaseModel):                  # data/seed/links.json
    from_ticker: Ticker                 # a claim about this company...
    to_pillar_ids: list[str]            # ...also brings in these pillars
    why: str

class LogEntry(BaseModel):              # written only when the analyst accepts
    id: str
    at: datetime
    suggestion_id: str
    change: Literal["pillar_evidence", "pillar_added",
                    "driver_updated", "conviction_changed"]
    item_id: str                        # pillar ID, driver ID or ticker
    before: float | None = None         # driver or conviction; filled by code
    after: float | None = None
    stance: Stance | None = None        # pillar evidence
    strength: Literal[1, 2, 3] | None = None   # pillar evidence
    pillar: Pillar | None = None        # the pillar added
    reverses: str | None = None         # the entry an undo cancels
    sections: list[LinkedSection]
```

Driver and pillar IDs carry the ticker as a prefix, so a book item is unambiguous on its own. The loader splits each JSONL row into an Email and an EmailLabel, and no pipeline stage can import the labels, which makes leaking ground truth into a prompt impossible by construction.

### Stage files

Each stage file is a JSON list of one contract, except the brief and the eval report, which are single objects. These files are the only interfaces between stages, and between work packages.

| File in `data/out/<set>/` | Contract | Written by | Read by |
| --- | --- | --- | --- |
| `redundancy.json` | `RedundancyRecord`, flagged emails only | 2 Check for repeats | Stages 4 and 5; evals; the app; the live route |
| `triage.json` | `TriageRecord` | 3 Classify | Stage 4; evals; the app |
| `results.json` | `EmailResult` | 4 Label and gate | Stages A and 5 to 9; evals; the app |
| `notes.json` | `AttentionNote` | A Write attention notes | Stage 9; the app |
| `claims.json` | `Claim` | 5 Extract | Stages 6 and 7; the app |
| `analysis.json` | `AnalysisRecord` | 6 Analyze | Stage 9; the app |
| `suggestions_raw.json` | `Suggestion`, all with status open | 6 Analyze | Stage 7 |
| `suggestions_checked.json` | `Suggestion`, open or rejected with a reason | 7 Validate | Stage 8; evals; the app's audit view |
| `suggestions.json` | `Suggestion`, merged and ordered | 8 Merge and rank | Stage 9; the app |
| `brief.json` | `Brief` | 9 Deliver | The app |
| `eval.json` | `EvalReport` | The eval script | The app |
| `metrics.json` | `UsageReport`, run-level only | `pipeline/run.py` | The app's Monitor screen; `SUMMARY.md` |
| `SUMMARY.md` | Markdown, generated by `pipeline/summary.py` from the stage files and metrics | `pipeline/run.py` | People |
| `criteria_history.json` (in `data/out/`, shared by all sets) | `CriteriaHistoryEntry` | The criteria check | The app's Criteria screen |

Five rules cover what the table leaves out:

- **Stage modules share one interface.** Each `pipeline/<stage>.py` exposes `run(in_dir, out_dir, ctx)` for a whole set and `process(...)` for one email. `ctx` is a `RunContext` (`pipeline/context.py`) holding the clients, recorder, cache, criteria and thresholds; tests pass fakes through it. The stage names are redundancy, classify, gate, human\_attention, extract, analyze, validate, merge and deliver. The emails are not a stage file: `ctx.emails` reads them from the corpus file named by `RunContext.emails_path` through the loader (`run.py` sets `data/corpus/<set>/emails.jsonl`; tests use `tests/fixtures/emails.jsonl`). `data/out/README.md` describes every output file.
- **Each set's outputs are kept apart.** The sets are `day_1`, `day_2` and `tuning`, named after their folders in `data/corpus/`. A run on a set writes its stage files to `data/out/<set>/`. The app reads the directory named in `TRIAGE_DATA_DIR`, which defaults to `data/out/day_1`; the deployed app uses the default once the final run exists, and the fixtures until then.
- **Tuned thresholds override starting values.** Stage 4 reads `tuned/thresholds.json` when it exists and `thresholds.py` otherwise. Stage 2 always uses the fixed values in `thresholds.py`.
- **Code assigns every ID.** A claim is `<email_id>.c<n>` and a raw suggestion is `<email_id>.s<n>`. After merging, a suggestion is `<pillar_id>.<stance>` or `<ticker>.new<n>`. A model never writes an ID of its own.
- **Session state is not a stage file.** The change log, each suggestion's accepted or dismissed status, and conviction reviews live in the visitor's session. Code raises a conviction review when an accepted entry crosses the threshold.

## Labels and suggestions

Every email gets one triage label in stage 4. Emails flagged for attention get a note, and emails that pass the gate can produce thesis suggestions. A suggestion is a recommendation: no model makes an investment decision, and nothing changes the book until the analyst accepts.

### What each label leads to

| Label or flag | Set by | What happens next | Usually appears in |
| --- | --- | --- | --- |
| thesis\_relevant | Jev | Goes to the analysis agent when it passes the gate, which it normally does. | Brief, with any suggestions |
| monitor | Jev | The same. Its suggestions are capped at strength 1. | Brief, under "worth watching" |
| redundant | Jev, or the redundancy check with a pointer to the earlier email | Stops, unless its signal score clears the gate. | Audit view, listed under the earlier email |
| low\_value | Jev | Stops, unless its signal score clears the gate. | Audit view |
| irrelevant | Jev | Stops, unless its signal score clears the gate. | Audit view |
| human\_attention | Jev | Takes the attention pathway and gets a note. | Brief, under "needs your attention" |
| Quarantine | Jev's two safety questions | Held unsummarized. | Quarantine list on the audit screen |

"Where each email appears" governs when an email fits more than one row.

### Kinds of suggestion

| Kind | Comes from | Raised when | What the analyst is shown |
| --- | --- | --- | --- |
| Change to an existing thesis | The existing-thesis skill | A claim supports or contradicts a pillar, or meets its "wrong if" test. | The pillar, the stance, a strength from 1 to 3, whether the test is met, and any stated figure beside the linked assumption. |
| New thesis | The new-thesis skill | Relevant information fits no existing pillar. | A candidate pillar: statement, what would prove it wrong, and linked drivers. |
| Conviction review | Code | Accepted contradicting evidence on one pillar reaches a net strength of 4. | A prompt to review conviction, with the evidence behind it. |

Every suggestion carries a one-sentence rationale and its linked emails, each opened at the quoted sections that support it. No suggestion proposes a number of its own, a trade or a position size.

### What the analyst can do

- **Accept.** For an existing thesis, the evidence is logged against the pillar. For a new thesis, the pillar is added to the book.
- **Update a linked assumption.** Where a suggestion shows a stated figure, the analyst can change the driver, and the app recomputes EPS and target price.
- **Edit.** Change the strength or the wording of a new pillar, then accept.
- **Dismiss.** The suggestion closes and stays visible in the company's history.
- **Set conviction.** On a conviction review, the analyst picks a conviction from 1 to 5 or dismisses the review. The app never proposes the value.
- **Verify.** An agent checks the claim against cached filings and returns a cited verdict.

### Validation in stage 7

- **Unknown item:** a claim ID is not one of the email's claims, a pillar ID is outside the candidate set recomputed from those claims' tickers, a new thesis names a ticker outside them, or a new pillar names a driver of another company. Reject.
- **Quote mismatch:** a section is not found verbatim after whitespace normalization. Reject.
- **Duplicate thesis:** a new-thesis candidate's statement reaches the duplicate threshold against an existing pillar, using the stage 2 embedding model. Reject.
- **Monitor only:** every linked email is labeled monitor. Set strength to 1, and reject a new-thesis candidate.
- **Out of bounds:** a stated figure falls outside the driver's bounds, or names a driver the pillar is not linked to. Keep the suggestion and drop the figure.
- **Wrong period:** the claim's period is missing, or is not exactly the model's fiscal year, such as FY2027. Keep the suggestion and drop the figure.
- **Second look:** no linked email is labeled thesis\_relevant or monitor. Keep the suggestion and mark it "second look".

### Merging in stage 8

Suggestions on the same pillar and stance merge into one, which lists every linked email. Four rules settle the merged record:

- **Strongest wins.** Strength is the highest among them, `wrong_if_met` is true if any was, and the rationale is the strongest one's.
- **Assumptions are pooled,** one entry per driver and stated value.
- **Opposite stances stay apart.** Two stances on one pillar remain two suggestions. The app shows them together as one card, and neither is preselected.
- **Similar candidates merge.** New-thesis candidates for one company merge when their statements reach the merge threshold. The first statement is kept.

After merging, code recomputes the second-look mark and the worth-watching placement from the merged emails.

### Order and alerts

Suggestions on existing pillars are ordered by position size, then strength, then the signal score of their strongest email. New-thesis candidates are ordered by position size, then signal score.

An item alerts in three cases: a "wrong if" test is met on a position of 150 basis points or more, a conviction review is triggered, or a human-attention probability reaches 0.8. The budget is three a day; overflow stays in the brief.

Met tests come first, by position size, then attention items by probability. A conviction review is raised in the session, is shown first and counts toward the three. Alerts appear as a banner at the top of the Brief.

### Where each email appears

| Email | Appears in |
| --- | --- |
| Quarantined | The quarantine list, by sender and subject only |
| Flagged for human attention | "Needs your attention", whatever else applies to it |
| Passed, with a valid suggestion | That suggestion's card: thesis changes, new thesis candidates, or "worth watching" when every linked email is labeled monitor |
| Passed, labeled thesis\_relevant or monitor, with no valid suggestion | "Relevant with no link to your book", with the no-change reason |
| Passed, with any other label and no valid suggestion | The audit view, with the no-change reason |
| Stopped | The audit view, with its reason |

A second-look suggestion stays in its own list, thesis changes or new thesis candidates, and is marked. A rejected suggestion appears only in the audit view, under its email, with the reject reason.

Two no-change reasons are written by code. When every suggestion from an email was rejected, the reason reads "all suggestions rejected in validation". When stage 5 found no claims, it reads "no claims extracted".

## Corpus: two test days of 300 emails, plus a tuning set

The corpus is whatever the corpus prompt in `docs/corpus_documentation/synthetic_data_prompt.md` produces. That prompt is the specification for the emails, and the pipeline adapts to its output. It contains no book: labels are written for an informed generalist who holds no position. The test corpus is two days of 300 emails each: `day_1` (Tuesday, Oct 13, 2026; `synthetic_000001` to `synthetic_000300`) and `day_2` (Wednesday, Oct 14, 2026; `synthetic_000301` to `synthetic_000600`). Each day is a separate set with its own run, brief and eval report. The tuning set is a separate run of the same prompt, still being generated.

### File format

Each set is one JSONL file, `data/corpus/<set>/emails.jsonl`, with one object per email and 14 fields. An `email_plan.jsonl` beside it holds the label plan the emails were written against. Only the loader and evals read it.

| Field | Role | Notes |
| --- | --- | --- |
| email\_id | Input | For example synthetic\_000001 |
| sender | Input | Free text naming a fictional person and organization |
| sender\_email | Input |  |
| subject | Input |  |
| body | Input | No length limit; may hold several items or forwarded material |
| triage | Label | One of the five primary labels |
| additional\_labels | Label | Any of macro, sector, government, other; may also hold human\_attention |
| affected\_tickers | Label | Any of the five tickers; empty when none is meaningfully affected |
| human\_attention | Label | True or false |
| reason | Label | The generator's justification; never shown to a model |
| email\_type | Generation label | Format, such as sell\_side\_research or meeting\_request; never shown to a model |
| systemic | Generation label | True when one development affects all five targets; never shown to a model |
| angle | Generation label | How the email earns its label; never shown to a model |
| day | Generation label | 1 or 2; never shown to a model |

The corpus has no `received_at` and no `redundant_of`. The loader assigns `received_at` in file order across the day's trading window. Redundancy is computed only at run time by stage 2, and no label says which earlier email a repeat copies.

### Label targets set by the prompt

| Label | Share | Emails per 300 |
| --- | --- | --- |
| thesis\_relevant | 10% | 30 |
| monitor | 15% | 45 |
| redundant | 10% | 30 |
| low\_value | 35% | 105 |
| irrelevant | 30% | 90 |
| **Total** | **100%** | **300** |

The prompt sets further targets, and five are checked. The loader reports the first, third and fourth. The eval script reports the second after stage 3, from Jev's email type (meeting\_request, event\_invitation or newsletter), under the key meetings\_share. The fifth uses a name-and-ticker match and is approximate.

- human\_attention is true on 15 to 25 emails.
- Meeting requests, newsletters and event announcements make up at least 60 emails.
- Macro, sector or government labels appear on 25 to 35 emails.
- Each ticker appears at about the same rate among thesis\_relevant emails, about six each.
- No more than 15% of low\_value and irrelevant emails name a target company directly.

### The loader

The loader does five things, in order:

1. Splits each row into an Email and an EmailLabel.
2. Normalizes label spellings, using the table below. Version 3 of the prompt removes these inconsistencies; the table stays as a safety net.
3. Takes file order as arrival order, assigning each row a `received_at` in that order within its day, and checks that every `email_id` is unique (IDs are identifiers only and need not increase).
4. Validates every row against the schema and lists failures for hand fixing.
5. Prints a distribution report against the prompt's targets.

| Found in a row | What the loader does |
| --- | --- |
| `relevent` or `relevant` as the triage value | Reads it as thesis\_relevant. |
| `macro_government` in additional\_labels | Splits it into macro and government. |
| `human_attention` as the triage value or inside additional\_labels | Sets the flag to true. If no primary label remains, lists the row for hand fixing. |
| A lower-case ticker, or GOOG | Upper-cases it and maps GOOG to GOOGL. |
| Any other label or ticker | Drops it and logs a warning. |
| Two rows with the same subject and body | Keeps the first and reports the pair. |

### Hard negatives are the test

The prompt plants noise that looks like signal. The pipeline must not surface any of these:

- Excellent research on companies with no read-through to the five.
- Sophisticated analysis of a target company that only repeats consensus.
- Detailed, data-heavy reports with no thesis-changing conclusion.
- Routine analyst meetings that offer no differentiated access.
- Prestigious conference invitations that are irrelevant to the desk.
- Credible macro commentary with no plausible effect on the five.
- Important-looking legal or government announcements with little real relevance.
- Useful analysis mixed with promotional or irrelevant material.

It must also catch the reverse: an understated email that holds a single material insight.

### What the labels cannot check

- **Impact on the book.** The corpus has no book, so no label says which pillar or driver an email bears on. Suggestions are reviewed by hand.
- **Whether the labels are right.** One generator wrote the emails and the labels, so the labels are its judgment of general relevance, not an analyst's.
- **Safety handling.** The prompt forbids confidential information and plants no instructions aimed at an AI, so quarantine is tested by two fixtures in the test suite, not by the corpus.

### Tuning set

- **Source:** a separate run of the same prompt into `data/corpus/tuning/`, planned at 100 emails (`synthetic_000601` onward, Thursday, Oct 15, 2026). It is being generated outside this build; the agent never generates or edits it.
- **Handling:** loaded and normalized exactly like the test days.
- **Separation:** checked against both test days by subject and body hash; overlaps are removed.
- **Internal split:** two-thirds to fit and one-third to validate, stratified by triage label with a fixed seed. The split is made in `corpus.py`.

Until `data/corpus/tuning/emails.jsonl` exists, tuning and the criteria check are reported as pending and the pipeline runs at starting values.

## Stack and repo layout

The whole application is Python, including the UI. Pages are rendered on the server, so there is no TypeScript and no front-end build step.

| Layer | Default | Why |
| --- | --- | --- |
| Language | Python 3.14 | One codebase and one set of models |
| Packaging | uv with a lock file | The same environment for the agent and the host |
| Contracts | Pydantic 2.11 or later | Runtime validation of model output; DSPy 3.4 requires it |
| Pipeline framework | DSPy 3.4 with its TypeSafe extra | Signatures, a model per stage, and ReAnchor |
| Classifier | Jev through the TypeSafe SDK, pinned to jev-1.13.0 | Tuned thresholds must not move with a new release |
| Criteria | Plain text files in the repo, one per label, loaded into the Jev questions at run time | Anyone can read, diff and extend them; git history is the audit trail |
| Subject matching | Token-set similarity, for example with rapidfuzz | A second signal beside content similarity; fast and local |
| Content similarity | A Hugging Face embedding model, pulled from the Hub with `huggingface-hub` and run locally with `sentence-transformers` (default `BAAI/bge-small-en-v1.5`), in `triage_app/embed.py`; long emails chunked to its input limit; cosine similarity in NumPy | Every email is embedded; no vector database, and no API key for embeddings |
| Model access | Every generative call goes through OpenRouter, in `triage_app/llm.py`; Jev keeps its own TypeSafe client | One key and one client for every generative model |
| Analysis model | Claude Haiku 5.5 for extraction, the analysis agent and verify (OpenRouter `anthropic/claude-haiku-5.5`) | Model IDs come only from `.env` |
| Attention notes model | Claude Haiku 5.5 (OpenRouter `anthropic/claude-haiku-5.5`) | The person's choice of model; prompts carry the focus on the desk's opportunity |
| Skills | One prompt file and one DSPy module per skill, registered with the analysis agent | A new investment question is a new file, not a longer prompt |
| Web | FastAPI with Jinja templates and HTMX | Server-rendered pages; one process to deploy |
| Storage | JSON and text files in the repo; accepted changes in server memory, keyed by a session cookie | No database; every visitor starts clean, and a restart clears sessions |
| Cache | Model calls and embeddings cached on disk and committed; pipeline output committed | The deployed app never reruns the corpus, and the live route re-embeds the day from the cache to compare a new email with it |
| Tests | pytest on the loader, redundancy check, gate, compute, fold, validate and merge | Pure functions are cheap to test |
| Deploy | One container on any host that runs Python; the image includes the embedding model | Pages and the live route ship together |
| Secrets | OpenRouter key and TypeSafe key, read from OPENROUTER\_API\_KEY and TYPESAFE\_API\_KEY in `.env`, server-side only. Other keys in `.env` are unused | Never sent to the browser |

The live route needs three protections because it spends real tokens on a public URL: a rate limit, a 10,000-character input cap, and cached results for the preset emails.

The six presets are `Email` objects in `data/live_presets/`, written by the lead; one is a quarantine case. A visitor session gets five live runs an hour, and "this mattered" draws on the same allowance. The trace is rendered once the run completes, and any note or suggestion it yields joins that session's brief.

```text
SPEC.md         this spec, exported to Markdown
DECISIONS.md    choices the agent made where this spec was silent
REVIEW.md       generated drafts awaiting review by a person
pyproject.toml  uv.lock  Dockerfile  .env.example
prompts/        the six generation prompts and their README
criteria/       one text file per label: definition plus rules
                thesis_relevant.md  monitor.md  redundant.md  low_value.md
                irrelevant.md  human_attention.md  macro.md  sector.md
                government.md  other.md  affected_tickers.md
skills/         alter_existing_thesis.md  spawn_new_thesis.md
instructions/   jev_questions.md  attention_note.md  extract_claims.md
                analysis_agent.md  verify_agent.md
tools/          analysis_agent.json  verify_agent.json
docs/
  corpus_documentation/
    synthetic_data_prompt.md         the corpus prompt
data/
  corpus/
    day_1/   emails.jsonl  email_plan.jsonl     300 emails with labels
    day_2/   emails.jsonl  email_plan.jsonl     300 emails with labels
    tuning/  emails.jsonl  email_plan.jsonl     tuning emails with labels, being generated
  seed/     models.json  theses.json  links.json      the example book
            models_draft.json           output of the book prompt, before the merge
  live_presets/                         six emails for the live route
  out/      criteria_history.json       scores for each criteria version
            README.md                   what every output file is
    day_1/  redundancy.json  triage.json  results.json
            notes.json  claims.json  analysis.json
            suggestions_raw.json  suggestions_checked.json  suggestions.json
            brief.json  eval.json
            metrics.json                run-level token use and latency
            SUMMARY.md                  a short summary of the run
            review_notes.csv  review_suggestions.csv   sheets for hand review
    day_2/  the same stage files for day 2
    tuning/ the same stage files for the tuning set
  cache/    model calls and embeddings, committed
tuned/      thresholds.json
transcripts/    the lead agent's session and every subagent's brief and report
src/triage_app/
  schema.py     Pydantic models: the single source of truth
  config.py     paths, sets, labels; resolves model IDs from .env
  thresholds.py every threshold, limit and tunable number, in one place
  llm.py        the OpenRouter client every generative call goes through
  embed.py      the Hugging Face embedder
  cache.py      the on-disk cache under data/cache/
  corpus.py     loader: split, normalize, check, report
  criteria.py   load, check and hash the criteria files
  monitoring.py client wrappers, stage timer, run-level usage report
  modules/      DSPy modules: classify, attention note, extract,
                analysis agent, verify agent, one module per skill
  pipeline/     context.py  redundancy.py  classify.py  gate.py  human_attention.py
                extract.py  analyze.py  validate.py  merge.py  deliver.py
                summary.py  run.py
  state/        compute.py  fold.py  apply.py  seed_merge.py
  evals/        metric.py  score.py  tune.py  criteria_check.py
  web/          main.py  templates/  static/
tests/          one test file per module
  fixtures/     ten hand-written emails, labels.jsonl, and a valid example
                of every stage file
```

### Commands

The agent implements these entry points with these names, so every "done when" test can be run as written.

| Command | What it does |
| --- | --- |
| `uv sync` | Installs the locked environment. |
| `uv run pytest` | Runs every test. No test needs a key or the network. |
| `uv run python -m triage_app.corpus --set day_1` | Loads and normalizes one set, and prints the distribution report. `--set` takes `day_1`, `day_2` or `tuning`. |
| `uv run python -m triage_app.pipeline.run --set day_1` | Runs every stage in order and writes the stage files to `data/out/day_1/`. `--stage classify` reruns one stage; `--from extract` reruns from a stage onward. |
| `uv run python -m triage_app.evals.tune` | Fits thresholds on the fit split and writes `tuned/thresholds.json`. |
| `uv run python -m triage_app.evals.criteria_check` | Reruns Jev on the tuning set with the current criteria files and prints before-and-after scores. |
| `uv run python -m triage_app.evals.score --set day_1` | Scores the set's stage files against its labels and writes `data/out/day_1/eval.json`. |
| `uv run uvicorn triage_app.web.main:app` | Serves the app locally. |
| `docker build -t triage-app .` then `docker run -p 8000:8000 --env-file .env triage-app` | Builds and runs the container. |

## Screens

The suggestion screen is the center of the demo: the suggested change on one side, the linked emails with their quoted sections on the other.

| Screen | Shows | Key interaction |
| --- | --- | --- |
| Brief | Header counts, then sections: suggested thesis changes, new thesis candidates, worth watching, needs your attention with its notes, relevant with no link to your book, and a link to the audit view. | Open any item; accept or dismiss inline. |
| Suggestion | The pillar or candidate pillar, any stated figure beside the linked assumption with its effect on EPS and target price, and each linked email opened at its quoted sections. | Accept, update an assumption, edit, dismiss or verify. |
| Company | Drivers with analyst value, consensus and gap; projections; pillars with accepted evidence; change history. | Click any change to open its emails. |
| Criteria | Each label's criteria file as written: its definition and numbered rules, with the version history and the scores for each version. | Read and compare versions; open a version to see the emails whose label it changed. |
| Audit | Every email not in the brief, grouped by label, with Jev's probabilities, the criteria version in force and, for flagged repeats, the earlier email and both similarity scores. | "This mattered" sends the email to the analysis agent. Quarantined emails are listed here by sender and subject only. |
| Inbox | The day's 300 emails in arrival order, as in the corpus file. A quarantined email shows its sender and subject only. | Shows the contrast with the brief. |
| Live | Paste or pick a new email and watch a stage-by-stage trace. | Proves the pipeline runs for real. |
| Eval | Scores against labels and a list of misses. | Open any miss. |
| Monitor | Tokens and latency for the set's latest run: per stage and per model, with spent and uncached totals, cache hits and email latency percentiles. | Compare stages and models. |

### Routes

Every page is a GET that returns HTML. Every action is a POST that returns an HTMX fragment and changes only the visitor's session.

| Route | Method | Screen or action |
| --- | --- | --- |
| `/` | GET | Brief |
| `/suggestion/{id}` | GET | Suggestion |
| `/suggestion/{id}/accept`, `/edit`, `/dismiss`, `/verify` | POST | Accept, edit, dismiss or verify one suggestion |
| `/driver/{driver_id}` | POST | Update a linked assumption and recompute |
| `/conviction/{ticker}` | POST | Set conviction after a conviction review |
| `/company/{ticker}` | GET | Company |
| `/criteria` and `/criteria/{label}` | GET | Criteria |
| `/audit` | GET | Audit, with the quarantine list |
| `/audit/{email_id}/mattered` | POST | Send a stopped email to the analysis agent |
| `/inbox` and `/email/{email_id}` | GET | Inbox, and one email with its quotes highlighted |
| `/live` | GET, POST | Live: the form, and one run of the pipeline on the submitted email |
| `/eval` | GET | Eval |
| `/monitor` | GET | Monitor |
| `/undo` and `/reset` | POST | Reverse the last change, or restore the seed state |

## Build order

Build in eight steps, each with a test that proves it is done. Steps 0 to 2 fit day one, 3 to 5 day two, and 6 to 7 day three with the screencast and write-up.

| Step | Build | Done when |
| --- | --- | --- |
| 0 | Python project with uv; Pydantic schemas; compute and fold with tests. Seed files: pillars, stances, driver IDs and links from this spec, driver values from the book prompt, base figures from filings. The 11 criteria files from the criteria prompt. Test fixtures. Monitoring wrappers and the usage report. A one-email Jev spike that picks the stage 3 route. | Compute returns EPS and target price for all five; folding an empty log returns the seed; a fake client's calls aggregate into a valid `UsageReport`; the criteria files load and hash; every fixture validates against its contract; the spike returns 14 answers for one email. |
| 1 | Corpus loader with normalization and the distribution report; every stage reads its emails through it. | `day_1` and `day_2` load (and `tuning` once it exists); the report prints label counts against the prompt's targets and lists any rows that need hand fixing. |
| 2 | Redundancy check: embed every email, compare with earlier emails of the same day, write redundancy records. | On `day_1`, a report lists every flagged email with its nearest earlier email and both scores, and how many flagged emails the corpus labels redundant. |
| 3 | Jev question wording from the stage-instructions prompt; classification with the criteria files; the label and gate stage. | Every email has one label and a reason; a report shows gate recall and gate reduction at the starting values, on the tuning set once it exists. |
| 4 | Skills and tool definitions from their prompts; attention notes; extraction; the analysis agent; validate and merge. | Every flagged email has a note; every suggestion is valid or carries a reject reason; every quoted section matches its email. |
| 5 | Accept and recompute; suggestion and company pages. | Accepting a thesis suggestion logs the evidence; updating a linked assumption changes EPS on screen; reset restores the seed. |
| 6 | Brief, criteria, audit, inbox and monitor pages; eval script and page; threshold tuning; review sheets. | Brief items plus audit items account for all 300 emails of each test day; the Monitor page shows tokens and latency per stage for the run; the criteria check prints before-and-after scores for an added rule; evaluation targets are met or every miss is listed. |
| 7 | Live route, alerts, verify agent, container deploy. | A pasted email yields a label and, if relevant, a note or a suggestion on the deployed URL. |

### Cut order if time runs short

1. Prompt optimization with GEPA or MIPROv2.
2. Verify agent.
3. The "this mattered" action.
4. Conviction review suggestions.
5. Version history on the Criteria screen, keeping the plain view of each file.
6. Alerts, leaving the brief as the only surface.

The suggestion screen with accept, the redundancy check, attention notes, both skills, the audit view, the eval page and the live route are never cut.

### Working rules for the coding agent

- Read `SPEC.md` whole before step 0.
- Commit after each step, and keep the full session transcript. The transcript is a submission deliverable.
- Where this spec is silent or contradicts itself, follow the design rules, choose the simpler option and record the choice in `DECISIONS.md`.
- Commit every file a generation prompt produces as a draft, and list it in `REVIEW.md`. Do not tune on a generated file that has not been listed.
- Pin the DSPy and TypeSafe SDK versions. The Jev integration is experimental and has no generative fallback.
- If the DSPy backend cannot take criteria text at run time, call the TypeSafe SDK directly for stage 3 and keep everything else unchanged.
- Send all 14 questions in one Jev request per email, never one request per question.
- Give Jev the email and the relevance criteria only: no book, no redundancy flag and no other emails.
- Keep views out of the criteria files, and never change a label's name or definition. Add rules beneath it.
- Keep each skill in its own prompt file and module. The analysis agent calls skills; it does not absorb them.
- Process emails in arrival order, so the day cache holds only earlier emails.
- No pipeline stage passes a corpus label, including its reason, to a model. Only the loader, eval and tuning code read EmailLabel. Jev's own label from stage 4 is pipeline output and may be shown to a skill.
- Tune only on the tuning set, and report scores only on the test days, `day_1` and `day_2`.
- Do not edit the corpus prompt or the emails to make a score pass. Report the miss.
- Never commit, print or log an API key. Commit `.env.example`, never `.env`.

## Work packages for subagents

The lead agent can hand nine packages to subagents once package 0 has frozen the contracts. A single agent can ignore the packages and follow the build order alone.

| # | Package | Owns | Reads, then writes | Spec sections to read | Done when, on the fixtures |
| --- | --- | --- | --- | --- | --- |
| 0 | Foundation, built by the lead | `pyproject.toml`, `uv.lock`, `schema.py`, `config.py`, `thresholds.py`, `criteria.py`, `monitoring.py`, `criteria/`, `state/compute.py`, `state/fold.py`, `state/seed_merge.py`, `data/seed/`, `data/filings/`, `tests/fixtures/`, `pipeline/run.py`, and a typed stub of every stage module | This spec, prompts 01 and 02 and the annual reports, then the seed files, criteria files, fixtures and stubs | Start here; Data contracts; Stage files; The book; State; Relevance criteria; Calling Jev; Starting values; Commands | Build step 0 passes. |
| 1 | Generated drafts | `skills/`, `instructions/`, `tools/` | Prompts 04, 05 and 06, then the drafts | Attention pathway; Analysis agent; Data contracts; `prompts/README.md` | Every file parses and passes its checks in the prompts README. The report lists each file for `REVIEW.md`. |
| 2 | Corpus | `corpus.py` | The fixture emails and labels | Corpus; Stage files | The fixtures load, split and normalize, and the report prints. Each row of the normalization table has a test. |
| 3 | Redundancy | `pipeline/redundancy.py` | The corpus emails, then `redundancy.json` (flagged only) | Redundancy check; Starting values | The fixture repeat is flagged and points to its earlier email. The first email has no nearest. The output validates. |
| 4 | Classify and gate | The classify module, `pipeline/classify.py`, `pipeline/gate.py` | The corpus emails, `redundancy.json`, the criteria set and `instructions/jev_questions.md`, then `triage.json` and `results.json` | Classification with Jev; Relevance criteria; Calling Jev | With a fake client, every fixture email gets one result. Each gate case under "Classification with Jev" has a test. A test proves the Jev request holds only the email and the criteria. |
| 5 | Attention notes | The attention module, `pipeline/human_attention.py` | The corpus emails and `results.json`, then `notes.json` | Attention pathway; Data contracts | With a fake client, every flagged fixture email gets a note. A section that fails the string match is dropped and counted, and the note stays. |
| 6 | Analysis | The extract, analysis agent, skill and verify modules with their tool functions; `pipeline/extract.py`, `analyze.py`, `validate.py`, `merge.py` | The corpus emails, `results.json`, `redundancy.json`, the seed files, `skills/`, `instructions/` and `tools/`, then `claims.json`, `analysis.json` and the three suggestion files | Analysis agent; Labels and suggestions; Read-through links; Data contracts | With fake clients, each validation rule and each merge rule has a test, and every output validates. |
| 7 | State and app | `state/apply.py`, `pipeline/deliver.py`, `web/` | Every stage file and the seed files, then `brief.json`, the pages and the session log | State; Labels and suggestions; Screens; Routes; Data contracts; Stage files; Starting values; the live-route rules under "Stack and repo layout" | Build step 5 passes on the fixtures. Every route under "Routes" answers, with a fake standing in for any module another package owns. Brief items plus audit items account for every fixture email. |
| 8 | Evals and tuning | `evals/` | The stage files and `labels.jsonl`, then `thresholds.json`, `eval.json`, `criteria_history.json` and the review sheets | Tuning; Starting values; Evaluation and guardrails; Stage files | The eval, tuning and criteria-check commands run on the fixtures, with a fake classifier, and write valid files. |
| 9 | Review, in a fresh context | Nothing; it is read-only | The repo and this spec, then a findings report | Design rules; Guardrails; Working rules | Every check in the last rule below passes, or the failure is reported. |
| L | Integration, by the lead | `Dockerfile`, `.env.example`, `DECISIONS.md`, `REVIEW.md`, `data/cache/`, `data/out/`, `data/live_presets/`, `tuned/`, `transcripts/` | The merged packages and both corpora, then the committed outputs and the deployed app | Build order; Where a person is needed; Commands | Build steps 1 to 7 pass on the real sets. |

Packages 1 to 8 can start together once package 0 is merged, because each builds and tests against the fixtures and stubs. Packages 4 and 6 use stub wording until the drafts from package 1 land.

The lead then integrates in stage order. Once the tuning set exists, it runs the pipeline on it and produces the tuning-set report that build step 3 names. It then tunes, makes the final run on `day_1` and `day_2`, and deploys.

Nine rules govern the hand-off:

- **Contracts freeze first.** Only the lead edits `schema.py`, `config.py` and `thresholds.py`. A subagent that needs a contract changed stops and asks.
- **One owner per file.** A package edits only the files it owns and adds tests only for them. A subagent returns lines for `REVIEW.md` and `DECISIONS.md` in its report; the lead writes them.
- **Fixtures stand in for upstream stages.** `tests/fixtures/` holds ten hand-written emails and a valid example of every stage file, so no package waits for another to run. The ten include two quarantine cases, a same-day repeat with its earlier email, an attention email and a second-look case.
- **A brief stands alone.** A subagent starts with no memory of the lead's session. Its brief names the package row, the spec sections to read, the contracts it uses, the done-when test and the working rules.
- **A report is evidence.** A subagent returns the files it changed, the test command with its output, any choice for `DECISIONS.md`, and anything left undone. The lead reruns the test before merging.
- **Labels stay with two packages.** Fixture labels sit in `tests/fixtures/labels.jsonl`. Only the loader in package 2 and the evals in package 8 read `EmailLabel`, and no brief includes a test-set label.
- **Only the lead runs a full corpus.** Subagents call live models on fixtures only, through the cache. This keeps cost bounded and makes the committed outputs come from one run.
- **Every transcript is kept.** Each subagent's brief, transcript and report go in `transcripts/`. They are part of the submission's record of AI interactions.
- **Review is independent.** Package 9 gets the repo and this spec, not the lead's summary. It checks that no corpus label reaches a prompt, the Jev request holds only the email and criteria, every quote matches its email, no tool writes or sends, a quarantined body reaches no later model or screen, every screen is marked synthetic, and the test set was never used for tuning.

## Evaluation and guardrails

The eval script compares pipeline output with the labels and writes the scores the eval page shows. Scores are reported on the test days only, one `eval.json` per day, and the targets are proposals.

| Measure | Key in `eval.json` | Definition | Target |
| --- | --- | --- | --- |
| Gate recall | `gate_recall` | Emails the corpus labels thesis\_relevant that pass the gate. | 100% |
| Monitor recall at the gate | `monitor_gate_recall` | Emails the corpus labels monitor that pass the gate. | 95% or better |
| Gate reduction | `gate_reduction` | Share of emails stopped before the analysis model. | Reported, not targeted |
| Signal accuracy | `signal_accuracy` | Label correct on three classes: signal (thesis\_relevant or monitor), redundant, and noise (low\_value or irrelevant). | 85% or better |
| Triage accuracy | `triage_accuracy` | Label equals the corpus label exactly, on all five. | Reported, with a confusion table |
| Ticker tagging | `ticker_f1` | Micro-averaged F1 on affected\_tickers. | 0.90 or better |
| Human attention | `human_attention_precision`, `human_attention_recall` | Precision and recall on the flag. | Recall 90% or better; precision 80% or better |
| Topic labels | `topic_f1` | Micro-averaged F1 on macro, sector, government and other. | Reported |
| Repeat detection | `repeat_flagged`, `repeat_precision` | Count of emails the check flags, and the share of flagged emails the corpus labels redundant. The corpus has no `redundant_of`, so recall and match to the right earlier email are not measured. | Reported |
| Stray suggestions | `stray_suggestions` | Count of suggestions whose only linked emails are labeled redundant, low\_value or irrelevant. | Reported; each one reviewed |
| Quote faithfulness | `quote_faithfulness` | Quoted sections that match the source exactly, in notes and suggestions. | 100%, enforced by code |
| Meeting-like share | `meetings_share` | Share of emails whose Jev email type is meeting\_request, event\_invitation or newsletter. | Reported |
| Email type | `email_type_accuracy` | Share of emails whose Jev email type (most probable option) equals the corpus `email_type`. A quarantined email counts as a miss. | Reported, no target |
| Attention note review | `note_review` | Hand review of every note: summary accurate, reason and action stated. | 90% or better |
| Suggestion review | `suggestion_review` | Hand review of every suggestion: right pillar, right stance, sections support it. | 90% or better |
| New-thesis review | `new_thesis_review` | Hand review of every candidate: new to the book and supported by its sections. | Reported |

A quarantined email counts as a miss on every label measure. Each review sheet has one row per item: its ID, its kind, a yes-or-no column for each check, and a comment. Checks that do not apply to a kind stay blank. A row passes when every applicable check is yes, and each review key is the share of passing rows. The person commits the filled sheets and the eval script reads them; until then the three review keys are empty.

Label scores are reported for the criteria files as committed. The corpus labels are fixed, and rules are tuned on the tuning set only.

The labels come from the same generator as the emails, so these scores show internal consistency, not performance on real mail.

The three hand reviews are done by a person, not by the coding agent. The agent writes one review sheet for notes and one for suggestions, and the eval page shows their results once they are filled in.

### Guardrails

- **No model makes an investment decision.** Models recommend; suggestions concern theses, never trades, position sizes or numbers of the model's own.
- **Nothing changes the book without the analyst.** Suggestions pass stage 7 before they are shown, and only an accepted suggestion is logged.
- **Classification stays free of the desk's views.** Jev gets the email and the relevance criteria, and the criteria hold no stances, pillars or estimates.
- **Email text is data.** It is delimited in every prompt and models return schema-bound output only. No tool can write, send or browse, so text in an email cannot cause an action.
- **Read-only on mail.** The system never sends mail and never touches the inbox.
- **Possible inside information is quarantined,** not summarized.
- **Synthetic content is labeled** on every screen.
- **Only synthetic mail goes to Jev and the generative models.** Sending real fund email to any vendor needs a compliance and data-processing review first.
- **API keys stay server-side,** and the live route is rate-limited.

## Beyond the prototype

With more time, the claim ledger becomes the team's shared memory of what the Street said, and email is only its first input.

| Order | What gets built | Why it matters |
| --- | --- | --- |
| Next | Read-only connection to real mail, run in shadow mode beside one analyst, with a weekly sample of suppressed items to confirm. | Measures recall on real mail before anyone relies on it. |
| Next | Research-log and model integration: accepted changes write to the real model, and thesis records live in the research system. | Closes the loop from email to model for real. |
| Then | All four calendar modes, including first-take cards minutes after a print and a scheduling agent for conference season. | The workflow follows the market calendar. |
| Then | Other inputs join the same ledger: filings, transcripts, expert-call notes and channel checks. | Stitches triage into the fund's other research workflows. |
| Later | Team layer: a PM digest across the four analysts, and read-throughs routed to whichever analyst covers the affected name. | The book belongs to the fund, not one analyst. |
| Later | Source track record: brokers and vendors scored on whether their past claims proved right. | Ranking improves from outcomes, not opinions. |

Three things need owners before any real deployment: compliance sign-off on the quarantine rule, retention of every decision for audit, and enforcement of research entitlements in the team layer.

## Decisions needed

The coding agent uses each default below until told otherwise.

| # | Question | Default |
| --- | --- | --- |
| 1 | Is the example book acceptable? | Yes. It lives only in the seed files and this document, never in the corpus prompt. |
| 2 | Who supplies the tuning set? | It is generated outside the build into `data/corpus/tuning/`. Until it exists, tuning is pending. |
| 3 | What do the criteria files start with? | The prompt's definition for each label and no more than four starter rules. Further rules are added through the criteria check. |
| 4 | Is the rule-proposal prompt used? | No. It shows tuning labels to a model, so new rules are written by hand unless the reviewer opts in. |
| 5 | Which embedding model? | A Hugging Face model run locally, named by `EMBEDDING_MODEL` in `.env`; default `BAAI/bge-small-en-v1.5`. |
| 6 | Which model writes attention notes? | Claude Haiku 5.5, through OpenRouter. |
| 7 | Which model runs extraction and the analysis agent? | Claude Haiku 5.5, through OpenRouter. |
| 8 | Are two skills enough for the prototype? | Yes: alter an existing thesis, and spawn a new thesis. |
| 9 | Which trading dates does the corpus use? | `day_1` is Tuesday, Oct 13, 2026, `day_2` is Wednesday, Oct 14, 2026, and the tuning set is Thursday, Oct 15, 2026. |
| 10 | How deep is the model? | 23 drivers, one forward year, four formulas. |
| 11 | What if the annual reports cannot be fetched? | Use labeled placeholder base figures and report it. |
| 12 | Where do accepted changes persist? | Server memory per visitor session, with a reset button. |
| 13 | What can the live route accept? | Six preset emails, plus free paste under the character cap. |
| 14 | How much tuning is in scope? | The thresholds under "Starting values" and hand-written criteria rules. Prompt optimization only if time remains. |
| 15 | Which coding agent and host? | Claude Code, deploying one container to a Python host. |



