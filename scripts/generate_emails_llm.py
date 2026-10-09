"""Draft synthetic emails for every planned slot that has no draft yet, using the Anthropic API.

Labels are fixed by data/corpus/day <N>/email_plan.jsonl; the model only writes
sender, sender_email, subject, body and reason so that each email defends its
pre-assigned labels. Each batch is written to <out-dir>/batch_<first email_id>.json
as full records (prompt schema fields plus generation labels) and merged into
<out-dir>/emails.jsonl by build_email_jsonl.py.

Reads ANTHROPIC_API_KEY, and optionally ANTHROPIC_WORKSPACE_ID and
ANTHROPIC_MODEL, from the environment or the project .env.

Usage:
    python scripts/generate_emails_llm.py --day 1 --out-dir "data/corpus/day 1" --limit 6
    python scripts/generate_emails_llm.py --day 1 --out-dir "data/corpus/day 1"
    python scripts/generate_emails_llm.py --day 2 --out-dir "data/corpus/day 2" --prior-dir "data/corpus/day 1"
"""

import argparse
import json
import os
import random
import re
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_email_jsonl import TICKER_NAMES, full_record, parse_drafts  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
PROMPT_PATH = ROOT / "docs" / "corpus_documentation" / "synthetic_data_prompt.md"
CORPUS_ROOT = ROOT / "data" / "corpus"
EXAMPLES_PATH = ROOT / "scripts" / "style_examples.json"
API_URL = "https://api.anthropic.com/v1/messages"

DAY_DATES = {
    1: "Tuesday, October 13, 2026",
    2: "Wednesday, October 14, 2026",
    "1": "Tuesday, October 13, 2026",
    "2": "Wednesday, October 14, 2026",
    "tuning": "Thursday, October 15, 2026",
}

TEXT_FIELDS = ("email_id", "sender", "sender_email", "subject", "body", "reason")
LABEL_FIELDS = ("triage", "additional_labels", "affected_tickers", "human_attention",
                "email_type", "systemic", "angle", "day")

CONTEXT = """\
## Generation context (applies to every email)

- Recipient: the TMT long/short desk at Larchmont Ridge Capital, a fictional New York hedge fund
  (domain larchmontridge.com). Desk members: Ellen Marsh (PM), Raj Iyer and Marcus Bell (analysts).
- Inbox date: {date}. Big-tech September-quarter earnings arrive in late October
  (GOOGL Oct 27, MSFT Oct 28, AMZN and AAPL Oct 29); NVDA reports in November.
- Every person, firm, fund, research product, dataset and number is fictional, but realistic.
  Use real company names only for the five targets and for widely known public companies when
  needed, and never present fabricated items as real news.
- Each email arrives with labels already assigned. Write the email so those labels are clearly
  defensible from its content. The labels are fixed and are attached to your output afterwards.
- Label vocabulary: triage is one of thesis_relevant (the label spelled "relevent" above),
  monitor, redundant, low_value, irrelevant. additional_labels draw from macro, government,
  sector, other and human_attention. affected_tickers draw from AMZN, NVDA, MSFT, AAPL, GOOGL,
  and every listed ticker must be named and materially discussed in the email.
- When affected_tickers is empty, do not make any of Amazon, Nvidia, Microsoft, Apple or
  Google/Alphabet a meaningful subject of the email.
- systemic=true means one development affecting all five targets together.
- human_attention=true: a credible, valuable, time-sensitive meeting or call worth taking.
  Meeting types with human_attention=false must read as noise (generic networking, sales,
  routine or low-access events).
- "angle" is a hint on how the email should earn its label.
- Vary senders, formats (full notes, bulletins, forwards, short personal notes, invitations,
  transcripts, data tables) and lengths (roughly 80 to 450 words in the body).
- Do not reuse scenarios, firms or headlines from the list of subjects already in the inbox.
"""

OUTPUT_RULES = """\
Return only a JSON array with one object per slot, in the same order, each with exactly these
keys: "email_id", "sender", "sender_email", "subject", "body", "reason".
- "sender": name, title and firm on one line.
- "body": the full email text with \\n line breaks.
- "reason": two or three concise sentences explaining the primary triage decision from the
  email's content (mention human attention when applicable).
No markdown fences, no commentary."""


