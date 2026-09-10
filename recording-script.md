# 5-minute recording script

The brief: *demonstrate the agent, explain your three most important decisions, and what you
tested.* They will test it themselves, so the demo is proof of life - spend the time on the
decisions.

**Before you hit record**

- Two windows: the call page on the left, the `?k=` review tab on the right, README open.
- Make one throwaway call first so the review tab has rows, then reload it.
- Headphones. Otherwise the agent hears itself.
- Say "Corafone" out loud once, to check the voice says it right.

---

## 0:00 - 0:25 · What it is

> "This is a collections agent for a $1,000 account that's 180 days past due. The thing worth
> looking at isn't the voice - it's that **every dollar figure it speaks comes from a policy
> service outside the model.** The agent can't invent a discount, and it can't log a deal the
> validator didn't approve. I'll show that, then explain the three decisions behind it."

## 0:25 - 1:40 · The demo

Call it. Be the uncooperative consumer - this is the shape they'll test.

1. **"Yeah, what do you want?"**
2. **"I'm not paying a thousand dollars. I can do four hundred."** → counters $600 + $400
3. **"I said four hundred."** → settles at $900, three payments
4. **"Four hundred. That's it."** → $800, the floor

> "Four hundred, three times, and it moved one rung each time. It never jumped to the maximum
> discount, because the ladder is server-side and descends one step per counter. Pressure
> doesn't move it - the model has no mechanism to skip ahead."

Switch to the **Review** tab, expand that call.

> "Here's the same call from the server's side. Left column is what the model asked for. Right
> column is what the validator returned - the verdict, the exact schedule, and the sentence it
> was allowed to say. Every figure you just heard is on the right-hand side. None of it
> originated in the model."

## 1:40 - 3:30 · The three decisions

**1 · The validator owns the ladder *and* the call state** (~40s)

> "The obvious design gives the model a tool that says valid or invalid, and lets the prompt
> handle strategy. That fails against pressure - push hard enough and the model finds the
> discount itself. So the server holds a rung index per call. It descends at most one rung per
> counter and never climbs back. Twenty percent off only exists at rung three of a list the
> model can't see, so there's no mechanism to jump to it."

**2 · Two gates, not one** (~35s)

Have `app/policy.py` open at `book`.

> "`evaluate_offer` approves terms on the way out. `book_agreement` re-checks them on the way
> back in - against policy, and against what the validator actually issued on that call. So a
> hallucinated '$400 and we're even' can be spoken once, but it can never be booked.
> `policy.legal()` is the single choke point both directions."

**3 · Compliance is code and a locked script, not persuasion tuning** (~35s)

> "The mini-Miranda is Vapi's `firstMessage`, so it's spoken verbatim on every call and the
> model can't paraphrase it away. Threats, court, garnishment, credit-report claims and
> invented deadlines are enumerated as forbidden sentences. Cease, dispute or attorney routes
> to a tool that ends the call *before* any close attempt. And the end-of-call webhook sweeps
> the transcript for banned language and flags the record.
>
> None of this trades compliance against conversion, because the ladder already caps how much
> pressure the agent is able to apply."

## 3:30 - 4:20 · What I tested

> "Three layers.
>
> **Properties, not examples.** The policy tests run the whole offer space: every tier is legal
> at every cadence, nothing ever totals under $800, no payment under 25%, the rung sequence is
> monotone and steps by at most one, and cents always sum exactly.
>
> **Real payload shapes.** The server tests use actual Vapi payloads - a hostile lowballer
> walked up the ladder to a close, an invented discount refused at booking, and empty, negative
> and non-numeric arguments that must never 500 and never leak a figure below the floor.
>
> **And the loop closed after the fact.** `agent/audit.py` re-reads the log, pulls every dollar
> figure out of the agent's own turns, and fails if any of them wasn't issued by the validator
> on that call. That's the central claim of the project, checked mechanically rather than
> trusted."

Run it on screen if you have a clean log:

```bash
python -m agent.audit
```

## 4:20 - 4:50 · What I'd change

Pick two. Naming real limits reads better than claiming there aren't any.

> "Call state is in-process, so it assumes one instance - Redis is the swap if it ever needs
> two. The compliance sweep is a regex, so it catches banned phrasing but not banned meaning;
> an LLM judge over the transcript is the upgrade. And there's one open question in the ladder:
> if you offer the floor as a lump sum on the first turn, it accepts, because $800 in hand
> genuinely beats $800 over sixty days - but it never tests whether you'd have paid $900. I
> documented that rather than quietly changing it."

## 4:50 - 5:00 · Close

> "Repo has the prompt, the tool definitions, the validator and the tests. The link is live and
> the review page is in the README. Thanks for your time - try to break it."

---

## Don't

- Don't read the ladder table aloud. Show it, say "preference order, not dollar order".
- Don't demo booking end to end unless you've rehearsed it - it needs a clean yes.
- Don't apologise for the tunnel URL or the missing phone number. State the choice, move on.
- Don't run over. They said max five minutes and they'll be testing it themselves anyway.
