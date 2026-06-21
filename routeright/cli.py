"""Command-line interface.

    routeright demo [--notional N] [--trades K] [--taker F] [--region R]
                    [--cap C] [--token] [--mm]

Runs an allocation on the indicative default schedules and prints the optimized
route against the best single venue. This is a demo over INDICATIVE data — see
the README on calibrating to live data and your own fills.
"""
from __future__ import annotations

import argparse

from .flow import FlowProfile
from .schedules import default_venues
from .optimize import optimize
from .cost import single_venue_costs


def _usd(n: float) -> str:
    return "$" + format(round(n), ",")


def _demo(args: argparse.Namespace) -> None:
    venues = default_venues()
    firm = FlowProfile(
        monthly_notional=args.notional,
        trade_count=args.trades,
        taker_fraction=args.taker,
        region=args.region,
        max_venue_share=args.cap,
        pay_fees_in_token=args.token,
        eligible_for_mm=args.mm,
    )

    singles = single_venue_costs(venues, firm)
    if not singles:
        print(f"No venues available in region {args.region!r}.")
        return
    best_name, best = min(singles.items(), key=lambda kv: kv[1].total)

    res = optimize(venues, firm)
    print(f"Route Right — {_usd(firm.monthly_notional)}/mo, "
          f"{firm.trade_count:,} trades, {int(firm.taker_fraction*100)}% taker, "
          f"region {firm.region}  [{res.solver}, {res.status}]")
    print("-" * 60)
    for name, vc in sorted(res.allocation.active().items(),
                           key=lambda kv: -kv[1].notional):
        share = vc.notional / firm.monthly_notional * 100
        mm = "  (MM)" if vc.used_mm else ""
        print(f"  {name:10s} {_usd(vc.notional):>14s}  ({share:4.1f}%)  "
              f"{vc.all_in_bps:5.2f} bps all-in{mm}")
    print("-" * 60)
    save = best.total - res.allocation.total
    print(f"  optimized : {_usd(res.allocation.total)}/mo  "
          f"({res.allocation.all_in_bps:.2f} bps)")
    print(f"  best single: {_usd(best.total)}/mo on {best_name}")
    print(f"  edge       : {_usd(save)}/mo  ({_usd(save*12)}/yr)")
    print("\nNote: indicative data. Calibrate to live schedules and your own "
          "fills before routing.")


def main(argv=None) -> None:
    p = argparse.ArgumentParser(
        prog="routeright",
        description="Multi-venue crypto fee-tier optimization engine.")
    sub = p.add_subparsers(dest="command")

    d = sub.add_parser("demo", help="run an example allocation")
    d.add_argument("--notional", type=float, default=50_000_000,
                   help="monthly notional USD (default 50M)")
    d.add_argument("--trades", type=int, default=10_000,
                   help="monthly trade count (default 10k)")
    d.add_argument("--taker", type=float, default=0.6,
                   help="taker fraction 0..1 (default 0.6)")
    d.add_argument("--region", default="OFFSHORE",
                   help="US | EU | OFFSHORE (default OFFSHORE)")
    d.add_argument("--cap", type=float, default=0.55,
                   help="max share per venue 0..1 (default 0.55)")
    d.add_argument("--token", action="store_true",
                   help="pay fees in native token where available")
    d.add_argument("--mm", action="store_true",
                   help="eligible for market-maker programs")
    d.set_defaults(func=_demo)

    args = p.parse_args(argv)
    if not getattr(args, "func", None):
        p.print_help()
        return
    args.func(args)


if __name__ == "__main__":
    main()
