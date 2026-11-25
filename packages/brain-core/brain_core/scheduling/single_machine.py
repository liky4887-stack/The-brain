"""Single-machine scheduling theory from Bertsimas & Tsitsiklis,
"Introduction to Linear Optimization" (Athena Scientific), sec. 12.5.

Every claim in this module is backed by tests/test_single_machine.py,
which checks the implementations against brute-force enumeration of all
permutations (optimality) and all 2^n subsets (separation).

Theorem 12.1 (WSPT): for jobs with weights w_i > 0 and processing times
p_i > 0 on a single machine, minimizing the weighted sum of completion
times sum_i w_i C_i (no release times, no precedence constraints,
nonpreemptive) is solved by sequencing jobs in nonincreasing order of
w_i / p_i.

Equation (12.1) / Theorem 12.2: the convex hull of feasible completion
time vectors (C_1, ..., C_n) is described by the supermodular
inequalities

    sum_{i in S} p_i C_i  >=  1/2 * sum_{i in S} p_i^2
                          +  1/2 * (sum_{i in S} p_i)^2      for all S,

and a given vector C can be checked (or a most-violated S found) in
O(n log n): sort jobs by increasing C_i, and only the n nested prefixes
of that order need to be examined.
"""

from __future__ import annotations


def wspt_order(weights, processing_times):
    """Optimal sequence for min sum_i w_i C_i on a single machine.

    Returns the list of job indices in nonincreasing w_i / p_i order.
    Ties are broken by smaller index; any tie order is optimal (equal
    ratios admit pairwise interchange with zero cost change, per the
    book's interchange argument in the proof of Theorem 12.1).
    """
    n = len(weights)
    if len(processing_times) != n:
        raise ValueError("weights and processing_times must have equal length")
    if any(w <= 0 for w in weights):
        raise ValueError("weights must be positive")
    if any(p <= 0 for p in processing_times):
        raise ValueError("processing times must be positive")
    # Compare w_i/p_i without floats: w_i*p_j vs w_j*p_i.
    from functools import cmp_to_key

    def cmp(i, j):
        lhs = weights[i] * processing_times[j]
        rhs = weights[j] * processing_times[i]
        if lhs != rhs:
            return -1 if lhs > rhs else 1
        return -1 if i < j else (1 if i > j else 0)

    return sorted(range(n), key=cmp_to_key(cmp))


def completion_times(sequence, processing_times):
    """Completion times of a sequence under nonidling processing."""
    times = {}
    t = 0
    for job in sequence:
        t += processing_times[job]
        times[job] = t
    return times


def weighted_completion_sum(sequence, weights, processing_times):
    """Objective value sum_i w_i C_i of a sequence."""
    times = completion_times(sequence, processing_times)
    return sum(weights[i] * times[i] for i in sequence)


def supermodular_rhs(subset, processing_times):
    """Right-hand side p(S) = 1/2 sum_{i in S} p_i^2 + 1/2 (sum_{i in S} p_i)^2.

    Returned doubled as an integer (2*p(S)) so callers can stay exact:
    2*p(S) = sum p_i^2 + (sum p_i)^2.
    """
    s = sum(processing_times[i] for i in subset)
    sq = sum(processing_times[i] ** 2 for i in subset)
    return sq + s * s  # equals 2 * p(S)


def supermodular_lhs_doubled(subset, completion, processing_times):
    """Left-hand side sum_{i in S} p_i C_i, doubled to match supermodular_rhs."""
    return 2 * sum(processing_times[i] * completion[i] for i in subset)


def separation(completion, processing_times):
    """Theorem 12.2 separation algorithm, O(n log n).

    Given a completion-time vector, decide whether it satisfies all
    supermodular inequalities (12.1); if not, return a subset S whose
    inequality is violated (one that maximizes the violation
    p(S) - sum_{i in S} p_i C_i).

    Returns (feasible, subset_or_None, violation_or_0) where violation
    is the doubled gap p(S) - lhs (positive when violated).
    """
    n = len(processing_times)
    order = sorted(range(n), key=lambda i: completion[i])
    best_violation = 0
    best_subset = None
    prefix = []
    for job in order:
        prefix.append(job)
        gap = supermodular_rhs(prefix, processing_times) - supermodular_lhs_doubled(
            prefix, completion, processing_times
        )
        if gap > best_violation:
            best_violation = gap
            best_subset = list(prefix)
    return (best_subset is None), best_subset, best_violation
