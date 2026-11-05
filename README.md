# Personal assistant — your own data, your own AI, on your laptop

A personal AI assistant made of plain markdown files. It knows who you are,
keeps your todos and calendar, files whatever you give it into a linked
knowledge base, and uses that knowledge to do real work for you: tailor your
CV, write cover letters, draft emails and updates, plan your day.

It comes with **My Day**, a small local window (and a `day` command) for
ticking todos, seeing your day, editing your goals, and being nudged with a
pop-up before events and every 40 minutes.

![My Day](docs/my-day.png)

Nothing leaves your laptop except what your AI agent sends to its model.
There's no server, no account and no database: every file is readable
markdown you can open, edit and back up.

## What you get

| Part | What it does | Where |
|---|---|---|
| **My Day** | Square window with Todo, Day and Goals tabs, subtasks, drag to reorder, pop-up check-ins, settings | `tools/day_ui.py` |
| **`day` command** | `day` opens the window; `day ls`, `day add`, `day done 2` work in any terminal | `tools/day.py` |
| **Your context** | Profile, goals, preferences, master CV | `me/` |
| **Semantic layer** | What things mean: note types, relations, aliases, who may write what | `schema.md` |
| **Knowledge base** | One note per course, project, person, event, opportunity… linked with `[[links]]` | `vault/` |
| **Skills** | Written procedures the agent follows (CV, cover letter, inbox, digests…) | `skills/` |
| **Rules** | What the agent must and mustn't do (never delete, cite sources, never invent) | `AGENTS.md` |

## Quick start (Windows, about 10 minutes)

1. **Get the folder:** clone or download this repository, e.g. to
   `C:\Users\<you>\assistant`. Then make it private (see "Keep it private").
2. **Install Python 3.9+** from python.org if you don't have it (tick "Add
   python.exe to PATH"). Nothing else to install: it's standard library only.
3. **Run setup** in the folder:
   ```powershell
   powershell -ExecutionPolicy Bypass -File setup.ps1
   ```
   It asks before each step: put `day` on your PATH, show My Day each
   morning, load the sample person, open the window.
