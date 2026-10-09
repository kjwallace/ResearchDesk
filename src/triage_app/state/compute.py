"""Revenue, EPS and target price from a company's drivers. Pure functions.

- Revenue is the sum of each line's base revenue times one plus its growth.
- Operating income is revenue times operating margin.
- EPS is operating income, less tax, divided by diluted shares.
- Target price is EPS times the target multiple.

`pct` drivers are in percentage points (12.5 means 12.5%); the tax rate is a fraction.
Capex does not feed EPS.
"""

from collections.abc import Mapping
from typing import Literal

from pydantic import BaseModel

from triage_app.schema import CompanyModel


class Projection(BaseModel):
    revenue_usd_bn: float
    operating_income_usd_bn: float
    eps: float
    target_price: float


def driver_values(model: CompanyModel, basis: Literal["analyst", "consensus"]) -> dict[str, float]:
    return {d.id: (d.analyst if basis == "analyst" else d.consensus) for d in model.drivers}


def project(model: CompanyModel, values: Mapping[str, float]) -> Projection:
    revenue = sum(line.base_revenue_usd_bn * (1 + values[line.driver_id] / 100) for line in model.revenue_lines)
    operating_income = revenue * values[f"{model.ticker}.operating_margin"] / 100
    eps = operating_income * (1 - model.tax_rate) / model.diluted_shares_bn
    return Projection(
        revenue_usd_bn=revenue,
        operating_income_usd_bn=operating_income,
        eps=eps,
        target_price=eps * model.target_multiple,
    )


def compute(model: CompanyModel) -> dict[str, Projection]:
    """Projections on the analyst's values and on consensus."""
    return {
        "analyst": project(model, driver_values(model, "analyst")),
        "consensus": project(model, driver_values(model, "consensus")),
    }
