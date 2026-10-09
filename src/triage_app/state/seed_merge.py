"""Merge the book prompt's draft with base figures from filings into data/seed/models.json.

Inputs:
  data/seed/models_draft.json  synthetic drivers, consensus, bounds and multiples (prompt 01)
  data/seed/base_figures.json  base revenue by line, tax rate and diluted shares from each 10-K

A company whose base figures are missing gets placeholder figures and
`placeholder_base: true`, so the Company screen can say so. An invented figure is never
presented as a reported one.

Usage:
    uv run python -m triage_app.state.seed_merge
"""

import json
from pathlib import Path
from typing import Any

from triage_app.config import SEED_DIR
from triage_app.schema import CompanyModel, RevenueLine

# Used only when a filing could not be read; marked placeholder_base on the model.
PLACEHOLDER_LINE_USD_BN = 10.0
PLACEHOLDER_TAX_RATE = 0.15
PLACEHOLDER_SHARES_BN = 1.0


def revenue_driver_ids(draft: dict[str, Any]) -> list[str]:
    return [d["id"] for d in draft["drivers"] if d["id"].endswith("_growth")]


def merge_one(draft: dict[str, Any], base: dict[str, Any] | None) -> CompanyModel:
    line_ids = revenue_driver_ids(draft)
    lines_in = (base or {}).get("revenue_lines") or {}
    tax = (base or {}).get("tax_rate")
    shares = (base or {}).get("diluted_shares_bn")
    complete = base is not None and all(lines_in.get(i) is not None for i in line_ids) \
        and tax is not None and shares is not None
    lines: list[RevenueLine]
    tax_rate: float
    shares_bn: float
    if complete and tax is not None and shares is not None:
        lines = [RevenueLine(driver_id=i, base_revenue_usd_bn=float(lines_in[i])) for i in line_ids]
        tax_rate, shares_bn = float(tax), float(shares)
    else:
        lines = [RevenueLine(driver_id=i, base_revenue_usd_bn=PLACEHOLDER_LINE_USD_BN) for i in line_ids]
        tax_rate, shares_bn = PLACEHOLDER_TAX_RATE, PLACEHOLDER_SHARES_BN
    fiscal_year = draft["fiscal_year"]
    if complete and base and base.get("fiscal_year_reported"):
        # compute applies one year of growth to the reported base, so the modeled
        # year is the year after the latest annual report.
        fiscal_year = f"FY{int(str(base['fiscal_year_reported'])[2:]) + 1}"
    return CompanyModel.model_validate({
        **{k: v for k, v in draft.items() if k in {"ticker", "synthetic", "target_multiple", "drivers"}},
        "fiscal_year": fiscal_year,
        "revenue_lines": [line.model_dump() for line in lines],
        "tax_rate": tax_rate,
        "diluted_shares_bn": shares_bn,
        "source_url": (base or {}).get("source_url"),
        "placeholder_base": not complete,
    })


def merge(seed_dir: Path = SEED_DIR) -> list[CompanyModel]:
    drafts: list[dict[str, Any]] = json.loads((seed_dir / "models_draft.json").read_text())
    base_path = seed_dir / "base_figures.json"
    bases: dict[str, Any] = json.loads(base_path.read_text()) if base_path.exists() else {}
    models = [merge_one(d, bases.get(d["ticker"])) for d in drafts]
    for m in models:
        for d in m.drivers:
            if not (d.min <= d.analyst <= d.max and d.min <= d.consensus <= d.max):
                raise ValueError(f"{d.id}: analyst or consensus outside its bounds")
    (seed_dir / "models.json").write_text(
        json.dumps([m.model_dump(mode="json") for m in models], indent=2) + "\n")
    return models


if __name__ == "__main__":
    for m in merge():
        flag = "PLACEHOLDER base figures" if m.placeholder_base else "base figures from filings"
        print(f"{m.ticker}: {len(m.drivers)} drivers, {flag}")
