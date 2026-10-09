"""Randomly generate the label / email-type plan for one day of synthetic desk email.

Follows "Label and Email Type Distribution" in docs/corpus_documentation/synthetic_data_prompt.md:

- triage mix of ~10/15/10/35/30 (thesis_relevant/monitor/redundant/low_value/irrelevant),
  jittered so batches vary
- target tickers rotated evenly through thesis_relevant and monitor
- at most ~15% of low_value + irrelevant emails reference a target ticker
- meeting requests, newsletters and event invitations are at least 20% of the flow
- human_attention on ~15-25 credible, actionable meeting requests only
- macro / government / sector labels on ~25-35 emails
- systemic all-ticker emails kept rare (well under 10%)

Counts that the prompt states as absolute numbers for a 300-email day (human
attention, macro/government/sector, systemic, "other") scale with --count.

Usage:
    python scripts/corpus_generation/generate_email_plan.py --day 1 --seed 1101 --start-id 1
    python scripts/corpus_generation/generate_email_plan.py --day 2 --seed 2202 --start-id 301
    python scripts/corpus_generation/generate_email_plan.py --day tuning --seed 3303 --start-id 601 --count 100 --out-dir data/corpus/tuning
"""

import argparse
import json
import random
from collections import Counter
from pathlib import Path

TICKERS = ["AMZN", "NVDA", "MSFT", "AAPL", "GOOGL"]

TRIAGE_TARGETS = {
    "thesis_relevant": 0.10,
    "monitor": 0.15,
    "redundant": 0.10,
    "low_value": 0.35,
    "irrelevant": 0.30,
}

MEETING_LIKE = {"meeting_request", "expert_call_offer", "event_invitation", "newsletter"}

TYPE_WEIGHTS = {
    "thesis_relevant": {
        "sell_side_research": 5, "channel_check": 4, "expert_network_transcript": 3,
        "industry_contact": 3, "news_alert": 2, "vendor_data_report": 2,
        "company_ir": 1, "sell_side_morning_note": 1, "internal_forward": 1,
    },
    "monitor": {
        "sell_side_research": 3, "channel_check": 3, "industry_contact": 3,
        "expert_network_transcript": 2, "news_alert": 3, "vendor_data_report": 2,
        "sell_side_sales_color": 1, "newsletter": 1, "internal_forward": 1,
        "meeting_request": 1, "event_invitation": 0.5,
    },
    "redundant": {
        "news_alert": 4, "sell_side_research": 3, "sell_side_morning_note": 3,
        "newsletter": 2, "company_ir": 1, "vendor_data_report": 1, "internal_forward": 1,
    },
    "low_value": {
        "newsletter": 2, "sell_side_research": 3, "vendor_data_report": 2, "news_alert": 2,
        "meeting_request": 1.5, "event_invitation": 1, "vendor_sales_pitch": 2,
        "sell_side_morning_note": 1.5, "industry_contact": 1, "sell_side_sales_color": 1,
        "expert_call_offer": 0.5,
    },
    "irrelevant": {
        "sell_side_research": 4, "newsletter": 2, "event_invitation": 2, "meeting_request": 1,
        "vendor_sales_pitch": 3, "news_alert": 3, "administrative": 1.5, "expert_call_offer": 0.5,
    },
}

LABEL_TYPE_WEIGHTS = {
    "macro": {"macro_strategy": 4, "news_alert": 2, "sell_side_morning_note": 2, "newsletter": 1},
    "government": {"government_regulatory": 4, "news_alert": 3, "sell_side_research": 1},
    "sector": {"sell_side_research": 3, "industry_contact": 2, "vendor_data_report": 2,
               "channel_check": 2, "news_alert": 1},
}

ANGLES = {
    "thesis_relevant": [
        "contradicts consensus with new evidence",
        "supports the thesis with genuinely new data",
        "unexpected development not yet priced",
        "understated email with a single material insight",
        "estimate-changing numbers (revenue, margin, capex, units)",
        "value depends on the desk's existing exposure",
    ],
    "monitor": [
        "early, unconfirmed signal",
        "second-order read-through from a non-target company",
        "developing regulatory or legal process",
        "anecdotal channel datapoint needing confirmation",
        "shift in management or customer tone",
        "supply-chain rumor from a plausible source",
    ],
    "redundant": [
        "rehash of widely reported news",
        "sophisticated analysis that repeats consensus",
        "duplicate of an earlier alert",
        "recap of a public earnings call or event",
        "re-forwarded note already circulated",
    ],
    "low_value": [
        "detailed data with no thesis-changing conclusion",
        "promotional content mixed with weak analysis",
        "tangential mention of a target company",
        "routine analyst meeting with no differentiated access",
        "stale or recycled datapoints",
        "speculative, weakly sourced claim",
    ],
    "irrelevant": [
        "excellent research on an unrelated company",
        "prestigious but irrelevant conference",
        "credible macro commentary with no target impact",
        "important-looking legal or government notice with no relevance",
        "vendor sales pitch",
        "administrative or operational email",
        "news from an unrelated sector",
    ],
}

