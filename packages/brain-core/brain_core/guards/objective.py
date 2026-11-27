"""Objective reconciliation: recompute the bucket-model objective from a
PLAN and the validator KPIs (which come from raw records) and compare it
with the solver's objective. A hidden or mis-weighted term shows up as a
mismatch (measured: setup + late*backlog_unit_days + early*early_unit_days
equals the monolith objective to 1e-8 relative on pools 0.9 seeds).

KPI names (docs): late_unit_days counts only NEW shortfall per day;
backlog_unit_days is the model's lateness term (cumulative shortfall
charged on every day it persists, including the horizon end)."""
from __future__ import annotations


def recomputed_objective(kpis: dict, weights) -> float:
    if getattr(weights, "energy", 0.0):
        raise ValueError("energy term cannot be reconciled from KPIs")
    return (weights.setup * kpis["setups"]
            + weights.late * kpis["backlog_unit_days"]
            + weights.early * kpis["early_unit_days"])


def reconciliation(solver_objective: float, kpis: dict, weights) -> dict:
    """Record fragment for check_record's objective_mismatch rule."""
    return {"solver": solver_objective,
            "recomputed": recomputed_objective(kpis, weights)}
