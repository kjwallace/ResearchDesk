import json
import re

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


# ---- Pillar detail, evidence and the street's view ----

# The 15 pillars' id, statement, wrong_if and driver_ids as first seeded; enrichment must not change them.
ORIGINAL_PILLARS: dict[str, tuple[str, str, list[str]]] = {
    'NVDA.p1': (
        'AI infrastructure spending by cloud and sovereign buyers keeps Data Center growth above consensus through the next fiscal year.',
        'Two of MSFT, AMZN and GOOGL guide capital expenditure flat or lower.',
        ['NVDA.data_center_growth'],
    ),
    'NVDA.p2': (
        'Supply of advanced packaging and high-bandwidth memory is sufficient to ship the newest platform on schedule.',
        'Credible evidence of a delay of a quarter or more.',
        ['NVDA.data_center_growth'],
    ),
    'NVDA.p3': (
        'In-house chips at large customers grow alongside Nvidia instead of replacing it, so pricing and margin hold.',
        'A top customer moves most new capacity to in-house chips, or Nvidia cuts pricing to defend share.',
        ['NVDA.operating_margin', 'NVDA.data_center_growth'],
    ),
    'MSFT.p1': (
        'Azure growth stays above consensus as data-center capacity comes online.',
        'Capacity constraints persist for two more quarters, or Azure guidance falls below consensus.',
        ['MSFT.intelligent_cloud_growth'],
    ),
    'MSFT.p2': (
        'Paid AI assistants raise revenue per seat in the productivity suite.',
        'Seat adoption or renewal data show enterprises cutting back.',
        ['MSFT.productivity_growth'],
    ),
    'MSFT.p3': (
        'Capital intensity peaks within the model year and operating margin holds.',
        'Capex guidance is raised again without matching growth in backlog.',
        ['MSFT.capex', 'MSFT.operating_margin'],
    ),
    'AMZN.p1': (
        'AWS growth re-accelerates as power and chip capacity is added.',
        'AWS growth decelerates for two consecutive quarters, or large workloads move to rivals.',
        ['AMZN.aws_growth'],
    ),
    'AMZN.p2': (
        'Retail operating margin keeps expanding through fulfillment efficiency and advertising.',
        'Fulfillment costs rise faster than revenue, or advertising growth slows sharply.',
        ['AMZN.operating_margin', 'AMZN.north_america_growth'],
    ),
    'AMZN.p3': (
        'Capital expenditure converts into AWS backlog instead of a lasting drag on free cash flow.',
        'Capex rises while backlog growth stalls.',
        ['AMZN.capex', 'AMZN.aws_growth'],
    ),
    'AAPL.p1': (
        'The iPhone upgrade cycle disappoints: AI features do not pull upgrades forward, and share in China stays under pressure.',
        'Sell-through or lead-time data show a clearly stronger cycle than consensus expects.',
        ['AAPL.iphone_growth'],
    ),
    'AAPL.p2': (
        'Services growth slows as regulation and litigation pressure App Store fees and search distribution payments.',
        'Rulings or settlements leave fees and payments intact and Services growth holds.',
        ['AAPL.services_growth'],
    ),
    'AAPL.p3': (
        'Operating margin is at risk from tariffs and component costs.',
        'Costs are absorbed or passed through and margin is guided flat or up.',
        ['AAPL.operating_margin'],
    ),
    'GOOGL.p1': (
        'AI answers reduce clicks on commercial queries, so Search revenue growth falls below consensus.',
        'Paid-click and pricing data show monetization holding or improving.',
        ['GOOGL.services_growth'],
    ),
    'GOOGL.p2': (
        'Rising capital expenditure and depreciation compress operating margin.',
        'Cloud growth and Cloud margin offset the step-up in depreciation.',
        ['GOOGL.operating_margin', 'GOOGL.capex', 'GOOGL.cloud_growth'],
    ),
    'GOOGL.p3': (
        'Regulatory remedies in search and advertising technology restrict distribution or the ad stack.',
        'Remedies are narrow or delayed, with little operating effect.',
        ['GOOGL.services_growth'],
    ),
}


def test_theses_have_summary_and_street_view() -> None:
    for t in load_seed().theses:
        assert t.summary.strip(), t.ticker
        assert t.street_view in {"buy", "hold", "sell"}, t.ticker
        assert t.street_view_note.strip(), t.ticker
        assert t.street_target_price is not None and t.street_target_price > 0, t.ticker


def test_pillars_have_summary_and_evidence() -> None:
    for t in load_seed().theses:
        for p in t.pillars:
            assert p.summary.strip(), p.id
            assert 3 <= len(p.evidence) <= 4, p.id
            for e in p.evidence:
                assert e.observation.strip() and e.source.strip(), p.id


def test_pillar_core_fields_unchanged() -> None:
    pillars = {p.id: p for t in load_seed().theses for p in t.pillars}
    assert set(pillars) == set(ORIGINAL_PILLARS)
    for pid, (statement, wrong_if, driver_ids) in ORIGINAL_PILLARS.items():
        p = pillars[pid]
        assert (p.statement, p.wrong_if, p.driver_ids) == (statement, wrong_if, driver_ids), pid


def test_10k_citations_use_only_base_figures() -> None:
    base = json.loads((SEED_DIR / "base_figures.json").read_text())
    for t in load_seed().theses:
        b = base[t.ticker]
        figures = {round(v, 1) for v in b["revenue_lines"].values()} | {round(b["total_revenue_usd_bn"], 1)}
        for p in t.pillars:
            for e in p.evidence:
                if "10-K" not in e.source:
                    continue
                for amount in re.findall(r"\$([\d,]+(?:\.\d+)?)\s*bn", e.observation):
                    assert float(amount.replace(",", "")) in figures, (p.id, amount)


def test_model_bases_match_filings_and_stance_matches_estimates() -> None:
    import json
    from triage_app.config import SEED_DIR
    from triage_app.state.compute import compute
    from triage_app.state.fold import load_seed

    base = json.loads((SEED_DIR / "base_figures.json").read_text())
    seed = load_seed()
    models = {m.ticker: m for m in seed.models}
    for m in seed.models:
        b = base[m.ticker]
        assert {x.driver_id: x.base_revenue_usd_bn for x in m.revenue_lines} == b["revenue_lines"]
        assert (m.tax_rate, m.diluted_shares_bn) == (b["tax_rate"], b["diluted_shares_bn"])
    for t in seed.theses:
        c = compute(models[t.ticker])
        assert (c["analyst"].eps > c["consensus"].eps) == (t.stance == "long"), t.ticker
        assert {d for p in t.pillars for d in p.driver_ids} <= {d.id for d in models[t.ticker].drivers}
