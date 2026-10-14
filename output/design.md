# Dashboard design

Design notes for the Campus Customs operations desk — `frontend/`, built with
React, Vite and TypeScript, talking to the FastAPI backend at
`http://localhost:8000`.

---

## The idea: a desk, not a log viewer

The thing being built is not a debugging tool for an AI pipeline. It is the
place a shop manager sits while five agents work the board on their behalf, and
the one place where they are asked to spend real money. That framing drove every
choice below. The question I kept asking was: *if this person looked away for
thirty seconds, what would they need to see the instant they looked back?*

Three things, which is why there are three columns.

---

## Layout: a three-column workspace

```
┌──────────────────────────────────────────────────────────────────────┐
│  brand   ·   shop date  ·  tickets closed  ·  checking  ·  backend   │
├──────────────┬─────────────────────────────────┬─────────────────────┤
│  THE BOARD   │        AGENT FLOOR              │     YOUR DESK       │
│              │                                 │                     │
│  ticket 101  │   live feed of what every       │   checking balance  │
│  ticket 102  │   agent says and every tool     │   approval queue    │
│  ticket 103  │   it calls, in order            │   what the team did │
│              │                                 │                     │
│  [hand to    │                                 │   [approve] [deny]  │
│   the team]  │                                 │                     │
└──────────────┴─────────────────────────────────┴─────────────────────┘
```

The columns are ordered the way the work actually flows: **what needs doing →
what is being done → what needs me**. Left is the backlog, centre is the
machine, right is the human. Nothing the operator must act on ever appears in
the middle column, so the right edge is the only place they have to watch.

The columns scroll independently and only the feed auto-scrolls. The board and
the approval queue stay put, because an approval card sliding away while
somebody is reading it is how mistakes with money happen.

The header is a status strip, not navigation. There is only one screen, so
chrome spent on navigation would be wasted; instead that space carries the four
numbers that matter — the shop's date (2026-08-31, deliberately shown because
the whole shop runs on *its* clock, not today's), tickets closed, the checking
balance, and whether the backend and its model are actually reachable.

---

## Telling the agents apart

Five agents talking in one feed is the core legibility problem. Text alone does
not solve it — by the fourth handoff nobody is reading names.

So **each agent owns a colour**, and that colour is used everywhere that agent
appears: its avatar tile, its name in the feed, its chip in the roster, and its
card in the recap.

| Agent | Colour | |
| --- | --- | --- |
| Boss | pink `#ff2d78` | the brand colour, because the Boss is the shop's voice |
| Inventory | amber `#ffb648` | warehouse / caution |
| Accounting | mint `#3ddc97` | money, and it matches the Approve button |
| Facilities | violet `#9d7cff` | distinct from everything commercial |
| Customer Service | cyan `#4cc9f0` | the "outward-facing" cool tone |
| You | white | the human is not one of the agents and should not look like one |

Each agent gets a two-letter avatar tile (`BO`, `IN`, `AC`, `FA`, `CS`) rather
than an icon, because abstract icons for "accounting" versus "facilities" are
guessable at best. Initials are instantly unambiguous and they tile cleanly at
21px.

A vertical rail connects the avatars down the feed, so a run reads as one
continuous conversation rather than a stack of disconnected rows.

### Speech versus action

An agent does two different kinds of thing, and conflating them makes the feed
unreadable. They are rendered differently on purpose:

- **What an agent says** — plain prose at full contrast. This is the agent's
  actual reported summary.
- **What an agent does** — a monospace pill on a black background,
  `find_restock_options sku=CC-TEE-WHITE size=S qty=1`. Tool calls are machine
  actions and are styled like machine actions. Arguments are truncated to one
  line so a call never swamps the sentence next to it.
- **A handoff** — a pink chip, `→ asks Inventory`, with the target agent's name
  in *that agent's* colour, followed by the actual task in muted text.
  Delegations are the most interesting moment in a multi-agent run, so they are
  the only inline element that gets the brand colour.
- **A depth marker** — `depth 1`, `depth 2`. Small, monospace, easy to ignore
  until you want it. It makes the delegation tree visible in a flat list.

Four event types get coloured banner treatment because they change what the
operator should do: `⏸ Waiting on you` in pink, decisions and completed
approvals in green, and errors and refused delegations in red.

Tool *results* are logged but **not** rendered. They are large JSON blobs that
would bury the conversation; the agent's own summary of what it found is the
useful version, and the raw result stays in `output/audit_trail.json` for
auditing.

A three-dot typing indicator sits on the newest event while a run is live, so
the feed never looks frozen during the long gaps while a model is thinking.

---

## Tickets and how "resolved" reads

Ticket cards carry a status badge in a colour that matches its meaning: amber
`open`, pink `in progress`, red `blocked`, green `resolved`. The badge sits at
the top-right where the eye lands last on a card, so scanning the column is a
single vertical sweep down the right edge.

A resolved ticket is **not** hidden or collapsed. It dims slightly and picks up
a faint green wash across the card, so finished work recedes without
disappearing — the operator can still see at a glance what the team concluded
and why. The resolution text the Boss wrote is pinned to the bottom of the card,
under a divider.

