"""Every threshold, limit and tunable number in the pipeline, in one place.

This is the only module that defines them. Code everywhere reads `thresholds.NAME`; no
other module writes one of these numbers. To audit or change a value, change it here.

"Set by" says how each value is chosen (SPEC.md, "Starting values" and "Tuning"):
  fixed     chosen by hand, never tuned
  sweep     a starting value; `evals/tune.py` fits it on the tuning set's fit split and
            writes tuned/thresholds.json, which overrides it at run time (`load_thresholds`)

Model IDs are not numbers and live only in .env (see config.py).
"""

from pathlib import Path

from triage_app.schema import Thresholds, Ticker, Topic

# ---- Stage 4: label and gate ----------------------------------------------------------

PASS_SIGNAL = 0.6            # sweep  signal score P(thesis_relevant)+P(monitor) that passes the gate
HUMAN_ATTENTION = 0.6        # sweep  human_attention probability that flags human attention
TICKER_THRESHOLD = 0.5       # sweep  per-ticker probability that lists a company (each ticker tuned)
TOPIC_THRESHOLD = 0.5        # sweep  per-topic probability that lists a topic (each topic tuned)
QUARANTINE = 0.65            # fixed  either safety probability (possible_mnpi, instructs_ai) that quarantines
SIGNAL_SCORE_DECIMALS = 6    # fixed  signal score is rounded before comparing, so 0.3 + 0.3 counts as 0.60

# ---- Stage 2: redundancy check (fixed: the corpus has no redundant_of labels) ---------

CONTENT_SIMILARITY = 0.85                # fixed  cosine that flags a repeat on content alone
CONTENT_SIMILARITY_WITH_SUBJECT = 0.75   # fixed  cosine that flags a repeat when subjects match
SUBJECT_MATCH = 0.6                      # fixed  token-set subject similarity that counts as a match
EMBEDDING_MAX_TOKENS = 512               # fixed  fallback input limit if the embedder reports none
SPECIAL_TOKEN_HEADROOM = 8               # fixed  tokens kept free under that limit when chunking

# ---- Stage 3: Jev -------------------------------------------------------------------------

JEV_INPUT_LIMIT_TOKENS = 32_000   # fixed  email plus the longest question; beyond it the body is trimmed
CHARS_PER_TOKEN = 4               # fixed  token estimate where a provider reports none

# ---- Stages 6 to 8: analysis, validation, merging ----------------------------------------

SKILL_CALLS_PER_EMAIL = 3         # fixed  analysis-agent skill calls per email
NEW_THESIS_DUPLICATE = 0.8        # fixed  cosine at which a new thesis duplicates an existing pillar (rejected)
NEW_THESIS_MERGE = 0.8            # fixed  cosine at which two new-thesis candidates merge

# ---- Delivery, alerts and the book --------------------------------------------------------

ALERTS_PER_DAY = 3                # fixed  alert budget; overflow stays in the brief
ALERT_HUMAN_ATTENTION = 0.8       # fixed  human_attention probability that raises an alert
ALERT_WRONG_IF_MIN_BPS = 150      # fixed  position size at which a met "wrong if" test raises an alert
CONVICTION_REVIEW_STRENGTH = 4    # fixed  net contradicting strength on a pillar that raises a conviction review

# ---- Verify agent -------------------------------------------------------------------------

VERIFY_TOOL_CALLS = 4             # fixed  tool calls per verify request
PASSAGE_CHARS = 1200              # fixed  filing passages are cut at this length (inside the embedder's limit)
MIN_PASSAGE_CHARS = 80            # fixed  shorter paragraphs join the next one
VERIFY_FILING_RESULTS = 3         # fixed  filing passages a filing search returns by default
VERIFY_LOG_RESULTS = 5            # fixed  change-log entries a log search returns by default

# ---- Live route ---------------------------------------------------------------------------

LIVE_INPUT_CAP_CHARS = 10_000     # fixed  longest pasted email accepted
LIVE_RUNS_PER_HOUR = 5            # fixed  live runs (and "this mattered") per visitor session
LIVE_RATE_WINDOW_S = 3600.0       # fixed  window for that limit, in seconds
LIVE_RUNS_PER_HOUR_GLOBAL = 60    # fixed  live runs per hour across every session (pastes, "this mattered", verify, cold presets)
SESSION_IDLE_TTL_S = 86400.0      # fixed  a visitor session idle this long is evicted from server memory
MAX_SESSIONS = 1000               # fixed  sessions held in memory; the least recently used is evicted beyond it

