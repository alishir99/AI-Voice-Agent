"""Push the assistant to Vapi. Creates it the first time, PATCHes it after.

    python -m agent.deploy_assistant

Injects x-vapi-secret here rather than into the tracked assistant.json.
"""
import json
import os
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def load_env():
    for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.split(" #")[0].strip())


def main():
    load_env()
    from . import build_assistant          # imported late: HOST is read at import time

    host = build_assistant.HOST
    if "NOT-SET" in host or not host.startswith("https://"):
        raise SystemExit(
            f"PUBLIC_HOST is {host!r}. Vapi needs an https:// webhook URL, so set it in .env:\n"
            "  sed -i 's|^PUBLIC_HOST=.*|PUBLIC_HOST=https://your-host|' .env")

    body = build_assistant.build()
    if secret := os.getenv("VAPI_SECRET"):
        headers = {"x-vapi-secret": secret}
        body["server"]["headers"] = headers
        for t in body["model"]["tools"]:
            if "server" in t:                       # built-ins like endCall have none
                t["server"]["headers"] = headers

    aid = os.getenv("VAPI_ASSISTANT_ID")
    req = urllib.request.Request(
        f"https://api.vapi.ai/assistant/{aid}" if aid else "https://api.vapi.ai/assistant",
        data=json.dumps(body).encode(),
        method="PATCH" if aid else "POST",
        # Cloudflare fronts api.vapi.ai and 1010s the default Python-urllib UA.
        headers={"Authorization": f"Bearer {os.environ['VAPI_API_KEY']}",
                 "Content-Type": "application/json",
                 "User-Agent": "curl/8.5.0"},
    )
    try:
        out = json.load(urllib.request.urlopen(req))
    except urllib.error.HTTPError as e:
        raise SystemExit(f"vapi {e.code}: {e.read().decode()[:600]}")

    print(f"{'updated' if aid else 'created'} assistant {out['id']}  ->  {build_assistant.HOST}")
    if not aid:
        print(f"\nadd to .env:\n  VAPI_ASSISTANT_ID={out['id']}")


if __name__ == "__main__":
    main()
