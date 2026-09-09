"""Build agent/assistant.json from prompt.md plus the tool definitions below.

assistant.json is generated: edit prompt.md or this file, never the JSON, or the
deployed prompt and the reviewed one drift apart.

    python -m agent.build_assistant            # write
    python -m agent.build_assistant --check    # fail if the JSON is stale (CI)
"""
import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE / "assistant.json"

# Where Vapi sends tool calls. Quick-tunnel URLs rotate on restart, so keep it in .env.
HOST = os.getenv("PUBLIC_HOST", "https://YOUR-APP.fly.dev").rstrip("/")

# --- Providers ---------------------------------------------------------------
# Add your own key for any of these under Vapi dashboard > Integrations. Once it
# validates Vapi stops billing you for that provider and the provider bills you
# directly, which is usually cheaper and can be free.
#
# The model here barely reasons: it extracts an offer and reads back the string
# the validator returned. So pick for TOOL-CALLING RELIABILITY, not intelligence.
# A model that occasionally answers with a figure instead of calling
# evaluate_offer bypasses the entire external-validation design.
#
# After changing MODEL: rebuild, PATCH the assistant, make a few calls, then run
#   python -m agent.audit
# which fails if the agent ever spoke a number the validator did not issue.
# Google closed the 2.5 family to new API keys, so anything 2.5 returns 404 on a
# fresh account no matter what the docs say. 3.5 Flash is the current default.
# Flash-Lite is faster but weakest at tool calling, the one thing that must not fail.
MODEL = {"provider": "google", "model": "gemini-3.5-flash", "temperature": 0.3}
# MODEL = {"provider": "google", "model": "gemini-3.1-flash-lite", "temperature": 0.3}
# Fallback with the strongest tool-calling record, billed through Vapi:
# MODEL = {"provider": "openai", "model": "gpt-4.1", "temperature": 0.3}

VOICE = {"provider": "cartesia", "voiceId": "a0e99841-438c-4a64-b679-ae501e7d6091"}
TRANSCRIBER = {"provider": "deepgram", "model": "nova-3", "language": "en", "endpointing": 180}


def tool(name, description, properties, required, filler):
    """A Vapi custom tool. `filler` is spoken while the webhook runs, which buys
    back the round trip the tool call costs."""
    return {
        "type": "function",
        "messages": [{"type": "request-start", "content": filler}],
        "function": {
            "name": name,
            "description": description,
            "parameters": {"type": "object", "properties": properties, "required": required},
        },
        "server": {"url": f"{HOST}/vapi/tool", "timeoutSeconds": 10},
    }


TOOLS = [
    tool(
        "evaluate_offer",
        "Validate what the consumer just offered and get the approved counter-offer. Call this "
        "every time they name an amount, a timeframe, or a payment frequency. You have no "
        "authority to set terms yourself.",
        {
            "amount_per_payment": {"type": "number", "description": "Dollars per instalment they named."},
            "num_payments": {"type": "integer", "description": "How many instalments, if they said. Omit if open-ended."},
            "cadence": {"type": "string", "enum": ["once", "weekly", "biweekly", "monthly"]},
            "down_payment": {"type": "number", "description": "Dollars they can pay today, if any."},
        },
        ["amount_per_payment"],
        "Let me see what I'm able to approve.",
    ),
    tool(
        "book_agreement",
        "Log the final agreement. Call only after evaluate_offer returned verdict 'accept' and the "
        "consumer said yes. Pass back exactly the terms that were returned.",
        {
            "total": {"type": "number"},
            "schedule": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "day": {"type": "integer", "description": "Days from today."},
                        "amount": {"type": "number"},
                    },
                    "required": ["day", "amount"],
                },
            },
        },
        ["total", "schedule"],
        "Locking that in now.",
    ),
    tool(
        "log_cease",
        "Record a cease-communication request, a dispute, a wrong-party claim, or attorney "
        "representation. Call immediately and stop collecting.",
        {"reason": {"type": "string", "enum": ["cease_communication", "dispute", "not_my_debt",
                                               "attorney_represented", "other"]}},
        ["reason"],
        "Of course.",
    ),
]


def build():
    return {
        "name": "Corafone - Alex",
        # The mini-Miranda lives here, not in the prompt, so it is spoken verbatim
        # on every call and the model cannot paraphrase it away.
        "firstMessage": (
            "Hi, this is Alex with Corafone. This is an attempt to collect a debt, "
            "and any information obtained will be used for that purpose. Am I speaking with the account holder?"
        ),
        "firstMessageMode": "assistant-speaks-first",
        "model": {
            **MODEL,
            "messages": [{"role": "system", "content": (HERE / "prompt.md").read_text(encoding="utf-8")}],
            "tools": TOOLS,
        },
        "voice": VOICE,
        "transcriber": TRANSCRIBER,
        "startSpeakingPlan": {
            "waitSeconds": 0.3,
            "smartEndpointingPlan": {"provider": "livekit",
                                     "waitFunction": "700 / (1 + exp(-10 * (x - 0.5)))"},
        },
        "stopSpeakingPlan": {"numWords": 2, "voiceSeconds": 0.2, "backoffSeconds": 1.0},
        "server": {"url": f"{HOST}/vapi/events"},
        "serverMessages": ["end-of-call-report"],
        "endCallFunctionEnabled": True,
        "silenceTimeoutSeconds": 20,
        "maxDurationSeconds": 420,
        "backgroundSound": "office",
    }


if __name__ == "__main__":
    fresh = json.dumps(build(), indent=2) + "\n"
    if "--check" in sys.argv:
        stale = not OUT.exists() or OUT.read_text(encoding="utf-8") != fresh
        print("assistant.json is stale, run: python -m agent.build_assistant" if stale
              else "assistant.json is up to date")
        sys.exit(1 if stale else 0)
    OUT.write_text(fresh, encoding="utf-8")
    print(f"wrote {OUT.relative_to(HERE.parent)}")
