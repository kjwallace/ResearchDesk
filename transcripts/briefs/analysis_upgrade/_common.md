## Working rules (analysis upgrade)

Repo root for this work: `/Users/kelvinwallace/Desktop/DE_Shaw_CaseStudy/.claude/worktrees/analysis-upgrade` (a git worktree on branch `analysis-upgrade`). Run every command from there, and never `cd` to the main checkout. Python 3.14, uv. Other subagents work in the same worktree at the same time, each on different files.

**Read first:** `CLAUDE.md`, `transcripts/briefs/_common.md` (the original working rules, which still apply), and `src/triage_app/schema.py`. The contracts below are new; they are frozen, so ask in your report if one must change.
- `NoteFields.follow_up`.
- `Pillar.summary` / `Pillar.evidence: list[PillarEvidence]`; `Thesis.summary` / `street_view` (buy/hold/sell) / `street_view_note`.
- `ExistingThesisDraft.stance` may be `"none"`, plus `relevance` (0–1, required), `street_view_shift` and `street_view_note`; `ExistingThesis` has `relevance`, `street_view_shift` and `street_view_note`.
- `NewThesisDraft.rationale` (3–5 sentences).
- New `ProjectionDraft` / `ProjectionChange` (`kind="projection_change"`).
- `SkillResult` takes all three draft kinds.

New numbers live only in `src/triage_app/thresholds.py`: `MIN_PILLAR_RELEVANCE` (0.7), `MAX_THESIS_SUGGESTIONS_PER_EMAIL` (2), `PROJECTION_MAX_GAP` (0.5), `MODEL_PRICES`. `state/compute.metric_value(model, metric, basis)` reads a driver or a computed revenue / operating_income / eps / target_price. `state/apply.accept` already handles `ProjectionChange`, and `pipeline/deliver.py` already lists `brief.projection_changes`.

**Hard rules:**
- Do not edit `src/triage_app/web/` or `tests/test_web.py` (another session owns the UI).
- Do not edit `schema.py`, `thresholds.py`, `config.py`, `monitoring.py`, `llm.py`, `modules/lm.py`, `state/*`, `pipeline/deliver.py` or `pipeline/summary.py`; ask instead.
- No test calls a live model; use `tests/fakes.py`.
- Do not call any model API and do not run the pipeline on a corpus set; the lead does the Sonnet rerun.
- Never print `.env`.
- No corpus label reaches a model. Models recommend and never decide; code assigns IDs and fills book values.
- `uv run mypy src` and `uv run mypy tests` stay clean with **no `type: ignore`**.
- Do not commit; the lead commits.

**Final report:** files changed; the test and mypy commands with their output; lines for `DECISIONS.md` (the lead numbers them) and for `REVIEW.md`; anything undone.
