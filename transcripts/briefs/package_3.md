# Work package 3: Redundancy

**You own:** `src/triage_app/pipeline/redundancy.py`, `tests/test_redundancy.py`. The file exists as a typed stub; replace it.

**SPEC sections:** "Redundancy check", "Starting values", "Stage files". Note the corpus has no `redundant_of` labels: thresholds are fixed (from `ctx.thresholds` / `config`), not swept.

**Build:** `run(in_dir, out_dir, ctx)` reads `parsed.json`, processes emails in arrival order with a `DayCache` (define it in this module: earlier emails' IDs, normalized subjects and vectors), writes `redundancy.json` (`RedundancyRecord` per email) and `vectors.npy` (one row per email in parsed.json order, float32). `process(email, day, ctx) -> RedundancyRecord` follows the five steps exactly:
1. Chunk the cleaned body to the embedder's input limit (`ctx.embedder.count_tokens`, `ctx.embedder.max_tokens`; split on paragraph then sentence boundaries, leave headroom for special tokens), embed all chunks in one `ctx.embedder.embed` call, take the mean and L2-normalize.
2. Highest cosine with any earlier email (dot product of normalized vectors) and that email's ID.
3. Subject score: normalize both subjects (lower-case; strip leading `re:`, `fw:`, `fwd:` prefixes repeatedly; strip punctuation) and score token-set similarity 0–1 with `rapidfuzz.fuzz.token_set_ratio / 100`.
4. Flag when content ≥ `content_similarity`, or content ≥ `content_similarity_with_subject` and subject ≥ `subject_match`. `nearest` is the most similar earlier email whether or not flagged; the first email has `nearest`, `content_similarity` and `subject_score` all None.
5. Add the email to the day cache, flagged or not.
Expose `subject_similarity(a, b) -> float` and `email_vector(text, embedder)` for the live route and tests. Wrap each email in `ctx.recorder.stage("redundancy", email_id)`.

**Tests (FakeEmbedder):** the fixture repeat is flagged and points to its earlier email; the first email has no nearest; the subject-only path (content between the two thresholds plus matching subject) flags; a long body is chunked; output validates against the contract.

**Done when** the above passes on the fixtures. Do not run it on a full corpus set.
