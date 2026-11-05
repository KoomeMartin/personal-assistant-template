---
name: morning-digest
description: Write the daily morning digest and send a short push notification. Use for the daily morning automation or when asked for today's digest, briefing or plan.
---
# Morning digest

1. Read `me/preferences.md`, `todos.md`, `calendar.md`, `me/goals.md`, and yesterday's digest in `digests/daily/` if there is one.
2. Write `digests/daily/YYYY-MM-DD.md`:
   - **Today's top 3** — with one-line reasons (deadlines first, then goals).
   - **Today's schedule** — from `calendar.md`.
   - **Coming up (next 7 days)** — deadlines and events.
   - **Overdue** — anything past due, stated plainly.
   - **Carry-over** — what yesterday's check-in said is unfinished.
   - **One goal nudge** — one small action toward a goal in `me/goals.md`.
3. Use the `notify` skill to send: title "Good morning — your top 3", message = the three items in under 160 characters. No private details.
4. Reply with the digest's path and the top 3.
