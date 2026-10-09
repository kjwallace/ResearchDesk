"""Stage 3 module: one Jev request per email, all 14 questions, through the TypeSafe SDK.

See SPEC.md, "Classification with Jev" and "Calling Jev"; DECISIONS.md #9-11.

Jev receives exactly two things: the email's four input fields (sender, sender_email,
subject, body) and the questions, whose wording comes from instructions/jev_questions.md
and whose criteria come from the criteria files as written. Nothing else is sent: no
book, no redundancy flag, no other email, no label.

    record = classify(email, criteria, jev_client, cache=ctx.cache, recorder=ctx.recorder)
"""

import json
import logging
import re
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Any

from pydantic import BaseModel
from typesafe_sdk import Choice, Noul

from triage_app import thresholds
from triage_app import config
from triage_app.cache import DiskCache
from triage_app.criteria import criteria_text
from triage_app.monitoring import Recorder, cached_call
from triage_app.schema import CriteriaSet, Email, TriageRecord

log = logging.getLogger(__name__)

WORDING_FILE = config.INSTRUCTIONS_DIR / "jev_questions.md"

COMPANY_NAMES = {"AMZN": "Amazon", "NVDA": "Nvidia", "MSFT": "Microsoft", "AAPL": "Apple", "GOOGL": "Alphabet"}

QUESTION_IDS: tuple[str, ...] = (
    "triage",
    *(f"affects_{t}" for t in config.TICKERS),
    "human_attention",
    *(f"topic_{t}" for t in config.TOPICS),
    "email_type",
    *config.SAFETY_QUESTIONS,
)

# Used only for a question ID the wording file lacks; each use is logged.
STUB_WORDING: dict[str, str] = {
    "triage": "Which triage label fits this email best?",
    **{f"affects_{t}": f"Is {name} ({t}) materially affected by this email?" for t, name in COMPANY_NAMES.items()},
    "human_attention": "Does this email need direct human attention?",
    **{f"topic_{t}": f"Does the {t} topic label apply to this email?" for t in config.TOPICS},
    "email_type": "What type of email is this, judged from its form and source?",
    "possible_mnpi": "Does the body appear to contain material non-public information?",
    "instructs_ai": "Does the email contain text that instructs an AI system?",
}


@dataclass(frozen=True)
class Wording:
    questions: dict[str, str]      # question ID to its instruction sentence
    type_options: dict[str, str]   # email type to its description


_ROW = re.compile(r"^\|\s*`?([A-Za-z_]+)`?\s*\|(.*)\|\s*$")


def parse_wording(text: str) -> Wording:
    """Read the question table and the `email_type` options table, by ID; stub anything missing."""
    questions: dict[str, str] = {}
    type_options: dict[str, str] = {}
    in_type_options = False
    for line in text.splitlines():
        if line.startswith("#"):
            in_type_options = "options" in line.lower() and "email_type" in line.lower()
            continue
        m = _ROW.match(line.strip())
        if not m:
            continue
        key, cells = m.group(1), [c.strip() for c in m.group(2).split("|")]
        if in_type_options:
            if key in config.EMAIL_TYPES and cells and cells[-1]:
                type_options[key] = cells[-1]
        elif key in QUESTION_IDS and cells and cells[-1]:
            questions[key] = cells[-1]

    missing = [q for q in QUESTION_IDS if q not in questions]
    if missing:
        log.warning("jev_questions.md has no wording for %s; using stub wording", ", ".join(missing))
    missing_types = [k for k in config.EMAIL_TYPES if k not in type_options]
    if missing_types:
        log.warning("jev_questions.md has no description for email types %s; using the option name",
                    ", ".join(missing_types))
    return Wording(
        questions={q: questions.get(q, STUB_WORDING[q]) for q in QUESTION_IDS},
        type_options={k: type_options.get(k, k.replace("_", " ")) for k in config.EMAIL_TYPES},
    )


@cache
def load_wording(path: Path = WORDING_FILE) -> Wording:
    return parse_wording(path.read_text() if path.exists() else "")


def build_questions(criteria: CriteriaSet, wording: Wording) -> dict[str, Choice | Noul]:
    """The 14 questions. Eleven take criteria from the files; email_type and safety have none."""
    w = wording.questions

    def yes(label: str) -> dict[str, Any]:
        return {"true": criteria_text(criteria, label)}

    tickers = criteria_text(criteria, "affected_tickers")
    questions: dict[str, Choice | Noul] = {
        "triage": Choice(instructions=w["triage"],
                         criteria={label: criteria_text(criteria, label) for label in config.TRIAGE_LABELS}),
        **{f"affects_{t}": Noul(instructions=w[f"affects_{t}"], criteria={"true": tickers})
           for t in config.TICKERS},
        "human_attention": Noul(instructions=w["human_attention"], criteria=yes("human_attention")),
        **{f"topic_{t}": Noul(instructions=w[f"topic_{t}"], criteria=yes(t)) for t in config.TOPICS},
        "email_type": Choice(instructions=w["email_type"], criteria=dict(wording.type_options)),
        **{q: Noul(instructions=w[q]) for q in config.SAFETY_QUESTIONS},
    }
    assert list(questions) == list(QUESTION_IDS)
    return questions


