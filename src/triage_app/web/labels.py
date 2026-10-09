"""Display names for the app: every enum, key and stage name a person reads, in one place.

The pipeline's values (`thesis_relevant`, `pass`, `human_attention`, ...) stay as they are in
the stage files; only what reaches the screen is turned into words here. IDs (email, pillar,
driver, suggestion, criteria version) are shown as written, in a monospace style.
"""

import re
from datetime import date, datetime

from triage_app import config

NAMES: dict[str, str] = {
    # Triage labels and flags
    # Triage labels, in plain words; the pipeline's values are unchanged.
    "thesis_relevant": "Actionable", "monitor": "Worth watching", "redundant": "Already known",
    "low_value": "Low priority", "irrelevant": "Not relevant", "human_attention": "Needs a person",
    "quarantined": "Quarantined", "unlabeled": "Unlabeled",
    # Topics
    "macro": "Macro", "sector": "Sector", "government": "Government", "other": "Other",
    # Gate and who decided
    "pass": "Passed", "stop": "Stopped", "quarantine": "Quarantined",
    "jev": "Jev", "redundancy_check": "Repeat check",
    # Safety questions
    "possible_mnpi": "Possible MNPI", "instructs_ai": "Instructs an AI",
    # Email types
    "sell_side_research": "Sell-side research", "primary_research": "Primary research",
    "news_alert": "News alert", "newsletter": "Newsletter", "data_report": "Data report",
    "company_release": "Company release", "meeting_request": "Meeting request",
    "event_invitation": "Event invitation", "vendor_pitch": "Vendor pitch",
    "internal_forward": "Internal forward", "administrative": "Administrative",
    # Suggestions
    "existing_thesis": "Existing thesis", "new_thesis": "New thesis", "conviction_review": "Conviction review",
    "supports": "Supports", "contradicts": "Contradicts", "wrong_if_met": "Pillar at risk",
    "open": "Open", "accepted": "Accepted", "dismissed": "Dismissed", "rejected": "Rejected",
    "long": "Long", "short": "Short",
    # Note actions
    "reply": "Reply", "attend": "Attend", "decide": "Decide", "read": "Read",
    # Change log
    "pillar_evidence": "Evidence logged", "pillar_added": "Pillar added",
    "driver_updated": "Assumption updated", "conviction_changed": "Conviction changed",
    # Verify verdicts
    "confirmed": "Confirmed", "contradicted": "Contradicted", "not_found": "Not found",
    # Live-trace step status
    "ok": "Done", "skipped": "Skipped", "unavailable": "Not built", "failed": "Failed",
    # Tuning splits and units
    "fit": "Fit", "validation": "Validation", "pct": "%", "usd_bn": "$bn",
    # Sets
    "day_1": "Day 1", "day_2": "Day 2", "tuning": "Tuning set", "live": "Live",
    # Brief counts
    "passed": "Passed", "stopped": "Stopped", "notes": "Attention notes", "suggestions": "Suggestions",
}

# Pipeline stages, named as the spec's stage table names them.
STAGES: dict[str, str] = {
    "redundancy": "Check for repeats", "classify": "Classify", "gate": "Label and gate",
    "human_attention": "Attention note", "extract": "Extract claims", "analyze": "Analyze",
    "validate": "Validate", "merge": "Merge and rank", "deliver": "Deliver", "verify": "Verify",
}

# Keys of eval.json and of the criteria history.
MEASURES: dict[str, str] = {
    "gate_recall": "Gate recall", "monitor_gate_recall": "Monitor recall at the gate",
    "gate_reduction": "Gate reduction", "signal_accuracy": "Signal accuracy",
    "triage_accuracy": "Triage accuracy", "ticker_f1": "Ticker F1",
    "human_attention_precision": "Needs-a-person precision", "human_attention_recall": "Needs-a-person recall",
    "topic_f1": "Topic F1", "repeat_flagged": "Repeats flagged", "repeat_precision": "Repeat precision",
    "stray_suggestions": "Stray suggestions", "quote_faithfulness": "Quote faithfulness",
    "meetings_share": "Meeting-like share", "email_type_accuracy": "Email type accuracy",
    "note_review": "Attention note review", "suggestion_review": "Suggestion review",
    "new_thesis_review": "New-thesis review",
}

