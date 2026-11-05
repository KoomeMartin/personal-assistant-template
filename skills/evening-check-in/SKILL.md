---
name: evening-check-in
description: Evening check-in on the day's progress. Use for the evening automation, or when the user wants to review their day or says what they got done.
---
# Evening check-in

1. Read today's digest in `digests/daily/` and `todos.md`.
2. Send a `notify` push: title "Evening check-in", message "Did you finish: <top 3, shortened>? Reply in the assistant."
3. In the conversation, ask the person what they finished, one question at a time if they answer briefly. Be encouraging and honest; don't lecture.
4. Update `todos.md` from their answers (tick done items, move unfinished ones to tomorrow or ask for a new date).
5. Append a short "Check-in" section to today's digest: done, carried over, one sentence on how the day went in their words.
6. If something has been carried over 3 days in a row, point it out and ask whether to break it into smaller steps, change the deadline, or drop it.
