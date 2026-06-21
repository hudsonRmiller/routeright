"""Effective fee model for a single venue.

Turns posted schedule rates into *expected effective* rates, accounting for:
  - which tier a given 30d notional lands in (and the venue's qualify rule),
  - native-token discount (positive fees only) net of token carry,
  - conditional market-maker program (better maker economics + obligations),
  - the fact that maker rebates are only earned on fills, and filled passive
    orders are adversely selected (expected maker cost != posted maker rate).

All rates returned are FRACTIONS of notional (0.001 == 10 bps).
"""
from __future__ import annotations

from .flow import FlowProfile
from .schedules import Venue, Tier


def resolve_tier(venue: Venue, notional: float, assets: float = 0.0) -> Tier:
    """Pick the tier the venue would assign, honoring its qualify rule.

    For "both", qualification needs volume AND a token/asset floor; if the
    firm hasn't met the floor we conservatively assume the floor is met when
    pay_fees_in_token holds (handled by caller passing assets). Here we treat
    the qualifying metric per rule and return the deepest tier reached.
    """
    tiers = venue.tiers_sorted()
    rule = venue.qualify
    if rule == "volume":
        metric = notional
    elif rule == "assets":
        metric = assets
    elif rule == "either":
        metric = max(notional, assets)
    elif rule == "both":
        # deepest tier whose threshold is met by BOTH metrics
        metric = min(notional, assets) if assets > 0 else notional
    else:
        raise ValueError(f"unknown qualify rule {rule!r}")
    chosen = tiers[0]
    for t in tiers:
        if metric >= t.threshold_usd:
            chosen = t
    return chosen


def effective_taker_rate(venue: Venue, tier: Tier, flow: FlowProfile) -> float:
    r = tier.taker
    if flow.pay_fees_in_token and venue.token and r > 0:
        r *= (1.0 - venue.token_discount)
    return r


def effective_maker_rate(venue: Venue, tier: Tier, flow: FlowProfile) -> float:
    """Expected effective maker rate including fill prob + adverse selection.

    Posted maker rate m (negative = rebate). On a passive order:
      - it fills with prob p; only then is the rebate earned / fee paid,
      - filled passive orders suffer adverse-selection loading a (bps),
      - unfilled orders eventually cost ~ the taker alternative (chase),
        approximated as a fraction of the spread.
    Token discount applies to positive maker fees only.
    """
    m = tier.maker
    if flow.pay_fees_in_token and venue.token and m > 0:
        m *= (1.0 - venue.token_discount)

    p = venue.maker_fill_prob
    a = venue.adverse_selection_bps / 1e4
    # cost of the unfilled remainder having to chase (rough: half a spread)
    chase = (venue.half_spread_bps / 1e4)
    eff = p * (m + a) + (1.0 - p) * chase
    return eff


def maybe_mm_rates(venue: Venue, notional: float, flow: FlowProfile):
    """If eligible and gated, return (maker, taker, obligation_bps) from the
    MM program; else None. Obligation cost is added by the cost layer."""
    if not (flow.eligible_for_mm and venue.mm):
        return None
    if notional < venue.mm.min_30d_notional:
        return None
    return (venue.mm.maker, venue.mm.taker, venue.mm.obligation_cost_bps)


def blended_explicit_rate(venue: Venue, notional: float, flow: FlowProfile,
                          assets: float = 0.0) -> dict:
    """Blended expected *explicit* fee rate (fraction of notional) for routing
    `notional` to `venue`, plus a breakdown. Implicit costs handled elsewhere.
    """
    tier = resolve_tier(venue, notional, assets)
    t_rate = effective_taker_rate(venue, tier, flow)
    m_rate = effective_maker_rate(venue, tier, flow)

    mm = maybe_mm_rates(venue, notional, flow)
    used_mm = False
    obligation = 0.0
    if mm is not None:
        mm_m, mm_t, ob_bps = mm
        # MM maker rate already net of nothing; compare blended program vs base
        base_blend = flow.taker_fraction * t_rate + flow.maker_fraction * m_rate
        prog_blend = (flow.taker_fraction * mm_t
                      + flow.maker_fraction * mm_m
                      + flow.maker_fraction * ob_bps / 1e4)
        if prog_blend < base_blend:
            t_rate, m_rate = mm_t, mm_m
            obligation = flow.maker_fraction * ob_bps / 1e4
            used_mm = True

    blended = (flow.taker_fraction * t_rate
               + flow.maker_fraction * m_rate
               + obligation)
    # token carry (only if actually paying in token)
    carry = (venue.token_carry_bps / 1e4) if (flow.pay_fees_in_token
                                              and venue.token) else 0.0
    blended += carry
    return {
        "tier": tier,
        "taker_rate": t_rate,
        "maker_rate": m_rate,
        "blended_rate": blended,
        "used_mm": used_mm,
        "carry": carry,
    }


def rate_for_tier(venue: Venue, tier: Tier, flow: FlowProfile) -> dict:
    """Blended expected explicit rate for a SPECIFIC tier bracket (used by the
    optimizer, which reasons bracket-by-bracket). MM eligibility is gated on
    the bracket's own threshold."""
    t_rate = effective_taker_rate(venue, tier, flow)
    m_rate = effective_maker_rate(venue, tier, flow)
    obligation = 0.0
    used_mm = False
    if flow.eligible_for_mm and venue.mm and \
            tier.threshold_usd >= venue.mm.min_30d_notional:
        base = flow.taker_fraction * t_rate + flow.maker_fraction * m_rate
        prog = (flow.taker_fraction * venue.mm.taker
                + flow.maker_fraction * venue.mm.maker
                + flow.maker_fraction * venue.mm.obligation_cost_bps / 1e4)
        if prog < base:
            t_rate, m_rate = venue.mm.taker, venue.mm.maker
            obligation = flow.maker_fraction * venue.mm.obligation_cost_bps / 1e4
            used_mm = True
    carry = (venue.token_carry_bps / 1e4) if (flow.pay_fees_in_token
                                              and venue.token) else 0.0
    blended = (flow.taker_fraction * t_rate
               + flow.maker_fraction * m_rate + obligation + carry)
    return {"blended_rate": blended, "used_mm": used_mm}
