# Work package 6b: Validate and merge (pure code)

**You own:** `src/triage_app/pipeline/validate.py`, `src/triage_app/pipeline/merge.py`, `tests/test_validate.py`, `tests/test_merge.py`.

**SPEC sections:** "Validation in stage 7", "Merging in stage 8", "Order and alerts" (ordering only — alerts belong to deliver), "Where each email appears", "Stage files", "Data contracts" (`Suggestion`, `ExistingThesis`, `NewThesis`, `LinkedAssumption`), "Starting values", "Read-through links".

**Build:**
1. `validate.py`: `run` reads `suggestions_raw.json`, `claims.json`, `parsed.json`, `results.json`, writes `suggestions_checked.json`. Apply every rule in "Validation in stage 7" in a fixed, documented order: unknown item (claim IDs not the email's; pillar outside the candidate set recomputed from the claims' tickers + links; new-thesis ticker outside them; new pillar naming another company's driver) → reject; quote mismatch (`quote_in`) → reject; duplicate thesis (statement cosine ≥ `config.NEW_THESIS_DUPLICATE` against any existing pillar statement, via `ctx.embedder`) → reject; monitor only → strength 1, reject a new-thesis candidate; out of bounds or driver not linked to the pillar → keep, drop the figure; wrong period (claim period missing or ≠ the company's `fiscal_year` in `data/seed/models.json`) → keep, drop the figure; second look (no linked email labeled thesis_relevant or monitor) → keep, mark. A rejected suggestion keeps status "rejected" and a one-line `reject_reason`. Pure code, no generative model.
2. `merge.py`: `run` reads `suggestions_checked.json` (+ results/seed as needed) and writes `suggestions.json` with open suggestions only: same pillar + stance merge (strongest wins; `wrong_if_met` OR; rationale of the strongest; assumptions pooled one per driver and stated value; every linked section kept); opposite stances stay apart; new-thesis candidates for one company merge at statement cosine ≥ `config.NEW_THESIS_MERGE` (first statement kept). Merged IDs `<pillar_id>.<stance>` / `<ticker>.new<n>`. Recompute second look after merging. Order: existing pillars by position size, then strength, then the strongest email's signal score; new-thesis candidates by position size, then signal score.

**Tests (FakeEmbedder, fixture stage files):** one test per validation rule and per merge rule, ordering, IDs, and every output validates.

**Done when** the above passes on the fixtures.
