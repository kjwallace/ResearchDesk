"""Stage 7 Validate: suggestions_raw.json, claims.json, the corpus emails, results.json -> suggestions_checked.json.

Pure code; no generative model. See SPEC.md: Validation in stage 7. Rules run in this
fixed order, and the first rule that rejects ends the check:

1. Unknown item (reject): a claim ID that is not one of the email's claims; a section
   quoting another email; a pillar outside the candidate set recomputed from the claims'
   tickers plus the pillars links.json ties to them; a new thesis on a ticker outside
   the claims' tickers; a new pillar naming a driver that is not its own company's.
2. Quote mismatch (reject): a section not found verbatim in the email body (`quote_in`).
3. Duplicate thesis (reject): a new-thesis statement whose cosine with any existing
   pillar statement reaches `thresholds.NEW_THESIS_DUPLICATE` (stage 2 embedding model).
4. Monitor only: every linked email is labeled monitor. Strength becomes 1; a new-thesis
   candidate is rejected.
5. Out of bounds (keep, drop the figure): a stated value outside the driver's bounds, or
   a driver the pillar is not linked to.
6. Wrong period (keep, drop the figure): no claim of the suggestion states the figure for
   exactly the company's modeled fiscal year (period missing or different).
7. Second look (keep, mark): no linked email is labeled thesis_relevant or monitor.

A rejected suggestion keeps everything it had, with status "rejected" and a one-line
`reject_reason`.
"""

import math
from collections import defaultdict
from collections.abc import Collection
from pathlib import Path

import numpy as np

from triage_app import thresholds
from triage_app import config
from triage_app.embed import Vector
from triage_app.pipeline.context import RunContext
from triage_app.pipeline.io import quote_in, read_list, write_list
from triage_app.schema import (
    Claim,
    CompanyModel,
    Email,
    EmailResult,
    ExistingThesis,
    LinkedAssumption,
    NewThesis,
    Pillar,
    Suggestion,
)
from triage_app.state.fold import Seed, load_seed

STAGE = "validate"
SIGNAL_LABELS = ("thesis_relevant", "monitor")


class Rejected(Exception):
    """Raised by a rule that rejects; the message is the one-line reason."""


class ValidationInputs:
    """Everything the rules look up: the set's claims, email bodies and results, and the book."""

    def __init__(self, claims: list[Claim], emails: list[Email], results: list[EmailResult],
                 seed: Seed) -> None:
        self.claims: dict[str, Claim] = {c.id: c for c in claims}
        self.bodies: dict[str, str] = {e.email_id: e.body for e in emails}
        self.results: dict[str, EmailResult] = {r.email_id: r for r in results}
        self.models: dict[str, CompanyModel] = {m.ticker: m for m in seed.models}
        self.pillars: dict[str, Pillar] = {p.id: p for t in seed.theses for p in t.pillars}
        self.links: dict[str, list[str]] = defaultdict(list)
        for link in seed.links:
            self.links[link.from_ticker].extend(link.to_pillar_ids)
        self._pillar_vectors: Vector | None = None

    def candidates(self, tickers: Collection[str]) -> set[str]:
        """Every pillar of each ticker, plus the pillars the links tie to those tickers."""
        found = {pid for pid in self.pillars if pid.split(".")[0] in tickers}
        for ticker in tickers:
            found.update(self.links.get(ticker, []))
        return found

    def pillar_vectors(self, ctx: RunContext) -> tuple[list[str], Vector]:
        ids = list(self.pillars)
        if self._pillar_vectors is None:
            self._pillar_vectors = ctx.embedder.embed([self.pillars[i].statement for i in ids])
        return ids, self._pillar_vectors


def email_of(suggestion_id: str) -> str:
    """The email a raw suggestion came from: `<email_id>.s<n>`."""
    return suggestion_id.rsplit(".s", 1)[0]


def linked_emails(suggestion: Suggestion) -> list[str]:
    """Every email a suggestion links to, by its sections and claims, in first-seen order."""
    ids = [s.email_id for s in suggestion.sections] + [c.rsplit(".c", 1)[0] for c in suggestion.claim_ids]
    return list(dict.fromkeys(ids))


def needs_second_look(suggestion: Suggestion, results: dict[str, EmailResult]) -> bool:
    return not any(_label(results, e) in SIGNAL_LABELS for e in linked_emails(suggestion))


def _label(results: dict[str, EmailResult], email_id: str) -> str | None:
    result = results.get(email_id)
    return result.triage if result else None


