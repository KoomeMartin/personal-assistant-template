---
name: capture
description: Save a quick fact, idea, person or reminder the user tells you in conversation. Use when they say "remember that...", "note that...", "I have an idea...", or "add ... to my notes".
---
# Capture

1. Read `schema.md`. Decide which type the statement is (idea, person, task, event, opportunity…). If it contains several facts, handle each one.
2. Find the existing note for the subject (file names + Aliases). Update it, or create it from the schema.
3. Link it: every captured note links to at least one existing note. For an idea, add `inspired_by::` (what sparked it) and `related::` (projects or ideas it connects to) — suggest the links and ask if you're unsure.
4. Tasks and events also go into `todos.md` / `calendar.md`.
5. If vector search tools are available, add or update the note in the `vault` collection.
6. Log it in `logs/actions.md`. Reply in one or two lines: what you saved, where, and what it's linked to.
