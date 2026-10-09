=== tools/analysis_agent.json ===
```json
[
  {
    "name": "alter_existing_thesis",
    "description": "Assesses whether extracted claims support or contradict a pillar the desk already holds, or meet a pillar's 'wrong if' test. Pass only claim IDs. Code works out which pillars to consider from the claims' tickers and the desk's links file, so do not name companies or pillars. Call it whenever any claim concerns AMZN, NVDA, MSFT, AAPL or GOOGL, and call it before spawn_new_thesis. Do not call it when no claim concerns a company in the book. It only recommends and changes nothing in the book.",
    "input_schema": {
      "type": "object",
      "properties": {
        "claim_ids": {
          "type": "array",
          "description": "The IDs of the extracted claims to assess, for example synthetic_000123.c1.",
          "items": {
            "type": "string",
            "pattern": "^synthetic_\\d{6}\\.c\\d+$"
          },
          "minItems": 1
        }
      },
      "required": ["claim_ids"],
      "additionalProperties": false
    },
    "returns": "A list of suggestions on existing pillars (each naming a pillar ID such as NVDA.p1), or a no-change reason."
  },
  {
    "name": "spawn_new_thesis",
    "description": "Assesses whether extracted claims point to a thesis the book does not hold for one company. Call it only after alter_existing_thesis, and only when no existing pillar covers the debate the claims raise. Do not use it to restate, refine or reverse an existing pillar; use alter_existing_thesis for that. It handles one company per call, so if the claims concern several companies, make a separate call for each with only that company's claims. It only recommends and changes nothing in the book.",
    "input_schema": {
      "type": "object",
      "properties": {
        "claim_ids": {
          "type": "array",
          "description": "The IDs of the extracted claims, all concerning the given ticker, that may point to a new thesis.",
          "items": {
            "type": "string",
            "pattern": "^synthetic_\\d{6}\\.c\\d+$"
          },
          "minItems": 1
        },
        "ticker": {
          "type": "string",
          "description": "The one company for which a new pillar is being considered.",
          "enum": ["AMZN", "NVDA", "MSFT", "AAPL", "GOOGL"]
        }
      },
      "required": ["claim_ids", "ticker"],
      "additionalProperties": false
    },
    "returns": "At most one candidate pillar for the given ticker, or a no-change reason."
  }
]
```

=== tools/verify_agent.json ===
```json
[
  {
    "name": "search_change_log",
    "description": "Searches the log of earlier accepted changes to find entries and their supporting quotes, to see whether a claim is already reflected in the book. Use it when the analyst asks whether something was already captured or why a pillar or driver was changed. Do not use it to read what the book says now (use get_book_item) or to check a company's annual report (use get_filing_excerpt). No matching entries means nothing similar was logged, not that the claim is false. It is read-only.",
    "input_schema": {
      "type": "object",
      "properties": {
        "query": {
          "type": "string",
          "description": "Plain words describing the change or topic to look for."
        },
        "ticker": {
          "type": "string",
          "description": "Optional company filter; omit it to search all five companies.",
          "enum": ["AMZN", "NVDA", "MSFT", "AAPL", "GOOGL"]
        },
        "limit": {
          "type": "integer",
          "description": "The maximum number of entries to return, from 1 to 10.",
          "minimum": 1,
          "maximum": 10,
          "default": 5
        }
      },
      "required": ["query"],
      "additionalProperties": false
    },
    "returns": "A list of matching log entries, each with its date, the book item changed and the quoted sections."
  },
  {
    "name": "get_filing_excerpt",
    "description": "Retrieves passages matching a query from the latest annual report of one of the five companies, as saved with the app. Use it to check a claim against what the company's annual report says. It cannot fetch new documents, quarterly filings, transcripts or anything from the internet, so do not use it for recent events. A result with no passages means the text is not in the cache, not that the claim is untrue. It is read-only.",
    "input_schema": {
      "type": "object",
      "properties": {
        "ticker": {
          "type": "string",
          "description": "The company whose saved annual report is searched.",
          "enum": ["AMZN", "NVDA", "MSFT", "AAPL", "GOOGL"]
        },
        "query": {
          "type": "string",
          "description": "Words describing the topic or figure to find in the report."
        },
        "limit": {
          "type": "integer",
          "description": "The maximum number of passages to return, from 1 to 5.",
          "minimum": 1,
          "maximum": 5,
          "default": 3
        }
      },
      "required": ["ticker", "query"],
      "additionalProperties": false
    },
    "returns": "A list of passages from the saved annual report, each with an identifier for citation."
  },
  {
    "name": "get_book_item",
    "description": "Reads one pillar or one driver from the book as it currently stands. Use it to check what the book says before comparing it with a claim. Do not use it to find the history of changes (use search_change_log) or to look up company filings (use get_filing_excerpt). It does not return positions or sizes. It is read-only and takes exactly one ID per call.",
    "input_schema": {
      "type": "object",
      "properties": {
        "item_id": {
          "type": "string",
          "description": "A pillar ID such as NVDA.p1 or a driver ID such as NVDA.data_center_growth.",
          "pattern": "^(AMZN|NVDA|MSFT|AAPL|GOOGL)\\.[a-z][a-z0-9_]*$"
        }
      },
      "required": ["item_id"],
      "additionalProperties": false
    },
    "returns": "For a pillar, its statement, 'wrong if' test and linked drivers; for a driver, its label, unit, the desk's value and consensus."
  }
]
```