"""Validate tests/fixtures/: every stage file against its contract, and the spec's cross-file rules.

Run from the repo root:  uv run python tests/fixtures/validate_fixtures.py
Exits 1 and lists every failure when any check fails.
"""

import json
import re
import sys
from pathlib import Path

import numpy as np
from pydantic import BaseModel, TypeAdapter

from triage_app import config
from triage_app.monitoring import build_report
from triage_app.pipeline.io import normalize_ws, quote_in
from triage_app.schema import (
    AnalysisRecord, AttentionNote, Brief, CallRecord, Claim, CompanyModel, CriteriaHistoryEntry,
    Email, EmailLabel, EmailResult, EvalReport, ExistingThesis, Link, NewThesis, RedundancyRecord,
    StageTiming, Suggestion, Thesis, TriageRecord, UsageReport,
)

FIX = Path(__file__).resolve().parent
OUT = FIX / "out"
SEED = config.SEED_DIR
IDS = [f"fixture_{n:03d}" for n in range(1, 11)]
ROW_FIELDS = ["email_id", "sender", "sender_email", "subject", "body", "triage",
              "additional_labels", "affected_tickers", "human_attention", "reason",
              "email_type", "systemic", "angle", "day"]
LABEL_FIELDS = set(ROW_FIELDS) - {"email_id", "sender", "sender_email", "subject", "body"}

failures: list[str] = []


def check(ok: bool, msg: str) -> None:
    if not ok:
        failures.append(msg)


def load_list(name: str, model: type[BaseModel]) -> list:
    try:
        return TypeAdapter(list[model]).validate_json((OUT / name).read_text())  # type: ignore[valid-type]
    except Exception as e:  # noqa: BLE001
        failures.append(f"{name}: does not load as list[{model.__name__}]: {e}")
        return []


def load_one(name: str, model: type[BaseModel]):
    try:
        return model.model_validate_json((OUT / name).read_text())
    except Exception as e:  # noqa: BLE001
        failures.append(f"{name}: does not load as {model.__name__}: {e}")
        return None


def by_id(items: list) -> dict:
    return {i.email_id: i for i in items}


# ---- corpus rows and labels ----

rows = [json.loads(line) for line in (FIX / "emails.jsonl").read_text().splitlines() if line.strip()]
check([r.get("email_id") for r in rows] == IDS, "emails.jsonl: IDs must be fixture_001..fixture_010 in order")
for r in rows:
    check(list(r) == ROW_FIELDS, f"emails.jsonl {r.get('email_id')}: fields must be the 14 corpus fields in order")
    check(r.get("day") == 1, f"emails.jsonl {r.get('email_id')}: day must be 1")
check(any(r["triage"] == "relevent" for r in rows), "emails.jsonl: needs a row with triage 'relevent'")
check(any(t == "GOOG" or (t.islower()) for r in rows for t in r["affected_tickers"]),
      "emails.jsonl: needs a row with GOOG or a lower-case ticker")

labels = [EmailLabel.model_validate_json(line) for line in (FIX / "labels.jsonl").read_text().splitlines() if line.strip()]
LAB = by_id(labels)
check([lab.email_id for lab in labels] == IDS, "labels.jsonl: one label per fixture email, in order")
check(all(lab.redundant_of is None for lab in labels), "labels.jsonl: redundant_of must be null everywhere")

# ---- stage files load with their contracts ----

raw = load_list("raw.json", Email)
parsed = load_list("parsed.json", Email)
red = load_list("redundancy.json", RedundancyRecord)
tri = load_list("triage.json", TriageRecord)
results = load_list("results.json", EmailResult)
notes = load_list("notes.json", AttentionNote)
claims = load_list("claims.json", Claim)
analysis = load_list("analysis.json", AnalysisRecord)
s_raw = load_list("suggestions_raw.json", Suggestion)
s_chk = load_list("suggestions_checked.json", Suggestion)
s_fin = load_list("suggestions.json", Suggestion)
history = load_list("criteria_history.json", CriteriaHistoryEntry)
brief = load_one("brief.json", Brief)
ev = load_one("eval.json", EvalReport)
metrics = load_one("metrics.json", UsageReport)
try:
    usage = json.loads((OUT / "usage.json").read_text())
    check(set(usage) == {"calls", "timings"}, "usage.json: keys must be exactly calls and timings")
    calls = TypeAdapter(list[CallRecord]).validate_python(usage["calls"])
    timings = TypeAdapter(list[StageTiming]).validate_python(usage["timings"])
