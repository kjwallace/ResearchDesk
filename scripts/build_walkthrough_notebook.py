"""Build notebooks/walkthrough.ipynb: the pipeline run cell by cell on three emails.

The notebook calls the real stage functions on one email at a time, in pipeline order:
  1. a thesis_relevant email -> the analysis agent suggests a thesis change -> the analyst accepts
  2. a human_attention email -> flagged -> an attention note with its summary
  3. an irrelevant email -> labeled irrelevant and stopped at the gate, with its reason

Every model call goes through the project's disk cache, so after a pipeline run on the
set the notebook replays from the cache at no cost. A cache miss calls OpenRouter / Jev
with the keys in .env.

    uv run --group notebook python scripts/build_walkthrough_notebook.py \
        --set day_1 --thesis <email_id> --attention <email_id> --irrelevant <email_id> --execute
"""

import argparse
from pathlib import Path

import nbformat
from nbformat.v4 import new_code_cell, new_markdown_cell, new_notebook

ROOT = Path(__file__).resolve().parents[1]


def md(text: str) -> nbformat.NotebookNode:
    return new_markdown_cell(text.strip())


def code(text: str) -> nbformat.NotebookNode:
    return new_code_cell(text.strip())


def stages_1_to_4(case: str, var: str) -> list[nbformat.NotebookNode]:
    """The shared front of the pipeline: the email, the repeat check, Jev and the gate."""
    return [
        md(f"""
### {case}: the email

Every stage reads the email from the corpus file through the loader, which drops every label. This is exactly what the models see: sender, address, subject and body.
"""),
        code(f"""
email = EMAILS[{var}]
show_email(email)
"""),
        md("""
### Stage 2: check for repeats

The email is embedded with the Hugging Face model and compared with every **earlier** email of the same day (cosine similarity), plus a token-set comparison of subjects. A flag is only a hint; stage 4 decides what to do with it.
"""),
        code("""
day = redundancy.build_day_cache(earlier_than(email), ctx)
repeat = redundancy.process(email, day, ctx)
show(repeat)
flagged = repeat if repeat.flagged else None
"""),
        md("""
### Stage 3: classify with Jev

One request with all 14 questions. Jev receives the email and the desk's relevance criteria (`criteria/*.md`) and nothing else: no book, no positions, no other emails, no repeat flag. It returns probabilities, not decisions.
"""),
        code("""
triage = classify.process(email, ctx)
show_triage(triage)
"""),
        md("""
### Stage 4: label and gate (code, no model)

Thresholds from `thresholds.py` (or `tuned/thresholds.json`) turn the probabilities into the label of record, the companies and topics, the human-attention flag and the gate. The one-line reason is composed by code.
"""),
        code("""
result = gate.process(triage, flagged, ctx.thresholds)
show(result)
"""),
    ]


