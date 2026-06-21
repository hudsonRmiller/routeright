"""Flow profile: the firm's trading demand to be allocated across venues.

The whole engine keys off the distinction the naive model misses: notional
volume V drives fee *tiers*, but trade count N (hence average trade size S=V/N)
drives *impact* and per-order costs. Both are first-class here.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class FlowProfile:
    """A monthly (trailing-30-day) trading demand to route.

    Attributes
    ----------
    monthly_notional : float
        Total USD notional to execute over the 30-day window (V).
    trade_count : int
        Number of executions over the window (N). Average trade size S = V/N.
        Drives impact and any per-order fees; does NOT change tier (tiers key
        off notional only).
    taker_fraction : float
        Fraction of *notional* executed as taker (crosses the spread). 0..1.
        Maker fraction is the complement.
    daily_vol : float
        Annualized? No -- per-trade price volatility used by the impact model,
        as a fraction (e.g. 0.03 = 3% typical move over the trade's horizon).
        Calibrate to the instrument; this is a knob, not a fact.
    region : str
        Regulatory domicile of the firm, e.g. "US", "EU", "OFFSHORE".
        Used to mask venues the firm legally cannot access.
    max_venue_share : float
        Counterparty-risk cap: no single venue may hold more than this
        fraction of total flow (0..1). 1.0 disables the cap.
    pay_fees_in_token : bool
        Whether the firm is willing to pay fees in venues' native tokens to
        capture the discount (incurs a modeled carry cost on the holding).
    eligible_for_mm : bool
        Whether the firm qualifies / is willing to take on market-maker
        program obligations (spread + uptime) to access enhanced maker rebates.
    instrument : str
        "spot" or "perp". Affects per-order fee handling and rate tables.
    """

    monthly_notional: float
    trade_count: int = 0
    taker_fraction: float = 0.6
    daily_vol: float = 0.03
    region: str = "OFFSHORE"
    max_venue_share: float = 1.0
    pay_fees_in_token: bool = False
    eligible_for_mm: bool = False
    instrument: str = "spot"

    def __post_init__(self):
        if not (0.0 <= self.taker_fraction <= 1.0):
            raise ValueError("taker_fraction must be in [0, 1]")
        if not (0.0 < self.max_venue_share <= 1.0):
            raise ValueError("max_venue_share must be in (0, 1]")
        if self.monthly_notional < 0:
            raise ValueError("monthly_notional must be >= 0")
        if self.trade_count < 0:
            raise ValueError("trade_count must be >= 0")

    @property
    def avg_trade_size(self) -> float:
        """S = V / N. Falls back to a sane block size if N unknown."""
        if self.trade_count > 0:
            return self.monthly_notional / self.trade_count
        return 25_000.0  # neutral default block size when N is unspecified

    @property
    def maker_fraction(self) -> float:
        return 1.0 - self.taker_fraction