def load_env() -> None:
    env_file = ROOT / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text().splitlines():
        key, sep, value = line.partition("=")
        if sep and not line.lstrip().startswith("#"):
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def read_plan(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line]


def slot_spec(slot: dict) -> dict:
    keys = ("email_id", "triage", "email_type", "affected_tickers", "additional_labels",
            "human_attention", "systemic", "angle")
    return {k: slot[k] for k in keys}


def examples_block() -> str:
    shots = []
    for example in json.loads(EXAMPLES_PATH.read_text()):
        shots.append(
            "SLOT: " + json.dumps(slot_spec(example))
            + "\nOUTPUT: " + json.dumps({k: example[k] for k in TEXT_FIELDS})
        )
    return (
        "## Style examples\n\nThese show the expected quality and how text earns its labels. "
        "Do not reuse their scenarios, people or firms.\n\n" + "\n\n".join(shots)
    )


def call_claude(*, system: str, user: str, model: str, max_tokens: int) -> str:
    headers = {
        "x-api-key": os.environ["ANTHROPIC_API_KEY"],
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }
    if os.environ.get("ANTHROPIC_WORKSPACE_ID"):
        headers["anthropic-workspace-id"] = os.environ["ANTHROPIC_WORKSPACE_ID"]
    payload = {
        "model": model,
        "max_tokens": max_tokens,
        "temperature": 1.0,
        "system": system,
        "messages": [{"role": "user", "content": user}],
    }
    request = urllib.request.Request(API_URL, data=json.dumps(payload).encode(), headers=headers)
    with urllib.request.urlopen(request, timeout=600) as response:
        data = json.loads(response.read())
    if data.get("stop_reason") == "max_tokens":
        raise ValueError("response truncated at max_tokens")
    return "".join(block.get("text", "") for block in data["content"])


def parse_batch(text: str, batch: list[dict]) -> list[dict]:
    start, end = text.find("["), text.rfind("]")
    items = json.loads(text[start:end + 1])
    expected = [s["email_id"] for s in batch]
    got = [item.get("email_id") for item in items]
    if got != expected:
        raise ValueError(f"email_ids {got} != {expected}")
    for item, slot in zip(items, batch):
        for key in ("sender", "sender_email", "subject", "body", "reason"):
            if not isinstance(item.get(key), str) or not item[key].strip():
                raise ValueError(f"{slot['email_id']} missing {key}")
        text_blob = item["subject"] + "\n" + item["body"]
        for ticker in slot["affected_tickers"]:
            if not any(name in text_blob for name in TICKER_NAMES[ticker]):
                raise ValueError(f"{slot['email_id']} never mentions {ticker}")
        for ticker, names in TICKER_NAMES.items():
            if ticker not in slot["affected_tickers"]:
                hits = sum(len(re.findall(rf"\b{re.escape(n)}\b", text_blob)) for n in names)
                if hits >= 3:
                    raise ValueError(f"{slot['email_id']} discusses untagged {ticker} ({hits} mentions)")
    records = [full_record(slot, item) for item, slot in zip(items, batch)]
    for record, slot in zip(records, batch):
        assert all(record[k] == slot[k] for k in LABEL_FIELDS), record["email_id"]
    return records


def user_message(batch: list[dict], subjects: list[str]) -> str:
    return (
        "Subjects already in the inbox (avoid repeating these scenarios):\n"
        + ("\n".join(f"- {s}" for s in subjects) or "- (none yet)")
        + "\n\nWrite one email for each slot below.\n\nSLOTS:\n"
        + "\n".join(json.dumps(slot_spec(s)) for s in batch)
        + "\n\n" + OUTPUT_RULES
    )


