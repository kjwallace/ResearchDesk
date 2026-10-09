# Thesis and projection code

**You own:** `src/triage_app/modules/skills.py`, `src/triage_app/modules/analysis_agent.py`, `src/triage_app/modules/extract.py` (only if needed), `src/triage_app/pipeline/analyze.py`, `src/triage_app/pipeline/validate.py`, `src/triage_app/pipeline/merge.py`, `src/triage_app/evals/metric.py` (only for the new suggestion kind), and tests `tests/test_analyze.py`, `tests/test_validate.py`, `tests/test_merge.py`, new `tests/test_projections.py`. You may add tests for `accept_projection` in a new `tests/test_projection_accept.py`, but do not edit `tests/test_apply.py`.

Another subagent is rewriting `skills/*.md`, `tools/analysis_agent.json` and `instructions/*.md` right now, including a new `skills/revise_projections.md` and a third tool `revise_projections`. Build against the contracts. Until those files land, load the projection skill's instructions with a short built-in fallback, as the other modules do. Test with scripted fakes, never with the generated files' wording.

**Build:**
1. **Projections skill** (`modules/skills.py`): a third DSPy skill module, `revise_projections`, registered with the others, returning `SkillResult` with `ProjectionDraft`s (keep only its own kind).
   - Its view, per candidate company in the claims: the company's modeled `fiscal_year`; each driver's ID, label, unit, desk value and consensus; and the computed projections `revenue`, `operating_income`, `eps`, `target_price` on desk and on consensus (via `state.compute.compute` / `metric_value`, rounded for display).
   - It never sees position size or conviction.
2. **Existing-thesis skill view:** add the desk's stance, the company's `street_view` and `street_view_note`, and each candidate pillar's `summary` and `evidence` (the evidence capped to keep prompts short; put the cap in your report, and if it needs a number, ask the lead to add it to `thresholds.py`).
3. **Analysis agent** (`modules/analysis_agent.py`): the third tool, from `tools/analysis_agent.json` once present, else a built-in definition with the same name and arguments (`claim_ids`, `ticker`). Still at most `SKILL_CALLS_PER_EMAIL` calls.
4. **Collect** (`pipeline/analyze.py`):
   - Drop existing-thesis drafts with `stance == "none"` (count them).
   - Carry `relevance`, `street_view_shift` and `street_view_note` into `ExistingThesis`.
   - Keep at most `thresholds.MAX_THESIS_SUGGESTIONS_PER_EMAIL` existing-thesis suggestions per email, the most relevant.
   - Turn each `ProjectionDraft` into a `ProjectionChange` with `book_value` and `consensus_value` filled by code from `metric_value(model, metric, "analyst"/"consensus")`. A metric that is neither a driver of that company nor an output metric is dropped.
   - Raw suggestion IDs stay `<email_id>.s<n>`.
5. **Validate** (`pipeline/validate.py`), in the documented rule order:
   - Existing thesis: `relevance < thresholds.MIN_PILLAR_RELEVANCE` → reject "weak match: relevance X below Y".
   - Projection, rejects:
     - unknown ticker or metric, or a ticker outside the claims' tickers;
     - quote mismatch;
     - period not exactly the company's `fiscal_year`;
     - the stated number not written in any of its claims' quotes (reuse `numbers_in`);
     - `abs(stated - book) / abs(book) > thresholds.PROJECTION_MAX_GAP` → "implausible: …";
     - a driver figure outside the driver's bounds.
   - Monitor-only and second-look apply to projections as to existing theses.
6. **Merge** (`pipeline/merge.py`): projections merge when ticker, metric, period and stated value match, pooling claims and sections. Different stated values for one metric stay separate suggestions. Merged ID `<ticker>.<metric>.proj<n>`. Order by position size, then the strongest email's signal score.
7. **Evals** (`evals/metric.py`): make sure `stray_suggestions`, `quote_faithfulness` and the review sheet treat `projection_change` sensibly (the review sheet gets kind `projection_change` with checks `right_metric`, `figure_stated`, `sections_support`). Only touch what's needed.

**Tests:**
- Fix the existing analyze tests: their scripted drafts now need `relevance`.
- Add tests for: none-stance dropping; the per-email cap; relevance rejection; each projection validation rule; projection merge and IDs; code-filled book and consensus values for a driver metric and for eps; the third tool's call limit.
- Accepting a driver projection logs `driver_updated`; accepting an eps projection logs `projection_noted` with before = the computed EPS.
- Every output validates.

**Done when:** `uv run pytest -q -p no:warnings` passes in full (except `tests/test_web.py`, which the UI session owns; if it fails because of your changes, say so), and `uv run mypy src`, `uv run mypy tests` are clean with no `type: ignore`.