_TICKERS = frozenset(config.TICKERS)
_SNAKE = re.compile(r"\b[a-z]+(?:_[a-z0-9]+)+\b")


def human(value: object) -> str:
    """A pipeline value as a person reads it: `low_value` -> "Low value"; tickers stay as written."""
    if value is None:
        return ""
    text = str(value)
    if text in _TICKERS:
        return text
    if text in NAMES:
        return NAMES[text]
    if text in MEASURES:
        return MEASURES[text]
    return sentence(text.replace("_", " "))


def stage(name: str) -> str:
    return STAGES.get(name, human(name))


def measure(key: str) -> str:
    return MEASURES.get(key, human(key))


def sentence(text: object) -> str:
    """Capitalize the first letter only; the rest is left as written (IDs, tickers, figures)."""
    s = "" if text is None else str(text)
    return s[:1].upper() + s[1:]


def _lower(token: str) -> str:
    name = NAMES.get(token) or STAGES.get(token) or MEASURES.get(token)
    if name is None:
        return token.replace("_", " ")
    # Mid-sentence, keep proper nouns and acronyms (Jev, MNPI, AI) and lower the rest.
    words = name.split(" ")
    return " ".join(w if (w.isupper() or w == "Jev") else w.lower() for w in words)


def prose(text: object) -> str:
    """Code-written text (gate reasons, trace details, reject reasons) made readable for display:
    known snake_case keys become words and the first letter is capitalized. IDs such as
    `synthetic_000001` or `NVDA.p2` are kept as written."""
    s = "" if text is None else str(text)
    s = re.sub(r"\bjev\b", "Jev", s)
    s = _SNAKE.sub(lambda m: m.group(0) if re.search(r"\d{3,}", m.group(0)) else _lower(m.group(0)), s)
    return sentence(s)


# ---- Attention requests: who is asking, the offer, and when a reply is due ----

REQUEST_KINDS: dict[str, str] = {"meeting_request": "meeting", "event_invitation": "event"}
REQUEST_KIND_NAMES: dict[str, str] = {"meeting": "Meeting requests", "event": "Event invitations",
                                      "other": "Other requests"}
DUE_BUCKETS: dict[str, str] = {"today": "Due today", "tomorrow": "Due tomorrow", "later": "Due later",
                               "none": "No deadline stated"}
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+(?=[A-Z])")


def request_kind(email_type: str | None) -> str:
    return REQUEST_KINDS.get(email_type or "", "other")


def due_bucket(deadline: datetime | None, day: date) -> str:
    if deadline is None:
        return "none"
    days = (deadline.date() - day).days
    return "today" if days <= 0 else ("tomorrow" if days == 1 else "later")


def due(deadline: datetime | None, day: date) -> str:
    """When a reply is due, relative to the brief's day: "Today, 5:00 PM", "Wed Oct 21, end of day"."""
    if deadline is None:
        return "No deadline stated"
    days = (deadline.date() - day).days
    when = "Today" if days == 0 else ("Tomorrow" if days == 1 else deadline.strftime("%a %b %d").replace(" 0", " "))
    if (deadline.hour, deadline.minute) == (23, 59):
        return f"{when}, end of day"
    return f"{when}, {deadline.strftime('%I:%M %p').lstrip('0')}"


def split_summary(text: str) -> tuple[str, str]:
    """The note's first sentence (shown bold, as the offer) and the rest."""
    parts = _SENTENCE_END.split(text.strip(), maxsplit=1)
    return parts[0], parts[1] if len(parts) > 1 else ""


def sender_parts(sender: str) -> tuple[str, str, str]:
    """"Name, Role, Firm" as (name, role, firm); a sender with no commas is all name."""
    parts = [p.strip() for p in sender.split(",") if p.strip()]
    if len(parts) == 1:
        return parts[0], "", ""
    if len(parts) == 2:
        return parts[0], "", parts[1]
    return parts[0], ", ".join(parts[1:-1]), parts[-1]
