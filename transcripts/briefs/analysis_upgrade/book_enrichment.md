# Book enrichment

**You own:** `data/seed/theses.json`, and new tests in `tests/test_seed.py` (append; don't rewrite existing tests).

**Why:** the person said the example pillars and theses are too bare. Each needs more detail, plus boilerplate evidence, data observations or citations. Each company also needs the street's view: a buy/hold/sell rating that the thesis tool can compare with the desk's stance.

**Task:** for each of the 5 companies in `data/seed/theses.json`:
- **Thesis:** add `summary` (a 3–4 sentence paragraph on the desk's view and how the pillars fit together), `street_view` (`buy`, `hold` or `sell`) and `street_view_note` (one sentence on where the street sits versus the desk, e.g. "The street rates NVDA a buy; the desk agrees and is above consensus on Data Center growth").
  - Choose street views that make the comparison interesting: the desk's longs (NVDA, MSFT, AMZN) mostly agree with a street buy, with at least one at hold. Its shorts (AAPL, GOOGL) are against a street buy or hold.
- **Each of the 15 pillars:** keep `id`, `statement`, `wrong_if` and `driver_ids` **exactly** as they are, and add:
  - `summary`: 2–3 sentences of reasoning behind the statement.
  - `evidence`: 3–4 `{"observation", "source"}` items, each a concrete data observation or citation supporting the pillar.

**Sources must be clearly synthetic or real public filings only:**
- Fictional desk work, e.g. "Desk channel check with two hyperscaler procurement leads, Sep 2026 (synthetic)" or "Desk model, FY2027 build (synthetic)".
- Fictional sell-side notes from invented firm names, marked "(synthetic)".
- The company's latest 10-K. If you cite a figure from one, it must match `data/seed/base_figures.json` exactly (read it; it holds the real reported segment revenue, tax rate and shares, with source URLs). Never invent a "reported" number.
- Never name a real person or a real research firm or bank.
- Figures you invent are fine if marked synthetic, but they must not contradict `data/seed/models.json` (the desk's driver values versus consensus, and which side is above).

The example book is fictional and not investment advice. Keep the tone of an analyst's notes: plain, specific, no hype.

**Tests to add in `tests/test_seed.py`:**
- Every thesis has a non-empty summary, a `street_view` in {buy, hold, sell} and a note.
- Every pillar has a summary and 3–4 evidence items, each with an observation and a source.
- The 15 pillars' `id`/`statement`/`wrong_if`/`driver_ids` are unchanged versus `git show HEAD:data/seed/theses.json`, or versus a constant copied into the test.
- Every source mentioning "10-K" uses only figures present in `base_figures.json` (a simple check: any `$…bn` number in such an observation appears, rounded to one decimal, among that company's base figures).

Also update `SPEC.md`'s "The book" section with a short subsection, "Pillar detail, evidence and the street's view", describing the new fields (not the content), and the `Pillar`/`Thesis` contract block in "Data contracts" to match `schema.py`.

**Done when:** `uv run pytest -q -p no:warnings tests/test_seed.py` passes and `uv run python -c "from triage_app.state.fold import load_seed; load_seed()"` loads.
