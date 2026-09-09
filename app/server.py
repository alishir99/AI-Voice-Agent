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
        # Vapi sends either {"name", "arguments"} or the OpenAI-shaped
        # {"function": {"name", "arguments"}}. Reading only the flat one leaves the
        # name empty, and every tool call becomes "unknown tool" mid-conversation.
        fn = tc.get("function") or {}
        name = fn.get("name") or tc.get("name") or ""
        args = fn.get("arguments") if fn.get("arguments") is not None else tc.get("arguments")
        args = args or {}
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except ValueError:
                args = {}
        try:
            out = handle(name, args, state)
        except Exception as e:                                   # dead air is worse than a bad answer
            out = {"error": "validator unavailable", "detail": str(e)}
        write("tool", call=call_id, tool=name, args=args, out=out)
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


@app.get("/calls", response_class=HTMLResponse)
def calls(k: str = ""):
    """Read-only call review. Gated on VAPI_SECRET because transcripts are
    conversation content; 404 rather than 401 so the route is not advertised."""
    if not SECRET or k != SECRET:
        return HTMLResponse("Not Found", status_code=404)

    grouped: dict[str, dict] = {}
    if LOG.exists():
        for line in LOG.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                r = json.loads(line)
            except ValueError:                      # a half-written line, skip it
                continue
            c = grouped.setdefault(r.get("call", "?"),
                                   {"call": r.get("call", "?"), "ts": r.get("ts", 0), "tools": []})
            c["ts"] = min(c["ts"] or r.get("ts", 0), r.get("ts", 0))
            if r.get("kind") == "tool":
                c["tools"].append({"ts": r.get("ts"), "tool": r.get("tool"),
                                   "args": r.get("args"), "out": r.get("out")})
            else:
                c["end"] = r.get("ts")
                for f in ("outcome", "rung", "compliance_flags", "recording", "transcript"):
                    c[f] = r.get(f)

    data = json.dumps(sorted(grouped.values(), key=lambda c: -(c["ts"] or 0)))
    page = (HERE / "web" / "calls.html").read_text(encoding="utf-8")
    # A transcript could contain "</script>" and end the block early.
    return page.replace("__DATA__", data.replace("</", r"<\/"))


@app.get("/", response_class=HTMLResponse)
def home():
    """Keys live in the environment, not in the file, so nothing secret-shaped is
    ever committed. Read per request so editing the page needs no restart."""
    page = (HERE / "web" / "index.html").read_text(encoding="utf-8")
    for name in ("VAPI_PUBLIC_KEY", "VAPI_ASSISTANT_ID"):
        page = page.replace(f"__{name}__", os.getenv(name, ""))
    return page