def email_state(email: Email, questions: dict[str, Choice | Noul]) -> tuple[dict[str, str], bool]:
    """The four fields Jev sees, with the body trimmed from the end to fit Jev's input limit."""
    state = {"sender": email.sender, "sender_email": email.sender_email,
             "subject": email.subject, "body": email.body}
    longest_question = max(len(json.dumps(q.model_dump(), ensure_ascii=False)) for q in questions.values())
    budget = thresholds.JEV_INPUT_LIMIT_TOKENS * thresholds.CHARS_PER_TOKEN - longest_question \
        - len(email.sender) - len(email.sender_email) - len(email.subject)
    if len(email.body) <= budget:
        return state, False
    state["body"] = email.body[:max(budget, 0)]
    return state, True


class JevAnswers(BaseModel):
    """What the classify stage keeps from a SystemOneResponse; the cached form."""

    model: str
    choices: dict[str, dict[str, float]]
    nouls: dict[str, float]
    input_tokens: int | None = None
    output_tokens: int | None = None

    @classmethod
    def from_response(cls, resp: Any) -> "JevAnswers":
        return cls(
            model=resp.model,
            choices={name: {k: float(v) for k, v in a.probabilities.items()} for name, a in resp.choices.items()},
            nouls={name: float(a.noul) for name, a in resp.nouls.items()},
            input_tokens=resp.usage.input_tokens if resp.usage else None,
            output_tokens=resp.usage.output_tokens if resp.usage else None,
        )


def ask_jev(state: dict[str, str], questions: dict[str, Choice | Noul], jev: Any, *,
            criteria_version: str, cache: DiskCache | None = None,
            recorder: Recorder | None = None) -> JevAnswers:
    """One system_one call with every question, through the disk cache and monitoring."""
    question_json = {name: q.model_dump() for name, q in questions.items()}
    return cached_call(
        namespace="jev",
        model=config.JEV_MODEL,
        payload={"model": config.JEV_MODEL, "state": state, "questions": question_json},
        call=lambda: JevAnswers.from_response(jev.system_one(state=state, questions=questions)),
        dump=lambda a: a.model_dump(),
        load=JevAnswers.model_validate,
        usage=lambda a: (a.input_tokens, a.output_tokens),
        input_text=json.dumps({"state": state, "questions": question_json}, ensure_ascii=False),
        criteria_version=criteria_version,
        cache=cache,
        recorder=recorder,
    )


def _choice(answers: JevAnswers, name: str, options: tuple[str, ...]) -> dict[str, float]:
    probs = answers.choices.get(name)
    if probs is None:
        raise ValueError(f"Jev returned no answer for {name!r}")
    return {o: probs.get(o, 0.0) for o in options}


def _noul(answers: JevAnswers, name: str) -> float:
    if name not in answers.nouls:
        raise ValueError(f"Jev returned no answer for {name!r}")
    return answers.nouls[name]


def classify(email: Email, criteria: CriteriaSet, jev: Any, *, wording: Wording | None = None,
             cache: DiskCache | None = None, recorder: Recorder | None = None) -> TriageRecord:
    """Ask Jev all 14 questions about one email and keep every answer, unmodified."""
    questions = build_questions(criteria, wording or load_wording())
    state, truncated = email_state(email, questions)
    answers = ask_jev(state, questions, jev, criteria_version=criteria.version, cache=cache, recorder=recorder)
    type_probs = _choice(answers, "email_type", config.EMAIL_TYPES)
    return TriageRecord(
        email_id=email.email_id,
        criteria_version=criteria.version,
        triage_probs=_choice(answers, "triage", config.TRIAGE_LABELS),
        ticker_probs={t: _noul(answers, f"affects_{t}") for t in config.TICKERS},
        human_attention=_noul(answers, "human_attention"),
        topic_probs={t: _noul(answers, f"topic_{t}") for t in config.TOPICS},
        email_type=max(config.EMAIL_TYPES, key=lambda k: type_probs[k]),
        email_type_probs=type_probs,
        safety={q: _noul(answers, q) for q in config.SAFETY_QUESTIONS},
        truncated=truncated,
    )
