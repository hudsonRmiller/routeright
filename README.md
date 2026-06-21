# Route Right — multi-venue crypto fee optimization engine

![tests](https://github.com/hudsonRmiller/routeright/actions/workflows/ci.yml/badge.svg)

A real cost model and allocation optimizer for routing a trading firm's monthly
flow across crypto venues with tiered fees, token discounts, market-maker
programs, and finite liquidity. This is the engine core, not a UI.

## Install

```bash
pip install routeright          # bundles the CBC solver via PuLP
routeright demo                 # run an example allocation
```

## What it actually does

Given a firm's monthly flow (notional, trade count, maker/taker mix, region,
risk limits), it finds the **flow allocation across venues that minimizes total
expected cost** — and total expected cost is modeled properly:

- **Tiered fees as a status** — your 30-day notional sets a tier; that rate
  applies to *all* flow. Per-venue explicit cost is therefore piecewise-linear
  and **non-convex** (steps down at thresholds → rewards concentration).
- **Convex market impact** — pushing more through one book costs convexly more
  (square-root law on participation) → penalizes concentration. The optimum
  balances the two; this is the whole game.
- **Trade count vs notional** — notional sets tiers; average trade size `S=V/N`
  sets per-order impact. Both are tracked. Fewer/larger orders cost more impact.
- **Non-volume incentives** — native-token discounts (with carry cost),
  conditional market-maker rebate programs (with obligation cost), and
  dual-criteria qualification (volume AND token, or volume OR assets).
- **Expected maker rate** — rebates are earned only on fills, and passive fills
  are adversely selected, so effective maker rate ≠ posted rate.
- **Rolling-30-day sprint** — whether to push volume now to re-rate remaining
  flow at a better tier, with the breakeven computed.

The allocation is solved as an exact **MILP** (CBC via PuLP): tier non-convexity
via binaries, convex impact via piecewise-linearization. At realistic scale
(~6–15 venues) it solves to proven optimality in milliseconds.

## Layout

```
routeright/
  flow.py        FlowProfile — the firm's demand (V, N, mix, region, limits)
  schedules.py   Venue/Tier schema + indicative default schedules (6 venues)
  fees.py        tier resolution, token discount, expected maker, MM programs
  impact.py      spread + convex participation impact + size (trade-count) impact
  cost.py        assemble + evaluate total expected cost of an allocation
  optimize.py    the MILP allocator (+ local-search fallback)
  sprint.py      rolling-30-day tier-sprint breakeven
example.py       end-to-end run for a $250M/mo desk
tests/           15 correctness tests (math, not just "it runs")
MODEL.tex/.pdf   formal spec: cost function, MILP, proofs of monotonicity
```

## Run

```bash
pip install pulp        # CBC solver bundled
python example.py
python -m pytest tests/ -q
```

## Quick use

```python
from routeright import FlowProfile, default_venues, optimize

firm = FlowProfile(monthly_notional=250_000_000, trade_count=40_000,
                   taker_fraction=0.65, region="OFFSHORE",
                   max_venue_share=0.55, pay_fees_in_token=True,
                   eligible_for_mm=True)

res = optimize(default_venues(), firm)
for name, vc in res.allocation.active().items():
    print(name, f"${vc.notional:,.0f}", f"{vc.all_in_bps:.2f} bps all-in")
print("total", f"${res.allocation.total:,.0f}/mo")
```

## Structure vs. data (read this before trusting a route)

The **structure** — tier non-convexity, convex impact, the MILP, the sprint
breakeven — is the defensible engine. The **parameters** are data to be
calibrated, and the engine's accuracy is bounded by them:

- tier thresholds/rates (live per venue; top tiers + MM terms are often
  negotiated/NDA),
- half-spreads, venue liquidity (`adv_usd`), depth fraction, impact coefficients
  (from order-book + TCA data),
- maker fill probabilities and adverse-selection loadings (from the firm's own
  realized passive fills).

Shipping with the indicative defaults in `schedules.py` is fine for a demo.
Wiring it to a customer's real fills and live fee feeds is what makes a route
trustworthy — and is the part that no engine writes for you.

## Not yet here (the honest backlog)

Live fee-schedule ingestion; per-instrument / per-pair modeling (this v1
aggregates); execution scheduling (the intra-window child-order problem, a layer
below allocation); a calibration harness against real TCA; and the data plumbing
to a firm's OMS/EMS. The engine is the brain; these are the senses and hands.

## Status & license

Alpha (v0.1.0). MIT licensed — use it freely in your own environment; your data
never leaves your machine. The engine is open on purpose: its value to you is
running on *your* fills, and the maintained data + calibration layer (below) is
the part worth paying for.

## Commercial

The open engine ships with **indicative** fee schedules and impact parameters.
Turning it into a route you'd trade on requires (a) live, normalized tier / MM /
incentive data across venues and (b) calibration of the impact and fill-
probability parameters against your own TCA. That's offered as a service —
reach out to have it calibrated on your book.
