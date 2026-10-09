import pytest

from triage_app.schema import CompanyModel, Driver, RevenueLine
from triage_app.state.compute import compute, project
from triage_app.state.fold import load_seed


def toy() -> CompanyModel:
    return CompanyModel(
        ticker="NVDA", fiscal_year="FY2027", tax_rate=0.2, diluted_shares_bn=2.0, target_multiple=10,
        revenue_lines=[RevenueLine(driver_id="NVDA.a_growth", base_revenue_usd_bn=100),
                       RevenueLine(driver_id="NVDA.b_growth", base_revenue_usd_bn=50)],
        drivers=[
            Driver(id="NVDA.a_growth", label="a", unit="pct", analyst=10, consensus=0, min=-50, max=50),
            Driver(id="NVDA.b_growth", label="b", unit="pct", analyst=-20, consensus=0, min=-50, max=50),
            Driver(id="NVDA.operating_margin", label="m", unit="pct", analyst=50, consensus=40, min=0, max=90),
        ],
    )


def test_formulas_by_hand() -> None:
    p = compute(toy())["analyst"]
    assert p.revenue_usd_bn == pytest.approx(110 + 40)
    assert p.operating_income_usd_bn == pytest.approx(75)
    assert p.eps == pytest.approx(75 * 0.8 / 2)
    assert p.target_price == pytest.approx(30 * 10)


def test_consensus_basis() -> None:
    p = compute(toy())["consensus"]
    assert p.revenue_usd_bn == pytest.approx(150)
    assert p.eps == pytest.approx(150 * 0.4 * 0.8 / 2)


def test_override_changes_eps() -> None:
    m = toy()
    base = project(m, {d.id: d.analyst for d in m.drivers})
    bumped = project(m, {**{d.id: d.analyst for d in m.drivers}, "NVDA.operating_margin": 60})
    assert bumped.eps > base.eps


def test_seed_computes_for_all_five() -> None:
    seed = load_seed()
    assert sorted(m.ticker for m in seed.models) == ["AAPL", "AMZN", "GOOGL", "MSFT", "NVDA"]
    for m in seed.models:
        for basis, p in compute(m).items():
            assert p.eps > 0 and p.target_price > 0, (m.ticker, basis)