**Status updates on its own.** When a run finishes, the dashboard refetches the
board and the card re-renders with whatever the agents actually decided. There
is no client-side guessing: the badge reflects the `tickets` table.

One deliberate decision here: the dashboard shows the *real* status rather than
forcing every completed run to "resolved". When the team worked ticket 101 it
ended **blocked**, correctly — the tee cannot ship until a human approves the
$840 invoice that has the vendor on hold. A dashboard that painted that green
would be lying to its operator about whether a customer is getting their order.
Honest state is worth more than a tidy board.

The run button only appears on the selected card, which keeps the column calm,
and it reports what it is doing — "Hand to the agent team", "Agents working…",
"Another run in progress", "Run agents again".

---

## The money

The balance is the single most important number on the screen, so it gets the
only gradient-filled card in the interface, a pink border, and 31px type — far
larger than anything else.

**It visibly falls.** When the balance changes, the figure turns pink for just
over two seconds and a delta line appears underneath: `−$840.00 just now`. The
colour fades; the delta stays until the next change. The point is that money
leaving the shop should feel like an event, not a silently re-rendered number.
The same figure is mirrored in the header, so it is visible even when the right
column is scrolled down.

Underneath, two supporting numbers: what is **awaiting your approval** and what
is genuinely **free**. Cash committed to pending approvals is money the operator
cannot actually spend twice, and showing only the raw balance would invite
exactly that mistake.

### Approval cards

Pending approvals get the brand pink border and an outer glow, which is the
strongest visual treatment anywhere in the app — they are the only thing in the
product that *requires* a human. The amount is set large and right-aligned so a
column of requests can be compared at a glance.

Each card states the kind, the ticket it traces back to, the memo, and which
agent asked, with the agent's name in its own colour. A purchase order also
shows the quantity, SKU, vendor and expected arrival date, because approving a
restock without knowing when it lands is not really a decision.

Approve is solid mint; Deny is a quiet outline that only turns red on hover.
The asymmetry is intentional — the common, safe action should be effortless and
the destructive one should take a half-second more thought. Both disable while a
decision is in flight, so the same payment cannot be double-clicked into
existence.

Once decided, the card keeps its place in the list and switches to a left border
— green for approved, red for denied — with "✓ Approved by Yunsik Jung". The
audit trail stays visible on screen, not just in a file.

### The recap

Below the queue, one card per agent that participated: avatar, name in its
colour, how many tool calls it made, its closing summary, and the deduplicated
list of tools it used. Above them sits the Boss's decision in a green verdict
panel with the reasoning, any approval ids the ticket is waiting on, and the
run's cost in model calls, tool calls and tokens.

Showing token cost on the operator's screen is a deliberate choice. Multi-agent
systems are expensive in a way that is invisible unless you surface it, and a
manager deciding whether to re-run a ticket deserves to know what the last one
cost.

---

## The feel

**Black and pink.** Near-black `#08080b` with a soft pink bloom in the top-left
corner, and `#ff2d78` reserved almost entirely for things that need a human:
pending approvals, handoffs, the run button, the falling balance. Because the
accent is rationed, it actually directs attention instead of decorating.

**Three type registers**, each meaning something: system sans for prose,
tabular-figure numerals for money so digits do not jitter as the balance
changes, and monospace for anything the machine produced — tool names,
arguments, timestamps, SKUs, depth markers. You can tell at a glance whether you
are reading a person's words or a machine's record.

**Restraint on motion.** There is no animation anywhere except the two places it
carries meaning: the typing indicator, so a live run never looks hung, and the
cash flash, so a payment registers. Everything else is a 150ms transition on
hover. A dashboard someone stares at for an hour should be still.

**Honest empty states.** Before a run: *"The desk is quiet — pick a ticket on the
left and hand it to the team."* With no approvals: *"Nothing is waiting on you.
When an agent asks to spend money, it lands here."* These explain the model of
the app rather than apologising for having no data.

**A live backend indicator.** A green or red dot in the header, labelled with
the model actually in use (`gpt-6-luna`). When the MCP server is down the
dashboard says so plainly instead of silently rendering stale numbers — which,
in a tool that spends money, is the difference between a quiet bug and a wrong
decision.

---

## Wiring

The frontend calls `http://localhost:8000` (overridable via `VITE_API_BASE`).
The backend enables CORS for `http://localhost:5173`, the Vite origin.

Live updates use **polling rather than websockets** — every 1.2s while a run is
active, every 4s when idle. `GET /api/activity?after=<cursor>` returns only
events past the cursor, so the feed appends rather than refetching. For a
single-operator desk this is simpler, survives a backend restart without
reconnection logic, and the latency is imperceptible against model calls that
take seconds.

On load the feed shows only the **most recent run**, not the entire append-only
audit trail. The trail deliberately spans every run in the project's history,
which is right for auditing and wrong for a screen that should show what just
happened.

```bash
npm run dev
```
