"""Collection-offer policy: pure functions, no I/O. The agent may not state a number
this module did not return. "25%" is read as 25% of the agreed total (max 4 payments)."""

# Vapi's endCallPhrases hangs up on this. Every terminal line ends with it, nothing else does.
BYE = "Goodbye."

BALANCE = 1000.00
FLOOR_TOTAL = 850          # 20% max discount
MIN_PAY_PCT = 0.25            # => at most 4 payments
SETTLE_MAX_PAYMENTS, SETTLE_MAX_DAYS = 3, 60
PLAN_MAX_PAYMENTS, PLAN_MAX_DAYS = 4, 90

STEP = {"once": 0, "weekly": 7, "biweekly": 14, "monthly": 30}

# Concession ladder in preference order. One rung per counter, never back.
TIERS = [
    {"key": "full",      "total": 1000.00, "n": 1, "cadence": "once",     "amounts": [1000.00]},
    {"key": "two_pay",   "total": 1000.00, "n": 2, "cadence": "biweekly", "amounts": [600.00, 400.00]},
    {"key": "settle_5",  "total":  950.00, "n": 3, "cadence": "monthly",  "amounts": None},
    {"key": "settle_10", "total":  900.00, "n": 3, "cadence": "monthly",  "amounts": None},
    {"key": "settle_15", "total":  850.00, "n": 3, "cadence": "monthly",  "amounts": None},
    {"key": "plan",      "total": 1000.00, "n": 3, "cadence": "monthly",  "amounts": None},
]
FLOOR_RUNG = next(i for i, t in enumerate(TIERS) if t["total"] == FLOOR_TOTAL)
LAST_RUNG = len(TIERS) - 1

# Payments of "$X per <cadence>" that fit in 90 days, when no count is named.
PERIODS_90 = {"once": 1, "weekly": 13, "biweekly": 6, "monthly": 3}


def split(total, n):
    """Even split in whole cents; remainder rides on the first payment."""
    cents = round(total * 100)
    base = cents // n
    return [(base + (cents - base * n if i == 0 else 0)) / 100 for i in range(n)]


def schedule_for(tier, pref_cadence=None):
    cadence = tier["cadence"]
    n = tier["n"]
    if tier["key"] == "plan" and pref_cadence in ("weekly", "biweekly"):
        cadence, n = pref_cadence, PLAN_MAX_PAYMENTS      # 4 x $250
    elif tier["amounts"] is None and pref_cadence in ("weekly", "biweekly", "monthly"):
        cadence = pref_cadence
    amounts = tier["amounts"] or split(tier["total"], n)
    sched = [{"day": i * STEP[cadence], "amount": a} for i, a in enumerate(amounts)]
    return {"tier": tier["key"], "total": tier["total"], "cadence": cadence, "schedule": sched}


def legal(total, schedule):
    """The single policy gate every number passes through."""
    if not schedule or total < FLOOR_TOTAL - 0.005 or total > BALANCE + 0.005:
        return False
    if abs(sum(p["amount"] for p in schedule) - total) > 0.02:
        return False
    if any(p["amount"] < total * MIN_PAY_PCT - 0.005 or p["day"] < 0 for p in schedule):
        return False
    settlement = total < BALANCE - 0.005
    max_n, max_days = (SETTLE_MAX_PAYMENTS, SETTLE_MAX_DAYS) if settlement else (PLAN_MAX_PAYMENTS, PLAN_MAX_DAYS)
    return len(schedule) <= max_n and schedule[-1]["day"] <= max_days


def value(total, schedule):
    """Lexicographic worth to the creditor. Money first, then speed."""
    return (round(total, 2), -len(schedule), -schedule[-1]["day"])


def _num(x, default=0.0):
    try:
        v = float(x)
        return v if v == v and abs(v) != float("inf") and v >= 0 else default
    except (TypeError, ValueError):
        return default


def _trim(sched):
    """Cut an overpaying schedule at the balance, keeping its dates.
    A final payment under 25% folds into the first one."""
    cents, left = [], round(BALANCE * 100)
    for p in sched:
        take = min(round(p["amount"] * 100), left)
        if take:
            cents.append([p["day"], take])
        left -= take
    if len(cents) > 1 and cents[-1][1] < BALANCE * MIN_PAY_PCT * 100:
        cents[0][1] += cents.pop()[1]
    return [{"day": d, "amount": c / 100} for d, c in cents]


