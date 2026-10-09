"""Merge drafted email text with the day's label plan and write validated JSONL.

Batch files live next to the plan in the day folder (e.g. "data/corpus/day 1").
JSON batches (written by generate_emails_llm.py) are arrays of records with at
least {email_id, sender, sender_email, subject, body, reason}. Hand-written .txt
drafts hold blocks like:

    @@@ synthetic_000001
    sender: Dana Whitcomb, Semiconductor Analyst, Marlowe Securities
    sender_email: dwhitcomb@marlowesec.com
    subject: NVDA: Supplier checks indicate tightening capacity
    reason: One or more sentences explaining the triage decision.
    body:
    Free-form multi-line body text...

An existing <dir>/emails.jsonl also counts as drafts, so batches can be merged
incrementally. After a verified merge the batch files are removed (pass
--keep-batches to keep them), leaving one email file per day.

Labels come from <dir>/email_plan.jsonl. Each record in <dir>/emails.jsonl holds
every field of the prompt's schema (email_id, sender, sender_email, subject,
body, triage, additional_labels, affected_tickers, human_attention, reason)
plus the generation labels (email_type, systemic, angle, day).

Usage:
    python scripts/build_email_jsonl.py --dir "data/corpus/day 1"
"""

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

from generate_email_plan import summarize

HEADER_FIELDS = ("sender", "sender_email", "subject", "reason")
BLOCK_START = re.compile(r"^@@@ (synthetic_\d{6})\s*$", re.MULTILINE)
TICKER_NAMES = {
    "AMZN": ("AMZN", "Amazon", "AWS"),
    "NVDA": ("NVDA", "Nvidia", "NVIDIA"),
    "MSFT": ("MSFT", "Microsoft", "Azure"),
    "AAPL": ("AAPL", "Apple", "iPhone"),
    "GOOGL": ("GOOGL", "Google", "Alphabet", "Gemini", "YouTube"),
}


def full_record(slot: dict, draft: dict) -> dict:
    """Prompt schema fields followed by the plan labels the email was generated from."""

    return {
        "email_id": slot["email_id"],
        "sender": draft["sender"],
        "sender_email": draft["sender_email"],
        "subject": draft["subject"],
        "body": draft["body"],
        "triage": slot["triage"],
        "additional_labels": slot["additional_labels"],
        "affected_tickers": slot["affected_tickers"],
        "human_attention": slot["human_attention"],
        "reason": draft["reason"],
        "email_type": slot["email_type"],
        "systemic": slot["systemic"],
        "angle": slot["angle"],
        "day": slot["day"],
    }


def parse_drafts(draft_dir: Path) -> dict[str, dict]:
    drafts: dict[str, dict] = {}
    for path in sorted(draft_dir.glob("batch_*.json")):
        for item in json.loads(path.read_text()):
            email_id = item["email_id"]
            missing = [f for f in (*HEADER_FIELDS, "body") if not str(item.get(f, "")).strip()]
            if missing:
                raise SystemExit(f"{path.name}:{email_id} is missing {missing}")
            if email_id in drafts:
                raise SystemExit(f"{email_id} is drafted twice")
            drafts[email_id] = {f: " ".join(str(item[f]).split()) for f in HEADER_FIELDS}
            drafts[email_id]["body"] = str(item["body"]).strip()
    for path in sorted(draft_dir.glob("*.txt")):
        text = path.read_text()
        starts = list(BLOCK_START.finditer(text))
        for i, match in enumerate(starts):
            email_id = match.group(1)
            end = starts[i + 1].start() if i + 1 < len(starts) else len(text)
            block = text[match.end():end].strip("\n")
            head, sep, body = block.partition("\nbody:\n")
            if not sep:
                raise SystemExit(f"{path.name}:{email_id} is missing a 'body:' line")
            fields = {}
            for line in head.splitlines():
                key, _, value = line.partition(":")
                fields[key.strip()] = value.strip()
            missing = [f for f in HEADER_FIELDS if not fields.get(f)]
            if missing:
                raise SystemExit(f"{path.name}:{email_id} is missing {missing}")
            if email_id in drafts:
                raise SystemExit(f"{email_id} is drafted twice")
            fields["body"] = body.strip()
            drafts[email_id] = fields
    merged = draft_dir / "emails.jsonl"
    if merged.exists():
        for line in merged.read_text().splitlines():
            if line:
                record = json.loads(line)
                drafts.setdefault(record["email_id"], {f: record[f] for f in (*HEADER_FIELDS, "body")})
    return drafts


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dir", type=Path, required=True,
                        help='day folder holding email_plan.jsonl and batch files, e.g. "data/corpus/day 1"')
    parser.add_argument("--keep-batches", action="store_true",
                        help="keep batch_*.json files after merging them into emails.jsonl")
    args = parser.parse_args()

    day_dir = args.dir
    plan = [json.loads(line) for line in (day_dir / "email_plan.jsonl").read_text().splitlines() if line]
    drafts = parse_drafts(day_dir)

    planned = {p["email_id"] for p in plan}
    missing = sorted(planned - drafts.keys())
    extra = sorted(drafts.keys() - planned)
    if missing or extra:
        raise SystemExit(f"missing drafts: {missing[:20]} ({len(missing)})\nunplanned drafts: {extra}")

    warnings = []
    records = []
    for slot in plan:
        draft = drafts[slot["email_id"]]
        text = f"{draft['subject']}\n{draft['body']}"
        for ticker in slot["affected_tickers"]:
            if not any(name in text for name in TICKER_NAMES[ticker]):
                warnings.append(f"{slot['email_id']}: {ticker} not mentioned")
        records.append(full_record(slot, draft))

    subjects = Counter(r["subject"] for r in records)
    dupes = [s for s, n in subjects.items() if n > 1]
    if dupes:
        warnings.append(f"duplicate subjects: {dupes}")

    out_path = day_dir / "emails.jsonl"
    out_path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records))
    words = [len(r["body"].split()) for r in records]
    print(f"wrote {out_path}: {len(records)} emails, body words min/avg/max "
          f"{min(words)}/{sum(words) // len(words)}/{max(words)}")
    print(summarize(records))
    for line in warnings:
        print("WARN", line, file=sys.stderr)

    written = {json.loads(line)["email_id"]: json.loads(line) for line in out_path.read_text().splitlines()}
    if not args.keep_batches and written == {r["email_id"]: r for r in records}:
        batches = sorted(day_dir.glob("batch_*.json"))
        for path in batches:
            path.unlink()
        print(f"merged and removed {len(batches)} batch files")


if __name__ == "__main__":
    main()
