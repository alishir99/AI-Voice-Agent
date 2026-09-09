"""Pull the live provider stack from Vapi back into build_assistant.py.

    python -m agent.pull_assistant           # show what differs
    python -m agent.pull_assistant --write   # write it into build_assistant.py
    python -m agent.pull_assistant --show    # print what is live right now

The Composer is fine for trying providers out; it is the wrong place to keep them,
because publishing drops the x-vapi-secret headers and the next deploy_assistant
reverts the change anyway. So: experiment in the dashboard, pull, then deploy.

Only MODEL, VOICE and TRANSCRIBER come back. The prompt and the tool definitions stay
one-way - they are the reviewed artifact, and editing them in a web form is how the
deployed prompt and the one in git drift apart.
"""
import json
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
SRC = HERE / "build_assistant.py"
FIELDS = {"MODEL": "model", "VOICE": "voice", "TRANSCRIBER": "transcriber"}


def load_env():
    env = {}
    for line in (HERE.parent / ".env").read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        env[k.strip()] = v.split(" #")[0].strip()
    return env


def fetch(env):
    req = urllib.request.Request(
        f"https://api.vapi.ai/assistant/{env['VAPI_ASSISTANT_ID']}",
        headers={"Authorization": f"Bearer {env['VAPI_API_KEY']}",
                 "User-Agent": "curl/8.5.0"})          # Cloudflare 1010s the urllib agent
    try:
        return json.load(urllib.request.urlopen(req))
    except urllib.error.HTTPError as e:
        raise SystemExit(f"vapi {e.code}: {e.read().decode()[:400]}")


def show(live, env):
    """What is actually answering calls right now. Printed after a sync so a wrong
    model is visible immediately rather than on the next call."""
    m = live.get("model") or {}
    v = live.get("voice") or {}
    t = live.get("transcriber") or {}
    extra = m.get("reasoningEffort") or m.get("temperature")
    hdr = (live.get("server") or {}).get("headers") or {}
    tools = live.get("model", {}).get("tools") or []
    url = (live.get("server") or {}).get("url", "?")

    print("\nlive at Vapi:")
    print(f"  model        {m.get('provider','?')} / {m.get('model','?')}"
          + (f"  ({extra})" if extra else ""))
    print(f"  voice        {v.get('provider','?')} / {v.get('voiceId','?')}")
    print(f"  transcriber  {t.get('provider','?')} / {t.get('model','?')}")
    print(f"  tools        {len(tools)}: {', '.join(x['function']['name'] for x in tools) or 'NONE'}")
    print(f"  webhook      {url}")
    if env.get("VAPI_SECRET"):
        print(f"  secret       {'set' if hdr.get('x-vapi-secret') else 'MISSING - webhooks are being rejected'}")


def main():
    env = load_env()
    if not env.get("VAPI_ASSISTANT_ID") or not env.get("VAPI_API_KEY"):
        raise SystemExit("VAPI_ASSISTANT_ID and VAPI_API_KEY must be set in .env")

    live = fetch(env)
    if "--show" in sys.argv:
        show(live, env)
        return
    src = SRC.read_text(encoding="utf-8")
    changed = []

    for name, key in FIELDS.items():
        block = live.get(key) or {}
        if name == "MODEL":                                   # drop what we own locally
            block = {k: v for k, v in block.items() if k not in ("messages", "tools")}
        new = f"{name} = {json.dumps(block)}"
        old = re.search(rf"^{name} = .*$", src, re.M)
        if not old:
            raise SystemExit(f"no {name} = line in build_assistant.py")
        if old.group(0) != new:
            changed.append((old.group(0), new))
            src = src[:old.start()] + new + src[old.end():]

    if not changed:
        print("build_assistant.py already matches the live assistant")
        return

    for old, new in changed:
        print(f"- {old}\n+ {new}")

    # A published assistant that lost its headers rejects every webhook, silently.
    if not (live.get("server") or {}).get("headers") and env.get("VAPI_SECRET"):
        print("\nwarning: the live assistant has no x-vapi-secret header, so webhooks are\n"
              "being rejected right now. python -m agent.deploy_assistant restores it.")

    if "--write" not in sys.argv:
        print("\nrun again with --write to apply, then: python -m agent.deploy_assistant")
        return

    SRC.write_text(src, encoding="utf-8")
    print(f"\nwrote {SRC.relative_to(HERE.parent)} - now run:")
    print("  python -m agent.build_assistant && python -m agent.deploy_assistant")


if __name__ == "__main__":
    main()
