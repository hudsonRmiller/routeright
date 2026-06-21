"""Venue fee schedules and the schema that holds them.

RATES ARE STORED AS FRACTIONS OF NOTIONAL: 0.0010 == 0.10% == 10 bps.
Negative maker rate == rebate.

Sources: public spot fee schedules, ~June 2026 (Binance, Coinbase Advanced,
Kraken Pro, OKX, Bybit, Bitfinex). Low/base tiers are firm; the highest tiers
and all *implicit-cost* parameters (half_spread_bps, adv_usd) are INDICATIVE
and MUST be recalibrated to live data and to the firm's own fills before any
real routing decision. Treat schedules as data to be replaced, not as truth.

Qualification rule semantics (`qualify`):
    "volume" : tier set by 30d notional only.
    "assets" : tier set by account asset balance only.
    "either" : best tier achievable by volume OR assets (e.g. Bybit).
    "both"   : must meet volume AND a token/asset floor (e.g. Binance VIP).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass(frozen=True)
class Tier:
    threshold_usd: float   # 30d notional (or asset) needed to reach this tier
    maker: float           # fraction of notional; negative = rebate
    taker: float


@dataclass
class MMProgram:
    """Conditional market-maker program: better maker economics in exchange
    for quoting obligations. Only applied if FlowProfile.eligible_for_mm."""
    maker: float                    # enhanced maker rate (often negative)
    taker: float
    min_30d_notional: float         # volume gate to apply
    obligation_cost_bps: float = 0.5  # modeled cost of meeting spread/uptime,
    #                                   as bps on maker notional (a knob)


@dataclass
class Venue:
    name: str
    tiers: list                       # list[Tier], ascending threshold
    qualify: str = "volume"
    regions: tuple = ("US", "EU", "OFFSHORE")   # where the firm may access it
    instrument: str = "spot"
    # native-token fee discount:
    token: Optional[str] = None
    token_discount: float = 0.0       # multiplicative on POSITIVE fees only
    token_carry_bps: float = 0.0      # amortized carry cost of holding token,
    #                                   as bps on total routed notional (knob)
    # per-order / flat fee (≈0 for crypto spot; nonzero for some products):
    per_order_usd: float = 0.0
    min_notional_usd: float = 0.0
    # conditional MM program:
    mm: Optional[MMProgram] = None
    # implicit-cost calibration (INDICATIVE — replace with live book data):
    half_spread_bps: float = 1.0      # half the typical quoted spread, in bps
    adv_usd: float = 5.0e9            # venue daily $ volume (impact reference)
    # expected-maker realism:
    maker_fill_prob: float = 0.7      # P(passive order fills) — rebate only
    #                                   earned on fills
    adverse_selection_bps: float = 0.3  # loading on filled maker orders (knob)
    note: str = ""

    def tiers_sorted(self):
        return sorted(self.tiers, key=lambda t: t.threshold_usd)


def _t(threshold, maker_pct, taker_pct):
    """Helper: take percentages (0.10 == 0.10%) -> store as fractions."""
    return Tier(threshold, maker_pct / 100.0, taker_pct / 100.0)


# --------------------------------------------------------------------------
# DEFAULT SCHEDULES  (edit freely; this is data, not logic)
# --------------------------------------------------------------------------
def default_venues() -> dict:
    venues = {}

    venues["Coinbase"] = Venue(
        name="Coinbase",
        qualify="volume",
        regions=("US", "EU", "OFFSHORE"),
        half_spread_bps=1.2, adv_usd=3.0e9,
        note="Coinbase Advanced spot. Top tiers approximate.",
        tiers=[
            _t(0, 0.60, 1.20), _t(1_000, 0.35, 0.75),
            _t(10_000, 0.25, 0.40), _t(50_000, 0.20, 0.30),
            _t(100_000, 0.18, 0.25), _t(1_000_000, 0.16, 0.25),
            _t(15_000_000, 0.14, 0.23), _t(75_000_000, 0.10, 0.18),
            _t(250_000_000, 0.08, 0.15), _t(400_000_000, 0.00, 0.05),
        ],
    )

    venues["Kraken"] = Venue(
        name="Kraken",
        qualify="volume",
        regions=("US", "EU", "OFFSHORE"),
        half_spread_bps=1.5, adv_usd=1.2e9,
        note="Kraken Pro spot.",
        tiers=[
            _t(0, 0.25, 0.40), _t(10_000, 0.20, 0.35),
            _t(50_000, 0.14, 0.24), _t(100_000, 0.12, 0.22),
            _t(250_000, 0.10, 0.20), _t(500_000, 0.08, 0.18),
            _t(1_000_000, 0.06, 0.16), _t(2_500_000, 0.04, 0.14),
            _t(5_000_000, 0.02, 0.12), _t(10_000_000, 0.00, 0.10),
            _t(100_000_000, 0.00, 0.08),
        ],
    )

    venues["Binance"] = Venue(
        name="Binance",
        qualify="both",                      # needs volume AND BNB held
        regions=("EU", "OFFSHORE"),          # not US (Binance.com)
        token="BNB", token_discount=0.25, token_carry_bps=0.4,
        half_spread_bps=0.6, adv_usd=12.0e9,
        note="Binance spot. VIP needs volume AND BNB balance.",
        tiers=[
            _t(0, 0.10, 0.10), _t(1_000_000, 0.09, 0.10),
            _t(5_000_000, 0.08, 0.10), _t(20_000_000, 0.042, 0.06),
            _t(100_000_000, 0.042, 0.054), _t(250_000_000, 0.036, 0.048),
        ],
    )

    venues["OKX"] = Venue(
        name="OKX",
        qualify="either",
        regions=("EU", "OFFSHORE"),
        token="OKB", token_discount=0.20, token_carry_bps=0.4,
        half_spread_bps=0.8, adv_usd=6.0e9,
        note="OKX spot. Approximate.",
        tiers=[
            _t(0, 0.08, 0.10), _t(5_000_000, 0.045, 0.05),
            _t(10_000_000, 0.04, 0.045), _t(20_000_000, 0.03, 0.04),
            _t(50_000_000, 0.02, 0.035), _t(100_000_000, 0.015, 0.03),
        ],
    )

    venues["Bybit"] = Venue(
        name="Bybit",
        qualify="either",                    # volume OR assets
        regions=("EU", "OFFSHORE"),
        half_spread_bps=0.9, adv_usd=4.0e9,
        note="Bybit spot. Approximate.",
        mm=MMProgram(maker=-0.015 / 100.0, taker=0.05 / 100.0,
                     min_30d_notional=50_000_000, obligation_cost_bps=0.6),
        tiers=[
            _t(0, 0.10, 0.10), _t(1_000_000, 0.06, 0.06),
            _t(5_000_000, 0.04, 0.06), _t(10_000_000, 0.02, 0.055),
            _t(50_000_000, 0.01, 0.05),
        ],
    )

    venues["Bitfinex"] = Venue(
        name="Bitfinex",
        qualify="volume",
        regions=("EU", "OFFSHORE"),
        half_spread_bps=1.1, adv_usd=0.8e9,
        note="Bitfinex spot. Negative maker (rebate) at top tiers.",
        tiers=[
            _t(0, 0.10, 0.20), _t(500_000, 0.08, 0.20),
            _t(1_000_000, 0.06, 0.18), _t(7_500_000, 0.04, 0.16),
            _t(15_000_000, 0.02, 0.14), _t(30_000_000, 0.00, 0.12),
            _t(75_000_000, -0.005, 0.10), _t(150_000_000, -0.01, 0.10),
        ],
    )

    return venues
