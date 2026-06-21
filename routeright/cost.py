"""Assemble the total expected monthly cost of a routing allocation.

C(x) = sum_v [ explicit_fee_v(x_v) + spread_v(x_v) + impact_v(x_v)
               + per_order_v(x_v) ]

where x_v is USD notional routed to venue v. explicit_fee_v is non-convex
(tiers step down); the implicit terms are convex/increasing. The optimizer in
optimize.py minimizes this; here we just evaluate and explain a given x.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict

from .flow import FlowProfile
from .schedules import Venue
from .fees import blended_explicit_rate
from .impact import spread_cost, impact_cost, per_order_fee_cost


@dataclass
class VenueCost:
    venue: str
    notional: float
    explicit: float
    spread: float
    impact: float
    per_order: float
    blended_rate: float          # explicit fee rate, fraction of notional
    tier_threshold: float
    used_mm: bool

    @property
    def total(self) -> float:
        return self.explicit + self.spread + self.impact + self.per_order

    @property
    def all_in_bps(self) -> float:
        if self.notional <= 0:
            return 0.0
        return self.total / self.notional * 1e4


@dataclass
class Allocation:
    by_venue: Dict[str, VenueCost]
    flow: FlowProfile

    @property
    def total(self) -> float:
        return sum(vc.total for vc in self.by_venue.values())

    @property
    def all_in_bps(self) -> float:
        n = self.flow.monthly_notional
        return self.total / n * 1e4 if n else 0.0

    def active(self):
        return {k: v for k, v in self.by_venue.items() if v.notional > 1e-6}


def venue_cost(venue: Venue, notional: float, flow: FlowProfile,
               assets: float = 0.0) -> VenueCost:
    info = blended_explicit_rate(venue, notional, flow, assets)
    explicit = notional * info["blended_rate"]
    return VenueCost(
        venue=venue.name,
        notional=notional,
        explicit=explicit,
        spread=spread_cost(venue, notional, flow),
        impact=impact_cost(venue, notional, flow),
        per_order=per_order_fee_cost(venue, notional, flow),
        blended_rate=info["blended_rate"],
        tier_threshold=info["tier"].threshold_usd,
        used_mm=info["used_mm"],
    )


def evaluate(allocation: Dict[str, float], venues: Dict[str, Venue],
             flow: FlowProfile, assets: Dict[str, float] = None) -> Allocation:
    """Evaluate a {venue_name: notional} allocation."""
    assets = assets or {}
    by_venue = {}
    for name, notional in allocation.items():
        by_venue[name] = venue_cost(venues[name], notional, flow,
                                    assets.get(name, 0.0))
    return Allocation(by_venue=by_venue, flow=flow)


def single_venue_costs(venues: Dict[str, Venue], flow: FlowProfile,
                       assets: Dict[str, float] = None) -> Dict[str, VenueCost]:
    """Cost of routing ALL flow to each venue individually (the baseline the
    naive tool computed). Used for the 'best single venue' comparison."""
    assets = assets or {}
    out = {}
    for name, v in venues.items():
        if flow.region not in v.regions:
            continue
        out[name] = venue_cost(v, flow.monthly_notional, flow,
                               assets.get(name, 0.0))
    return out