HA_TYPES = {"meeting_request": 6, "expert_call_offer": 3, "event_invitation": 1}


def weighted_choice(rng: random.Random, weights: dict[str, float]) -> str:
    keys = list(weights)
    return rng.choices(keys, weights=[weights[k] for k in keys], k=1)[0]


def scaled_range(rng: random.Random, total: int, lo: int, hi: int, *, floor: int = 0) -> int:
    """Scale a 300-email count range to `total` emails."""

    a = max(floor, round(lo * total / 300))
    b = max(a, round(hi * total / 300))
    return rng.randint(a, b)


def triage_counts(rng: random.Random, total: int) -> dict[str, int]:
    jitter = max(1, round(3 * total / 300))
    counts = {label: round(share * total) + rng.randint(-jitter, jitter) for label, share in TRIAGE_TARGETS.items()}
    while sum(counts.values()) != total:
        label = rng.choice(["low_value", "irrelevant"])
        counts[label] += 1 if sum(counts.values()) < total else -1
    return counts


def balanced_tickers(rng: random.Random, n: int) -> list[str]:
    pool: list[str] = []
    while len(pool) < n:
        cycle = TICKERS[:]
        rng.shuffle(cycle)
        pool.extend(cycle)
    return pool[:n]


def build_plan(rng: random.Random, total: int, start_id: int, day: int) -> list[dict]:
    counts = triage_counts(rng, total)
    slots = [{"triage": label} for label, n in counts.items() for _ in range(n)]

    for slot in slots:
        slot.update(additional_labels=[], affected_tickers=[], human_attention=False, systemic=False)

    by_triage = {label: [s for s in slots if s["triage"] == label] for label in counts}

    # Systemic all-ticker emails: rare, carry macro/government/sector drivers.
    systemic_pool = by_triage["thesis_relevant"][:1] + by_triage["monitor"] + by_triage["redundant"]
    n_systemic = min(len(systemic_pool), scaled_range(rng, total, 3, 6, floor=1))
    for slot in rng.sample(systemic_pool, n_systemic):
        slot["systemic"] = True
        slot["affected_tickers"] = TICKERS[:]
        slot["additional_labels"] = [rng.choice(["macro", "government", "sector"])]

    # Balanced single-name coverage across thesis_relevant and monitor.
    for label, second_prob in (("thesis_relevant", 0.2), ("monitor", 0.25)):
        names = [s for s in by_triage[label] if not s["systemic"]]
        for slot, ticker in zip(names, balanced_tickers(rng, len(names))):
            slot["affected_tickers"] = [ticker]
            if rng.random() < second_prob:
                slot["affected_tickers"].append(rng.choice([t for t in TICKERS if t != ticker]))

    for slot in by_triage["redundant"]:
        if not slot["systemic"] and rng.random() < 0.7:
            slot["affected_tickers"] = [rng.choice(TICKERS)]

    # Noise: cap direct target references at ~15% of low_value + irrelevant.
    noise = by_triage["low_value"] + by_triage["irrelevant"]
    cap = int(0.15 * len(noise))
    trim = min(max(0, cap - 1), scaled_range(rng, total, 1, 3, floor=0))
    n_lv = min(max(0, cap - trim), len(by_triage["low_value"]))
    if n_lv:
        for slot in rng.sample(by_triage["low_value"], n_lv):
            slot["affected_tickers"] = [rng.choice(TICKERS)]
    n_ir = min(max(0, cap - n_lv), len(by_triage["irrelevant"]))
    if n_ir:
        for slot in rng.sample(by_triage["irrelevant"], n_ir):
            slot["affected_tickers"] = [rng.choice(TICKERS)]

    # macro / government / sector on ~10% of emails (25–35 per 300).
    target_labeled = scaled_range(rng, total, 27, 33, floor=1)
    already = sum(1 for s in slots if s["additional_labels"])
    candidates = [s for s in slots if not s["additional_labels"]]
    label_bias = {"thesis_relevant": 1.0, "monitor": 2.0, "redundant": 1.0, "low_value": 1.2, "irrelevant": 1.2}
    chosen: list[dict] = []
    need = max(0, min(target_labeled - already, len(candidates)))
    while len(chosen) < need:
        pick = rng.choices(candidates, weights=[label_bias[s["triage"]] for s in candidates], k=1)[0]
        if pick not in chosen:
            chosen.append(pick)
    for slot in chosen:
        slot["additional_labels"] = [rng.choice(["macro", "government", "sector"])]
        if rng.random() < 0.2:
            extra = rng.choice([x for x in ("macro", "government", "sector") if x not in slot["additional_labels"]])
            slot["additional_labels"].append(extra)

    unlabeled = [s for s in slots if not s["additional_labels"]]
    n_other = min(len(unlabeled), scaled_range(rng, total, 4, 8, floor=0))
    if n_other:
        for slot in rng.sample(unlabeled, n_other):
            slot["additional_labels"] = ["other"]

    # human_attention: ~5–7.5% (15–25 per 300), only in thesis_relevant / monitor.
    ha_pool = [s for s in by_triage["thesis_relevant"] + by_triage["monitor"] if not s["systemic"]]
    n_ha = min(len(ha_pool), scaled_range(rng, total, 17, 23, floor=1))
    for slot in rng.sample(ha_pool, n_ha):
        slot["human_attention"] = True
        slot["email_type"] = weighted_choice(rng, HA_TYPES)

    for slot in slots:
        if "email_type" in slot:
            continue
        labels = [x for x in slot["additional_labels"] if x in LABEL_TYPE_WEIGHTS]
        if labels and rng.random() < 0.8:
            slot["email_type"] = weighted_choice(rng, LABEL_TYPE_WEIGHTS[rng.choice(labels)])
        else:
            slot["email_type"] = weighted_choice(rng, TYPE_WEIGHTS[slot["triage"]])

    # Meeting requests, newsletters and events must be at least 20% of the day.
    minimum = int(0.2 * total) + scaled_range(rng, total, 2, 8, floor=0)
    convertible = [s for s in noise if s["email_type"] not in MEETING_LIKE and not s["additional_labels"]]
    rng.shuffle(convertible)
    while sum(s["email_type"] in MEETING_LIKE for s in slots) < minimum and convertible:
        convertible.pop()["email_type"] = rng.choice(
            ["meeting_request", "event_invitation", "newsletter", "newsletter", "expert_call_offer"]
        )

    for slot in slots:
        slot["angle"] = rng.choice(ANGLES[slot["triage"]])
        if slot["human_attention"]:
            slot["additional_labels"] = slot["additional_labels"] + ["human_attention"]

    rng.shuffle(slots)
    plan = []
    for offset, slot in enumerate(slots):
        plan.append(
            {
                "email_id": f"synthetic_{start_id + offset:06d}",
                "day": day,
                "triage": slot["triage"],
                "email_type": slot["email_type"],
                "affected_tickers": slot["affected_tickers"],
                "additional_labels": slot["additional_labels"],
                "human_attention": slot["human_attention"],
                "systemic": slot["systemic"],
                "angle": slot["angle"],
            }
        )
    return plan


