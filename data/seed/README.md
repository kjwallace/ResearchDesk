# Seed files: the book

| File | What it is |
|---|---|
| `theses.json` | Each company's thesis: stance, size, conviction, pillars with evidence, and the Street's view. |
| `models.json` | Each company's model: drivers (analyst and consensus values, bounds), revenue lines, tax rate, diluted shares and target multiple. Built by `state/seed_merge.py` from the two files below; do not edit by hand. |
| `models_draft.json` | The synthetic drivers, consensus, bounds and multiples that came out of the book prompt. Input to the merge. |
| `base_figures.json` | Base revenue by line, tax rate and diluted shares from each company's latest 10-K. Input to the merge. |
| `links.json` | Read-through links: which company's news bears on which pillars of another. |
| `daily_summaries.json` | The text on the Summaries tab, per day and company. |

Current state is never stored: it is these files plus the session's change log (`state/fold.py`).
