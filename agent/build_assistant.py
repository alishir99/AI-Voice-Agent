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
HOST = os.getenv("PUBLIC_HOST", "https://PUBLIC-HOST-NOT-SET").rstrip("/")

# Pick for tool-calling reliability, not intelligence: a model that speaks a figure
# instead of calling evaluate_offer bypasses the design. `python -m agent.audit` catches it.
MODEL = {"provider": "openai", "model": "gpt-5.6-terra"}
# MODEL = {"provider": "openai", "model": "gpt-4.1", "temperature": 0.3}
# MODEL = {"provider": "google", "model": "gemini-3.5-flash", "temperature": 0.3}

# Call behaviour, round-tripped by pull_assistant. silenceTimeoutSeconds runs from the
# start of the call, and the disclosure alone takes ~10s, so it must clear that plus 3 checks.
CALL = {
  "firstMessageMode": "assistant-speaks-first",
  "startSpeakingPlan": {"waitSeconds": 0.4,
                        "smartEndpointingPlan": {"provider": "livekit",
                                                 "waitFunction": "200 + 4000 * x"}},
  "stopSpeakingPlan": {"numWords": 2, "voiceSeconds": 0.2, "backoffSeconds": 1.0},
  # One hook per check: triggerMaxCount needs a fresh speech-then-silence cycle to
  # re-fire, so a caller who never speaks gets exactly one. Separate timeouts do not.
  "hooks": [
    {"on": "customer.speech.timeout", "name": "idle_1",
     "options": {"timeoutSeconds": 5, "triggerMaxCount": 3, "triggerResetMode": "onUserSpeech"},
     "do": [{"type": "say", "exact": ["Hello? Can you hear me?"]}]},
    {"on": "customer.speech.timeout", "name": "idle_2",
     "options": {"timeoutSeconds": 10, "triggerMaxCount": 3, "triggerResetMode": "onUserSpeech"},
     "do": [{"type": "say", "exact": ["Are you still there?"]}]},
    {"on": "customer.speech.timeout", "name": "idle_3",
     "options": {"timeoutSeconds": 15, "triggerMaxCount": 3, "triggerResetMode": "onUserSpeech"},
     "do": [{"type": "say", "exact": ["I can't hear anything. I'll let you go for now."]}]},
  ],
  "endCallFunctionEnabled": True,
  # Vapi hangs up the moment the assistant speaks this. Every line that ends a call
  # carries it, and nothing else does, so the hangup needs no extra model turn.
  "endCallPhrases": ["Goodbye", "goodbye"],
  "silenceTimeoutSeconds": 22,
  "maxDurationSeconds": 420,
  "backgroundSound": "office",
}

VOICE = {"provider": "vapi", "voiceId": "Elliot", "version": "2"}
TRANSCRIBER = {"provider": "soniox", "model": "stt-rt-v5", "language": "en", "languages": ["en"]}


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
    # Built-in. Without it in the array the model has no way to hang up, and
    # endCallFunctionEnabled alone leaves it saying goodbye to an open line.
    {"type": "endCall"},
]


def build():
    return {
        "name": "Corafone - Alex",
        # Here rather than in the prompt, so it is verbatim on every call.
        "firstMessage": (
            "Hi, this is Alex with Corafone. This is an attempt to collect a debt, "
            "and any information obtained will be used for that purpose. Am I speaking with the account holder?"
        ),
        "model": {
            **MODEL,
            "messages": [{"role": "system", "content": (HERE / "prompt.md").read_text(encoding="utf-8")}],
            "tools": TOOLS,
        },
        "voice": VOICE,
        "transcriber": TRANSCRIBER,
        "server": {"url": f"{HOST}/vapi/events"},
        "serverMessages": ["end-of-call-report"],
        **CALL,
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
