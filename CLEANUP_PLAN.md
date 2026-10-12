# Cleanup plan (proposed, not yet applied)

Branch: `cleanup/repo-presentation`, started from `main` after merging `cursor/vercel-day1-web` (Live tab on Vercel). Nothing below has been changed yet. Each item says what was found, how it was found, the risk, and how to confirm the change is safe. Tick an item when it is applied and the checks pass.

**Standing checks for every item:** `uv run pytest`, `uv run mypy --strict src tests`, and for anything that touches the web app a render of `/`, `/inbox`, `/summaries`, `/book`, `/attention`, `/live`. Cached model replies must still replay with zero misses (`tests/test_vercel.py` covers the ten presets).

**Method:** `vulture` (dead code), `ruff` rules F and B (imports, unused locals), a script comparing every constant and helper name against all other files, a scan of CSS class names against templates and scripts, and a manual read of `git ls-files`.

## A. Dead code (low risk)

- [x] **A1. `evals/score.py: load_labels`.** Defined, referenced nowhere, not in any doc. Remove.
- [x] **A2. `web/labels.py: REQUEST_KIND_NAMES`.** Constant used nowhere (the attention page builds its own tab names). Remove.
- [x] **A3. `web/main.py: http_error`** is the registered HTTP error handler (decorated), so vulture's report is a false positive. Keep.
- [x] **A4. Unused CSS.** Ten selectors match no template, script or Python string: `dots`, `faint`, `stack`, `req-by`, `req-label`, `req-name`, `req-org`, `req-subj`, `req-time`, `req-top` (the old request-card layout). `t1`, `t2`, `t3` and `htmx-request` are built dynamically and must stay. Remove the ten after a visual check of Needs attention.
- [ ] **A5. `evals/metric.projection_review`** is defined and tested but `evals/score.py` never calls it, so it feeds no report. Either wire it into the scorer and `eval.json`, or remove it with its test. (`View.seed_driver` is used by `company.html` and stays.)
- [ ] **A6. Placeholder route `research_log_page`.** The docstring says "not connected to anything". Decide: keep as a labelled placeholder (the Book page links to it) or remove the route and the link.

## B. Lint-level tidy (low risk, mechanical)

- [x] **B1. Unused imports.** `config` in `pipeline/merge.py` and `pipeline/validate.py`; `shutil` and `Email` in `tests/test_classify.py`; `Email` in `tests/test_deliver.py` and `tests/test_validate.py`; `config` in `tests/test_redundancy.py`; `claims_of` in `tests/test_projections.py`; `TypeAdapter` in `tests/fixtures/validate_fixtures.py`. `ruff --fix` handles nine of them.
- [x] **B2. Unused local** `body` in `tests/test_extract.py:101`.
- [x] **B3. `zip()` without `strict=`** in 11 places (corpus loader, tuning, scripts, tests). Add `strict=True` where lengths must match; this documents the invariant.
- [x] **B4. Decide on a linter.** Add `ruff` with a small rule set (F, B, I) to `pyproject.toml` so B1-B3 stay fixed; `mypy --strict` is already enforced.

## C. Dependencies (medium risk, verify with a clean install)

- [x] **C1. `jupyter` is a main dependency** but nothing imports it; the notebook builder already has its own `notebook` group. Remove it from `dependencies` (it drags in a large tree).
- [x] **C2. `huggingface-hub` is declared directly** but never imported (it arrives through `sentence-transformers`). Remove the direct line.
- [x] **C3. Two dependency lists.** `pyproject.toml` / `uv.lock` (local, full) and `requirements.txt` (Vercel, slim) can drift. Add a test that every package in `requirements.txt` also appears in `uv.lock` at the same version, and document why the two exist.
- [ ] **C4. Confirm `itsdangerous` and `python-multipart`** are required at runtime (session cookies and forms) and keep them; note this in the lists so they are not "cleaned" later.

## D. Data and cache (medium risk, large size win)