except Exception as e:  # noqa: BLE001
    failures.append(f"usage.json: does not load: {e}")
    calls, timings = [], []

for name, items in [("raw.json", raw), ("parsed.json", parsed), ("redundancy.json", red),
                    ("triage.json", tri), ("results.json", results)]:
    check([i.email_id for i in items] == IDS, f"{name}: one record per email, in arrival order")

# ---- stage 1 ----

ROW = {r["email_id"]: r for r in rows}
for f in ("raw.json", "parsed.json"):
    for item in json.loads((OUT / f).read_text()):
        check(not (set(item) & LABEL_FIELDS), f"{f} {item.get('email_id')}: holds label fields")
for a, b in zip(raw, parsed):
    check(a.body == ROW[a.email_id]["body"], f"raw.json {a.email_id}: body must be the corpus body")
    check(b.body == normalize_ws(a.body), f"parsed.json {a.email_id}: body must be the cleaned raw body")
    check((a.sender, a.sender_email, a.subject, a.received_at) == (b.sender, b.sender_email, b.subject, b.received_at),
          f"parsed.json {a.email_id}: header fields differ from raw.json")
    check(str(a.received_at.date()) == config.SET_DATES["day_1"], f"raw.json {a.email_id}: received_at not on day_1")
check(all(x.received_at < y.received_at for x, y in zip(raw, raw[1:])), "raw.json: received_at must increase")
BODY = {p.email_id: p.body for p in parsed}

# ---- stage 2 ----

V = np.load(OUT / "vectors.npy")
check(V.dtype == np.float32, f"vectors.npy: dtype {V.dtype}, want float32")
check(V.shape == (10, 8), f"vectors.npy: shape {V.shape}, want (10, 8)")
check(bool(np.allclose(np.linalg.norm(V, axis=1), 1.0, atol=1e-5)), "vectors.npy: rows must be L2-normalized")
RED = by_id(red)
for i, r in enumerate(red):
    if i == 0:
        check(r.nearest is None and r.content_similarity is None and r.subject_score is None and not r.flagged,
              "redundancy.json: first email must have no nearest and no scores")
        continue
    sims = V[:i] @ V[i]
    j = int(np.argmax(sims))
    check(r.nearest == IDS[j], f"redundancy.json {r.email_id}: nearest should be {IDS[j]}")
    check(r.content_similarity is not None and abs(r.content_similarity - float(sims[j])) < 1e-3,
          f"redundancy.json {r.email_id}: content_similarity disagrees with vectors.npy")
    c, s = r.content_similarity or 0.0, r.subject_score or 0.0
    want = c >= config.CONTENT_SIMILARITY or (c >= config.CONTENT_SIMILARITY_WITH_SUBJECT and s >= config.SUBJECT_MATCH)
    check(r.flagged == want, f"redundancy.json {r.email_id}: flagged={r.flagged} disagrees with the thresholds")

# ---- stage 3 and 4 ----

TRI = by_id(tri)
RES = by_id(results)
for t in tri:
    check(t.criteria_version == "fixture0000", f"triage.json {t.email_id}: criteria_version must be fixture0000")
    check(set(t.triage_probs) == set(config.TRIAGE_LABELS), f"triage.json {t.email_id}: triage_probs keys")
    check(abs(sum(t.triage_probs.values()) - 1) < 1e-6, f"triage.json {t.email_id}: triage_probs must sum to 1")
    check(set(t.ticker_probs) == set(config.TICKERS), f"triage.json {t.email_id}: ticker_probs keys")
    check(set(t.topic_probs) == set(config.TOPICS), f"triage.json {t.email_id}: topic_probs keys")
    check(set(t.kind_probs) == set(config.EMAIL_KINDS) and t.kind == max(t.kind_probs, key=t.kind_probs.get),
          f"triage.json {t.email_id}: kind must be the most probable of the six kinds")
    check(set(t.safety) == set(config.SAFETY_QUESTIONS), f"triage.json {t.email_id}: safety keys")

