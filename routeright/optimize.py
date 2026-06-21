"""Allocation optimizer.

Minimize total expected monthly cost by choosing how much notional x_v to route
to each venue. The hard part is structural:

  * explicit fees are TIERED and status-based: the tier rate applies to the
    whole volume on a venue, so per-venue explicit cost is piecewise-linear and
    NON-CONVEX (it steps down at thresholds). Concave savings reward
    concentrating flow to climb a venue's tiers.
  * participation impact is CONVEX in x_v (~x^1.5): it penalizes concentration.

The optimum balances the two. We formulate an exact MILP (CBC via PuLP):

  decision  x_v >= 0                               (notional to venue v)
  tiers     y_{v,k} >= 0, z_{v,k} in {0,1}         (bracket disaggregation)
            sum_k z_{v,k} = 1,  x_v = sum_k y_{v,k}
            L_k z_{v,k} <= y_{v,k} <= U_k z_{v,k}   (pick exactly one bracket)
            explicit_fee_v = sum_k r_{v,k} y_{v,k}  (linear given brackets)
  impact    x_v = sum_j d_{v,j},  0 <= d_{v,j} <= width_j   (convex PWL;
            increasing slopes => LP fills cheap segments first, exact)
  linear    spread + size-impact + per-order folded as c_v * x_v
  balance   sum_v x_v = V
  risk      x_v <= max_venue_share * V
  access    x_v = 0 if firm's region can't reach venue v

A robust local-search fallback runs if PuLP/CBC is unavailable.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Dict, List

from .flow import FlowProfile
from .schedules import Venue
from .fees import rate_for_tier
from .impact import participation_impact, linear_coeff
from .cost import evaluate, Allocation

try:
    import pulp
    _HAVE_PULP = True
except Exception:                                   # pragma: no cover
    _HAVE_PULP = False


def _impact_breakpoints(cap: float, n: int = 12) -> List[float]:
    """Breakpoints for PWL of the convex participation-impact term, denser at
    the low end where curvature is highest."""
    if cap <= 0:
        return [0.0]
    pts = [cap * (i / n) ** 1.5 for i in range(n + 1)]
    pts[0] = 0.0
    pts[-1] = cap
    return pts


@dataclass
class OptResult:
    allocation: Allocation
    status: str
    solver: str

    @property
    def total(self):
        return self.allocation.total


def optimize(venues: Dict[str, Venue], flow: FlowProfile,
             assets: Dict[str, float] = None, verbose: bool = False) -> OptResult:
    assets = assets or {}
    avail = {n: v for n, v in venues.items() if flow.region in v.regions}
    if not avail:
        raise ValueError(f"No venues available in region {flow.region!r}")
    V = flow.monthly_notional
    cap = flow.max_venue_share * V

    if _HAVE_PULP:
        alloc, status = _solve_milp(avail, flow, V, cap, verbose)
        solver = "CBC/MILP"
    else:                                           # pragma: no cover
        alloc, status = _solve_local(avail, flow, V, cap)
        solver = "local-search"

    return OptResult(allocation=evaluate(alloc, venues, flow, assets),
                     status=status, solver=solver)


def _solve_milp(avail, flow, V, cap, verbose):
    prob = pulp.LpProblem("route_right", pulp.LpMinimize)
    x = {}
    obj_terms = []

    for name, v in avail.items():
        tiers = v.tiers_sorted()
        # cap this venue can hold
        vcap = min(cap, V)
        x[name] = pulp.LpVariable(f"x_{name}", lowBound=0, upBound=vcap)

        # ---- tiered explicit fee: bracket disaggregation ----
        y, z = [], []
        for k, t in enumerate(tiers):
            low = t.threshold_usd
            up = tiers[k + 1].threshold_usd if k + 1 < len(tiers) else vcap
            up = min(up, vcap)
            zk = pulp.LpVariable(f"z_{name}_{k}", cat="Binary")
            # if bracket lower bound exceeds cap, bracket is unreachable
            reachable = low <= vcap + 1e-9
            yk = pulp.LpVariable(f"y_{name}_{k}", lowBound=0, upBound=max(up, 0))
            z.append(zk)
            y.append(yk)
            if not reachable:
                prob += zk == 0
            # y_k active only if z_k chosen, within [low, up]
            prob += yk <= up * zk
            prob += yk >= low * zk
            rate = rate_for_tier(v, t, flow)["blended_rate"]
            obj_terms.append(rate * yk)
        prob += pulp.lpSum(z) == 1
        prob += x[name] == pulp.lpSum(y)

        # ---- convex participation impact: PWL (no binaries needed) ----
        bps = _impact_breakpoints(vcap)
        deltas = []
        for j in range(len(bps) - 1):
            w = bps[j + 1] - bps[j]
            dj = pulp.LpVariable(f"d_{name}_{j}", lowBound=0, upBound=max(w, 0))
            f0 = participation_impact(v, bps[j], flow)
            f1 = participation_impact(v, bps[j + 1], flow)
            slope = (f1 - f0) / w if w > 0 else 0.0
            obj_terms.append(slope * dj)
            deltas.append(dj)
        if deltas:
            prob += x[name] == pulp.lpSum(deltas)

        # ---- linear terms (spread + size impact + per-order) ----
        obj_terms.append(linear_coeff(v, flow) * x[name])

    prob += pulp.lpSum(x[name] for name in avail) == V
    prob += pulp.lpSum(obj_terms)

    prob.solve(pulp.PULP_CBC_CMD(msg=1 if verbose else 0))
    status = pulp.LpStatus[prob.status]
    alloc = {name: max(0.0, pulp.value(x[name]) or 0.0) for name in avail}
    # clean tiny residuals
    alloc = {n: (0.0 if val < 1.0 else val) for n, val in alloc.items()}
    return alloc, status


def _solve_local(avail, flow, V, cap):              # pragma: no cover
    """Heuristic fallback: greedy seed + coordinate descent on the true cost."""
    from .cost import evaluate
    names = list(avail)
    # seed: everything on the best single venue
    best_single, best_cost = names[0], float("inf")
    for n in names:
        c = evaluate({n: V}, avail, flow).total
        if c < best_cost:
            best_single, best_cost = n, c
    alloc = {n: (V if n == best_single else 0.0) for n in names}

    step = V * 0.1
    for _ in range(400):
        improved = False
        for a in names:
            for b in names:
                if a == b or alloc[a] < step:
                    continue
                if alloc[b] + step > cap:
                    continue
                trial = dict(alloc)
                trial[a] -= step
                trial[b] += step
                if evaluate(trial, avail, flow).total < \
                        evaluate(alloc, avail, flow).total - 1e-6:
                    alloc = trial
                    improved = True
        if not improved:
            step *= 0.5
            if step < V * 1e-4:
                break
    return alloc, "heuristic"
