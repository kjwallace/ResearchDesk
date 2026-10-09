## Role

You are writing tool definitions for two agents in an email triage system used by a technology desk that follows Amazon (AMZN), Nvidia (NVDA), Microsoft (MSFT), Apple (AAPL) and Alphabet (GOOGL).

A tool definition tells an agent what a tool does, when to use it and what arguments it takes. The build wraps a Python function around each definition, so names and argument types must be exact. Write the definitions as JSON.

## Format of one definition

```json
{
  "name": "snake_case_name",
  "description": "What the tool does, when to call it, when not to call it, and what it returns. Three to six sentences.",
  "input_schema": {
    "type": "object",
    "properties": {
      "argument_name": {"type": "string", "description": "What this argument is."}
    },
    "required": ["argument_name"],
    "additionalProperties": false
  },
  "returns": "One sentence describing the shape of the result."
}
```

Requirements for every definition:

- The description is written for the agent. It states plainly when the tool is the wrong choice.
- Every argument has a type and a one-sentence description. Use `enum` wherever the values are a fixed set.
- IDs follow the system's patterns: tickers are `AMZN`, `NVDA`, `MSFT`, `AAPL`, `GOOGL`; pillar IDs look like `NVDA.p1`; driver IDs look like `NVDA.data_center_growth`; email IDs look like `synthetic_000123`; claim IDs look like `synthetic_000123.c1`.
- No tool can write to the book, send a message, place an order or reach the open internet. Do not define one.

## File 1: `tools/analysis_agent.json`

The analysis agent recommends thesis changes. Its two tools are its skills.

**`alter_existing_thesis`**

- Purpose: assess whether extracted claims support or contradict a pillar the desk already holds, or meet a pillar's "wrong if" test.
- Arguments: `claim_ids` (array of strings, at least one). Code works out which pillars to consider from the claims' tickers and the desk's links file, so the agent does not name companies.
- Returns: a list of suggestions on existing pillars, or a no-change reason.
- Use when any claim concerns a company in the book. Call it before `spawn_new_thesis`.

**`spawn_new_thesis`**

- Purpose: assess whether extracted claims point to a thesis the book does not hold for one company.
- Arguments: `claim_ids` (array of strings, at least one), `ticker` (one of the five; one company a call).
- Returns: at most one candidate pillar, or a no-change reason.
- Use only when no existing pillar covers the debate the claims raise. Not for restating or reversing an existing pillar.

## File 2: `tools/verify_agent.json`

The verify agent checks one claim against the record when the analyst asks. All three tools are read-only.

**`search_change_log`**

- Purpose: find earlier accepted changes and their supporting quotes, to see whether a claim is already reflected in the book.
- Arguments: `query` (string, plain words), `ticker` (one of the five, optional), `limit` (integer 1 to 10, default 5).
- Returns: matching log entries with their date, the book item changed and the quoted sections.

**`get_filing_excerpt`**

- Purpose: retrieve passages that match a query from the latest annual report of one of the five companies, as saved with the app.
- Arguments: `ticker` (one of the five), `query` (string), `limit` (integer 1 to 5, default 3).
- Returns: passages, each with an identifier for citation.
- Works only on the annual reports saved with the app. It cannot fetch new documents. A result of no passages means "not in the cache", not "untrue".

**`get_book_item`**

- Purpose: read one pillar or one driver from the book as it currently stands.
- Arguments: `item_id` (string; a pillar ID or a driver ID).
- Returns: for a pillar, its statement, "wrong if" test and linked drivers; for a driver, its label, unit, the desk's value and consensus.
- Use to check what the book says before comparing it with a claim. It does not return positions or sizes.

## Output format

Return two JSON documents and nothing else. Start each with a line `=== tools/<name>.json ===`. Each document is an array of definitions in the format above. The JSON must parse.

## Checks before you answer

1. Two tools in the first file and three in the second, with the names given above.
2. Every argument listed above is present with the right type, and `required` lists only arguments without a default.
3. Each description says when not to call the tool.
4. No tool writes, sends, trades or browses.
5. Both documents are valid JSON.