4. **Install an AI agent** for the smart parts. The default is
   [Claude Code](https://docs.claude.com/en/docs/claude-code): install it,
   run `claude` once in this folder and sign in. It reads `AGENTS.md`
   (through `CLAUDE.md`) automatically. Any agent that reads `AGENTS.md`
   works. No API? Install [Ollama](https://ollama.com) and a small model
   (`ollama pull qwen3.5:4b`) and My Day answers locally; see "API or local
   model".

macOS / Linux: run `python3 tools/day_ui.py` for the window and add `tools/`
to your PATH for the `day` command (`tools/day`). The morning task and
`setup.ps1` are Windows-only.

## Try it with the sample person first

`setup.ps1` offers to load **Alex**, a fictional student with courses, a
capstone project, a hackathon next week and an internship to apply for.
Dates are set relative to today, so the demo is always current. Or run:

```
python tools/sample.py load
```

Then open My Day (`day`) and ask your agent things like:

- "What should I do today?"
- "What do I know about the Brightpath internship, and what's missing?"
- "Tailor my CV for the Brightpath internship." → `me/applications/`
- "Write the cover letter for it."
- "Draft a two-line message to my team about the hackathon demo slot."

When you're ready for your own data:

```
python tools/sample.py clear
```

The sample moves to `archive/` (nothing is deleted) and the blank templates
come back.

## Make it yours

1. **Tell it about you.** Fill in `me/profile.md`, `me/goals.md`,
   `me/preferences.md` and `me/cv.md`, or ask your agent: *"Interview me to
   fill in my profile, goals and preferences."* Goals are yours only: the
   agent never writes them.
2. **Feed it.** Drop files into `inbox/` (your CV as a PDF, a course outline,
   a job posting, a chat export) and say *"Process my inbox."* Each one is
   filed into `vault/` and the original is kept in `archive/`.
3. **Add your shorthand** to the Aliases table in `schema.md` ("DS" means
   Data Structures, and so on).
4. **Correct it.** When it gets something wrong, say so: it writes the lesson
   into `memory.md` and follows it next time.

## Do more with your own data

The point of keeping your context in one place is that the agent can do
work that needs it:

| Ask | Skill | What you get |
|---|---|---|
| "Tailor my CV for this job: …" | `tailor-resume` | Match table (requirement → evidence → source), a one-page CV, honest gaps |
| "Write a cover letter for …" | `cover-letter` | A letter built around one argument, every claim traced to your notes |
| "Reply to this email…", "Write my bio for…", "Draft a LinkedIn post about my project" | `draft-with-my-context` | Ready-to-paste text using real names, dates and results from your notes |
| "Process my inbox." | `ingest` | Files sorted into the knowledge base, deadlines in the calendar |
| "Remember that…" | `capture` | A linked note, no copy-paste |
| "What do I know about…?" | `ask-my-notes` | An answer with citations, or "not in your notes" |
| "What should I do today?" | `todos` | Top 3 with reasons (deadlines first, then goals) |
| Morning, evening, Sunday | `morning-digest`, `evening-check-in`, `weekly-review` | Digests in `digests/` |

The agent never invents experience, dates, grades or skills, and ends
anything you'll send with one thing to check yourself. Read before you send.

## My Day

- **Todo:** Today / This week / Later from `todos.md`. Click to tick. Hover
  for **+** (add steps; finish with Enter on an empty line or **Done**) and
  **✕** (remove to archive; Ctrl+Z undoes). Drag to reorder or move between
  lists. **✦ Suggest** plans your day: it sees today's schedule and free
  time, the next 7 days, your goals (short term first) and open todos, and
  proposes 3 specific todos, each placed in a free slot before the thing it
  prepares for. Only you add the suggestions.

**No wasted AI calls.** My Day calls the API only when you press ✦ Suggest
or ask with **?** (and `day ask` in the terminal). Suggestions are saved for
2 hours while your todos, calendar and goals don't change, so pressing again,
or restarting, costs nothing. With the local model, suggestions are prepared
in the background while the window is open, since that's free. Every call
is a line in `logs/ai-calls.log`, and ⚙ Settings → Assistant shows today's
count. The other tools (`day` commands, calendar sync, notifications) never
call an AI.
- **Day:** your calendar, one day at a time, with a "now" line.
- **Goals:** short and long term; click to edit, hover to move, mark
  achieved or remove. Dated goals appear in the calendar automatically. Below
  them, a reading list from your feeds ranked by your interests and goals
  (paste any blog, Substack or YouTube channel URL to add it).
- **Pop-ups:** before timed events and a check-in every 40 minutes (08:00–22:00),
  above every other window until you answer. Change it all under **⚙**.
- **Terminal:** `day ls`, `day add "…"` (`--week`, `--later`), `day done 2`,
  `day done 1.2`, `day step 1 "…"`, `day rm 3`, `day goals`, `day ask "…"`.

It watches the files, so edits by you or the agent appear within seconds.

### Optional: Google Calendar

Copy `tools/gcal_sync.config.example.json` to `tools/gcal_sync.config.json`
and paste your calendar's secret iCal address (Google Calendar → Settings →
Integrate calendar). Run `python tools/gcal_sync.py` on a schedule (e.g.
every 5 minutes in Task Scheduler) and your events appear in `calendar.md`.

### Optional: phone notifications

`tools/notify.py` can push to your phone through the free ntfy app: copy
`tools/notify.config.example.json` to `tools/notify.config.json` and set a
long, random topic name. Anyone who knows the topic can read the pushes.

## API or local model

My Day's **?** and **✦ Suggest** can use a cloud agent (through its API) or a
model running on your own laptop. Choose in **⚙ Settings → Assistant →
Answered by**:

| Setting | What answers |
|---|---|
| **auto** (default) | The API agent first. If it can't answer (not installed, no key, not logged in, offline), the local model takes over, and My Day stops retrying the API for 10 minutes. |
| **api** | Only the API agent. |
| **local** | Only the local model: private and works offline. |

Every answer says who gave it (e.g. "— local · qwen3.5:4b").

**Local model (free, offline):** install [Ollama](https://ollama.com), then
pull a small model:

```
ollama pull qwen3.5:4b
```

Pick any installed model under **Settings → Local model**. A local model
can't open files itself, so My Day pastes in your profile, goals, todos,
calendar, memory and the vault notes that best match your question. Small
models make more mistakes than big ones: check what they tell you. The first
answer after a while is slow (the model loads), then it stays loaded for 30
minutes.

**API agent:** set `"assistant_command"` in `tools/day_ui.config.json` to a
command that reads a prompt on stdin and prints the answer:

- **Claude Code** (default): `["claude", "-p", "--model", "{model}", "--allowedTools", "{tools}"]`.
  It reads `CLAUDE.md` → `AGENTS.md`. Run `claude` once to sign in.
- **DeepSeek Harness**: `["<path to>/dsh.cmd", "--profile", "headless", "-"]`
  (`dsh.cmd` is in the app's `resources/runtime/cli/bin/`). Headless runs need
  the model's API key as an environment variable, e.g. `DEEPSEEK_API_KEY`.
- **Any other agent** (Codex, Gemini CLI…): point it at this folder and tell
  it to read `AGENTS.md` first.

For the skills (CV, cover letter, inbox…), use the agent itself in this
folder; the local model only powers My Day's quick questions and suggestions.

## Keep it private

Once you fill it in, this folder holds your life. **Never push a filled-in
copy to a public repository.** Use a private repo (or no remote at all) for
your own copy. `.gitignore` already keeps out your config secrets, caches and
`me/applications/`.

## Undo the setup

```powershell
Unregister-ScheduledTask "My Day morning"
```
and remove the `tools` folder from your user PATH (Settings → System →
About → Advanced system settings → Environment Variables).

## Folder map

```
AGENTS.md          the agent's rules (CLAUDE.md points here)
schema.md          semantic layer: types, relations, aliases, ownership
me/                profile, goals, preferences, master CV
vault/             knowledge base, one folder per note type
todos.md           your todo list
calendar.md        events and deadlines
memory.md          lessons from your corrections
skills/            the procedures the agent follows
inbox/             drop files here
archive/           originals and anything removed (nothing is deleted)
digests/           daily digests and weekly reviews
logs/actions.md    every file change
tools/             My Day, day command, calendar sync, notifications, sample loader
examples/          Alex (sample person) and blank templates
automations/       optional scheduled prompts for your agent
```

## Licence

MIT. See `LICENSE`.
