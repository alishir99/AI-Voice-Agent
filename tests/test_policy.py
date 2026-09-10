"""Run: python -m tests.test_policy   (asserts only, no framework)"""
from itertools import product
from app.policy import (BALANCE, FLOOR_TOTAL, MIN_PAY_PCT, TIERS, LAST_RUNG,
                    evaluate, book, legal, schedule_for, split)


def offer(**kw):
    return {"amount_per_payment": None, "num_payments": None, "cadence": None, "down_payment": None, **kw}


# --- every tier we can ever offer is itself legal, at every cadence -------------
for t, c in product(TIERS, [None, "weekly", "biweekly", "monthly"]):
    s = schedule_for(t, c)
    assert legal(s["total"], s["schedule"]), (t["key"], c)

# --- the floors hold for anything the ladder can produce ------------------------
for rung in range(len(TIERS)):
    for c in [None, "weekly", "biweekly", "monthly"]:
        s = schedule_for(TIERS[rung], c)
        assert s["total"] >= FLOOR_TOTAL
        assert all(p["amount"] >= s["total"] * MIN_PAY_PCT - 0.005 for p in s["schedule"])
        assert len(s["schedule"]) <= 4
        assert abs(sum(p["amount"] for p in s["schedule"]) - s["total"]) < 0.02

# --- split is cents-exact -------------------------------------------------------
for total, n in product([800, 900, 1000, 833.33], [1, 2, 3, 4]):
    assert abs(sum(split(total, n)) - total) < 0.005

# --- ladder descends one rung at a time and never climbs back -------------------
st, seen = {}, []
for _ in range(8):
    r = evaluate(st, offer(amount_per_payment=1, num_payments=1))   # absurd lowball
    seen.append(st.get("rung", 0))
    if r["verdict"] == "hardship":
        break
assert seen == sorted(seen), seen
assert max(seen) >= 3, seen                              # the $800 floor was shown before giving up
assert all(b - a <= 1 for a, b in zip(seen, seen[1:])), seen
assert r["verdict"] == "hardship", r

# --- regression: a lowball below the floor must NOT hand over the max discount ----
st = {}
r = evaluate(st, offer(amount_per_payment=25, cadence="monthly"))
assert st["rung"] == 1 and r["terms"]["total"] == 1000.00, (st, r)   # one rung, no discount

# --- capacity-aware: "$300 a month" -> the $900 settlement, not a blind next rung
st = {}
r = evaluate(st, offer(amount_per_payment=300, cadence="monthly"))
assert r["verdict"] == "counter" and r["terms"]["total"] == 900.00, r
assert all(p["amount"] <= 300.01 for p in r["terms"]["schedule"]), r

# --- full payment is accepted at rung 0 -----------------------------------------
st = {}
r = evaluate(st, offer(amount_per_payment=1000, num_payments=1, cadence="once"))
assert r["verdict"] == "accept" and r["terms"]["total"] == 1000.00, r

# --- an offer better than our standing counter is accepted, whatever its shape ---
st = {"rung": 3}                                        # we are at the $800 floor
r = evaluate(st, offer(down_payment=500, amount_per_payment=500, num_payments=1, cadence="monthly"))
assert r["verdict"] == "accept" and r["terms"]["total"] == 1000.00, r

# --- overpayment is clamped to the balance --------------------------------------
st = {}
r = evaluate(st, offer(amount_per_payment=2000, num_payments=1, cadence="once"))
assert r["verdict"] == "accept" and r["terms"]["total"] == BALANCE, r

# --- regression: never counter with something no better than their own offer -----
st = {}
r = evaluate(st, offer(down_payment=600, amount_per_payment=400, num_payments=1, cadence="biweekly"))
assert r["verdict"] == "accept" and r["terms"]["total"] == 1000.00, r    # our own rung-1 terms

# --- regression: a full-balance offer never draws a discounted counter ----------
st = {"rung": 1}
r = evaluate(st, offer(amount_per_payment=250, num_payments=4, cadence="weekly"))
assert r["verdict"] == "accept" and r["terms"]["total"] == 1000.00, r    # $1000 > any settlement
for rung in range(len(TIERS)):
    st = {"rung": rung}
    r = evaluate(st, offer(amount_per_payment=1000, num_payments=1, cadence="once"))
    assert r["verdict"] == "accept", (rung, r)

# --- booking gate: nothing below policy, nothing unaccepted, gets logged ---------
assert book({}, {"total": 800, "schedule": [{"day": 0, "amount": 800}]})["ok"] is False
st = {}
evaluate(st, offer(amount_per_payment=1000, num_payments=1, cadence="once"))
assert book(st, st["accepted"])["ok"] is True
assert book(st, {"total": 1000, "schedule": [{"day": 0, "amount": 1000}]})["ok"] is True
assert book(st, {"total": 400, "schedule": [{"day": 0, "amount": 400}]})["ok"] is False   # invented discount
assert book(st, {"total": 1000, "schedule": [{"day": 0, "amount": 1000}]*1})["ok"] is True

# --- illegal shapes are rejected by the gate ------------------------------------
assert not legal(799.99, [{"day": 0, "amount": 799.99}])                       # under floor
assert not legal(1000, [{"day": i * 30, "amount": 200} for i in range(5)])     # 5 payments, <25%
assert not legal(1000, [{"day": i * 30, "amount": 250} for i in range(4)][:3] + [{"day": 120, "amount": 250}])
assert not legal(800, [{"day": 0, "amount": 200}] * 4)                         # settlement, 4 payments
assert legal(1000, [{"day": i * 14, "amount": 250} for i in range(4)])         # biweekly plan, ok

# --- saying yes to our own counter is bookable; an invented figure is not ------
st = {}
r = evaluate(st, offer(amount_per_payment=400, num_payments=1, cadence="once"))
assert r["verdict"] == "counter", r
terms = r["terms"]
ok = book(st, {"total": terms["total"], "schedule": terms["schedule"]})
assert ok["ok"], ok
assert book(st, {"total": 400, "schedule": [{"day": 0, "amount": 400}]})["ok"] is False
# the standing counter moves with the ladder, so a stale rung cannot be booked later
st2 = {}
first = evaluate(st2, offer(amount_per_payment=400, num_payments=1, cadence="once"))["terms"]
evaluate(st2, offer(amount_per_payment=400, num_payments=1, cadence="once"))
stale = book(st2, {"total": first["total"], "schedule": first["schedule"]})
assert stale["ok"] is False or first["total"] == st2["offered"]["total"], stale

# --- a booked deal carries its own closing line ---------------------------------
st = {}
r = evaluate(st, offer(amount_per_payment=400, num_payments=1, cadence="once"))
ok = book(st, {"total": r["terms"]["total"], "schedule": r["terms"]["schedule"]})
assert ok["ok"] and "locked in" in ok["say"], ok
assert f"{r['terms']['total']:.2f}" in ok["say"], ok
assert "say" not in book(st, {"total": 400, "schedule": [{"day": 0, "amount": 400}]})

# --- every line that ends a call carries the hangup phrase, nothing else does ----
from app.policy import BYE
st = {}
r = evaluate(st, offer(amount_per_payment=400, num_payments=1, cadence="once"))
assert BYE not in r["say"], "a counter must not end the call"
assert BYE in book(st, {"total": r["terms"]["total"], "schedule": r["terms"]["schedule"]})["say"]
st2 = {}
for _ in range(9):
    last = evaluate(st2, offer(amount_per_payment=400, num_payments=1, cadence="once"))
    if last.get("verdict") == "hardship":
        break
assert last["verdict"] == "hardship" and BYE in last["say"], last

print("all policy tests pass")