def normalize(offer):
    """Untrusted input from the LLM -> (total, schedule|None, capacity_90, cadence)."""
    cadence = offer.get("cadence")
    cadence = cadence if cadence in STEP else None
    per = _num(offer.get("amount_per_payment"))
    down = _num(offer.get("down_payment"))
    n = int(_num(offer.get("num_payments")))

    if n and per:
        sched = ([{"day": 0, "amount": down}] if down else []) + [
            {"day": (i + (1 if down else 0)) * STEP[cadence or "monthly"], "amount": per} for i in range(n)
        ]
        total = down + per * n
        if total > BALANCE:                             # never collect more than owed
            return BALANCE, _trim(sched), BALANCE, cadence
        return total, sched, total, cadence
    if per:                                             # open-ended "$X a month"
        cap = down + per * PERIODS_90.get(cadence or "monthly", 3)
        return 0.0, None, min(cap, BALANCE), cadence
    if down:                                            # "I can put down $X"
        return down, [{"day": 0, "amount": down}], down, cadence
    return 0.0, None, 0.0, cadence


def phrase(counter):
    parts = []
    for p in counter["schedule"]:
        when = "today" if p["day"] == 0 else f"in {p['day']} days"
        parts.append(f"${p['amount']:.2f} {when}")
    if counter["tier"].startswith("settle"):
        head = f"I can settle the full ${BALANCE:.0f} for ${counter['total']:.0f}"
    elif counter["tier"] == "full":
        head = f"The balance is ${BALANCE:.0f}"
    else:
        head = f"We can clear the full ${counter['total']:.0f}"
    return head + ": " + ", then ".join(parts) + "."


def evaluate(state, offer):
    """The whole negotiation. `state` is a mutable dict owned by the server."""
    rung = state.get("rung", 0)
    total, sched, cap, cadence = normalize(offer)
    current = schedule_for(TIERS[rung], cadence)

    ok = bool(sched) and legal(total, sched)

    def accept():
        state["accepted"] = {"total": round(total, 2), "schedule": sched}
        return {"verdict": "accept", "terms": state["accepted"], "final": True,
                "say": f"That works. ${total:.2f} total, {len(sched)} payment(s). I'll lock that in."}

    # The full balance in any legal shape is accepted, whatever our standing offer.
    if ok and (total >= BALANCE - 0.005 or value(total, sched) >= value(current["total"], current["schedule"])):
        return accept()

    if cap < FLOOR_TOTAL - 0.005:
        state["below_floor"] = state.get("below_floor", 0) + 1
        # Only give up once the floor offer has been heard.
        if state["below_floor"] >= 3 and rung >= FLOOR_RUNG:
            return {"verdict": "hardship", "final": True, "say":
                    "It sounds like nothing in my authority fits your situation right now. "
                    f"I'll note that on the account and have someone follow up. "
                    f"Thank you for your time. {BYE}"}

    nxt = min(rung + 1, LAST_RUNG)
    # Skip rungs only for inferred capacity ("$300 a month"). A concrete figure is an
    # anchor, so naming $800 outright must not hand over the whole discount.
    infer = sched is None
    chosen = (next((i for i in range(nxt, len(TIERS)) if TIERS[i]["total"] <= cap + 0.005), LAST_RUNG)
              if infer and cap >= FLOOR_TOTAL - 0.005 else nxt)
    counter = schedule_for(TIERS[chosen], cadence)
    # Never counter with something no better than their own offer.
    if ok and value(total, sched) >= value(counter["total"], counter["schedule"]):
        return accept()

    state["rung"] = chosen                                    # ratchet: never climbs back
    state["offered"] = {"total": counter["total"], "schedule": counter["schedule"]}  # bookable on "yes"
    return {"verdict": "counter", "terms": counter, "final": chosen == LAST_RUNG,
            "say": phrase(counter)}


def _matches(issued, total, sched):
    """Same total and the same payments, day for day, to the cent."""
    return (abs(issued["total"] - total) <= 0.02 and len(issued["schedule"]) == len(sched)
            and all(a["day"] == b["day"] and abs(a["amount"] - b["amount"]) <= 0.01
                    for a, b in zip(issued["schedule"], sched)))


def book(state, terms):
    """Second gate: only legal terms the validator issued on this call can be logged."""
    total, sched = _num(terms.get("total")), terms.get("schedule") or []
    sched = [{"day": int(_num(p.get("day"))), "amount": _num(p.get("amount"))} for p in sched]
    issued = [t for t in (state.get("accepted"), state.get("offered")) if t]
    if not any(_matches(t, total, sched) for t in issued):
        return {"ok": False, "reason": "no matching offer issued on this call"}
    if not legal(total, sched):
        return {"ok": False, "reason": "terms violate policy"}
    first = sched[0]
    return {"ok": True, "total": round(total, 2), "schedule": sched,
            "say": f"That's locked in. ${total:.2f} total, starting with "
                   f"${first['amount']:.2f} {'today' if first['day'] == 0 else f'in {first["day"]} days'}. "
                   f"Thank you for taking care of this. {BYE}"}