- [ ] **D1. Two caches in git.** `data/cache` (3,083 files, 30 MB) and `data/cache_web` (708 files, 13 MB) overlap: every `cache_web` entry is a copy of a `cache` entry. Regenerate `cache_web` with a script (`scripts/build_web_cache.py`) from a cache trace so it is reproducible rather than hand-copied, and document it.
- [ ] **D2. Stale entries in `data/cache`.** The `embed` namespace alone holds 1,538 entries from two models (the local one and the hosted one), and each deployment needs only one of them; model replies from earlier criteria versions are never read. `scripts/prune_cache.py` (trace-based) exists: run the three sets plus the presets with `TRIAGE_CACHE_TRACE`, prune, and record the entry count before and after in `DECISIONS.md`.
- [ ] **D3. `data/seed/models_draft.json`** is input to `state/seed_merge.py` and must stay, but add a one-line note in `data/seed/` explaining draft versus merged files.
- [ ] **D4. Review which `data/out` files need to be tracked** for each set. `day_2` and `tuning` outputs are not served by the Vercel app; keep them if the Docker app and the evals read them, otherwise drop.

## E. Documentation that has drifted from the code (low risk, high visibility)

- [x] **E1. `CLAUDE.md`** still says "two skills" in the analysis agent (there are three: alter existing thesis, revise projections, spawn new thesis), calls the embedding "local" only, and lists `EMBEDDING_PROVIDER`/`EMBEDDING_DIM` as leftovers while the app now uses `EMBEDDING_BACKEND`. Update, and mention the Vercel files.
- [x] **E2. `DECISIONS.md` #125** says keys go to Preview only; #126 and the deployment supersede it. Mark #125 as superseded rather than editing history.
- [ ] **E3. `README.md`:** the owner deliberately removed the running instructions from the README, so leave that as is; only add a pointer to this plan if wanted.
- [x] **E4. `SPEC.md` / `KICKOFF.md`** refer to `transcripts/`; the transcripts now live in `AI_transcripts/`. Leave the spec text alone (it is the source of truth) but add a one-line note at the top of each pointing to the new location.
- [x] **E5. `scripts/run_generation_prompt.py`** still writes to `transcripts/generation/`. Point it at `AI_transcripts/agent_transcripts/generation/`.

## F. Repository layout and presentation (decisions needed)

- [ ] **F1. Root folder.** Twenty-plus entries at the top level. Proposed grouping: keep `src/`, `tests/`, `data/`, `criteria/`, `skills/`, `instructions/`, `tools/`, `tuned/`, `notebooks/`, `scripts/`; move `SPEC.md`, `KICKOFF.md`, `DECISIONS.md`, `REVIEW.md` into `docs/` (leave `README.md`, `CLAUDE.md`, `CLEANUP_PLAN.md` at the root). Needs the Dockerfile, `CLAUDE.md` and links updated.
- [ ] **F2. `scripts/jev_spike.py`** is a one-off spike (its result is recorded in `DECISIONS.md`). Move to `scripts/archive/` or delete.
- [ ] **F3. Tooling folders.** `.claude/launch.json` is tracked; `.claude/worktrees` and `.cursor` are tooling leftovers. Add them to `.gitignore` except `launch.json`, and confirm `.vercel/` stays ignored.
- [ ] **F4. `AI_transcripts/`** is 20+ MB of raw session logs. Keep (it is a deliverable) but add a one-page `AI_transcripts/README.md` saying what each file is and that tool output is truncated.
- [ ] **F5. `data/live_presets`, `data/filings`** each get a one-line README so a new reader knows what feeds them.

## G. Tests (low risk)

- [ ] **G1. Fixtures.** `tests/fixtures/validate_fixtures.py` is a script, not a test; confirm it is wired into a test or documented as a manual check.

## H. Web app (low risk)

- [ ] **H1. `web/main.py` is 922 lines.** Propose splitting into route modules (`routes/brief.py`, `routes/inbox.py`, `routes/attention.py`, `routes/live.py`, `routes/book.py`) sharing the view helpers, with no behaviour change; the web tests are the safety net.
- [ ] **H2. Inline template styles** (`style="..."` attributes) in several templates could move into `style.css`.
- [ ] **H3. `app.js`** is one file with several unrelated blocks (filters, inbox, attention counts, review shortcuts); split by page or add section comments and a table of contents.

## Suggested order

1. A, B (small, safe, reviewable in one commit each).
2. E (docs) so the written description matches the code.
3. C (dependencies), verified with a clean `uv sync` and a Vercel preview build.
4. D (cache), with before and after counts recorded.
5. F and H1, which move files and need your say-so first.

## Questions for the owner

- Keep or drop `research_log_page` (A6)?
- Is moving the spec and decision files into `docs/` acceptable (F1), given `CLAUDE.md` calls `SPEC.md` the source of truth?
- Should `day_2` and `tuning` outputs stay tracked (D4)?
- Delete or archive the Jev spike (F2)?
