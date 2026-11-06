# Guided demo: meet Alex

A 20–25 minute live walkthrough of the assistant, using Alex Rivera, a
fictional third-year student. You show the files, the knowledge graph in
Obsidian and My Day. Then you feed it a WhatsApp chat, a coursework brief and
a job posting, watch the graph grow, and use it to write a tailored CV.

Everything here is sample data that ships with the repo:

| What | Where | Loaded by |
|---|---|---|
| Alex: profile, goals, CV, todos, calendar, 10 linked notes | `examples/alex/` | `python tools/sample.py load` |
| 5 new files to ingest live (chat, brief, job post, voice memo, meeting notes) | `examples/demo-inbox/` | `python tools/sample.py inbox` |
| Obsidian graph coloured by note type | `examples/obsidian/graph.json` | copied by `load` |

Dates are filled in relative to the day you run `load`. For example, the
hackathon is always 6 days away and the DS assignment always 3 days away.

Repo for the audience: **github.com/KoomeMartin/personal-assistant-template**

---

## Before the talk

### The day before

1. **Make a fresh demo copy.** Don't use your own assistant folder:
   ```
   git clone https://github.com/KoomeMartin/personal-assistant-template C:\demo\alex
   ```
2. **Install [Obsidian](https://obsidian.md)**, if needed. Don't open the
   vault yet: `load` must write the graph colours first.
3. **Check your agent** opens in `C:\demo\alex`. With Claude Code, run
   `claude` there; with DeepSeek Harness, start a session in that folder.
4. **For the local-model part:** run `ollama pull qwen3.5:4b`.
5. **Rehearse once,** end to end, in a *second* clone. Then delete that
   clone yourself, so tomorrow's copy is untouched.

### On the day, 30 minutes before

1. **Hide your own data.** This matters: My Day allows one window per
   computer (port 59432).
   - Quit your own My Day with **Ctrl+Q**. Otherwise `python tools\day_ui.py`
     in the demo folder just brings *your* window, with your todos, onto the
     projector.
   - The `day` command on your PATH reads *your* folder. In the demo, always
     type `python tools\day.py …` inside `C:\demo\alex` instead.
   - Turn on Windows **Do not disturb**, so your calendar-sync reminders
     don't pop up on screen.
2. **Load Alex today,** so the dates line up:
   ```
   cd C:\demo\alex
   python tools\sample.py load
   ```
3. **Open Obsidian:** Open folder as vault → `C:\demo\alex`. Press
   **Ctrl+G** for the graph. You should see coloured dots, with Alex in the
   middle.
4. **Start the demo My Day:** run `python tools\day_ui.py`. Then open
   **⚙ Settings**:
   - Turn check-ins off, so nothing pops up mid-sentence.
   - Under Assistant, choose who answers. Choose **local** if the Wi-Fi is
     doubtful.
5. **Warm the local model** if you'll use it. The first answer takes about
   50 seconds while the model loads:
   ```
   ollama run qwen3.5:4b "hi"
   ```
6. **Arrange the screen:** Obsidian graph on the left half; the agent
   terminal and My Day on the right. Make the font bigger: Ctrl+= in
   Obsidian, Ctrl+scroll in the terminal.
7. **Don't run `sample.py inbox` yet.** The inbox should be empty when you
   start.

---

## The walkthrough

Timings are a guide. **Say** is what to tell the room; **Do** is what to click
or type; **They see** is what should be on screen.

### 1. It's just a folder (2 min)

**Do:** open `C:\demo\alex` in File Explorer or VS Code.

**Say:** "This is the whole assistant. No server, no database, no account.
Every file is markdown you can open and edit. An AI agent works *on* this
folder, and the folder is its memory."

**Do:** point at four things:
- `me/`: who Alex is.
- `vault/`: what Alex knows.
- `skills/`: how to do things.
- `AGENTS.md`: the rules.

**Show:** `AGENTS.md`, rules 1–3 (follow the schema, cite sources, never
delete).

### 2. Meet Alex (2 min)

**Do:** open `me/profile.md`, then `me/goals.md`.

**Say:** "Alex is a CS student and TA, building a study app for a hackathon
next week, with an internship deadline in 12 days. The goals file is Alex's
alone: the agent reads it but never writes it."

### 3. The semantic layer (3 min)

**Do:** open `schema.md`. Scroll through the note types, then the relations
table.

**Say:** "This is the important part. Before the agent writes anything, it
reads what things *mean*:
- a person, a course, a project, an opportunity;
- how they relate: `teaches`, `takes`, `part_of`, `requires`;
- what my shorthand means: 'DS' is Data Structures, 'the app' is Study Buddy.

You edit this in plain English. You're defining your own ontology without
code."

**Do:** open `vault/projects/study-buddy-app.md`. Point at the frontmatter
(type, status, deadline) and the `part_of:: [[intro-to-machine-learning]]`
lines at the bottom.

### 4. The knowledge graph (3 min)

**Do:** switch to Obsidian, graph view (Ctrl+G).

**They see:** about 15 coloured nodes, one colour per type:

| Colour | Type |
|---|---|
| Yellow | Alex (`me/`) |
| Red | people |
| Blue | courses |
| Green | projects |
| Orange | tasks |
| Purple | events |
| Pink | opportunities |
| Teal | ideas |
| Grey | documents |

**Do:**
- Hover **study-buddy-app** to light up its neighbours: the course, the
  hackathon, the flashcard idea.
- Click **brightpath-data-analyst-internship**. Show it `requires::` Dr
  Okafor as referee.

**Say:** "Nobody drew this graph. It's the links the agent writes when it
files things, and it uses those links to answer you."

**Remember this picture:** you'll come back to it after step 6.

### 5. My Day: the window you actually live in (4 min)

**Do:** bring up My Day.

- **Todo tab.**
  - Tick "Read the brief" under the DS assignment: the step count updates.
  - Hover a todo, click **+**, type a step, press Enter. Press Enter on an
    empty line (or click **Done**) to leave step mode.
  - Drag "Check the garden sensor batteries" from This week up to Today.
  - Hover a todo, click **✕** to remove it, then **Ctrl+Z** to undo.
- **Day tab:** today's lecture, TA lab and team sync, with a "now" line.
  Click ‹ › to look ahead.
- **Goals tab:** the two short-term goals with their dates. Click one to
  edit it.
- **✦ Suggest** (Todo tab). This uses the AI, so it takes 20–60 seconds;
  keep talking.
  - **Say:** "It reads today's free slots, the next 7 days and the goals,
    and proposes three todos, each placed in a free slot. It suggests; Alex
    decides. Nothing gets added unless I click."
  - **Then:** click one to add it.
- **The terminal,** in the demo folder:
  ```
  python tools\day.py ls
  python tools\day.py add "Book a room for the demo rehearsal" --week
  ```
  The window updates within 2 seconds: both read the same file.
- **Pop-up:** say "it also nudges me before events and every 40 minutes".
  To show one, quit with Ctrl+Q and run `python tools\day_ui.py --demo`.

### 6. Feed it: the inbox (5 min)

This is the core of the demo.

**Do:**
```
python tools\sample.py inbox
```

**Say:** "Five things landed in Alex's life today:
- a WhatsApp chat with the hackathon team;
- the second ML coursework brief;
- a job posting;
- a voice memo with an idea;
- the team's meeting notes.

This is the messy input everyone has."

**Do:** open `inbox/hackathon-team-chat.txt` for a few seconds. Point out the
memes and stickers mixed in with real information: a slot change, a
deadline, a mentor's office hours.

**Do:** in the agent:
> Process my inbox.

**While it works,** watch the Obsidian graph: new nodes appear and link
themselves in. Expect 1–3 minutes.

**What a good run does** (check this when you rehearse):

| From | Expected result |
|---|---|
| Chat | Hackathon event updated from 13:00 to **14:30**. Submission form deadline (in 4 days) in `calendar.md`. Pilot numbers on Study Buddy updated from 25 to **42**. Stickers and jokes ignored. |
| Chat | Dr Tomás Reyes is a one-off mentor, so **no person note** (the schema's minimisation rule). He may appear as plain text. |
| Meeting notes + chat | "Record the 2-minute backup video" appears **once**, not twice: the same task from two sources. |
| Todos | `todos.md` is **not touched**. The report ends with **Suggested todos** (backup video, submission form, ML coursework…), and Alex adds the ones they want. |
| ML brief | A task note `due_for:: [[intro-to-machine-learning]]`, deadline in 9 days in the calendar. |
| Job post | A new opportunity note, GreenLeaf, linked to garden-sensors and study-buddy as evidence. |
| Voice memo | An idea note `inspired_by::` / `related:: [[study-buddy-app]]`, plus a question for Dr Okafor. |
| Every file | A `document` note with a summary; the original moved to `archive/YYYY-MM/`; each step logged in `logs/actions.md`. |

**Do:** show four things:
- **Obsidian:** the graph again, now bigger. Click the GreenLeaf node.
- **My Day:** the Day tab has the new deadlines, already there.
- **`logs/actions.md`:** "every change it made, one line each".
- **`inbox/`:** empty. "Nothing deleted; originals are in `archive/`."

**Do:** add one of the suggested todos yourself:
```
python tools\day.py add "Record the 2-minute backup video" --week
```

**Say:** "It files and suggests; my todo list stays mine. And it ends its
report with what it wasn't sure about. That's the bit to read."

### 7. Ask it, with sources (2 min)

**Do:** in the agent:
> When is our hackathon demo now, and what do I still need to do before it?

**They see:** 14:30, the backup video, the submission form, the feature
freeze, each cited as `[[campus-ai-hackathon]]`,
`[[hackathon-team-chat-…]]` and so on.

**Do:**
> What grade did I get in Data Structures last term?

**They see:** "That's not in your notes" and a question back. **Say:** "It's
allowed to not know. It's not allowed to guess."

### 8. Real work with your own data (4 min)

**Do:**
> Tailor my CV for the GreenLeaf junior ML engineer role.

**They see:**
- A **match table**: each requirement → evidence → source note. Garden
  sensors maps to "real-world messy data" and "explain to non-technical
  people".
- **Honest gaps:** cloud deployment and Docker. It doesn't invent them.
- The pilot number. Watch whether it uses **42** (from today's chat) or
  **25** (from the old CV), and whether it flags the difference.
- A one-page CV in `me/applications/`.

**Then:**
> Write the cover letter, max 300 words, about the garden sensors project.

**Say:** "Every claim traces back to a note. It ends with one thing *I* should
check before sending, because it's my name on it."

### 9. Correct it once (1 min)

**Do:**
> Write dates as "6 Nov", never as 2026-11-06.

**They see:** a new line in `memory.md`. **Say:** "Next time it reads this
first. That's how it learns my taste, with no fine-tuning."

### 10. Private and offline (1 min)

**Do:** in My Day, go to ⚙ → Assistant → Answered by → **local**. Ask with
`?`:
> ? what's due this week

**They see:** the answer tagged "— local · qwen3.5:4b".

**Say:** "Same files, a small model on this laptop, no internet. Auto mode
uses the API and falls back to this when it can't reach it. And it only
calls the API when I click: ⚙ shows today's count."

### 11. Make it yours (1 min)

**Show** (don't run):
```
python tools\sample.py clear
```
"Alex moves to `archive/` and you get blank templates. Then tell your agent:
*'Interview me to fill in my profile, goals and preferences.'*"

Then show the repo link. Remind them never to push a filled-in copy to a
public repo.

---

## If something goes wrong

| Problem | Do this |
|---|---|
| Wi-Fi or API down | ⚙ → Answered by → **local**. For the inbox, say "here's one I ran earlier" and show your rehearsal clone's graph and `logs/actions.md`. |
| Ingest is slow | Keep talking over the graph. If it's still going after 3 minutes, run step 7 in a second terminal; it works on what's filed so far. |
| My Day shows *your* todos | Your own My Day was still running. Ctrl+Q it, then run `python tools\day_ui.py` in `C:\demo\alex`. |
| Graph is all grey | Obsidian was opened before `load`. Close Obsidian, copy `examples\obsidian\graph.json` to `.obsidian\graph.json`, reopen. |
| Graph shows duplicate nodes | The filter was cleared. In graph settings → Filters, paste: `-path:examples -path:archive -path:skills -path:docs -path:automations -path:inbox -path:logs -path:digests -file:README` |
| A pop-up appears mid-talk | Click **Quiet 2h**. |

## Reset for another run

The demo writes into the folder (that's the point), so use a fresh clone each
time:

```
git clone https://github.com/KoomeMartin/personal-assistant-template C:\demo\alex2
cd C:\demo\alex2
python tools\sample.py load
```

Then open `C:\demo\alex2` as a new vault in Obsidian.

## Hands-on for the audience (optional, 10 min)

If people have laptops:

1. Clone the repo and run `python tools\sample.py load`, then
   `python tools\day_ui.py`. No AI needed for My Day itself.
2. Open the folder in Obsidian and press Ctrl+G.
3. Run `python tools\sample.py inbox`, then point any agent that reads
   `AGENTS.md` (Claude Code, Codex, Gemini CLI…) at the folder and say
   "Process my inbox."
4. Edit `schema.md`: add an alias or a relation, and ask again.
