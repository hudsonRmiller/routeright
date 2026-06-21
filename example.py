"""End-to-end example: a mid-tier crypto prop firm.

Run:  python example.py
"""
from routeright import (FlowProfile, default_venues, optimize,
                        single_venue_costs, sprint_advice)


def bps(rate):
    return f"{rate * 1e4:6.2f} bps"


def usd(n):
    return "$" + format(round(n), ",")


def main():
    venues = default_venues()

    firm = FlowProfile(
        monthly_notional=250_000_000,   # $250M/mo — a real mid-tier desk
        trade_count=40_000,             # avg ~$6.25k/order
        taker_fraction=0.65,
        daily_vol=0.025,
        region="OFFSHORE",              # can reach Binance/OKX/Bybit/etc.
        max_venue_share=0.55,           # counterparty risk: <=55% on any venue
        pay_fees_in_token=True,
        eligible_for_mm=True,
    )

    print("=" * 64)
    print("ROUTE RIGHT — allocation for a $250M/mo OFFSHORE desk")
    print("=" * 64)

    # 1) Naive baseline: best single venue (what the v1 calculator did)
    singles = single_venue_costs(venues, firm)
    ranked = sorted(singles.items(), key=lambda kv: kv[1].total)
    print("\nBest single venue (naive baseline):")
    for name, vc in ranked[:4]:
        print(f"  {name:10s}  {usd(vc.total):>12s}/mo   "
              f"all-in {vc.all_in_bps:5.2f} bps")
    best_single_name, best_single = ranked[0]

    # 2) Optimized multi-venue allocation
    res = optimize(venues, firm)
    print(f"\nOptimized allocation  [{res.solver}, {res.status}]:")
    for name, vc in sorted(res.allocation.active().items(),
                           key=lambda kv: -kv[1].notional):
        share = vc.notional / firm.monthly_notional * 100
        mm = " (MM program)" if vc.used_mm else ""
        print(f"  {name:10s}  {usd(vc.notional):>13s}  ({share:4.1f}%)   "
              f"fee {bps(vc.blended_rate)}  +impact {usd(vc.impact)}{mm}")

    opt_total = res.allocation.total
    print(f"\n  Optimized total : {usd(opt_total)}/mo  "
          f"({res.allocation.all_in_bps:.2f} bps all-in)")
    print(f"  Best single     : {usd(best_single.total)}/mo  "
          f"on {best_single_name}")
    save = best_single.total - opt_total
    print(f"  Edge from routing: {usd(save)}/mo  ({usd(save * 12)}/yr)")

    # 3) Rolling-30-day sprint check on the current venue
    print("\nTier-sprint check (Kraken, day 20 of 30):")
    adv = sprint_advice(venues["Kraken"], firm,
                        current_30d_volume=85_000_000, days_elapsed=20)
    print("  " + adv.message)


if __name__ == "__main__":
    main()
