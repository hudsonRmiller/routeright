"""Rolling-30-day tier sprint.

Tiers are set by *trailing* 30-day volume, so mid-window a firm can choose to
push extra volume now to cross a threshold and re-rate ALL remaining flow at the
better tier. This module computes the breakeven and the net benefit.

Inputs are the firm's current trailing volume on a venue, days elapsed, and its
run-rate. The decision: crossing threshold Theta now costs the fees+impact on
the extra (Theta - current) notional, but saves (rate_below - rate_above) on the
remaining projected flow for the rest of the window. Sprint iff saving > cost.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from .flow import FlowProfile
from .schedules import Venue
from .fees import rate_for_tier


@dataclass
class SprintAdvice:
    venue: str
    worth_it: bool
    next_threshold: Optional[float]
    extra_volume_needed: float
    remaining_flow: float
    rate_drop_bps: float
    gross_saving: float          # saved on remaining flow at the better rate
    sprint_cost: float           # cost of executing the extra volume
    net_benefit: float
    message: str


def sprint_advice(venue: Venue, flow: FlowProfile, current_30d_volume: float,
                  days_elapsed: float, window_days: float = 30.0) -> SprintAdvice:
    tiers = venue.tiers_sorted()
    # current tier and the next one up
    cur = tiers[0]
    nxt = None
    for i, t in enumerate(tiers):
        if current_30d_volume >= t.threshold_usd:
            cur = t
            nxt = tiers[i + 1] if i + 1 < len(tiers) else None
    if nxt is None:
        return SprintAdvice(venue.name, False, None, 0, 0, 0, 0, 0, 0,
                            "Already at the venue's top tier — nothing to sprint to.")

    extra = max(0.0, nxt.threshold_usd - current_30d_volume)
    days_left = max(0.0, window_days - days_elapsed)
    run_rate = current_30d_volume / days_elapsed if days_elapsed > 0 else 0.0
    remaining_flow = run_rate * days_left

    rate_now = rate_for_tier(venue, cur, flow)["blended_rate"]
    rate_next = rate_for_tier(venue, nxt, flow)["blended_rate"]
    drop = rate_now - rate_next                       # fraction of notional
    gross_saving = drop * remaining_flow

    # cost of the sprint: you pay the (current-tier) blended rate on the extra
    # notional, plus you'd execute it anyway only partially -> treat full extra
    # as incremental, charged at current rate (conservative).
    sprint_cost = rate_now * extra
    net = gross_saving - sprint_cost
    worth = net > 0 and extra > 0

    if worth:
        msg = (f"Sprint: push {_usd(extra)} more on {venue.name} now to reach "
               f"the {_bps(rate_next)} tier. Saves {_usd(gross_saving)} on the "
               f"~{_usd(remaining_flow)} of remaining flow this window; net "
               f"+{_usd(net)} after the {_usd(sprint_cost)} sprint cost.")
    else:
        msg = (f"Hold: crossing the next {venue.name} tier needs {_usd(extra)} "
               f"more, but only saves {_usd(gross_saving)} on remaining flow — "
               f"not worth the {_usd(sprint_cost)} sprint cost.")
    return SprintAdvice(venue.name, worth, nxt.threshold_usd, extra,
                        remaining_flow, drop * 1e4, gross_saving, sprint_cost,
                        net, msg)


def _usd(n):
    return "$" + format(round(n), ",")


def _bps(rate):
    return f"{rate * 1e4:.1f} bps"