def _check_unknown(suggestion: Suggestion, email_id: str, inputs: ValidationInputs) -> None:
    for cid in suggestion.claim_ids:
        claim = inputs.claims.get(cid)
        if claim is None or claim.email_id != email_id:
            raise Rejected(f"unknown item: {cid} is not a claim of {email_id}")
    for section in suggestion.sections:
        if section.email_id != email_id:
            raise Rejected(f"unknown item: section quotes {section.email_id}, not {email_id}")
    tickers = {t for cid in suggestion.claim_ids for t in inputs.claims[cid].tickers}
    body = suggestion.body
    if isinstance(body, ExistingThesis):
        if body.pillar_id not in inputs.candidates(tickers):
            raise Rejected(f"unknown item: pillar {body.pillar_id} is not a candidate for the claims' tickers")
    elif isinstance(body, NewThesis):
        if body.ticker not in tickers:
            raise Rejected(f"unknown item: new thesis on {body.ticker}, outside the claims' tickers")
        own = {d.id for d in inputs.models[body.ticker].drivers} if body.ticker in inputs.models else set()
        for driver_id in body.driver_ids:
            if driver_id not in own:
                raise Rejected(f"unknown item: driver {driver_id} is not a driver of {body.ticker}")
    else:
        raise Rejected(f"unknown item: stage 6 does not raise {body.kind}")


def _check_quotes(suggestion: Suggestion, inputs: ValidationInputs) -> None:
    for section in suggestion.sections:
        if not quote_in(section.quote, inputs.bodies.get(section.email_id, "")):
            raise Rejected(f"quote mismatch: section not found in {section.email_id}")


def _check_duplicate(body: NewThesis, inputs: ValidationInputs, ctx: RunContext) -> None:
    ids, vectors = inputs.pillar_vectors(ctx)
    if not ids:
        return
    sims = vectors @ ctx.embedder.embed([body.statement])[0]
    best = int(np.argmax(sims))
    if float(sims[best]) >= thresholds.NEW_THESIS_DUPLICATE:
        raise Rejected(f"duplicate thesis: statement matches {ids[best]} ({float(sims[best]):.2f})")


def _figure_in_bounds(a: LinkedAssumption, pillar: Pillar | None, model: CompanyModel | None) -> bool:
    if pillar is None or model is None or a.driver_id not in pillar.driver_ids:
        return False
    driver = next((d for d in model.drivers if d.id == a.driver_id), None)
    return driver is not None and driver.min <= a.stated_value <= driver.max


def _figure_in_period(a: LinkedAssumption, claims: list[Claim], model: CompanyModel | None) -> bool:
    if model is None:
        return False
    return any(c.value is not None and math.isclose(c.value, a.stated_value) and c.period == model.fiscal_year
               for c in claims)


def check(suggestion: Suggestion, ctx: RunContext, inputs: ValidationInputs) -> Suggestion:
    """Apply rules 1 to 7 in order; raises Rejected at the first rule that rejects."""
    email_id = email_of(suggestion.id)
    _check_unknown(suggestion, email_id, inputs)
    _check_quotes(suggestion, inputs)
    body = suggestion.body
    if isinstance(body, NewThesis):
        _check_duplicate(body, inputs, ctx)
    monitor_only = all(_label(inputs.results, e) == "monitor" for e in linked_emails(suggestion))
    if isinstance(body, NewThesis):
        if monitor_only:
            raise Rejected("monitor only: a new thesis needs an email not labeled monitor")
    elif isinstance(body, ExistingThesis):
        pillar = inputs.pillars.get(body.pillar_id)
        model = inputs.models.get(body.pillar_id.split(".")[0])
        claims = [inputs.claims[c] for c in suggestion.claim_ids]
        kept = [a for a in body.assumptions
                if _figure_in_bounds(a, pillar, model) and _figure_in_period(a, claims, model)]
        body = body.model_copy(update={"strength": 1 if monitor_only else body.strength, "assumptions": kept})
    checked = suggestion.model_copy(update={"body": body})
    return checked.model_copy(update={"second_look": needs_second_look(checked, inputs.results)})


def process(suggestion: Suggestion, ctx: RunContext, inputs: ValidationInputs) -> Suggestion:
    """Valid, adjusted (figure dropped, strength capped, second look), or rejected with a reason."""
    if suggestion.status != "open":
        return suggestion
    try:
        return check(suggestion, ctx, inputs)
    except Rejected as reason:
        return suggestion.model_copy(update={"status": "rejected", "reject_reason": str(reason)})


def run(in_dir: Path, out_dir: Path, ctx: RunContext, seed: Seed | None = None) -> None:
    raw = read_list(in_dir / "suggestions_raw.json", Suggestion)
    inputs = ValidationInputs(
        claims=read_list(in_dir / "claims.json", Claim),
        emails=ctx.emails,
        results=read_list(in_dir / "results.json", EmailResult),
        seed=seed or load_seed(),
    )
    by_email: dict[str, list[Suggestion]] = defaultdict(list)
    for s in raw:
        by_email[email_of(s.id)].append(s)
    checked: list[Suggestion] = []
    for email_id, suggestions in by_email.items():
        with ctx.recorder.stage(STAGE, email_id):
            checked.extend(process(s, ctx, inputs) for s in suggestions)
    write_list(out_dir / "suggestions_checked.json", checked)