for r in results:
    t = TRI[r.email_id]
    sig = t.triage_probs["thesis_relevant"] + t.triage_probs["monitor"]
    check(abs(r.signal_score - sig) < 1e-3, f"results.json {r.email_id}: signal_score must be P(tr)+P(monitor)")
    check("\n" not in r.reason and r.reason.strip() != "", f"results.json {r.email_id}: reason must be one line")
    quarantined = max(t.safety.values()) >= config.QUARANTINE
    if quarantined:
        check(r.triage is None and r.decided_by == "quarantine" and r.gate == "quarantine"
              and r.affected_tickers == [] and r.additional_labels == [] and not r.human_attention
              and r.redundant_of is None,
              f"results.json {r.email_id}: quarantined result must have null label, empty lists, no attention")
        check(any(k in r.reason for k in config.SAFETY_QUESTIONS), f"results.json {r.email_id}: reason must name the safety question")
        continue
    check(r.triage is not None and r.gate != "quarantine", f"results.json {r.email_id}: not quarantined but marked so")
    passed = sig >= config.PASS_SIGNAL or t.truncated
    check(r.gate == ("pass" if passed else "stop"), f"results.json {r.email_id}: gate disagrees with signal score")
    check(f"signal score {sig:.2f}" in r.reason and f"{config.PASS_SIGNAL:.2f}" in r.reason,
          f"results.json {r.email_id}: reason must name the signal score and threshold")
    top = max(t.triage_probs, key=t.triage_probs.get)
    rr = RED[r.email_id]
    if r.decided_by == "redundancy_check":
        check(rr.flagged and not passed and top != "redundant" and r.triage == "redundant"
              and r.redundant_of == rr.nearest,
              f"results.json {r.email_id}: redundancy_check result must point to the flagged nearest email")
    else:
        check(r.decided_by == "jev" and r.triage == top and r.redundant_of is None,
              f"results.json {r.email_id}: jev result must carry Jev's top label and no redundant_of")
    check(r.affected_tickers == [x for x in config.TICKERS if t.ticker_probs[x] >= config.TICKER_THRESHOLD],
          f"results.json {r.email_id}: affected_tickers disagree with ticker_probs")
    check(r.additional_labels == [x for x in config.TOPICS if t.topic_probs[x] >= config.TOPIC_THRESHOLD],
          f"results.json {r.email_id}: additional_labels disagree with topic_probs")
    check(r.human_attention == (t.attention >= config.ATTENTION), f"results.json {r.email_id}: attention flag")

QUAR = {r.email_id for r in results if r.gate == "quarantine"}
PASSED = {r.email_id for r in results if r.gate == "pass"}
check(len(QUAR) == 2, "results.json: need exactly two quarantine cases")
check({TRI[i].safety["instructs_ai"] >= config.QUARANTINE for i in QUAR} == {True, False}
      and any(TRI[i].safety["possible_mnpi"] >= config.QUARANTINE for i in QUAR),
      "results.json: one quarantine must be instructs_ai and one possible_mnpi")
repeats = [r for r in results if r.decided_by == "redundancy_check"]
check(len(repeats) == 1, "results.json: need one same-day repeat decided by the redundancy check")
for r in repeats:
    a, b = IDS.index(r.redundant_of), IDS.index(r.email_id)
    check(a < b and float(V[a] @ V[b]) >= 0.85, "repeat pair: earlier email first and cosine >= 0.85")
    check(LAB[r.email_id].triage == "redundant", "repeat: corpus label must be redundant")

# ---- quotes: notes, claims, suggestions ----


def check_quote(where: str, email_id: str, q: str) -> None:
    check(email_id not in QUAR, f"{where}: refers to quarantined email {email_id}")
    check(email_id in BODY and quote_in(q, BODY[email_id]), f"{where}: quote not verbatim in {email_id}: {q!r}")


NOTE = by_id(notes)
check(set(NOTE) == {r.email_id for r in results if r.human_attention},
      "notes.json: exactly one note per email flagged for attention")
for n in notes:
    check(len(n.sections) > 0, f"notes.json {n.email_id}: needs sections")
    for s in n.sections:
        check(s.email_id == n.email_id, f"notes.json {n.email_id}: section from another email")
        check_quote(f"notes.json {n.email_id}", s.email_id, s.quote)

