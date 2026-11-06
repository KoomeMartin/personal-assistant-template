---
name: ingest
description: Process everything in inbox/ into the knowledge base. Use when asked to process, file, import or ingest the inbox, new files, a chat export, or documents, and for the hourly inbox automation.
---
# Ingest the inbox

1. Read `schema.md` and `me/profile.md`. List every file in `inbox/` except `README.md`. If it is empty, stop and say "Inbox is empty."
2. For each file:
   a. Read it. For a chat export (e.g. WhatsApp), skip greetings, memes and small talk; keep deadlines, room or time changes, announcements, decisions and resources.
   b. Identify every entity it mentions that fits a schema type: people, courses, projects, tasks, events, ideas, opportunities.
   c. For each entity, search `vault/` for an existing note (check file names and the Aliases table). Update it if it exists; create it from the schema if it doesn't. Never create duplicates.
   d. Create one `document` note for the file itself with a 2–3 sentence summary, and add `mentioned_in:: [[that-document]]` to every note you created or updated from it.
   e. Add new events and deadlines to `calendar.md`, sorted by date. Don't touch `todos.md`: the person adds their own todos. Keep each new task as a `task` note (with its deadline in the calendar) and collect it for the report.
   f. If vector search tools are available (tools named `mcp__chroma__...`), add or update each changed note in the `vault` collection with the note's path as its id and its `type` as metadata.
   g. Move the original to `archive/YYYY-MM/` (create the folder if needed). Keep the file name; if it is meaningless (e.g. `IMG_2041`, `Document1`), rename it to describe its content.
3. Log every create, update and move in `logs/actions.md`.
4. Reply with a short report: files processed, notes created, notes updated, new deadlines (soonest first), and **Suggested todos**: one line per new task with its due date, ready for the person to add (e.g. `day add "…"` or in My Day). Never add them yourself. End with anything you were unsure about, so the person can check it.
