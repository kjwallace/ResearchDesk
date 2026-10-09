# Prompt and tool rewrite

**You own:**
- `instructions/attention_note.md`, `instructions/extract_claims.md`, `instructions/analysis_agent.md`, `instructions/verify_agent.md`
- `skills/alter_existing_thesis.md`, `skills/spawn_new_thesis.md`, a new `skills/revise_projections.md`
- `tools/analysis_agent.json`, `tools/verify_agent.json`

Do not edit `instructions/jev_questions.md` or `criteria/`.

Read each file whole first, then `schema.py` (the new draft contracts), `prompts/README.md` ("What to check in each output"), and in `SPEC.md` "Attention pathway", "Analysis agent" and "Validation in stage 7". The analysis and note models will be Claude Sonnet 5.5.

**Changes the person asked for:**
1. **Attention note** (`attention_note.md`):
   - The `summary` focuses on the target stock(s) the email bears on and the investment opportunity it offers.
   - `why_attention` says what attending or replying does for the firm (the access, information or edge it gives the desk).
   - The new `follow_up` field says what follow-up action is needed (who should do what, by when).
   - Keep `action` and `deadline` as they are. Update the JSON shape and the examples to include `follow_up`, and keep quotes from the body only.
2. **Existing-thesis skill** (`alter_existing_thesis.md`):
   - Raise the bar for relevance so emails overlap less across pillars and match a pillar's exact claim. A suggestion requires that the claims bear **directly** on that specific pillar's statement or "wrong if" test, not merely on the same company or theme.
   - Each suggestion carries `relevance` (0–1, calibrated with examples). Code rejects anything below 0.7 and keeps at most the 2 most relevant per email.
   - Allow a **none** option: for a pillar the claims touch only loosely, return `"stance": "none"`, or return no suggestion with a `no_change_reason`. Make none the expected outcome when the match isn't exact.
   - Compare the desk's stance (long/short) with the street's view (`street_view` buy/hold/sell and its note, shown with each company). Set `street_view_shift` (`toward_buy` / `toward_sell` / `none`) when an analyst's email in the claims (e.g. a `rating_change` or `estimate_change` from a sell-side source) signals the street's view moving. Add `street_view_note`, one sentence comparing the street with the desk.
3. **New-thesis skill** (`spawn_new_thesis.md`): more verbose reasoning. The `rationale` is 3–5 sentences: what was noticed in the claims, why no existing pillar covers it, what would have to be true, and what would prove it wrong.
4. **New projections skill** (`skills/revise_projections.md`, matching the other skills' layout): it reads claims that state financial projections (EPS, revenue, operating income, target price, or a figure for one of the company's drivers such as segment growth, operating margin or capex). It compares each with the book's current projection for the same metric and period, and returns `ProjectionDraft`s.
   - Shape: `kind="projection_change"`, `ticker`, `metric` (a driver ID shown to it, or `revenue` / `operating_income` / `eps` / `target_price`), `period`, `stated_value` (exactly as the email states it, in the metric's unit: pct points for growth and margin, USD bn for revenue, operating income and capex, USD for EPS and target price), `rationale`, `claim_ids`, `sections`.
   - Only figures the email states for the company's modeled fiscal year (shown to it). Never compute, convert or invent a number. Return none when no such figure exists.
   - Add the matching tool, `revise_projections`, to `tools/analysis_agent.json` (same format as the two existing tools; it says when not to call it). Update `instructions/analysis_agent.md` so the agent knows the third skill and when to use it, still at most 3 calls per email.
5. **Extraction** (`extract_claims.md`): make sure stated projections (EPS, revenue, margin, growth, capex, target price, with their period and unit) are captured as claims with `metric`, `period`, `value` and `unit` filled, so the projections skill has them.
6. **Human-sounding outputs, everywhere you own:**
   - Every rationale, note and explanation reads like an analyst's write-up: "The analysis suggests…", "These were noticed…", "This points to…", "The email reports…".
   - Never "the model says / thinks", "as an AI", "I" or "we", and no references to prompts, skills, tools or instructions in the text the analyst reads.
   - Update the examples to match. Tool descriptions in `tools/*.json` should read the same way.

Every JSON shape must match `schema.py` field for field (`NoteDraft` with `follow_up`; `ExistingThesisDraft` with `stance` incl. "none", `relevance`, `street_view_shift`, `street_view_note`; `NewThesisDraft`; `ProjectionDraft`; `VerifyDraft`). No example may contain a trade, a position size, or a number its claims don't state. Every example quote must appear verbatim in that example's claims. Examples are invented, apart from the five company names.

**Done when:** a check script you write in the scratchpad (`/private/tmp/claude-501/-Users-kelvinwallace-Desktop-DE-Shaw-CaseStudy/d2841d3f-e0ef-4457-add3-381be37ad699/scratchpad/`) passes:
- both tool files parse, with 3 tools in analysis_agent.json and 3 in verify_agent.json;
- every example JSON validates against its contract;
- every example quote is verbatim in its claims;
- no banned phrasing ("the model", "as an AI", first person in outputs);
- all files are loadable by the existing loaders (`modules.attention.load_instructions`, `modules.skills` instruction loading by skill name, tool loading in `modules.analysis_agent`).

Report each file with one `REVIEW.md` line.
