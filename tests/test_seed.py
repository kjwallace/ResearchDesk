import json

from triage_app.config import SEED_DIR
from triage_app.state.fold import load_seed


def test_seed_matches_spec_shape() -> None:
    seed = load_seed()
    assert sum(len(t.pillars) for t in seed.theses) == 15
    assert sum(len(m.drivers) for m in seed.models) == 23
    driver_ids = {d.id for m in seed.models for d in m.drivers}
    for t in seed.theses:
        for p in t.pillars:
            assert p.id.startswith(t.ticker + ".") and set(p.driver_ids) <= driver_ids
    pillar_ids = {p.id for t in seed.theses for p in t.pillars}
    assert all(set(link.to_pillar_ids) <= pillar_ids for link in seed.links)


def test_drivers_within_bounds_and_directions() -> None:
    seed = load_seed()
    above = {"NVDA.data_center_growth", "MSFT.intelligent_cloud_growth", "MSFT.productivity_growth",
             "AMZN.aws_growth", "AMZN.operating_margin", "GOOGL.capex"}
    below = {"AAPL.iphone_growth", "AAPL.services_growth", "AAPL.operating_margin",
             "GOOGL.services_growth", "GOOGL.operating_margin"}
    for m in seed.models:
        assert not m.placeholder_base and m.source_url
        for d in m.drivers:
            assert d.min <= d.analyst <= d.max and d.min <= d.consensus <= d.max
            if d.id in above:
                assert d.analyst > d.consensus, d.id
            elif d.id in below:
                assert d.analyst < d.consensus, d.id
            else:
                assert d.analyst == d.consensus, d.id


def test_draft_has_no_base_figures() -> None:
    draft = json.loads((SEED_DIR / "models_draft.json").read_text())
    text = json.dumps(draft)
    for banned in ("base_revenue", "tax_rate", "diluted_shares"):
        assert banned not in text