def build(corpus_set: str, thesis_id: str, attention_id: str, irrelevant_id: str) -> nbformat.NotebookNode:
    cells: list[nbformat.NotebookNode] = [
        md(f"""
# Email triage, cell by cell

**Synthetic data.** The companies are real; every email, sender, position, thesis and estimate is invented. Nothing here is investment advice.

This notebook runs the pipeline's real stage functions on three emails from `{corpus_set}`, one stage per cell:

1. **Thesis relevant:** Jev labels it `thesis_relevant`, the analysis agent suggests a change to an existing thesis, code validates it, and the analyst accepts it into the book.
2. **Human attention:** Jev flags it for a person, and a small model writes an attention note with a summary, the reason and the action asked for.
3. **Irrelevant:** Jev labels it `irrelevant`, and the gate stops it with a reason, so no further model sees it.

Models recommend; only the analyst changes the book. Every model call goes through the project's disk cache, so after a pipeline run on `{corpus_set}` this notebook replays at no cost.
"""),
        md("## Setup"),
        code(f"""
import json
from IPython.display import Markdown, display

from triage_app import config, thresholds
from triage_app.corpus import load
from triage_app.monitoring import format_summary, recording
from triage_app.pipeline import analyze, classify, extract, gate, human_attention, merge, redundancy, validate
from triage_app.pipeline.context import RunContext
from triage_app.state import apply
from triage_app.state.compute import compute
from triage_app.state.fold import fold, load_seed

CORPUS_SET = "{corpus_set}"
ctx = RunContext(CORPUS_SET, emails_path=config.corpus_file(CORPUS_SET))
recording(ctx.recorder).__enter__()          # record tokens and latency for every call below
EMAILS = {{e.email_id: e for e in ctx.emails}}  # label-free, in arrival order
SEED = load_seed()
print(f"{{len(EMAILS)}} emails in {{CORPUS_SET}}; Jev model {{config.JEV_MODEL}}; "
      f"analysis model {{config.ANALYSIS_MODEL}}; notes model {{config.NOTES_MODEL}}")
"""),
        code("""
def show(model):
    \"\"\"Pretty-print a contract (a Pydantic model or a list of them).\"\"\"
    data = [m.model_dump(mode="json") for m in model] if isinstance(model, list) else model.model_dump(mode="json")
    print(json.dumps(data, indent=2, ensure_ascii=False))


def show_email(email, chars=1500):
    body = email.body if len(email.body) <= chars else email.body[:chars] + " …"
    display(Markdown(f"**From:** {email.sender} <{email.sender_email}>  \\n**Subject:** {email.subject}  \\n"
                     f"**Received:** {email.received_at:%Y-%m-%d %H:%M}"))
    print(body)


def show_triage(t):
    top = sorted(t.triage_probs.items(), key=lambda kv: -kv[1])
    print("triage:          ", ", ".join(f"{k} {v:.2f}" for k, v in top))
    print("signal score:    ", round(t.triage_probs["thesis_relevant"] + t.triage_probs["monitor"], 3))
    print("email_type:      ", t.email_type, f"({t.email_type_probs[t.email_type]:.2f})")
    print("human_attention: ", round(t.human_attention, 3))
    print("tickers:         ", {k: round(v, 2) for k, v in t.ticker_probs.items() if v >= 0.05})
    print("topics:          ", {k: round(v, 2) for k, v in t.topic_probs.items() if v >= 0.05})
    print("safety:          ", {k: round(v, 2) for k, v in t.safety.items()})
    print("criteria version:", t.criteria_version, "| truncated:", t.truncated)


def earlier_than(email):
    \"\"\"The day's emails that arrived before this one: the repeat check's day cache.\"\"\"
    return [e for e in ctx.emails if e.received_at < email.received_at]


def corpus_label(email_id):
    \"\"\"The corpus label, read here only to compare with the pipeline. No stage ever sends it to a model.\"\"\"
    labels = {lb.email_id: lb for lb in load(config.corpus_file(CORPUS_SET))[1]}
    lb = labels[email_id]
    return {"triage": lb.triage, "human_attention": lb.human_attention, "affected_tickers": lb.affected_tickers,
            "email_type": lb.email_type}
"""),
        # ---- Case 1 ----
        md("""
---
## Case 1: a thesis-relevant email changes a thesis

The email passes the gate, so it takes the analysis pathway: extract claims, let the analysis agent call a skill, validate the suggestion in code, merge, and put it in front of the analyst.
"""),
        code(f'THESIS_EMAIL = "{thesis_id}"'),
        *stages_1_to_4("Case 1", "THESIS_EMAIL"),
        md("""
### Stage 5: extract claims

A schema-constrained call to the analysis model. Each claim carries a verbatim quote; code checks every quote against the email by string match and drops any that fail. Code assigns the claim IDs.
"""),
        code("""
earlier = EMAILS.get(repeat.nearest) if repeat.flagged and repeat.nearest else None
claims = extract.process(email, result, earlier, ctx)
show(claims)
"""),
        md("""
### Stage 6: the analysis agent

Code picks the candidate pillars (the claims' companies plus the read-through links). The agent sees the claims and those pillars' statements, and chooses which skill to call (at most three calls): **alter an existing thesis** or **spawn a new one**. Suggestions come from the skills' structured output, never from the agent's free text. Code fills the book's current value and consensus beside any figure the email states.
"""),
        code("""
book = fold(SEED, [])
record, raw_suggestions = analyze.process(email.email_id, claims, result, ctx, book=book)
print("skills called:", record.skills_called, "| no-change reason:", record.no_change_reason)
show(raw_suggestions)
"""),
        md("""
### Stages 7 and 8: validate and merge (code, no model)

Validation rejects unknown IDs, quotes that are not in the email, and duplicate theses. It drops a stated figure that is out of bounds, for the wrong period, or not written in the claim's quote, and caps monitor-only evidence at strength 1. Merging then gives one suggestion per pillar and stance.
"""),
        code("""
inputs = validate.ValidationInputs(claims, list(ctx.emails), [result], SEED)
checked = [validate.process(s, ctx, inputs) for s in raw_suggestions]
for s in checked:
    print(s.id, "->", s.status, s.reject_reason or "")
suggestions = merge.process(checked, ctx, [result], SEED)
show(suggestions)
"""),
        md("""
### The analyst decides

Only an accepted suggestion changes the book, through the change log. Accepting logs the evidence against the pillar with its quoted sections. When the suggestion shows a stated figure for a linked driver, the analyst can also update the assumption, and code recomputes EPS and the target price.
"""),
        code("""
suggestion = suggestions[0]
log = [apply.accept(SEED, [], suggestion)]
state = fold(SEED, log)
body = suggestion.body
pillar_id = getattr(body, "pillar_id", None)
print("logged:", log[0].change, log[0].item_id, getattr(log[0], "stance", None), "strength", log[0].strength)
if pillar_id:
    pillar = next(p for t in state.theses.values() for p in t.pillars if p.id == pillar_id)
    print("\\npillar:", pillar.statement)
    print("wrong if:", pillar.wrong_if)
    print("accepted evidence on this pillar:", len(state.evidence[pillar_id]))
"""),
        code("""
ticker = (pillar_id or getattr(body, "ticker", "")).split(".")[0]
before = compute(fold(SEED, []).models[ticker])["analyst"]
assumptions = getattr(body, "assumptions", [])
if assumptions:
    a = assumptions[0]
    print(f"email states {a.driver_id} = {a.stated_value} (book {a.book_value}, consensus {a.consensus_value})")
    log.append(apply.update_driver(SEED, log, a.driver_id, a.stated_value, suggestion_id=suggestion.id))
after = compute(fold(SEED, log).models[ticker])["analyst"]
print(f"{ticker} EPS {before.eps:.2f} -> {after.eps:.2f}; target price {before.target_price:.0f} -> {after.target_price:.0f}")
"""),
        code("corpus_label(THESIS_EMAIL)"),
        # ---- Case 2 ----
        md("""
---
## Case 2: an email that needs a person

Jev's human-attention probability clears its threshold, so the email takes the attention pathway. A small generative model writes a note: a two-sentence summary, why it needs a person, the action asked for and any deadline, with supporting quotes that code checks against the email.
"""),
        code(f'ATTENTION_EMAIL = "{attention_id}"'),
        *stages_1_to_4("Case 2", "ATTENTION_EMAIL"),
        md("""
### Stage A: the attention note

The note explains the flag; it cannot remove it, and it never recommends an investment action.
"""),
        code("""
note = human_attention.process(email, result, ctx)
display(Markdown(f"**Summary.** {note.summary}\\n\\n**Why it needs a person.** {note.why_attention}\\n\\n"
                 f"**Action:** {note.action}  \\n**Deadline:** {note.deadline or 'none stated'}"))
for s in note.sections:
    print("quote:", s.quote)
"""),
        code("corpus_label(ATTENTION_EMAIL)"),
        # ---- Case 3 ----
        md("""
---
## Case 3: an irrelevant email is stopped

Jev labels it `irrelevant` and its signal score is below the pass threshold, so the gate stops it. No further model reads it; it appears only in the audit view, with the reason below.
"""),
        code(f'IRRELEVANT_EMAIL = "{irrelevant_id}"'),
        *stages_1_to_4("Case 3", "IRRELEVANT_EMAIL"),
        md("""
### After the gate

Stopped emails make no further model calls: extraction returns nothing, and no note is written unless Jev flagged the email for a person.
"""),
        code("""
print("gate:", result.gate, "| human attention:", result.human_attention)
print("claims extracted:", extract.process(email, result, None, ctx))
"""),
        code("corpus_label(IRRELEVANT_EMAIL)"),
        # ---- Monitoring ----
        md("""
---
## Token use and latency for this notebook

Every call above was recorded. Cache hits cost nothing; the spent and uncached columns show the difference.
"""),
        code("""
print(format_summary(ctx.recorder.report(CORPUS_SET, emails=3)))
"""),
    ]
    nb = new_notebook(cells=cells)
    nb.metadata["kernelspec"] = {"name": "python3", "display_name": "Python 3", "language": "python"}
    return nb


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--set", dest="corpus_set", default="day_1")
    parser.add_argument("--thesis", required=True)
    parser.add_argument("--attention", required=True)
    parser.add_argument("--irrelevant", required=True)
    parser.add_argument("--out", type=Path, default=ROOT / "notebooks" / "walkthrough.ipynb")
    parser.add_argument("--execute", action="store_true", help="run every cell and save the outputs")
    args = parser.parse_args()

    nb = build(args.corpus_set, args.thesis, args.attention, args.irrelevant)
    if args.execute:
        from nbclient import NotebookClient
        NotebookClient(nb, timeout=1800, kernel_name="python3",
                       resources={"metadata": {"path": str(ROOT)}}).execute()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    nbformat.write(nb, args.out)
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
