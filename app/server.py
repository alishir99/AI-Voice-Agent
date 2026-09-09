"""Vapi webhook + the page the web link points at. One process, one deploy.

  POST /vapi/tool    custom-tool calls  (evaluate_offer | book_agreement | log_cease)
  POST /vapi/events  end-of-call report -> compliance sweep -> agreements.jsonl
  GET  /             the talk-to-it page
"""
import json, os, re, time
from pathlib import Path
from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse

from . import policy

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

app = FastAPI()
HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
LOG = ROOT / "agreements.jsonl"
SECRET = os.getenv("VAPI_SECRET")            # optional shared secret on the webhook

# ponytail: in-process, dies on redeploy. One always-on instance for a 7-day window
# is the whole requirement; swap for Redis if you ever run more than one replica.
CALLS: dict[str, dict] = {}

# Claims we must never make. Post-call sweep flags them; the prompt forbids them.
BANNED = re.compile(
    r"\b(arrest|jail|prison|garnish\w*|sue you|lawsuit|take you to court|warrant|"
    r"criminal|police|seize|repossess|credit (?:report|score|bureau)|"
    r"expires? (?:today|in \d+ minutes?)|last chance|final warning)\b", re.I)


def write(kind, **row):
    with LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps({"ts": time.time(), "kind": kind, **row}) + "\n")


def handle(name, args, state):
    if name == "evaluate_offer":
        return policy.evaluate(state, args)
    if name == "book_agreement":
        r = policy.book(state, args)
        if r["ok"]:
            state["booked"] = r
        return r
    if name == "log_cease":
        state["cease"] = args.get("reason", "unspecified")
        return {"ok": True, "say": "Understood. I've noted that and I'll end the call here."}
    return {"error": f"unknown tool {name}"}


@app.post("/vapi/tool")
async def tool(req: Request):
    body = await req.json()
    msg = body.get("message", {})
    if SECRET and req.headers.get("x-vapi-secret") != SECRET:
        return JSONResponse({"results": []})                    # always 200 for Vapi
    call_id = (msg.get("call") or {}).get("id", "web")
    state = CALLS.setdefault(call_id, {})
    results = []
    for tc in msg.get("toolCallList", []):
        args = tc.get("arguments") or {}
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except ValueError:
                args = {}
        try:
            out = handle(tc.get("name", ""), args, state)
        except Exception as e:                                   # dead air is worse than a bad answer
            out = {"error": "validator unavailable", "detail": str(e)}
        write("tool", call=call_id, tool=tc.get("name"), args=args, out=out)
        results.append({"toolCallId": tc.get("id"), "result": json.dumps(out)})
    return {"results": results}


@app.post("/vapi/events")
async def events(req: Request):
    if SECRET and req.headers.get("x-vapi-secret") != SECRET:
        return JSONResponse({"ok": True})                        # always 200 for Vapi
    msg = (await req.json()).get("message", {})
    if msg.get("type") != "end-of-call-report":
        return {"ok": True}
    call_id = (msg.get("call") or {}).get("id", "web")
    state = CALLS.pop(call_id, {})
    transcript = msg.get("transcript") or ""
    flags = sorted({m.group(0).lower() for m in BANNED.finditer(transcript)})
    write("call", call=call_id, outcome=state.get("booked") or state.get("cease") or "no_agreement",
          rung=state.get("rung", 0), compliance_flags=flags,
          recording=msg.get("recordingUrl"), transcript=transcript)
    return {"ok": True}


@app.get("/health")
def health():
    return {"ok": True, "open_calls": len(CALLS)}


@app.get("/", response_class=HTMLResponse)
def home():
    """Keys live in the environment, not in the file, so nothing secret-shaped is
    ever committed. Read per request so editing the page needs no restart."""
    page = (HERE / "web" / "index.html").read_text(encoding="utf-8")
    for name in ("VAPI_PUBLIC_KEY", "VAPI_ASSISTANT_ID"):
        page = page.replace(f"__{name}__", os.getenv(name, ""))
    return page
