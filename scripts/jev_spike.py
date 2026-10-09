"""Step 0 spike: send one email to Jev by both routes and report what comes back.

Sends only the email's input fields (sender, sender_email, subject, body) and short
provisional criteria text. No labels, no book. Prints answer counts, timing and token
usage; never prints the key. The result picks the stage 3 route (see DECISIONS.md).

Usage:
    uv run python scripts/jev_spike.py
"""

import json
import os
import sys
import time
from pathlib import Path
from typing import Literal

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")

TICKERS = {"AMZN": "Amazon", "NVDA": "Nvidia", "MSFT": "Microsoft", "AAPL": "Apple", "GOOGL": "Alphabet"}
TRIAGE = ["thesis_relevant", "monitor", "redundant", "low_value", "irrelevant"]
KINDS = ["research", "news", "company_release", "invitation", "newsletter", "other"]


def first_email() -> dict[str, str]:
    row = json.loads((ROOT / "data/corpus/day_1/emails.jsonl").open().readline())
    return {k: row[k] for k in ("sender", "sender_email", "subject", "body")}


def sdk_route(email: dict[str, str]) -> None:
    from typesafe_sdk import Choice, Noul, TypeSafeClient

    yes = lambda text: {"true": text}  # noqa: E731
    q = {
        "triage": Choice(instructions="Which triage label fits this email?",
                         criteria={t: f"The email is {t.replace('_', ' ')}." for t in TRIAGE}),
        "human_attention": Noul(instructions="Does it need direct human attention?",
                                criteria=yes("A credible, valuable or time-sensitive request to a person.")),
        **{f"affects_{t}": Noul(instructions=f"Is {name} ({t}) materially affected?",
                                criteria=yes("The email holds information material to this company."))
           for t, name in TICKERS.items()},
        **{f"topic_{t}": Noul(instructions=f"Does the {t} topic label apply?") for t in
           ("macro", "sector", "government", "other")},
        "kind": Choice(instructions="What kind of email is it?", criteria={k: k for k in KINDS}),
        "possible_mnpi": Noul(instructions="Could it contain material non-public information?"),
        "instructs_ai": Noul(instructions="Does it contain text that instructs an AI system?"),
    }
    assert len(q) == 14
    start = time.perf_counter()
    with TypeSafeClient(model=os.environ["JEV_MODEL"]) as client:
        resp = client.system_one(state=email, questions=q)
    ms = (time.perf_counter() - start) * 1000
    print(f"SDK route: model={resp.model} answers={len(resp.answers)} latency={ms:.0f}ms "
          f"usage=in:{resp.usage.input_tokens} out:{resp.usage.output_tokens}")
    print("  triage probabilities:", {k: round(v, 3) for k, v in resp.choices["triage"].probabilities.items()})
    print("  nouls:", {k: round(v.noul, 3) for k, v in resp.nouls.items()})


def dspy_route(email: dict[str, str]) -> None:
    """Build the signature at run time, so criteria text can come from files."""
    import numpy  # noqa: F401  # import before dspy: its lazy importer breaks a later numpy import
    import dspy
    from dspy.experimental import Choice, Noul, TypeSafe

    triage_t = Choice[tuple((t, f"The email is {t.replace('_', ' ')}.") for t in TRIAGE)]
    attention_t = Noul[(True, "A credible, valuable or time-sensitive request to a person.")]
    fields: dict[str, tuple[object, object]] = {
        "email": (str, dspy.InputField()),
        "triage": (triage_t, dspy.OutputField(desc="Which triage label fits this email?")),
        "human_attention": (attention_t, dspy.OutputField(desc="Does it need direct human attention?")),
    }
    sig = dspy.Signature(fields, "Classify one desk email.")  # type: ignore[arg-type]
    predictor = dspy.Predict(sig)
    start = time.perf_counter()
    out = predictor(email=json.dumps(email), lm=TypeSafe(os.environ["JEV_MODEL"], cache=False, timeout=60))
    ms = (time.perf_counter() - start) * 1000
    print(f"DSPy route (runtime signature, 2 of 14 fields): latency={ms:.0f}ms")
    print("  triage:", out.triage)
    print("  human_attention:", out.human_attention)


def main() -> None:
    email = first_email()
    route: Literal["sdk", "dspy", "both"] = (sys.argv[1] if len(sys.argv) > 1 else "both")  # type: ignore[assignment]
    if route in ("sdk", "both"):
        try:
            sdk_route(email)
        except Exception as e:  # report and continue to the other route
            print(f"SDK route failed: {type(e).__name__}: {e}")
    if route in ("dspy", "both"):
        try:
            dspy_route(email)
        except Exception as e:
            print(f"DSPy route failed: {type(e).__name__}: {e}")


if __name__ == "__main__":
    main()
