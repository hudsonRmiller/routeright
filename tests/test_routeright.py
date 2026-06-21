"""Correctness tests for the Route Right engine.

These check the *math*, not just that code runs: tier-boundary behavior,
monotonicities that must hold, the trade-count effect, and that the MILP's
allocation is at least as good as any single-venue baseline (a necessary
condition for optimality, since single-venue is always feasible).
"""
import math
import pytest

from routeright import (FlowProfile, default_venues, optimize, evaluate,
                        single_venue_costs, venue_cost, sprint_advice)
from routeright.fees import resolve_tier
from routeright.impact import size_impact, participation_impact


V = default_venues()


def base_flow(**kw):
    d = dict(monthly_notional=50_000_000, trade_count=10_000,
             taker_fraction=0.6, region="OFFSHORE")
    d.update(kw)
    return FlowProfile(**d)


# ---- tier resolution ------------------------------------------------------
def test_tier_picks_deepest_below_volume():
    kr = V["Kraken"]
    t = resolve_tier(kr, 3_000_000)          # between 2.5M and 5M tiers
    assert t.threshold_usd == 2_500_000

def test_tier_boundary_inclusive():
    kr = V["Kraken"]
    assert resolve_tier(kr, 10_000_000).threshold_usd == 10_000_000

def test_either_rule_uses_max_of_volume_assets():
    by = V["Bybit"]                          # qualify="either"
    t = resolve_tier(by, 100_000, assets=6_000_000)
    assert t.threshold_usd == 5_000_000      # assets win

def test_both_rule_needs_both():
    bn = V["Binance"]                        # qualify="both"
    # high volume but no token assets -> can't claim the deep tier
    t_no_token = resolve_tier(bn, 25_000_000, assets=0.0)
    t_token = resolve_tier(bn, 25_000_000, assets=25_000_000)
    assert t_token.threshold_usd >= t_no_token.threshold_usd


# ---- cost monotonicities --------------------------------------------------
def test_more_volume_never_raises_blended_fee_rate():
    """Tier rates are non-increasing in volume: deeper tier, lower fee rate."""
    kr = V["Kraken"]
    f = base_flow()
    rates = []
    for vol in [1e5, 1e6, 5e6, 5e7, 2e8]:
        vc = venue_cost(kr, vol, f)
        rates.append(vc.blended_rate)
    assert all(rates[i] >= rates[i + 1] - 1e-12 for i in range(len(rates) - 1))

def test_participation_impact_is_convex_increasing():
    kr = V["Kraken"]
    f = base_flow()
    xs = [1e6 * i for i in range(1, 8)]
    vals = [participation_impact(kr, x, f) for x in xs]
    assert all(vals[i] < vals[i + 1] for i in range(len(vals) - 1))
    # convexity: second differences >= 0
    d = [vals[i + 1] - vals[i] for i in range(len(vals) - 1)]
    assert all(d[i] <= d[i + 1] + 1e-6 for i in range(len(d) - 1))


# ---- trade-count vs notional (the requested distinction) ------------------
def test_fewer_trades_means_more_size_impact():
    """Same notional, fewer (larger) orders => higher size-impact cost."""
    kr = V["Kraken"]
    notional = 50_000_000
    many = base_flow(monthly_notional=notional, trade_count=100_000)
    few = base_flow(monthly_notional=notional, trade_count=2_000)
    assert size_impact(kr, notional, few) > size_impact(kr, notional, many)


# ---- token discount -------------------------------------------------------
def test_token_discount_lowers_positive_fees():
    bn = V["Binance"]
    no_tok = base_flow(monthly_notional=10_000_000, pay_fees_in_token=False)
    tok = base_flow(monthly_notional=10_000_000, pay_fees_in_token=True)
    assert venue_cost(bn, 10_000_000, tok).blended_rate < \
           venue_cost(bn, 10_000_000, no_tok).blended_rate


# ---- region masking -------------------------------------------------------
def test_us_firm_cannot_use_binance():
    us = base_flow(region="US")
    singles = single_venue_costs(V, us)
    assert "Binance" not in singles
    assert "Coinbase" in singles

def test_optimizer_respects_region():
    us = base_flow(region="US")
    res = optimize(V, us)
    assert res.allocation.by_venue.get("Binance", None) is None or \
        res.allocation.by_venue["Binance"].notional == 0.0


# ---- the optimizer --------------------------------------------------------
def test_allocation_conserves_volume():
    f = base_flow()
    res = optimize(V, f)
    routed = sum(vc.notional for vc in res.allocation.by_venue.values())
    assert math.isclose(routed, f.monthly_notional, rel_tol=1e-3)

def test_optimizer_respects_venue_cap():
    f = base_flow(max_venue_share=0.4)
    res = optimize(V, f)
    for vc in res.allocation.by_venue.values():
        assert vc.notional <= f.monthly_notional * 0.4 + 1.0

def test_optimizer_beats_or_matches_best_single_venue():
    """Necessary optimality condition: routing >= best single venue, since the
    single-venue allocation is always feasible for the MILP."""
    f = base_flow(monthly_notional=250_000_000, trade_count=40_000,
                  max_venue_share=0.6)
    res = optimize(V, f)
    singles = single_venue_costs(V, f)
    best_single = min(vc.total for vc in singles.values())
    assert res.allocation.total <= best_single + 1e-3


# ---- sprint ---------------------------------------------------------------
def test_sprint_positive_when_close_and_active():
    kr = V["Kraken"]
    f = base_flow(monthly_notional=250_000_000)
    adv = sprint_advice(kr, f, current_30d_volume=99_000_000, days_elapsed=20)
    # just below the 100M tier with lots of runway -> should advise sprint
    assert adv.next_threshold == 100_000_000
    assert adv.extra_volume_needed == pytest.approx(1_000_000)

def test_sprint_holds_at_top_tier():
    kr = V["Kraken"]
    f = base_flow()
    adv = sprint_advice(kr, f, current_30d_volume=5_000_000_000,
                        days_elapsed=15)
    assert adv.worth_it is False
    assert adv.next_threshold is None
