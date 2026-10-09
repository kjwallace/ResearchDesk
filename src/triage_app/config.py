"""Paths, corpus sets, labels and model-ID resolution.

Every threshold and tunable number lives in triage_app/thresholds.py; model IDs live
only in .env. Only the lead edits this file.
"""

import os
from pathlib import Path
from typing import Literal, get_args

from dotenv import load_dotenv

from triage_app.schema import Ticker, Topic, Triage

# ---- Paths ----

ROOT = Path(__file__).resolve().parents[2]
CORPUS_DIR = ROOT / "data" / "corpus"
SEED_DIR = ROOT / "data" / "seed"
FILINGS_DIR = ROOT / "data" / "filings"
OUT_DIR = ROOT / "data" / "out"
CACHE_DIR = ROOT / "data" / "cache"
LIVE_PRESETS_DIR = ROOT / "data" / "live_presets"
CRITERIA_DIR = ROOT / "criteria"
SKILLS_DIR = ROOT / "skills"
INSTRUCTIONS_DIR = ROOT / "instructions"
TOOLS_DIR = ROOT / "tools"
TUNED_THRESHOLDS = ROOT / "tuned" / "thresholds.json"
FIXTURES_DIR = ROOT / "tests" / "fixtures"

CorpusSet = Literal["day_1", "day_2", "tuning"]
CORPUS_SETS: tuple[CorpusSet, ...] = get_args(CorpusSet)
TEST_SETS: tuple[CorpusSet, ...] = ("day_1", "day_2")
SET_DATES: dict[CorpusSet, str] = {
    "day_1": "2026-10-13",
    "day_2": "2026-10-14",
    "tuning": "2026-10-15",
}
SET_TZ_OFFSET = "-04:00"  # US Eastern, daylight time in October
SET_WINDOW = ("05:30", "19:00")  # arrival window the loader spreads emails across


def corpus_file(corpus_set: CorpusSet) -> Path:
    return CORPUS_DIR / corpus_set / "emails.jsonl"


def out_dir(corpus_set: CorpusSet) -> Path:
    return OUT_DIR / corpus_set


# ---- Labels ----

TICKERS: tuple[Ticker, ...] = get_args(Ticker)
TRIAGE_LABELS: tuple[Triage, ...] = get_args(Triage)
TOPICS: tuple[Topic, ...] = get_args(Topic)
EMAIL_KINDS = ("research", "news", "company_release", "invitation", "newsletter", "other")
SAFETY_QUESTIONS = ("possible_mnpi", "instructs_ai")

CRITERIA_FILES = (
    "thesis_relevant", "monitor", "redundant", "low_value", "irrelevant",
    "human_attention", "macro", "sector", "government", "other", "affected_tickers",
)

# ---- Models ----
# Every model ID comes from .env (or the environment); none is defined here. Each name
# below is read when first used, so modules and tests that need no model never require it.
#   JEV_MODEL         TypeSafe model for stage 3, e.g. a pinned jev-<version>
#   ANALYSIS_MODEL    OpenRouter slug: extraction, analysis agent, verify agent, generation prompts
#   NOTES_MODEL       OpenRouter slug: attention notes
#   EMBEDDING_MODEL   Hugging Face repo ID, run locally: redundancy check, duplicate checks, filing search

MODEL_ENV_VARS = ("JEV_MODEL", "ANALYSIS_MODEL", "NOTES_MODEL", "EMBEDDING_MODEL")

load_dotenv(ROOT / ".env")


class MissingModelError(RuntimeError):
    pass


def model_id(name: str) -> str:
    """The model ID set in .env for `name`; raises when it is unset."""
    if name not in MODEL_ENV_VARS:
        raise KeyError(name)
    value = os.environ.get(name, "").strip()
    if not value:
        raise MissingModelError(f"{name} is not set; add it to .env (see .env.example)")
    return value


def __getattr__(name: str) -> str:
    # PEP 562: config.ANALYSIS_MODEL etc. resolve from the environment on access.
    if name in MODEL_ENV_VARS:
        return model_id(name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