# ---- App screens ----------------------------------------------------------------------------


# ---- Model calls --------------------------------------------------------------------------

LLM_TEMPERATURE = 0.0             # fixed  every generative call
LLM_MAX_TOKENS = 4096             # fixed  default output cap for a chat call
DSPY_MAX_TOKENS = 8000            # fixed  output cap for DSPy modules (notes, extraction, skills, agents)
LLM_TIMEOUT_S = 300.0             # fixed  OpenRouter request timeout
JEV_TIMEOUT_S = 60.0              # fixed  TypeSafe request timeout
OPENROUTER_REQUESTS_PER_MINUTE = 20   # fixed  client-side throttle per model (OpenRouter's new-account limit)
LLM_MAX_RETRIES = 6               # fixed  retries on 429 / 5xx before a call fails
LLM_RETRY_BASE_S = 5.0            # fixed  first backoff when the provider gives no reset time (doubles each retry)
LLM_RETRY_MAX_S = 90.0            # fixed  longest single backoff
LLM_PARSE_RETRIES = 2             # fixed  fresh calls when a reply cannot be parsed, before the email fails

# ---- Criteria files -----------------------------------------------------------------------

RULES_PER_CRITERIA_FILE = 12      # fixed  most rules a criteria file may hold

# ---- Tuning (evals/tune.py) ---------------------------------------------------------------

MONITOR_PASS_SHARE = 0.95         # fixed  share of monitor emails the tuned pass threshold must still pass
PASS_THRESHOLD_DECIMALS = 4       # fixed  the tuned pass threshold is floored to this many decimals
SPLIT_SEED = 13                   # fixed  seed of the tuning set's fit/validation split
FIT_SHARE = 2 / 3                 # fixed  share of each label that goes to the fit split

# ---- Eval targets (SPEC "Evaluation and guardrails"; proposals, shown on the Eval page) -----

EVAL_TARGETS = {                  # fixed  eval.json key to its target share; keys not listed are reported only
    "gate_recall": 1.0, "monitor_gate_recall": 0.95, "signal_accuracy": 0.85, "ticker_f1": 0.90,
    "human_attention_recall": 0.90, "human_attention_precision": 0.80, "quote_faithfulness": 1.0,
    "note_review": 0.90, "suggestion_review": 0.90,
}

# ---- Corpus report targets (from the corpus prompt, per 300 emails; scaled by set size) --

TARGET_BASE = 300
TARGET_SHARES = {"thesis_relevant": 0.10, "monitor": 0.15, "redundant": 0.10, "low_value": 0.35, "irrelevant": 0.30}
HUMAN_ATTENTION_RANGE = (15, 25)
MACRO_SECTOR_GOVERNMENT_RANGE = (25, 35)


# ---- Thresholds the gate reads: starting values, overridden by tuned/thresholds.json ----

def starting_thresholds() -> Thresholds:
    from triage_app.config import TICKERS, TOPICS

    tickers: tuple[Ticker, ...] = TICKERS
    topics: tuple[Topic, ...] = TOPICS
    return Thresholds(
        pass_signal=PASS_SIGNAL,
        human_attention=HUMAN_ATTENTION,
        ticker={t: TICKER_THRESHOLD for t in tickers},
        topic={t: TOPIC_THRESHOLD for t in topics},
        content_similarity=CONTENT_SIMILARITY,
        content_similarity_with_subject=CONTENT_SIMILARITY_WITH_SUBJECT,
        subject_match=SUBJECT_MATCH,
    )


def load_thresholds(path: Path | None = None) -> Thresholds:
    """Tuned values from tuned/thresholds.json when it exists, starting values otherwise.

    The redundancy thresholds are fixed, so they always come from this module.
    """
    from triage_app.config import TUNED_THRESHOLDS

    path = path or TUNED_THRESHOLDS
    if not path.exists():
        return starting_thresholds()
    tuned = Thresholds.model_validate_json(path.read_text())
    return tuned.model_copy(update={
        "content_similarity": CONTENT_SIMILARITY,
        "content_similarity_with_subject": CONTENT_SIMILARITY_WITH_SUBJECT,
        "subject_match": SUBJECT_MATCH,
    })
