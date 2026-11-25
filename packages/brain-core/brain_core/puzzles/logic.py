"""Logic and word puzzles as CP-SAT models.

Source: Hürlimann, Puzzles and Games (6th ed. 2025): einstein (sec
5.1), alcuin Wolf-Goat-Cabbage (sec 5.2, time-indexed formulation from
the cited paper), sendmore (sec 5.9), change (sec 2.27). Models follow
the book's LPL listings; the Einstein variant uses the book's drinks
(coffee/tea/milk/juice/water) and cigars.
"""

from __future__ import annotations

from ortools.sat.python import cp_model


def _solve(model: cp_model.CpModel, time_limit_s: float):
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = time_limit_s
    status = solver.solve(model)
    name = solver.status_name(status)
    if name not in ("OPTIMAL", "FEASIBLE"):
        return name, None
    return name, solver


def einstein(time_limit_s: float = 10.0) -> dict:
    """Einstein's zebra puzzle (book variant). Locked answer: the
    German owns the fish."""
    nationalities = ["Norwegian", "Dane", "Briton", "Swede", "German"]
    colors = ["yellow", "blue", "red", "green", "white"]
    pets = ["cat", "bird", "dog", "horse", "fish"]
    drinks = ["coffee", "tea", "milk", "juice", "water"]
    cigars = ["Dunhill", "Marlboro", "Pall-Mall", "Bluemaster", "Prince"]
    groups = [nationalities, colors, pets, drinks, cigars]
    model = cp_model.CpModel()
    pos = []
    for gi, group in enumerate(groups):
        pos.append({name: model.new_int_var(1, 5, f"p{gi}_{k}") for k, name in enumerate(group)})
        model.add_all_different(pos[gi].values())
    A, B, C, D, E = pos
    # The 15 rules, transcribed from the book's LPL listing (its rule
    # numbering; rules 13/14 there are folded into R13/R14 below).
    model.add(A["Briton"] == B["red"])                    # R1
    model.add(A["Swede"] == C["dog"])                     # R2
    model.add(A["Dane"] == D["tea"])                      # R3
    model.add(B["green"] + 1 == B["white"])               # R4
    model.add(B["green"] == D["coffee"])                  # R5
    model.add(E["Pall-Mall"] == C["bird"])                # R6
    model.add(D["milk"] == 3)                             # R7
    model.add(B["yellow"] == E["Dunhill"])                # R8
    model.add(A["Norwegian"] == 1)                        # R9
    # R10/R11/R15 are disjunctions |u - v| = 1, encoded directly:
    for u, v in [(E["Marlboro"], C["cat"]), (C["horse"], E["Dunhill"]),
                 (E["Marlboro"], D["water"])]:
        d = model.new_int_var(-4, 4, "d")
        model.add(d == u - v)
        model.add_abs_equality(model.new_int_var(1, 1, "ad"), d)
    model.add(E["Bluemaster"] == D["juice"])              # R12
    model.add(B["blue"] == 2)                             # R13 (blue house 2)
    model.add(A["German"] == E["Prince"])                 # R14
    # R14': Norwegian next to the blue house (prose rule 14)
    d = model.new_int_var(-4, 4, "d14")
    model.add(d == A["Norwegian"] - B["blue"])
    model.add_abs_equality(model.new_int_var(1, 1, "ad14"), d)
    status, solver = _solve(model, time_limit_s)
    if solver is None:
        return {"status": status, "assignment": None, "fish_owner": None}
    assignment = {
        gi_name: {name: solver.value(var) for name, var in group.items()}
        for gi_name, group in zip(
            ["nationality", "color", "pet", "drink", "cigar"], pos
        )
    }
    fish_pos = assignment["pet"]["fish"]
    fish_owner = next(
        name for name, p in assignment["nationality"].items() if p == fish_pos
    )
    return {"status": status, "assignment": assignment, "fish_owner": fish_owner}


