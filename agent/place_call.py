"""Place an outbound call, so the agent rings you rather than the other way round.

    python -m agent.place_call +46701234567

Reads VAPI_API_KEY, VAPI_PHONE_NUMBER_ID and VAPI_ASSISTANT_ID from .env.

Free Vapi numbers cannot do this: they are US inbound only. Import a Twilio number
and enable the destination country under Voice > Settings > Geo permissions.
"""
import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

API = "https://api.vapi.ai/call"


def main(argv):
    if len(argv) != 1:
        sys.exit(__doc__)
    to = argv[0].replace(" ", "")
    # E.164: the single most common reason a call silently never arrives.
    if not re.fullmatch(r"\+[1-9]\d{7,14}", to):
        sys.exit(f"{to!r} is not E.164. Use the full international form, e.g. +46701234567")

    env = {k: os.getenv(k) for k in ("VAPI_API_KEY", "VAPI_PHONE_NUMBER_ID", "VAPI_ASSISTANT_ID")}
    missing = [k for k, v in env.items() if not v]
    if missing:
        sys.exit("missing environment variables: " + ", ".join(missing))

    req = urllib.request.Request(
        API,
        data=json.dumps({
            "assistantId": env["VAPI_ASSISTANT_ID"],
            "phoneNumberId": env["VAPI_PHONE_NUMBER_ID"],
            "customer": {"number": to},
        }).encode(),
        headers={"Authorization": f"Bearer {env['VAPI_API_KEY']}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            call = json.load(r)
    except urllib.error.HTTPError as e:
        sys.exit(f"Vapi returned {e.code}: {e.read().decode()[:500]}")

    print(f"calling {to}\ncall id: {call.get('id')}\nstatus:  {call.get('status')}")


if __name__ == "__main__":
    main(sys.argv[1:])
