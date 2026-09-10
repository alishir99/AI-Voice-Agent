# Collections voice agent

Negotiates a $1,000 delinquent account. **Every number it speaks comes from a policy service
outside the model.** The agent cannot invent a discount and cannot log a deal the validator
did not approve.

- **Talk to it:** https://fed-tmp-improvement-defined.trycloudflare.com/
- **Recording:** _<link>_

---

## The three decisions

**1. The validator owns the ladder and the call state.** The obvious design gives the LLM a
"valid / invalid" tool and lets the prompt handle strategy. Enough pressure and the model
finds the discount itself. Here the server holds a per-call rung index, descends at most one
rung per counter, and never climbs back. The agent has no mechanism to jump to 20% off,
because 20% off only exists at rung 3 of a list it cannot see.

**2. Two gates.** `evaluate_offer` approves terms. `book_agreement` re-validates them against
policy *and* against what the validator actually issued on this call — an offer it accepted, or
the counter currently on the table. A hallucinated "$400 and we're even" matches neither, so it
can be spoken once but never booked. `policy.legal()` is the single choke point, outbound and
inbound.

**3. Compliance is code, not persuasion tuning.** The mini-Miranda is Vapi's `firstMessage`,
so it is spoken verbatim and cannot be paraphrased away. Threats, court, garnishment,
credit-report claims and invented deadlines are enumerated as forbidden sentences.
Cease/dispute/attorney routes to a tool that ends the call before any close attempt. The
end-of-call webhook regex-sweeps the transcript and flags the record.

---

## The policy (`app/policy.py`)

| | |
|---|---|
| Balance | $1,000 |
| Settlement floor | $800 (20% max discount) |
| Minimum payment | 25% of the agreed total, so at most 4 payments |
| Settlement | 3 payments max, 60 days max |
| Plan | no discount, 4 payments max, 90 days max, weekly / biweekly / monthly |

**On "25%":** the brief doesn't name a base. Read here as 25% of the agreed total. Every tier
at every cadence also clears 25% of the $1,000 balance, so the ladder is valid under either
reading. The 4 x $250 plan sits exactly on both boundaries.

### The ladder

| Rung | Offer |
|---|---|
| 0 | $1,000 today |
| 1 | $600 today + $400 in 14 days |
| 2 | Settle $900 (10% off), 3 payments |
| 3 | Settle $800 (20% off), 3 payments |
| 4 | Plan $1,000, up to 4 payments of $250, 90 days |

Order is the brief's preference order, not dollar order: an $800 settlement outranks a $1,000
plan. A settled account closes; a plan has three chances to break.

Three rules make it hold:

1. **Ratchet.** One rung per counter, monotone, server-side. Shouting doesn't move it.
2. **Capacity-aware descent.** Skip tiers they demonstrably can't afford, so "$300 a month"
   gets the $900 settlement (3 x $300), not a pointless $1,000 counter. But a lowball *below*
   the floor advances exactly one rung and surrenders no discount. (Was a real bug; the
   regression test stays.)
3. **Lexicographic acceptance.** Accept only if legal **and** `(total, -payments, -horizon)`
   beats our standing counter. Stops a rigid tier-matcher rejecting "$1,000 in two payments"
   for being the wrong shape.

Three sub-floor offers in a row triggers `hardship`: note it, end politely. No loop.

---

## Layout

```
caller --web/phone--> Vapi (Soniox, LLM, Vapi voice, LiveKit turn-taking)
                        |  tool call
                        v
                 FastAPI  +-- app/policy.py       pure, no I/O, stdlib only
                          +-- CALLS               per-call rung, in-process
                          +-- agreements.jsonl
                 GET /    serves app/web/index.html, the web link itself
```

One deploy serves both the page and the webhook. `/` is the call page; add
`?k=<VAPI_SECRET>` and a Call/Review toggle appears - the review tab lists every call, the
offers the agent made, the verdict the validator returned for each, and the transcript - every offer the agent made, the
verdict the validator returned, and the transcript. Without the key that section does not
render at all, because transcripts are conversation content and the URL is public.

```
app/policy.py              the whole negotiation. Pure functions, no deps
app/server.py              Vapi webhooks + serves the page
app/web/index.html         call page + gated call review, Vapi Web SDK
agent/prompt.md            system prompt (source of truth)
agent/build_assistant.py   prompt.md + tool defs -> assistant.json
agent/deploy_assistant.py  push to Vapi: POST first time, PATCH after
agent/pull_assistant.py    pull the live provider stack back into build_assistant.py
agent/audit.py             fails if the agent ever spoke an unissued figure
agent/place_call.py        outbound test call
tests/                     python -m tests.test_policy && python -m tests.test_server
```

`assistant.json` is generated. Otherwise the prompt exists twice and the deployed one drifts
from the reviewed one. `python -m agent.build_assistant --check` fails if they diverge.

---

## Run it

```bash
cp .env.example .env      # fill in keys
docker compose up         # http://localhost:8080
```