CLAIM = {c.id: c for c in claims}
for c in claims:
    check(c.email_id in PASSED, f"claims.json {c.id}: claim from an email that did not pass")
    check(re.fullmatch(rf"{re.escape(c.email_id)}\.c\d+", c.id) is not None, f"claims.json {c.id}: ID must be <email_id>.c<n>")
    check_quote(f"claims.json {c.id}", c.email_id, c.quote)
for eid in {c.email_id for c in claims}:
    ns = sorted(int(c.id.rsplit(".c", 1)[1]) for c in claims if c.email_id == eid)
    check(ns == list(range(1, len(ns) + 1)), f"claims.json {eid}: claim numbers must run 1..n")

check([a.email_id for a in analysis] == [i for i in IDS if i in PASSED], "analysis.json: one record per passed email, in order")
for a in analysis:
    check(bool(a.suggestion_ids) != bool(a.no_change_reason), f"analysis.json {a.email_id}: suggestions xor a no-change reason")
    check(len(a.skills_called) <= config.SKILL_CALLS_PER_EMAIL, f"analysis.json {a.email_id}: too many skill calls")
    if not any(c.email_id == a.email_id for c in claims):
        check(a.no_change_reason == "no claims extracted", f"analysis.json {a.email_id}: no claims must read 'no claims extracted'")

theses = [Thesis.model_validate(x) for x in json.loads((SEED / "theses.json").read_text())]
models = {m.ticker: m for m in (CompanyModel.model_validate(x) for x in json.loads((SEED / "models.json").read_text()))}
links = [Link.model_validate(x) for x in json.loads((SEED / "links.json").read_text())]
PILLAR = {p.id: p for t in theses for p in t.pillars}
SIZE = {t.ticker: t.size_bps for t in theses}
DRIVER = {d.id: d for m in models.values() for d in m.drivers}


def candidates(tickers: set[str]) -> set[str]:
    out = {p.id for t in theses if t.ticker in tickers for p in t.pillars}
    out |= {pid for lk in links if lk.from_ticker in tickers for pid in lk.to_pillar_ids}
    return out


def check_suggestion(where: str, s: Suggestion, may_mismatch: bool) -> None:
    for sec in s.sections:
        if may_mismatch:
            check(sec.email_id not in QUAR, f"{where}: refers to quarantined email {sec.email_id}")
        else:
            check_quote(where, sec.email_id, sec.quote)
    for cid in s.claim_ids:
        check(cid in CLAIM, f"{where}: unknown claim {cid}")
    linked = {sec.email_id for sec in s.sections}
    check(all(CLAIM[c].email_id in linked for c in s.claim_ids if c in CLAIM), f"{where}: claim from an unlinked email")
    tickers = {t for c in s.claim_ids if c in CLAIM for t in CLAIM[c].tickers}
    b = s.body
    if isinstance(b, ExistingThesis):
        check(b.pillar_id in candidates(tickers), f"{where}: pillar {b.pillar_id} outside the candidate set")
        for a in b.assumptions:
            d = DRIVER.get(a.driver_id)
            check(d is not None and a.driver_id in PILLAR[b.pillar_id].driver_ids, f"{where}: {a.driver_id} not linked to the pillar")
            if d:
                check(a.book_value == d.analyst and a.consensus_value == d.consensus, f"{where}: book or consensus value not from models.json")
                check(d.min <= a.stated_value <= d.max, f"{where}: stated value out of bounds")
                fy = models[a.driver_id.split(".")[0]].fiscal_year
                check(any(CLAIM[c].period == fy and CLAIM[c].value == a.stated_value for c in s.claim_ids if c in CLAIM),
                      f"{where}: stated figure needs a claim with period {fy} and the same value")
    elif isinstance(b, NewThesis):
        check(b.ticker in tickers, f"{where}: new thesis ticker outside the claims' tickers")
        check(all(d.startswith(b.ticker + ".") and d in DRIVER for d in b.driver_ids), f"{where}: new pillar names another company's driver")