def generate_batch(batch, *, system, subjects, model, max_tokens, out_dir, attempts=5) -> list[dict]:
    user = user_message(batch, subjects)
    last_error = None
    for attempt in range(attempts):
        try:
            items = parse_batch(call_claude(system=system, user=user, model=model, max_tokens=max_tokens), batch)
            path = out_dir / f"batch_{batch[0]['email_id']}.json"
            path.write_text(json.dumps(items, indent=2, ensure_ascii=False))
            return items
        except urllib.error.HTTPError as exc:
            last_error = f"HTTP {exc.code}: {exc.read().decode(errors='replace')[:300]}"
            if exc.code not in (429, 500, 502, 503, 529):
                break
        except (ValueError, KeyError, json.JSONDecodeError, urllib.error.URLError, TimeoutError) as exc:
            last_error = repr(exc)
        time.sleep(2 ** attempt * 5 + random.random() * 3)
    raise RuntimeError(f"batch starting {batch[0]['email_id']} failed: {last_error}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--day", required=True, help='1, 2, or "tuning"; used for date context and default out-dir')
    parser.add_argument("--out-dir", type=Path, default=None,
                        help='directory for batch files (default: "data/corpus/day <N>" or data/corpus/tuning)')
    parser.add_argument("--plan", type=Path, default=None,
                        help="label plan (default: <out-dir>/email_plan.jsonl)")
    parser.add_argument("--prior-dir", type=Path, action="append", default=None,
                        help="inbox to treat as already seen (repeatable; default: previous calendar day)")
    parser.add_argument("--model", default=None)
    parser.add_argument("--batch-size", type=int, default=6)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--max-tokens", type=int, default=16000)
    parser.add_argument("--limit", type=int, default=None, help="only draft this many slots")
    parser.add_argument("--dry-run", action="store_true", help="print the first request and exit")
    args = parser.parse_args()

    load_env()
    model = args.model or os.environ.get("ANTHROPIC_MODEL") or "claude-sonnet-5-5"

    out_dir = args.out_dir or CORPUS_ROOT / (f"day {args.day}" if str(args.day).isdigit() else str(args.day))
    out_dir.mkdir(parents=True, exist_ok=True)
    plan = read_plan(args.plan or out_dir / "email_plan.jsonl")
    drafts = parse_drafts(out_dir)
    todo = [s for s in plan if s["email_id"] not in drafts][: args.limit]
    if not todo:
        print("nothing to draft")
        return

    system = "\n\n".join([
        PROMPT_PATH.read_text(),
        CONTEXT.format(date=DAY_DATES.get(args.day, DAY_DATES.get(int(args.day) if str(args.day).isdigit() else None, f"day {args.day}"))),
        examples_block(),
    ])

    subjects = [d["subject"] for d in drafts.values()]
    prior_dirs = args.prior_dir
    if prior_dirs is None and str(args.day).isdigit() and int(args.day) > 1:
        prior_dirs = [CORPUS_ROOT / f"day {int(args.day) - 1}"]
    for prior_dir in prior_dirs or []:
        if prior_dir.exists():
            prior = parse_drafts(prior_dir)
            subjects += [f"(already in corpus) {d['subject']}" for d in prior.values()]

    batches = [todo[i:i + args.batch_size] for i in range(0, len(todo), args.batch_size)]
    if args.dry_run:
        print(f"SYSTEM ({len(system)} chars):\n{system}\n\nUSER:\n{user_message(batches[0], subjects)}")
        return
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise SystemExit("ANTHROPIC_API_KEY is not set")

    print(f"day {args.day}: drafting {len(todo)} emails in {len(batches)} batches with {model} -> {out_dir}")
    failures = []
    waves = [batches[i:i + args.workers] for i in range(0, len(batches), args.workers)]
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        for wave in waves:
            futures = [
                pool.submit(generate_batch, batch, system=system, subjects=list(subjects), model=model,
                            max_tokens=args.max_tokens, out_dir=out_dir)
                for batch in wave
            ]
            for future in as_completed(futures):
                try:
                    items = future.result()
                except RuntimeError as exc:
                    failures.append(str(exc))
                    print("FAILED", exc, flush=True)
                    continue
                subjects += [item["subject"] for item in items]
                print(f"{items[0]['email_id']}..{items[-1]['email_id']}: {len(items)} emails", flush=True)
    if failures:
        raise SystemExit(f"{len(failures)} batches failed; rerun to retry the remaining slots")


if __name__ == "__main__":
    main()
