"""Pull the live provider stack from Vapi back into build_assistant.py.

    python -m agent.pull_assistant [--write [--force] | --show]

MODEL, VOICE, TRANSCRIBER and CALL come back; prompt, tools and webhook URLs stay one-way.
"""
import json
import re
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
SRC = HERE / "build_assistant.py"
FIELDS = {"MODEL": "model", "VOICE": "voice", "TRANSCRIBER": "transcriber"}
# Everything in CALL comes back too, so dashboard tuning is not silently reverted.
CALL_KEYS = ["firstMessageMode", "startSpeakingPlan", "stopSpeakingPlan", "hooks",
             "endCallPhrases",
             "endCallFunctionEnabled", "silenceTimeoutSeconds", "maxDurationSeconds",
             "backgroundSound"]


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
    names = [x.get("function", {}).get("name") or x.get("type", "?") for x in tools]
    print(f"  tools        {len(tools)}: {', '.join(names) or 'NONE'}")
    print(f"  webhook      {url}")
    if env.get("VAPI_SECRET"):
        print(f"  secret       {'set' if hdr.get('x-vapi-secret') else 'MISSING - webhooks are being rejected'}")


def dirty():
    """True if build_assistant.py has uncommitted changes. Outside git, assume clean."""
    try:
        r = subprocess.run(["git", "status", "--porcelain", "--", str(SRC)],
                           cwd=HERE.parent, capture_output=True, text=True, timeout=5)
        return bool(r.stdout.strip())
    except Exception:
        return False


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

    for name, key in {**FIELDS, "CALL": None}.items():
        if name == "CALL":
            block = {k: live[k] for k in CALL_KEYS if k in live}
        else:
            block = live.get(key) or {}
            if name == "MODEL":                               # drop what we own locally
                block = {k: v for k, v in block.items() if k not in ("messages", "tools")}
        # repr, not json.dumps: this is Python source, where true/false/null are NameErrors.
        if name == "CALL":
            body = "".join(f"  {k!r}: {v!r},\n" for k, v in block.items())
            new = "CALL = {\n" + body + "}"
            old = re.search(r"^CALL = \{.*?^\}$", src, re.M | re.S)
        else:
            new = f"{name} = {block!r}"
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

    # Overwriting local edits with the live version silently reverts anything just
    # pulled or hand-edited but not yet deployed.
    if "--force" not in sys.argv and dirty():
        raise SystemExit(
            "\nbuild_assistant.py has uncommitted changes and --write would discard them.\n"
            "  deploy them instead:  ./sync.sh\n"
            "  or overwrite anyway:  python -m agent.pull_assistant --write --force")

    SRC.write_text(src, encoding="utf-8")
    print(f"\nwrote {SRC.relative_to(HERE.parent)} - now run:")
    print("  python -m agent.build_assistant && python -m agent.deploy_assistant")


if __name__ == "__main__":
    main()
