"""Display names for the app: every enum, key and stage name a person reads, in one place.

The pipeline's values (`thesis_relevant`, `pass`, `human_attention`, ...) stay as they are in
the stage files; only what reaches the screen is turned into words here. IDs (email, pillar,
driver, suggestion, criteria version) are shown as written, in a monospace style.
"""

import re
from datetime import date, datetime
from functools import cache

from triage_app import config

NAMES: dict[str, str] = {
    # Triage labels and flags
    # Triage labels, in plain words; the pipeline's values are unchanged.
    "thesis_relevant": "Actionable", "monitor": "Worth watching", "redundant": "Already known",
    "low_value": "Low priority", "irrelevant": "Not relevant", "human_attention": "Attention required",
    "quarantined": "Quarantined", "unlabeled": "Unlabeled",
    # Topics
    "macro": "Macro", "sector": "Sector", "government": "Government", "other": "Other",
    "affected_tickers": "Companies affected",
    # Gate and who decided
    "pass": "Passed", "stop": "Stopped", "quarantine": "Quarantined",
    "jev": "The classifier", "redundancy_check": "Repeat check",
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
    "pillar_edited": "Pillar edited", "pillar_removed": "Pillar removed", "projection_noted": "Projection noted",
    "projection_change": "Projection change",
    # Street view
    "buy": "Buy", "hold": "Hold", "sell": "Sell", "toward_buy": "Toward buy", "toward_sell": "Toward sell",
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
    "human_attention_precision": "Attention-required precision", "human_attention_recall": "Attention-required recall",
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
    s = ids_in_text("" if text is None else str(text))
    return s[:1].upper() + s[1:]


def _lower(token: str) -> str:
    name = NAMES.get(token) or MEASURES.get(token) or STAGES.get(token)
    if name is None:
        return token.replace("_", " ")
    # Mid-sentence, keep proper nouns and acronyms (Jev, MNPI, AI) and lower the rest.
    words = name.split(" ")
    return " ".join(w if w.isupper() else w.lower() for w in words)


def prose(text: object) -> str:
    """Code-written text (gate reasons, trace details, reject reasons) made readable for display:
    known snake_case keys become words and the first letter is capitalized. IDs such as
    `synthetic_000001` or `NVDA.p2` are kept as written."""
    s = "" if text is None else str(text)
    s = ids_in_text(s)
    s = re.sub(r"\bjev\b", "classifier", s)
    # One-word labels where a reason names them: "monitor 0.76", "redundant: repeat of ...".
    s = re.sub(r"\b(monitor|redundant|irrelevant)\b(?=:| \d)", lambda m: _lower(m.group(1)), s)
    s = re.sub(r"\bclassifier (?=[a-z][a-z ]* \d)", "classifier: ", s)
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


def verdict(result: object) -> str:
    """What happened to an email, in words and without scores (the scores sit behind "View scores")."""
    gate = getattr(result, "gate", None)
    if gate == "quarantine":
        return "Held in quarantine: the body is never summarized or sent to a model."
    label = human(getattr(result, "triage", None)).lower()
    if getattr(result, "decided_by", None) == "redundancy_check":
        first = "Already known: it repeats an earlier email."
    else:
        first = f"Classified as {label}."
    second = "Passed on for analysis." if gate == "pass" else "Stopped before analysis."
    return f"{first} {second}"


# ---- IDs as words: "AAPL.p1" -> "AAPL pillar 1", "synthetic_000197" -> "Email 197" ----

_STANCE_WORDS = {"supports": "Supports", "contradicts": "Contradicts", "review": "Conviction review"}
_EMAIL_ID = r"(?:synthetic|fixture|live)_\d+"
_ID_PATTERN = re.compile(
    rf"\b(?P<email>{_EMAIL_ID})(?:\.(?P<rest>[A-Za-z0-9_.]+?))?(?=[^A-Za-z0-9_.]|\.(?:\s|$)|$)"
    r"|\b(?P<ticker>[A-Z]{2,5})\.(?P<item>p\d+(?:\.(?:supports|contradicts|review))?|new\d+"
    r"|[a-z][a-z_]*[a-z](?:\.proj\d+)?)\b"
)


@cache
def _driver_units() -> dict[str, str]:
    from triage_app.state.fold import load_seed
    return {d.id: d.unit for m in load_seed().models for d in m.drivers}


@cache
def _driver_labels() -> dict[str, str]:
    from triage_app.state.fold import load_seed
    return {d.id: d.label for m in load_seed().models for d in m.drivers}


def _email_name(email_id: str) -> str:
    kind, _, number = email_id.partition("_")
    return f"{'Live email' if kind == 'live' else 'Email'} {int(number)}"


def _item_name(ticker: str, item: str) -> str:
    if m := re.fullmatch(r"p(\d+)(?:\.(supports|contradicts|review))?", item):
        name = f"{ticker} pillar {m.group(1)}"
        return f"{name} · {_STANCE_WORDS[m.group(2)]}" if m.group(2) else name
    if m := re.fullmatch(r"new(\d+)", item):
        return f"{ticker} new thesis {m.group(1)}"
    if m := re.fullmatch(r"([a-z][a-z_]*[a-z])\.proj(\d+)", item):
        return f"{ticker} {metric_name(ticker, m.group(1))} · projection {m.group(2)}"
    if item in OUTPUT_METRICS:
        return f"{ticker} {OUTPUT_METRICS[item][0]}"
    return _driver_labels().get(f"{ticker}.{item}", f"{ticker} {item.replace('_', ' ')}")


def pretty_id(value: object) -> str:
    """One ID as words; anything that is not an ID is returned as written."""
    text = "" if value is None else str(value)
    m = _ID_PATTERN.fullmatch(text)
    if m is None:
        return text
    if m.group("email"):
        email = _email_name(m.group("email"))
        rest = m.group("rest")
        if not rest:
            return email
        if s := re.fullmatch(r"s(\d+)", rest):
            return f"Suggestion {s.group(1)} from {email.lower()}"
        inner = pretty_id(rest)
        return f"{inner} (from {email.lower()})"
    return _item_name(m.group("ticker"), m.group("item"))


def ids_in_text(text: str) -> str:
    """Every ID inside a sentence rewritten as words."""
    return _ID_PATTERN.sub(lambda m: pretty_id(m.group(0)), text)


# ---- Positions in dollars and shares (synthetic NAV and reference prices, display only) ----

def position_usd(size_bps: float) -> float:
    from triage_app import thresholds
    return size_bps / 10_000 * thresholds.SYNTHETIC_NAV_USD


def position_shares(ticker: str, size_bps: float) -> int:
    from triage_app import thresholds
    return round(position_usd(size_bps) / thresholds.SYNTHETIC_PRICE_USD[ticker])


def money(usd: float) -> str:
    """$30.0m, $1.2bn, $950k."""
    if abs(usd) >= 1e9:
        return f"${usd / 1e9:,.1f}bn"
    if abs(usd) >= 1e6:
        return f"${usd / 1e6:,.1f}m"
    return f"${usd / 1e3:,.0f}k"


def position(ticker: str, size_bps: float) -> str:
    """'$30.0m · 166,667 shares'."""
    return f"{money(position_usd(size_bps))} · {position_shares(ticker, size_bps):,} shares"


# ---- The criteria page: files grouped by what they decide ----

CRITERIA_GROUPS: list[tuple[str, str, str, list[str]]] = [
    ("categories", "Email categories",
     "Which of the five categories each email falls into. Every email gets exactly one.",
     ["thesis_relevant", "monitor", "redundant", "low_value", "irrelevant"]),
    ("attention", "Attention required",
     "Whether an email asks a person on the desk to act, such as accept a meeting or answer a question.",
     ["human_attention"]),
    ("topics", "Topics and companies",
     "Which topics an email touches and which of the five covered companies it materially affects.",
     ["macro", "sector", "government", "other", "affected_tickers"]),
]



# ---- Projection metrics: a driver, or one of the computed outputs ----

OUTPUT_METRICS: dict[str, tuple[str, str]] = {   # metric: (name, unit)
    "revenue": ("revenue", "usd_bn"), "operating_income": ("operating income", "usd_bn"),
    "eps": ("EPS", "usd"), "target_price": ("target price", "usd"),
}


def metric_name(ticker: str, metric: str) -> str:
    """'EPS', 'revenue', or a driver's label for a driver metric (given as an ID or a bare name)."""
    if metric in OUTPUT_METRICS:
        return OUTPUT_METRICS[metric][0]
    driver_id = metric if "." in metric else f"{ticker}.{metric}"
    return _driver_labels().get(driver_id, metric.replace("_", " "))


def metric_value(metric: str, value: float | None, unit: str | None = None) -> str:
    """A projection figure with its unit: '12.5%', '$81.0bn', '$6.55'."""
    if value is None:
        return ""
    unit = unit or (OUTPUT_METRICS[metric][1] if metric in OUTPUT_METRICS else _driver_units().get(metric, "pct"))
    if unit == "usd_bn":
        return f"${value:,.1f}bn"
    if unit == "usd":
        return f"${value:,.2f}"
    return f"{value:,.1f}%"


# ---- What each evaluation measure means, in a sentence ----

MEASURE_EXPLAINERS: dict[str, str] = {
    "gate_recall": "Of the emails that should reach analysis, the share that did. Misses here are insights lost.",
    "monitor_gate_recall": "The same for emails worth watching: how many reached analysis.",
    "gate_reduction": "The share of all email stopped before analysis, so no analyst or model spends time on it.",
    "signal_accuracy": "How often the classifier sorts an email correctly into signal, already known, or noise.",
    "triage_accuracy": "How often the exact category (one of five) matches the reference label.",
    "ticker_f1": "How well the companies tagged on each email match the companies it really affects.",
    "human_attention_precision": "Of the emails flagged as needing a person, the share that really did.",
    "human_attention_recall": "Of the emails that needed a person, the share that were flagged.",
    "topic_f1": "How well the topic tags (macro, sector, government, other) match the reference tags.",
    "repeat_flagged": "How many emails the repeat check flagged as repeating an earlier one today.",
    "repeat_precision": "Of the flagged repeats, the share the reference labels call already known.",
    "stray_suggestions": "Suggestions whose only emails were low priority, not relevant or already known.",
    "quote_faithfulness": "The share of quoted passages that appear word for word in their email.",
    "meetings_share": "The share of email that is meeting requests, event invitations or newsletters.",
    "email_type_accuracy": "How often the email type (research, news alert, meeting request…) matches the reference.",
    "note_review": "Share of attention notes a reviewer judged accurate, with the reason and action stated.",
    "suggestion_review": "Share of suggestions a reviewer judged to have the right pillar, stance and evidence.",
    "new_thesis_review": "Share of new-thesis candidates a reviewer judged new to the book and well supported.",
}
