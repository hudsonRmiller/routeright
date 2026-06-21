"""Route Right — crypto fee-tier optimization engine (core).

Public API:
    FlowProfile            the firm's monthly trading demand
    default_venues()       indicative venue fee schedules (replace with live)
    evaluate()             cost of a given {venue: notional} allocation
    single_venue_costs()   baseline: all flow on each venue (the naive view)
    optimize()             MILP allocation that minimizes total expected cost
    sprint_advice()        rolling-30-day tier-sprint breakeven

Rates are fractions of notional (0.001 == 10 bps). Implicit-cost params and
top-tier rates are INDICATIVE — calibrate to live data before real routing.
"""
from .flow import FlowProfile
from .schedules import default_venues, Venue, Tier, MMProgram
from .cost import (evaluate, single_venue_costs, venue_cost, Allocation,
                   VenueCost)
from .optimize import optimize, OptResult
from .sprint import sprint_advice, SprintAdvice

__all__ = [
    "FlowProfile", "default_venues", "Venue", "Tier", "MMProgram",
    "evaluate", "single_venue_costs", "venue_cost", "Allocation", "VenueCost",
    "optimize", "OptResult", "sprint_advice", "SprintAdvice",
]
__version__ = "0.1.0"