def wolf_goat_cabbage(time_limit_s: float = 10.0) -> dict:
    """Wolf-goat-cabbage river crossing (alcuin), time-indexed per the
    book. Locked answer: 7 crossings (T = 2*5 - 1 = 9 time points)."""
    items = ["wolf", "goat", "cabbage"]
    T = 9
    model = cp_model.CpModel()
    x = {(t, i): model.new_bool_var(f"x_{t}_{i}") for t in range(T + 1) for i in items}
    y = {(t, i): model.new_bool_var(f"y_{t}_{i}") for t in range(T + 1) for i in items}
    z = {(t, i): model.new_bool_var(f"z_{t}_{i}") for t in range(T + 1) for i in items}
    for i in items:  # initial state: all left
        model.add(x[(0, i)] == 1)
        model.add(y[(0, i)] == 0)
        model.add(z[(0, i)] == 0)
    for i in items:  # final state: all right
        model.add(z[(T, i)] == 1)
    for t in range(T):
        for i in items:
            if t % 2 == 0:  # left-to-right shipment at t+1
                model.add(x[(t + 1, i)] == x[(t, i)] - y[(t + 1, i)])
                model.add(z[(t + 1, i)] == z[(t, i)] + y[(t + 1, i)])
            else:           # right-to-left shipment at t+1
                model.add(x[(t + 1, i)] == x[(t, i)] + y[(t + 1, i)])
                model.add(z[(t + 1, i)] == z[(t, i)] - y[(t + 1, i)])
    for t in range(1, T + 1):  # at most one item per shipment
        model.add(sum(y[(t, i)] for i in items) <= 1)
    w, g, c = items
    # Safety (the book's C1/C2 pairwise on the left bank, D1/D2 as its
    # aggregate cuts on the right bank; both only for t < T):
    for t in range(1, T):
        if t % 2 == 1:  # man on the right, left bank unattended
            model.add(x[(t, w)] + x[(t, g)] <= 1)
            model.add(x[(t, g)] + x[(t, c)] <= 1)
        else:  # man on the left, right bank unattended (book's cuts)
            model.add(z[(t, g)] + z[(t, c)] - z[(t, w)] <= 1)
            model.add(z[(t, w)] + z[(t, g)] - z[(t, c)] <= 1)
    model.minimize(sum(x[(t, i)] for t in range(T + 1) for i in items))
    status, solver = _solve(model, time_limit_s)
    if solver is None:
        return {"status": status, "crossings": None, "plan": None}
    # The crossing is complete at the first time point with all items
    # on the right bank; the plan is the shipments up to there.
    done = next(t for t in range(T + 1)
                if all(solver.value(z[(t, i)]) for i in items))
    plan = [
        next((i for i in items if solver.value(y[(t, i)])), "empty")
        for t in range(1, done + 1)
    ]
    return {"status": status, "crossings": done, "plan": plan}


def send_more_money(time_limit_s: float = 10.0) -> dict:
    """SEND + MORE = MONEY (sendmore). Locked unique answer:
    9567 + 1085 = 10652."""
    letters = ["S", "E", "N", "D", "M", "O", "R", "Y"]
    model = cp_model.CpModel()
    d = {ch: model.new_int_var(0, 9, ch) for ch in letters}
    model.add_all_different(d.values())
    model.add(d["S"] != 0)
    model.add(d["M"] != 0)
    send = 1000 * d["S"] + 100 * d["E"] + 10 * d["N"] + d["D"]
    more = 1000 * d["M"] + 100 * d["O"] + 10 * d["R"] + d["E"]
    money = (10000 * d["M"] + 1000 * d["O"] + 100 * d["N"]
             + 10 * d["E"] + d["Y"])
    model.add(send + more == money)
    status, solver = _solve(model, time_limit_s)
    if solver is None:
        return {"status": status, "digits": None}
    digits = {ch: solver.value(v) for ch, v in d.items()}
    return {"status": status, "digits": digits}


def change_dollar(time_limit_s: float = 10.0) -> dict:
    """Change for one dollar (change). Locked unique answer:
    one 50c, one 25c, four 10c coins ($1.15 total)."""
    model = cp_model.CpModel()
    a = model.new_int_var(0, 1, "a")   # 50-cent coins
    b = model.new_int_var(0, 1, "b")   # quarters
    c = model.new_int_var(0, 4, "c")   # dimes
    d = model.new_int_var(0, 1, "d")   # nickels
    e = model.new_int_var(0, 4, "e")   # cents
    model.add(50 * a + 25 * b + 10 * c + 5 * d + e == 115)
    status, solver = _solve(model, time_limit_s)
    if solver is None:
        return {"status": status, "coins": None}
    coins = {"50c": solver.value(a), "25c": solver.value(b),
             "10c": solver.value(c), "5c": solver.value(d), "1c": solver.value(e)}
    return {"status": status, "coins": coins}
