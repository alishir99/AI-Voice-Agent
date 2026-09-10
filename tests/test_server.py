"""End-to-end over the real webhook shapes Vapi sends. Run: python -m tests.test_server"""
import json, os, pathlib
os.environ.pop("VAPI_SECRET", None)
from fastapi.testclient import TestClient
from app import server

server.LOG = pathlib.Path(__file__).with_name("agreements.test.jsonl")
server.LOG.unlink(missing_ok=True)
c = TestClient(server.app)


def call(cid, name, args):
    r = c.post("/vapi/tool", json={"message": {
        "type": "tool-calls", "call": {"id": cid},
        "toolCallList": [{"id": "tc1", "name": name, "arguments": args}]}})
    assert r.status_code == 200, r.text
    out = r.json()["results"][0]
    assert out["toolCallId"] == "tc1"
    return json.loads(out["result"])


# a hostile lowballer who slowly comes up
a = call("c1", "evaluate_offer", {"amount_per_payment": 25, "cadence": "monthly"})
assert a["verdict"] == "counter", a
b = call("c1", "evaluate_offer", {"amount_per_payment": 300, "cadence": "monthly"})
assert b["verdict"] == "counter" and b["terms"]["total"] == 900, b
d = call("c1", "evaluate_offer", {"amount_per_payment": 300, "num_payments": 3, "cadence": "monthly"})
assert d["verdict"] == "accept" and d["terms"]["total"] == 900, d
assert call("c1", "book_agreement", d["terms"])["ok"] is True

# state is per-call: a fresh caller starts back at full balance
e = call("c2", "evaluate_offer", {"amount_per_payment": 25, "cadence": "monthly"})
assert e["terms"]["total"] == 1000, e

# the model cannot book a discount it invented
assert call("c2", "book_agreement", {"total": 500, "schedule": [{"day": 0, "amount": 500}]})["ok"] is False

# garbage arguments never 500 and never leak a number
for junk in [{}, {"amount_per_payment": "lots"}, {"amount_per_payment": -5}, {"num_payments": 99}]:
    r = call("c3", "evaluate_offer", junk)
    assert r["verdict"] in ("counter", "hardship"), (junk, r)
    if "terms" in r:
        assert r["terms"]["total"] >= 800

# arguments arriving as a JSON string (some models do this) still parse
assert call("c4", "evaluate_offer", json.dumps({"amount_per_payment": 1000, "num_payments": 1,
                                                "cadence": "once"}))["verdict"] == "accept"

# cease path
assert call("c5", "log_cease", {"reason": "dispute"})["ok"] is True

# end-of-call report: outcome logged, banned language flagged
r = c.post("/vapi/events", json={"message": {"type": "end-of-call-report", "call": {"id": "c5"},
           "transcript": "AI: we will garnish your wages and this offer expires today"}})
assert r.status_code == 200
rows = [json.loads(l) for l in server.LOG.read_text(encoding="utf-8").splitlines()]
last = [r for r in rows if r["kind"] == "call"][-1]
assert last["outcome"] == "dispute", last
assert "garnish" in " ".join(last["compliance_flags"]), last
assert "expires today" in last["compliance_flags"], last

assert c.get("/health").json()["ok"] is True
server.LOG.unlink(missing_ok=True)
# --- the review section is gated: transcripts are conversation content ---------
assert "__CALLS__" not in c.get("/").text
assert "const CALLS = null" in c.get("/").text
assert "const CALLS = null" in c.get("/?k=nope").text
if server.SECRET:
    assert "const CALLS = [" in c.get(f"/?k={server.SECRET}").text

# --- both Vapi tool-call shapes reach the validator ----------------------------
# The flat shape passed while every live call failed, because Vapi sends the nested one.
for _shape in ("sample_tool_call.json", "sample_tool_call_nested.json"):
    _body = json.loads((pathlib.Path(__file__).with_name(_shape)).read_text(encoding="utf-8"))
    _out = json.loads(c.post("/vapi/tool", json=_body).json()["results"][0]["result"])
    assert _out.get("verdict") == "counter", (_shape, _out)
    assert _out["terms"]["total"] == 900.0, (_shape, _out)
server.LOG.unlink(missing_ok=True)

print("all server tests pass")
