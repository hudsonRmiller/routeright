"""Implicit-cost model: spread + market impact.

This is the counterweight that stops the optimizer from dumping everything on
the lowest-fee venue. It is the most important correction to 'volume x rate'.

Three pieces, all INDICATIVE and parametric — calibrate to real book data and
the firm's real fills before trusting a route:

  spread cost        : takers cross the spread every taker trade.
                       Linear in taker notional.   (~ x)

  participation cost : absorbing a large share of a venue's window volume moves
                       price (square-root law on participation x/ADV). CONVEX
                       in x_v (~ x^1.5) -> this is what makes spreading across
                       venues worthwhile and creates an interior optimum.

  size cost          : holding notional fixed, fewer/larger orders dig deeper
                       into the instantaneous book. Scales with sqrt(S) where
                       S = V/N is average trade size. THIS is where the
                       trade-count-vs-notional distinction bites: same notional,
                       smaller N => larger S => more impact. Linear in x_v.

Plus optional flat per-order fees (~0 for crypto spot; nonzero some products).
"""
from __future__ import annotations

import math

from .flow import FlowProfile
from .schedules import Venue

IMPACT_COEFF = 0.4          # participation-impact coefficient (calibrate)
SIZE_COEFF = 0.25           # order-size-impact coefficient (calibrate)
INSTANT_DEPTH_FRAC = 0.002  # instantaneous book depth as a fraction of ADV


def spread_cost(venue: Venue, notional: float, flow: FlowProfile) -> float:
    taker_notional = notional * flow.taker_fraction
    return taker_notional * (venue.half_spread_bps / 1e4)


def participation_impact(venue: Venue, notional: float,
                         flow: FlowProfile) -> float:
    """Convex (~x^1.5) impact from taking a share of the venue's window volume."""
    if notional <= 0:
        return 0.0
    part = notional / venue.adv_usd
    return IMPACT_COEFF * flow.daily_vol * notional * math.sqrt(max(part, 0.0))


def size_impact(venue: Venue, notional: float, flow: FlowProfile) -> float:
    """Impact penalty for large average order size S = V/N. Linear in notional,
    scales with sqrt(S) so it grows as trade count N falls for fixed notional."""
    if notional <= 0:
        return 0.0
    S = flow.avg_trade_size
    depth = venue.adv_usd * INSTANT_DEPTH_FRAC
    return SIZE_COEFF * flow.daily_vol * notional * math.sqrt(max(S / depth, 0.0))


def per_order_fee_cost(venue: Venue, notional: float,
                       flow: FlowProfile) -> float:
    if venue.per_order_usd <= 0 or notional <= 0:
        return 0.0
    frac = notional / flow.monthly_notional if flow.monthly_notional else 1.0
    orders_here = (flow.trade_count * frac) if flow.trade_count else \
        (notional / flow.avg_trade_size)
    return max(0.0, orders_here) * venue.per_order_usd


def impact_cost(venue: Venue, notional: float, flow: FlowProfile) -> float:
    return (participation_impact(venue, notional, flow)
            + size_impact(venue, notional, flow))


def implicit_cost(venue: Venue, notional: float, flow: FlowProfile) -> float:
    return (spread_cost(venue, notional, flow)
            + impact_cost(venue, notional, flow)
            + per_order_fee_cost(venue, notional, flow))


# linear coefficient (per $ notional) for the parts that are linear in x_v:
def linear_coeff(venue: Venue, flow: FlowProfile) -> float:
    """Spread + size-impact + per-order, expressed as cost per $ of notional."""
    spread = flow.taker_fraction * (venue.half_spread_bps / 1e4)
    S = flow.avg_trade_size
    depth = venue.adv_usd * INSTANT_DEPTH_FRAC
    size = SIZE_COEFF * flow.daily_vol * math.sqrt(max(S / depth, 0.0))
    per_order = 0.0
    if venue.per_order_usd > 0 and flow.avg_trade_size > 0:
        per_order = venue.per_order_usd / flow.avg_trade_size
    return spread + size + per_order