for s in s_raw:
    check(re.fullmatch(r"fixture_\d{3}\.s\d+", s.id) is not None, f"suggestions_raw.json {s.id}: ID must be <email_id>.s<n>")
    check(s.status == "open" and s.reject_reason is None, f"suggestions_raw.json {s.id}: must be open")
    check_suggestion(f"suggestions_raw.json {s.id}", s, may_mismatch=True)
check(sorted(i for a in analysis for i in a.suggestion_ids) == sorted(s.id for s in s_raw),
      "analysis.json: suggestion_ids must match suggestions_raw.json")

check([s.id for s in s_chk] == [s.id for s in s_raw], "suggestions_checked.json: same suggestions as raw, same order")
rejected = [s for s in s_chk if s.status == "rejected"]
check(len(rejected) >= 1, "suggestions_checked.json: need at least one rejected suggestion")
for s in s_chk:
    check(s.status in ("open", "rejected"), f"suggestions_checked.json {s.id}: status must be open or rejected")
    check((s.status == "rejected") == (s.reject_reason is not None), f"suggestions_checked.json {s.id}: reject_reason iff rejected")
    if s.status == "rejected":
        if s.reject_reason and s.reject_reason.startswith("quote mismatch"):
            check(any(not quote_in(x.quote, BODY.get(x.email_id, "")) for x in s.sections),
                  f"suggestions_checked.json {s.id}: rejected for quote mismatch but every quote matches")
        check_suggestion(f"suggestions_checked.json {s.id}", s, may_mismatch=True)
        continue
    check_suggestion(f"suggestions_checked.json {s.id}", s, may_mismatch=False)
    labs = {RES[x.email_id].triage for x in s.sections}
    check(s.second_look == (not labs & {"thesis_relevant", "monitor"}), f"suggestions_checked.json {s.id}: second_look mark")
    if labs == {"monitor"}:
        check(isinstance(s.body, ExistingThesis) and s.body.strength == 1, f"suggestions_checked.json {s.id}: monitor-only must be strength 1")

valid_sections = {(x.email_id, normalize_ws(x.quote)) for s in s_chk if s.status == "open" for x in s.sections}
SFIN = {s.id: s for s in s_fin}
for s in s_fin:
    where = f"suggestions.json {s.id}"
    if isinstance(s.body, ExistingThesis):
        check(s.id == f"{s.body.pillar_id}.{s.body.stance}", f"{where}: ID must be <pillar_id>.<stance>")
    elif isinstance(s.body, NewThesis):
        check(re.fullmatch(rf"{s.body.ticker}\.new\d+", s.id) is not None, f"{where}: ID must be <ticker>.new<n>")
    check(s.status == "open" and s.reject_reason is None, f"{where}: must be open")
    check_suggestion(where, s, may_mismatch=False)
    check(all((x.email_id, normalize_ws(x.quote)) in valid_sections for x in s.sections), f"{where}: section not from a valid checked suggestion")
    labs = {RES[x.email_id].triage for x in s.sections}
    check(s.second_look == (not labs & {"thesis_relevant", "monitor"}), f"{where}: second_look mark")
check(len(SFIN) == len(s_fin), "suggestions.json: duplicate IDs")

# required cases
figure_ok = any(isinstance(s.body, ExistingThesis) and s.body.assumptions
                and any(RES[x.email_id].triage == "thesis_relevant" for x in s.sections) for s in s_fin)
check(figure_ok, "need a thesis_relevant existing-thesis suggestion with a stated figure")
second = [s for s in s_fin if s.second_look]
check(any(all(RES[x.email_id].triage in ("low_value", "irrelevant") and RES[x.email_id].gate == "pass"
              and RES[x.email_id].signal_score >= config.PASS_SIGNAL for x in s.sections) for s in second),
      "need a second-look suggestion from a passed low_value or irrelevant email")
check(any(isinstance(s.body, NewThesis) for s in s_fin), "need a new-thesis suggestion")
check(any(r.triage == "monitor" for r in results), "need a monitor email")
check(any(n.deadline is not None for n in notes), "need an attention note with a deadline")

# ---- brief accounting ----