def summarize(plan: list[dict]) -> str:
    total = len(plan)
    triage = Counter(p["triage"] for p in plan)
    lines = [f"emails: {total}", "triage:"]
    lines += [f"  {k:<16}{triage[k]:>4}  ({triage[k] / total:.0%})" for k in TRIAGE_TARGETS]
    signal = [p for p in plan if p["triage"] in ("thesis_relevant", "monitor")]
    for label in ("thesis_relevant", "monitor"):
        tick = Counter(t for p in plan if p["triage"] == label for t in p["affected_tickers"])
        lines.append(f"{label} tickers: " + ", ".join(f"{t}={tick[t]}" for t in TICKERS))
    noise = [p for p in plan if p["triage"] in ("low_value", "irrelevant")]
    noisy_refs = sum(bool(p["affected_tickers"]) for p in noise)
    lines.append(f"noise referencing a target: {noisy_refs}/{len(noise)} ({noisy_refs / len(noise):.0%})")
    meet = sum(p["email_type"] in MEETING_LIKE for p in plan)
    lines.append(f"meeting/newsletter/event: {meet} ({meet / total:.0%})")
    lines.append(f"human_attention: {sum(p['human_attention'] for p in plan)}")
    mgs = sum(any(x in ("macro", "government", "sector") for x in p["additional_labels"]) for p in plan)
    lines.append(f"macro/government/sector: {mgs}")
    lines.append(f"systemic all-ticker: {sum(p['systemic'] for p in plan)}")
    lines.append(f"signal emails: {len(signal)}")
    lines.append("email types: " + ", ".join(f"{k}={v}" for k, v in Counter(p["email_type"] for p in plan).most_common()))
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--day", required=True, help='stored in each slot: 1, 2, or "tuning"')
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--count", type=int, default=300)
    parser.add_argument("--start-id", type=int, default=1)
    parser.add_argument("--out-root", type=Path, default=Path("data/corpus"))
    parser.add_argument("--out-dir", type=Path, default=None,
                        help='plan directory (default: <out-root>/day <N>)')
    args = parser.parse_args()

    day = int(args.day) if args.day.isdigit() else args.day
    plan = build_plan(random.Random(args.seed), args.count, args.start_id, day)
    out_dir = args.out_dir or args.out_root / (f"day {day}" if isinstance(day, int) else str(day))
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "email_plan.jsonl"
    out_path.write_text("".join(json.dumps(p) + "\n" for p in plan))
    print(f"wrote {out_path}")
    print(summarize(plan))


if __name__ == "__main__":
    main()
