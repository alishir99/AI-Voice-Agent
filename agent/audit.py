"""Did the agent ever speak a dollar figure the validator did not issue?

That is the whole claim of this project, so it is worth checking mechanically
rather than trusting a prompt. Run it after any change to the model, the prompt,
or the tool descriptions:

    python -m agent.audit                    # reads agreements.jsonl
    python -m agent.audit path/to/log.jsonl

Exit code 1 if any call has an unissued figure, so it works in CI.
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BALANCE = 1000.00                       # the one number the agent may state unprompted

# "$266.68", "$800", "266.68 dollars". Bare integers are skipped on purpose:
# "three payments" and "30 days" are not money, and matching them is all noise.
MONEY = re.compile(r"\$\s?(\d[\d,]*(?:\.\d{1,2})?)|(\d[\d,]*(?:\.\d{1,2})?)\s*dollars\b", re.I)
AGENT_TURN = re.compile(r"^\s*(?:ai|assistant|bot)\s*:\s*(.*)$", re.I)


def numbers_in(obj, out):
    """Every number the validator put on the wire, at any depth."""
    if isinstance(obj, bool):
        return out
    if isinstance(obj, (int, float)):
        out.add(round(float(obj), 2))
    elif isinstance(obj, dict):
        for v in obj.values():
            numbers_in(v, out)
    elif isinstance(obj, list):
        for v in obj:
            numbers_in(v, out)
    return out


def spoken_amounts(transcript):
    """Dollar figures in the agent's own turns. What the consumer says is theirs
    to say; only what the agent asserts is in scope."""
    found = []
    for line in (transcript or "").splitlines():
        m = AGENT_TURN.match(line)
        if not m:
            continue
        for a, b in MONEY.findall(m.group(1)):
            found.append(round(float((a or b).replace(",", "")), 2))
    return found


def audit(path):
    rows = [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]
    issued, transcripts = {}, {}
    for r in rows:
        cid = r.get("call", "?")
        if r["kind"] == "tool":
            numbers_in(r.get("out"), issued.setdefault(cid, {BALANCE}))
        elif r["kind"] == "call":
            transcripts[cid] = r.get("transcript") or ""

    if not transcripts:
        print("no completed calls in the log yet. Deploy, take a call, then re-run.")
        return 0

    bad = 0
    for cid, transcript in transcripts.items():
        ok = issued.get(cid, {BALANCE})
        # A cent of slack: the agent may round $266.68 to $266.67 when reading aloud.
        unissued = [a for a in spoken_amounts(transcript)
                    if not any(abs(a - v) <= 0.011 for v in ok)]
        if unissued:
            bad += 1
            print(f"FAIL {cid}: agent spoke {unissued}, validator issued {sorted(ok)}")
        else:
            print(f"ok   {cid}: every figure traced to a tool response")
    print(f"\n{len(transcripts)} calls, {bad} with an unissued figure")
    return 1 if bad else 0


if __name__ == "__main__":
    log = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "agreements.jsonl"
    if not log.exists():
        sys.exit(f"no log at {log}")
    sys.exit(audit(log))