if brief is not None:
    check(str(brief.day) == config.SET_DATES["day_1"], "brief.json: day must be day_1's date")

    def emails_of(sids: list[str]) -> set[str]:
        out = set()
        for sid in sids:
            check(sid in SFIN, f"brief.json: unknown suggestion {sid}")
            if sid in SFIN:
                out |= {x.email_id for x in SFIN[sid].sections}
        return out

    listed = brief.thesis_changes + brief.new_theses + brief.worth_watching
    check(sorted(listed) == sorted(SFIN), "brief.json: suggestion lists must hold every suggestion exactly once")
    for sid in brief.thesis_changes:
        check(sid in SFIN and isinstance(SFIN[sid].body, ExistingThesis), f"brief.json: {sid} in thesis_changes is not existing_thesis")
    for sid in brief.new_theses:
        check(sid in SFIN and isinstance(SFIN[sid].body, NewThesis), f"brief.json: {sid} in new_theses is not new_thesis")
    for sid in listed:
        if sid in SFIN:
            all_mon = {RES[x.email_id].triage for x in SFIN[sid].sections} == {"monitor"}
            check(all_mon == (sid in brief.worth_watching), f"brief.json: worth_watching placement of {sid}")
    check(brief.needs_attention == [n.email_id for n in sorted(notes, key=lambda n: -TRI[n.email_id].attention)],
          "brief.json: needs_attention must list every note's email by attention probability")
    check(sorted(brief.quarantined) == sorted(QUAR), "brief.json: quarantined must be the quarantined emails")
    # Every email placed exactly once: suggestion lists (by linked email), relevant_unlinked, audit,
    # quarantined. needs_attention is an overlay and may repeat an email placed elsewhere.
    places = [emails_of(brief.thesis_changes), emails_of(brief.new_theses), emails_of(brief.worth_watching),
              set(brief.relevant_unlinked), set(brief.audit), set(brief.quarantined)]
    flat = [e for p in places for e in p]
    check(sorted(flat) == sorted(IDS), f"brief.json: emails not placed exactly once: {sorted(flat)}")
    check(len(brief.relevant_unlinked) == len(set(brief.relevant_unlinked)) and len(brief.audit) == len(set(brief.audit)),
          "brief.json: duplicate IDs in a list")
    for eid in brief.relevant_unlinked:
        check(RES[eid].gate == "pass" and RES[eid].triage in ("thesis_relevant", "monitor"),
              f"brief.json: {eid} in relevant_unlinked must be passed signal")
    check(brief.relevant_unlinked == sorted(brief.relevant_unlinked, key=lambda e: -RES[e].signal_score),
          "brief.json: relevant_unlinked must be ordered by signal score")
    check(len(brief.alerts) <= config.ALERTS_PER_DAY, "brief.json: at most three alerts")
    for al in brief.alerts:
        if al.kind == "human_attention":
            check(TRI[al.ref_id].attention >= config.ALERT_ATTENTION, f"brief.json: alert {al.ref_id} below the alert threshold")
    check(brief.counts.get("notes") == len(notes) and brief.counts.get("suggestions") == len(s_fin),
          "brief.json: counts of notes and suggestions")

# ---- eval, usage, metrics, criteria history ----

if ev is not None:
    check(ev.corpus == "day_1" and ev.criteria_version == "fixture0000", "eval.json: corpus day_1, criteria_version fixture0000")
    check(sum(sum(v.values()) for v in ev.confusion.values()) == 10, "eval.json: confusion must count ten emails")
    check(ev.measures.get("quote_faithfulness") == 1.0, "eval.json: quote_faithfulness must be 1.0 on delivered items")
if metrics is not None:
    want = build_report("day_1", calls, timings, emails=10).model_dump(exclude={"run_at"})
    check(metrics.model_dump(exclude={"run_at"}) == want, "metrics.json: does not match build_report(usage.json)")
check(all(c.email_id is None or c.email_id not in QUAR or c.stage in ("redundancy", "classify") for c in calls),
      "usage.json: a quarantined email reached a model after stage 3")
check(len(history) == 1 and history[0].criteria_version == "fixture0000", "criteria_history.json: one entry, fixture0000")

if failures:
    print(f"FAIL: {len(failures)} check(s) failed")
    for f in failures:
        print(" -", f)
    sys.exit(1)
print(f"OK: fixtures valid ({len(IDS)} emails, {len(claims)} claims, {len(s_raw)} raw / {len(s_fin)} merged suggestions, "
      f"{len(rejected)} rejected, {len(notes)} note)")
