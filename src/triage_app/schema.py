"""Pydantic contracts between the corpus, the pipeline and the UI.

Copied from SPEC.md, "Data contracts". This is the single source of truth: only the
lead edits it.
"""

from datetime import date, datetime
from typing import Annotated, Literal
from pydantic import BaseModel, Field

Ticker = Literal["AMZN", "NVDA", "MSFT", "AAPL", "GOOGL"]
Triage = Literal["thesis_relevant", "monitor", "redundant",
                 "low_value", "irrelevant"]
Topic = Literal["macro", "sector", "government", "other"]
Stance = Literal["supports", "contradicts"]


# ---- Corpus ----

class Email(BaseModel):                 # input fields of one JSONL row
    email_id: str
    received_at: datetime
    sender: str
    sender_email: str
    subject: str
    body: str                           # raw in the corpus; cleaned in parsed.json

class EmailLabel(BaseModel):            # corpus label fields of the same row
    email_id: str                       # read only by the loader, evals and tuning
    triage: Triage
    additional_labels: list[Topic]
    affected_tickers: list[Ticker]
    human_attention: bool
    redundant_of: str | None = None     # absent from the corpus; always None today
    reason: str


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

class RedundancyRecord(BaseModel):      # stage 2 output, one per email
    email_id: str
    nearest: str | None                 # email_id of the most similar earlier email
    content_similarity: float | None    # cosine; None for the first email
    subject_score: float | None         # token-set similarity with that email, 0 to 1
    flagged: bool                       # potentially redundant

class TriageRecord(BaseModel):          # stage 3 output: Jev's answers, unmodified
    email_id: str
    criteria_version: str               # hash of the criteria files in force
    triage_probs: dict[str, float]      # Choice over the five labels
    ticker_probs: dict[str, float]      # Noul per ticker
    attention: float                    # Noul
    topic_probs: dict[str, float]       # Noul per topic label
    kind: str                           # most probable option; display only
    kind_probs: dict[str, float]        # Choice over the six email kinds
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

class NoteDraft(BaseModel):             # stage A model output
    summary: str                        # two sentences
    why_attention: str                  # one or two sentences
    action: Literal["reply", "attend", "decide", "read", "other"]
    deadline: datetime | None = None    # only when the email states one
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

class AttentionNote(NoteDraft):         # stage A output
    email_id: str
    sections: list[LinkedSection]  # type: ignore[assignment]  # code adds the email_id to each quote

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

class Thresholds(BaseModel):            # tuned/thresholds.json; overrides config.py
    pass_signal: float
    attention: float
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

class CallRecord(BaseModel):            # one model or embedding call; usage.json
    stage: str                          # a stage name, or "live" / "verify"
    email_id: str | None                # None for set-level calls
    model: str                          # model ID from config.py
    input_tokens: int
    output_tokens: int
    estimated: bool = False             # true when the provider reported no usage
    cache_hit: bool
    latency_ms: float                   # wall clock
    at: datetime

class StageTiming(BaseModel):           # one stage over one email, or over the set; usage.json
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

class Pillar(BaseModel):
    id: str                             # e.g. "NVDA.p1"
    statement: str
    wrong_if: str
    driver_ids: list[str]

class Thesis(BaseModel):                # data/seed/theses.json
    ticker: Ticker
    stance: Literal["long", "short"]
    size_bps: int
    conviction: Literal[1, 2, 3, 4, 5]
    pillars: list[Pillar]

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