Check it without any voice stack:

```bash
python -m tests.test_policy && python -m tests.test_server
curl -s localhost:8080/vapi/tool -H "Content-Type: application/json" -d @tests/sample_tool_call.json
```

That should counter with $900 in three payments.

### Deploy

Vapi calls your webhook, so it needs a public HTTPS URL. Anything works; this runs on a NAS
behind a Cloudflare tunnel, with no ports opened:

```bash
docker compose -f compose.nas.yaml up -d --build
```

Then point the assistant at it:

```bash
echo "PUBLIC_HOST=https://your-url" >> .env
python -m agent.deploy_assistant     # prints the assistant id; put it in .env
```

Re-run `deploy_assistant` after any prompt, tool or model change. It PATCHes once
`VAPI_ASSISTANT_ID` is set. `fly.toml` is included if you'd rather use Fly.

**Providers live in code, not the dashboard.** Publishing from the Vapi Composer drops the
`x-vapi-secret` headers, so the webhooks start silently rejecting, and the next deploy reverts
your change anyway. Try providers out in the dashboard if you like, then bring them back:

```bash
./sync.sh            # code -> Vapi, after editing build_assistant.py or prompt.md
./sync.sh --pull     # Vapi -> code -> Vapi, after publishing from the Composer
```

The prompt and tool definitions are deliberately one-way. They are the reviewed artifact.

### .env

| key | from | secret |
|---|---|---|
| `VAPI_PUBLIC_KEY` | Vapi, API Keys, public | no, ships in the browser |
| `VAPI_ASSISTANT_ID` | `deploy_assistant` output | no |
| `VAPI_API_KEY` | Vapi, API Keys, private | **yes** |
| `VAPI_SECRET` | any random string; sent as `x-vapi-secret` on both webhooks | **yes** |
| `PUBLIC_HOST` | your public URL | no |
| `VAPI_PHONE_NUMBER_ID` | Vapi, Phone Numbers; outbound only | no |

The page substitutes these at request time, so no key is committed.

### Model

`MODEL`, `VOICE` and `TRANSCRIBER` at the top of `agent/build_assistant.py`. Vapi supplies all three
and bills them per minute, so no accounts are needed. Add your own key under Dashboard,
Integrations, and that provider bills you directly instead.

**Pick for tool-calling reliability, not intelligence.** The model barely reasons here: it
extracts an offer and reads back the validator's string. One that answers with a figure
instead of calling `evaluate_offer` bypasses the entire design. `gpt-4.1` has the strongest
record and is one commented line away.

After any model change, redeploy, take a few calls, then:

```bash
python -m agent.audit
```

It pulls every dollar figure from the agent's own turns and checks it against what the
validator issued on that call. Exit 1 if the agent said a number nobody gave it.

```
ok   3f2a...: every figure traced to a tool response
FAIL 9c81...: agent spoke [400.0], validator issued [0.0, 300.0, 900.0, 1000.0]
```

### Phone number

Inbound: assign the assistant to the number in the dashboard, nothing in code. Outbound: put
the number's **ID** in `VAPI_PHONE_NUMBER_ID`, then `python -m agent.place_call +46...`.
Free Vapi numbers are US-inbound only. Import a Twilio number for both directions and enable
the destination country under Twilio, Voice, Geo permissions.

---

## Tested

`tests/test_policy.py` covers properties over the whole offer space, not examples: every tier
is legal at every cadence; nothing totals under $800; no payment under 25%; never more than 4
payments, 3 for a settlement; never past 90 days; rung sequence monotone and stepping by at
most one; any legal offer beating our counter is accepted; cents sum exactly.

`tests/test_server.py` covers real Vapi payload shapes: a hostile lowballer walked up the
ladder to a close; per-call state isolation; an invented discount refused at booking;
arguments arriving as a JSON string; empty, negative, non-numeric and absurd arguments never
500 and never leak a figure below the floor; cease logged; the end-of-call sweep flagging
banned language.

Live adversarial passes: "$50/month for 20 months", "prove it's mine", "stop calling me",
dead silence, talk-over, "$400 and that's it", repeated lowball, hostile/abusive, "call my
lawyer", wrong party, and asking the agent to invent a better offer itself.

---

## Known limits

- Call state is in-process: it dies on redeploy and assumes one replica. Redis is the swap if
  it ever needs two.
- The compliance sweep is a regex, so it catches banned phrasing rather than banned *meaning*.
  An LLM judge over the transcript is the upgrade, marked in the code.
- The call button drives the Vapi Web SDK (pinned to 2.7.0) rather than the drop-in widget,
  which has no inline layout. The cost is that mic-permission, connect-failure and mid-call
  errors are handled in `index.html`. All four paths were exercised in a browser.
- The ladder resets per call, so hanging up and calling back starts at full balance. There is
  no callback scheduling, and any retry logic would have to respect Reg F's 7-in-7 rule.
- No payment instrument is collected. Booking records the agreement, not a transaction.
