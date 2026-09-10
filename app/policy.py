"""Collection-offer policy. Pure functions, no I/O. This is the logic that lives
OUTSIDE the voice agent. The agent may not state a number this module did not return.

Rules (from the brief):
  balance $1,000; settlement up to 20% off, max 3 payments; plan = no discount,
  max 3 months, weekly/biweekly/monthly; no payment below 25%.

Stated assumption: "25%" is 25% OF THE AGREED TOTAL. That is the only reading that
makes weekly/biweekly meaningful: it caps every schedule at 4 payments.
"""

BALANCE = 1000.00
FLOOR_TOTAL = 800.00          # 20% max discount
MIN_PAY_PCT = 0.25            # => at most 4 payments
SETTLE_MAX_PAYMENTS, SETTLE_MAX_DAYS = 3, 60
PLAN_MAX_PAYMENTS, PLAN_MAX_DAYS = 4, 90

STEP = {"once": 0, "weekly": 7, "biweekly": 14, "monthly": 30}

# Concession ladder, in the brief's preference order. One rung per counter, never
# back. 5/10/15 exist so the maximum discount is five counters away, not three.
TIERS = [
    {"key": "full",      "total": 1000.00, "n": 1, "cadence": "once",     "amounts": [1000.00]},
    {"key": "two_pay",   "total": 1000.00, "n": 2, "cadence": "biweekly", "amounts": [600.00, 400.00]},
    {"key": "settle_5",  "total":  950.00, "n": 3, "cadence": "monthly",  "amounts": None},
    {"key": "settle_10", "total":  900.00, "n": 3, "cadence": "monthly",  "amounts": None},
    {"key": "settle_15", "total":  850.00, "n": 3, "cadence": "monthly",  "amounts": None},
    {"key": "settle_20", "total":  800.00, "n": 3, "cadence": "monthly",  "amounts": None},
    {"key": "plan",      "total": 1000.00, "n": 3, "cadence": "monthly",  "amounts": None},
]
FLOOR_RUNG = next(i for i, t in enumerate(TIERS) if t["total"] == FLOOR_TOTAL)
LAST_RUNG = len(TIERS) - 1

# 90-day capacity implied by "$X per <cadence>" when the consumer names no end date.
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
    """Would this deal survive an audit? The single gate every number passes through."""
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
            return BALANCE, [{"day": 0, "amount": BALANCE}], BALANCE, cadence
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

    if ok and value(total, sched) >= value(current["total"], current["schedule"]):
        return accept()

    if cap < FLOOR_TOTAL - 0.005:
        state["below_floor"] = state.get("below_floor", 0) + 1
        # Surface the floor before giving up. They should hear our best offer once.
        if state["below_floor"] >= 3 and rung >= FLOOR_RUNG:
            return {"verdict": "hardship", "final": True, "say":
                    "It sounds like nothing in my authority fits your situation right now. "
                    "I'll note that on the account and have someone follow up. Thank you for your time."}

    nxt = min(rung + 1, LAST_RUNG)
    # Skip rungs they demonstrably cannot afford, but a lowball below the floor buys
    # them nothing: it advances us exactly one rung, it does not surrender the discount.
    chosen = (next((i for i in range(nxt, len(TIERS)) if TIERS[i]["total"] <= cap + 0.005), LAST_RUNG)
              if cap >= FLOOR_TOTAL - 0.005 else nxt)
    counter = schedule_for(TIERS[chosen], cadence)
    # Never counter with something no better than what they already put on the table.
    # That is how an agent talks itself out of the full balance.
    if ok and value(total, sched) >= value(counter["total"], counter["schedule"]):
        return accept()

    state["rung"] = chosen                                    # ratchet: never climbs back
    # The standing offer, so agreeing to our own counter is bookable.
    state["offered"] = {"total": counter["total"], "schedule": counter["schedule"]}
    return {"verdict": "counter", "terms": counter, "final": chosen == LAST_RUNG,
            "say": phrase(counter)}


def book(state, terms):
    """Second gate. An out-of-policy deal cannot be logged even if the model invents one."""
    total, sched = _num(terms.get("total")), terms.get("schedule") or []
    sched = [{"day": int(_num(p.get("day"))), "amount": _num(p.get("amount"))} for p in sched]
    # Bookable iff the validator issued these terms on this call. An invented
    # figure matches neither, which is the point of this gate.
    issued = [t for t in (state.get("accepted"), state.get("offered")) if t]
    if not any(abs(t["total"] - total) <= 0.02 for t in issued):
        return {"ok": False, "reason": "no matching offer issued on this call"}
    if not legal(total, sched):
        return {"ok": False, "reason": "terms violate policy"}
    first = sched[0]
    return {"ok": True, "total": round(total, 2), "schedule": sched,
            # The closing line comes from here too, so the agent has nothing to invent
            # at the one moment the call is worth something.
            "say": f"That's locked in. ${total:.2f} total, starting with "
                   f"${first['amount']:.2f} {'today' if first['day'] == 0 else f'in {first["day"]} days'}. "
                   f"Thank you for taking care of this."}
