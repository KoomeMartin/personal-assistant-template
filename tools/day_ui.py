#!/usr/bin/env python3
"""My Day — a small, square, local window over the assistant's files.

Three tabs:
- Todo:  Today / This week / Later from todos.md. Click a row to tick it; hover
         for + (add a step) and ✕ (remove to archive; Ctrl+Z undoes).
         "Suggest" asks the assistant for todos based on the calendar and goals.
- Day:   the calendar for one day (‹ › to move), from calendar.md.
- Goals: Short term / Long term from me/goals.md (you write these), plus a
         reading list from tools/feeds.json (Substack, blogs, YouTube),
         ranked by your interests and goals.

One input line: Enter adds a todo (or, on Goals, a goal; a URL adds a feed).
Start with "?" to ask the assistant (the command in day_ui.config.json →
"assistant_command"; Claude Code by default), run in this folder.
Watches the markdown files, so outside edits appear within seconds.
Pop-ups: 15 min before a timed event, and a check-in every 40 min (08:00-22:00),
the window jumps above everything until you press Got it / Snooze / Quiet 2h.
Settings: tools/day_ui.config.json.
Single instance: launching again brings the window forward. Esc or ✕ minimises
(it keeps watching); Ctrl+Q quits. --hidden starts minimised; --demo shows a check-in.

Standard library only (Tkinter). Launch: pythonw tools/day_ui.py, or `day` in a
terminal (tools/day.py, which also lists and ticks todos without the window).
"""
import collections
import concurrent.futures
import ctypes
import datetime as dt
import email.utils
import html
import json
import os
import pathlib
import queue
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import tkinter as tk
import tkinter.font as tkfont
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
import xml.etree.ElementTree as ET

try:
    import winsound
except ImportError:  # not on Windows
    winsound = None

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent
TODOS = ROOT / "todos.md"
CAL = ROOT / "calendar.md"
GOALS = ROOT / "me" / "goals.md"
FEEDS = HERE / "feeds.json"
FEED_CACHE = HERE / "feeds_cache.json"
TZ_CFG = HERE / "gcal_sync.config.json"
UI_CFG = HERE / "day_ui.config.json"
PORT = 59432

BG = "#101014"
SURFACE = "#18181e"
HOVER = "#1d1d25"
LINE = "#26262f"
TEXT = "#ececf1"
DIM = "#8b8b99"
FAINT = "#4f4f5c"
ACCENT = "#8ab4ff"
NOW = "#7ee0a1"

TABS = ["Todo", "Day", "Goals"]
TODO_SECTIONS = ["Today", "This week", "Later"]
GOAL_SECTIONS = ["Short term", "Long term"]
PLACEHOLDERS = {"Todo": "Add a todo…", "Day": "Add a todo for today…",
                "Goals": "Add a goal, or paste a Substack / blog URL…",
                "Settings": "Add an interest (-word removes), or paste a feed URL…"}

EVENT_RE = re.compile(r"^- (\d{4}-\d{2}-\d{2})(?:\s+(\d{2}:\d{2}))?\s*(?:\((?:today|tomorrow)\))?\s*[—-]+\s+(.+)$")
TODO_RE = re.compile(r"^- \[( |x)\] (.+)$")
SUB_RE = re.compile(r"^(?:\s{2,}|\t)- \[( |x)\] (.+)$")
LINK_RE = re.compile(r"\[\[([^\]|]+)(?:\|([^\]]+))?\]\]")


def local_tz():
    """The time zone in day_ui.config.json (or the calendar sync config), else
    the computer's own."""
    for path in (UI_CFG, TZ_CFG):
        try:
            name = json.loads(path.read_text(encoding="utf-8")).get("timezone")
            if name:
                return __import__("zoneinfo").ZoneInfo(name)
        except Exception:
            pass
    return dt.datetime.now().astimezone().tzinfo


def unlink(text):
    return LINK_RE.sub(lambda m: m.group(2) or m.group(1), text).replace("`", "")


# ---------- calendar ----------
def load_events(day):
    """Return the day's events as (time_or_None, title, location), soonest first."""
    events = []
    if not CAL.exists():
        return events
    for line in CAL.read_text(encoding="utf-8").splitlines():
        m = EVENT_RE.match(line.strip())
        if not m or m.group(1) != day.isoformat():
            continue
        parts = [p.strip() for p in m.group(3).replace(GOAL_TAG, "").split("—")]
        if parts[0].lower() == "all day" and len(parts) > 1:
            parts = parts[1:]
        parts = parts[:1] + [p for p in parts[1:] if not re.fullmatch(r"\[\[[^\]]+\]\]", p)]
        events.append((m.group(2), unlink(parts[0]), " — ".join(p for p in parts[1:] if p)))
    return sorted(events, key=lambda e: e[0] or "00:00")


# ---------- todos ----------
Todo = collections.namedtuple("Todo", "done text raw idx subs")


def load_todos():
    """Return {section: [Todo]} for Today / This week / Later. Indented
    `  - [ ] ...` lines under a todo are its subtasks (Todo.subs)."""
    out, section, parent = {s: [] for s in TODO_SECTIONS}, None, None
    if not TODOS.exists():
        return out
    for i, line in enumerate(TODOS.read_text(encoding="utf-8").splitlines()):
        h = re.match(r"^## (.+)$", line)
        if h:
            section, parent = h.group(1).strip(), None
        elif section in out:
            m, s = TODO_RE.match(line), SUB_RE.match(line)
            if m:
                parent = Todo(m.group(1) == "x", m.group(2).strip(), line, i, [])
                out[section].append(parent)
            elif s and parent:
                parent.subs.append(Todo(s.group(1) == "x", s.group(2).strip(), line, i, []))
    return out


def tidy(text):
    """Split a todo line into a readable title and a short meta (due date)."""
    parts = [p.strip() for p in re.split(r"\s+—\s+", text)]
    meta = ""
    for p in parts[1:]:
        m = re.match(r"due (\d{4}-\d{2}-\d{2})", p)
        if m:
            meta = "due " + dt.date.fromisoformat(m.group(1)).strftime("%a %d %b")
    return unlink(parts[0]), meta


def _find(lines, idx, raw):
    """The line's index now (the file may have changed since it was read)."""
    if idx < len(lines) and lines[idx] == raw:
        return idx
    return lines.index(raw) if raw in lines else None


def _block(lines, i):
    """Index range of the subtasks directly under top-level todo i."""
    j = i + 1
    while j < len(lines) and SUB_RE.match(lines[j]):
        j += 1
    return range(i + 1, j)


def _set(line, done):
    return re.sub(r"- \[[ x]\] ", "- [x] " if done else "- [ ] ", line, count=1)


def toggle_todo(idx, raw):
    """Tick/untick a todo. Ticking a task ticks its subtasks; a task is ticked
    automatically when all its subtasks are, and unticked when one reopens."""
    lines = TODOS.read_text(encoding="utf-8").splitlines()
    i = _find(lines, idx, raw)
    if i is None:
        return
    done = "- [ ] " in lines[i]
    lines[i] = _set(lines[i], done)
    if TODO_RE.match(lines[i]):
        if done:
            for j in _block(lines, i):
                lines[j] = _set(lines[j], True)
    else:
        p = i
        while p > 0 and SUB_RE.match(lines[p]):
            p -= 1
        if TODO_RE.match(lines[p]):
            lines[p] = _set(lines[p], all("- [x] " in lines[j] for j in _block(lines, p)))
    TODOS.write_text("\n".join(lines) + "\n", encoding="utf-8")


def add_subtask(idx, raw, title):
    lines = TODOS.read_text(encoding="utf-8").splitlines()
    i = _find(lines, idx, raw)
    if i is None:
        return
    lines.insert(_block(lines, i).stop, f"  - [ ] {title}")
    lines[i] = _set(lines[i], False)  # a new step means the task isn't finished
    TODOS.write_text("\n".join(lines) + "\n", encoding="utf-8")


def remove_todo(idx, raw):
    """Never deleted: the todo (with its steps) moves to archive/YYYY-MM/todos-removed.md.
    Returns (log text, file text before, file text after) for the log and undo, or None."""
    before = TODOS.read_text(encoding="utf-8")
    lines = before.splitlines()
    i = _find(lines, idx, raw)
    if i is None:
        return None
    end = _block(lines, i).stop if TODO_RE.match(lines[i]) else i + 1
    gone = lines[i:end]
    del lines[i:end]
    if not TODO_RE.match(raw):  # a step: its task is done if every remaining step is
        p = i - 1
        while p > 0 and SUB_RE.match(lines[p]):
            p -= 1
        steps = _block(lines, p)
        if TODO_RE.match(lines[p]) and len(steps):
            lines[p] = _set(lines[p], all("- [x] " in lines[j] for j in steps))
    after = "\n".join(lines) + "\n"
    TODOS.write_text(after, encoding="utf-8")
    today = dt.date.today()
    dest = ROOT / "archive" / today.strftime("%Y-%m") / "todos-removed.md"
    dest.parent.mkdir(parents=True, exist_ok=True)
    if not dest.exists():
        dest.write_text("# Todos removed in My Day\n\nMove a line back into `todos.md` to restore it.\n\n",
                        encoding="utf-8")
    with dest.open("a", encoding="utf-8") as f:
        f.write("\n".join([gone[0].strip() + f" — removed {today.isoformat()}"] + gone[1:]) + "\n")
    title = tidy(re.sub(r"^\s*- \[[ x]\] ", "", raw))[0]
    return f"removed todo (archived): {title}", before, after


def move_todo(idx, raw, section, before=None):
    """Move a task (with its steps) to just above the task `before`, or to the
    end of `section` when before is None."""
    lines = TODOS.read_text(encoding="utf-8").splitlines()
    i = _find(lines, idx, raw)
    if i is None or raw == before:
        return False
    end = _block(lines, i).stop
    block = lines[i:end]
    del lines[i:end]
    if before in lines:
        at = lines.index(before)
    else:
        start = next((k for k, l in enumerate(lines) if l.strip() == f"## {section}"), None)
        if start is None:
            lines += ["", f"## {section}"]
            start = len(lines) - 1
        at = start + 1
        for k in range(start + 1, len(lines)):
            if lines[k].startswith("## "):
                break
            if TODO_RE.match(lines[k]) or SUB_RE.match(lines[k]):
                at = k + 1
    lines[at:at] = block
    TODOS.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return True


def move_step(idx, raw, parent_raw, before=None):
    """Move a step within its task: above the step `before`, or to the end."""
    lines = TODOS.read_text(encoding="utf-8").splitlines()
    i = _find(lines, idx, raw)
    if i is None or raw == before:
        return False
    line = lines.pop(i)
    if before in lines:
        at = lines.index(before)
    elif parent_raw in lines:
        at = _block(lines, lines.index(parent_raw)).stop
    else:
        return False
    lines.insert(at, line)
    TODOS.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return True


def restore_todos(before, after):
    """Undo the last removal, if todos.md hasn't changed since."""
    if TODOS.read_text(encoding="utf-8") != after:
        return False
    TODOS.write_text(before, encoding="utf-8")
    dest = ROOT / "archive" / dt.date.today().strftime("%Y-%m") / "todos-removed.md"
    with dest.open("a", encoding="utf-8") as f:
        f.write("  ↩ restored the same day\n")
    return True


def append_to_section(path, section, line, title="# Todos", item_re=re.compile(r"^- ")):
    """Append a line after the last item of a '## section' (creates it if missing)."""
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else [title]
    start = next((i for i, l in enumerate(lines) if l.strip() == f"## {section}"), None)
    if start is None:
        lines += ["", f"## {section}", "", line]
    else:
        at = start + 1
        for i in range(start + 1, len(lines)):
            if lines[i].startswith("## "):
                break
            if item_re.match(lines[i]) or (lines[i].startswith("  ") and at == i):
                at = i + 1
        lines.insert(at, line)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def add_todo(title, section):
    append_to_section(TODOS, section, f"- [ ] {title}", item_re=TODO_RE)


# ---------- goals ----------
Goal = collections.namedtuple("Goal", "text date link idx raw")
GOAL_TAG = "<!-- from goals -->"  # marks calendar lines that mirror a dated goal


def parse_goal(line, idx=-1):
    """'- text — YYYY-MM-DD — [[note]]' -> Goal (date and link optional, any order)."""
    parts = [p.strip() for p in re.split(r"\s+—\s+", line[2:].strip())]
    date = next((dt.date.fromisoformat(p) for p in parts[1:] if re.fullmatch(r"\d{4}-\d{2}-\d{2}", p)), None)
    link = next((m.group(1) for p in parts[1:] for m in [re.fullmatch(r"\[\[([^\]|]+)\]\]", p)] if m), None)
    return Goal(unlink(parts[0]), date, link, idx, line)


def format_goal(text, date=None, link=None):
    return "- " + " — ".join(x for x in (text.strip(), date and date.isoformat(), link and f"[[{link}]]") if x)


def load_goals():
    """Return [(section, [Goal])] for Short term and Long term."""
    if not GOALS.exists():
        return [(s, []) for s in GOAL_SECTIONS]
    sections, cur = {}, None
    for i, line in enumerate(GOALS.read_text(encoding="utf-8").splitlines()):
        h = re.match(r"^## (.+?)\s*$", line)
        if h:
            cur = h.group(1).strip()
            sections[cur] = []
        elif cur and line.startswith("- "):
            sections[cur].append(parse_goal(line, i))
    return [(name, sections.get(name, [])) for name in GOAL_SECTIONS]


def goal_texts():
    return [g.text for _, goals in load_goals() for g in goals]


def parse_goal_input(text):
    """Typed goal: 'Demo day 2026-12-04', 'Demo day — 4 Dec' or just 'Demo day'."""
    m = re.search(r"\s*(?:—|-|@|on|by)?\s*(\d{4}-\d{2}-\d{2}|\d{1,2} [A-Za-z]{3,9}(?: \d{4})?)\s*$", text)
    if not m:
        return text.strip(), None
    raw, date = m.group(1), None
    try:
        date = dt.date.fromisoformat(raw)
    except ValueError:
        for fmt in ("%d %b %Y", "%d %B %Y", "%d %b", "%d %B"):
            try:
                d = dt.datetime.strptime(raw, fmt).date()
                if "%Y" not in fmt:  # no year: the next such date from today
                    d = d.replace(year=dt.date.today().year)
                    if d < dt.date.today():
                        d = d.replace(year=d.year + 1)
                date = d
                break
            except ValueError:
                pass
    return (text[:m.start()].strip(), date) if date else (text.strip(), None)


def add_goal(text, section=GOAL_SECTIONS[0]):
    title, date = parse_goal_input(text)
    append_to_section(GOALS, section, format_goal(title, date), title="# Goals")
    return f"added goal to {section}: {title}"


def _goal_lines(goal):
    lines = GOALS.read_text(encoding="utf-8").splitlines()
    return lines, _find(lines, goal.idx, goal.raw)


def update_goal(goal, text, date):
    lines, i = _goal_lines(goal)
    if i is None:
        return None
    lines[i] = format_goal(text, date, goal.link)
    GOALS.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return f"edited goal: {goal.text} → {text}" + (f" ({date})" if date != goal.date else "")


def move_goal(goal, to_section):
    """Move to another section ('Short term', 'Long term' or 'Achieved')."""
    lines, i = _goal_lines(goal)
    if i is None:
        return None
    line = lines.pop(i)
    if to_section == "Achieved":
        line += f" — achieved {dt.date.today().isoformat()}"
    GOALS.write_text("\n".join(lines) + "\n", encoding="utf-8")
    append_to_section(GOALS, to_section, line, title="# Goals")
    return f"goal → {to_section}: {goal.text}"


def remove_goal(goal):
    """Never deleted: the line moves to archive/YYYY-MM/goals-removed.md."""
    lines, i = _goal_lines(goal)
    if i is None:
        return None
    line = lines.pop(i)
    GOALS.write_text("\n".join(lines) + "\n", encoding="utf-8")
    today = dt.date.today()
    dest = ROOT / "archive" / today.strftime("%Y-%m") / "goals-removed.md"
    dest.parent.mkdir(parents=True, exist_ok=True)
    if not dest.exists():
        dest.write_text("# Goals removed in My Day\n\nMove a line back into `me/goals.md` to restore it.\n\n",
                        encoding="utf-8")
    with dest.open("a", encoding="utf-8") as f:
        f.write(f"{line} — removed {today.isoformat()}\n")
    return f"removed goal (archived): {goal.text}"


def find_note(slug):
    return next((p for p in (ROOT / "vault").rglob(f"{slug}.md")), None)


def sync_goals():
    """Propagate goals.md to what tracks it; returns a list of changes.

    - calendar.md "## Added by me": one line per dated goal, tagged GOAL_TAG
      (added, re-dated, renamed or dropped to match the goals).
    - a linked event note ([[note]] with type: event): its `date:` follows the goal.
    """
    changes = []
    goals = [g for _, gs in load_goals() for g in gs]
    titles = {g.text for g in goals}
    if CAL.exists():
        text = CAL.read_text(encoding="utf-8")
        head, sep, tail = text.partition("## Added by me")
        if sep:
            keep = []
            for line in tail.splitlines()[1:]:
                m = EVENT_RE.match(line.strip())
                title = m and unlink(re.split(r"\s+—\s+", m.group(3).replace(GOAL_TAG, "").strip())[0])
                if GOAL_TAG in line or (m and title in titles):
                    continue  # regenerated below
                keep.append(line)
            mirrored = [f"- {g.date.isoformat()} — {g.text}" + (f" — [[{g.link}]]" if g.link else "") + f" {GOAL_TAG}"
                        for g in sorted((g for g in goals if g.date), key=lambda g: g.date)]
            while keep and not keep[0].strip():
                keep.pop(0)
            body = "\n\n" + "\n".join(mirrored) + ("\n" if mirrored else "") + ("\n" + "\n".join(keep) if keep else "")
            new = head + sep + body.rstrip("\n") + "\n"
            if new != text:
                CAL.write_text(new, encoding="utf-8")
                changes.append(("update", "calendar.md", f"mirrored {len(mirrored)} dated goal(s)"))
    for g in goals:
        note = g.link and g.date and find_note(g.link)
        if not note:
            continue
        t = note.read_text(encoding="utf-8")
        if re.search(r"^type: event\s*$", t, re.M):
            new = re.sub(r"^date: .*$", f"date: {g.date.isoformat()}", t, count=1, flags=re.M)
            if new != t:
                note.write_text(new, encoding="utf-8")
                changes.append(("update", str(note.relative_to(ROOT)).replace("\\", "/"),
                                f"date follows goal: {g.date.isoformat()}"))
    return changes


def log_action(action, path, why):
    stamp = dt.datetime.now(local_tz()).strftime("%Y-%m-%d %H:%M")
    with (ROOT / "logs" / "actions.md").open("a", encoding="utf-8") as f:
        f.write(f"{stamp} | {action} | {path} | {why} (My Day)\n")


# ---------- reading list ----------
def load_config():
    cfg = {"assistant": "auto", "local_model": "qwen3.5:4b", "ollama_url": "http://127.0.0.1:11434",
           "checkin_minutes": 40, "event_lead_minutes": 15, "active_hours": ["08:00", "22:00"],
           "sound": True, "checkins": True, "event_reminders": True, "pin": False,
           "start_tab": "Todo", "model": "sonnet", "feed_hours": 3, "timezone": "",
           # the AI used by "?" and Suggest; the prompt goes to its stdin.
           # {model} and {tools} are filled in. Any command that reads a prompt on
           # stdin and prints an answer works, e.g. ["ollama", "run", "llama3.2"].
           "assistant_command": ["claude", "-p", "--model", "{model}", "--allowedTools", "{tools}"]}
    try:
        cfg.update(json.loads(UI_CFG.read_text(encoding="utf-8")))
    except Exception:
        pass
    return cfg


def edit_interest(word):
    """'word' adds an interest for ranking the reading list; '-word' removes it."""
    cfg = json.loads(FEEDS.read_text(encoding="utf-8")) if FEEDS.exists() else {"feeds": []}
    interests = cfg.setdefault("interests", [])
    w = word.strip().lower()
    if w.startswith("-"):
        cfg["interests"] = [i for i in interests if i != w[1:].strip()]
    elif w and w not in interests:
        interests.append(w)
    FEEDS.write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")


def load_feed_config():
    try:
        return json.loads(FEEDS.read_text(encoding="utf-8"))
    except Exception:
        return {"feeds": [], "interests": []}


def youtube_feed(url):
    """Turn a YouTube channel link (@handle, /channel/…, or a video) into its RSS feed."""
    m = re.search(r"/channel/(UC[\w-]{22})", url)
    if not m:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0", "Accept-Language": "en"})
        page = urllib.request.urlopen(req, timeout=20).read().decode("utf-8", "ignore")
        m = (re.search(r'"(?:channelId|externalId)":"(UC[\w-]{22})"', page)
             or re.search(r'youtube\.com/channel/(UC[\w-]{22})', page))
    return f"https://www.youtube.com/feeds/videos.xml?channel_id={m.group(1)}" if m else None


def add_feed(url, name=None):
    url = url.strip().rstrip("/")
    if "youtube.com/" in url and "feeds/videos.xml" not in url or "youtu.be/" in url:
        name = name or (re.search(r"/@([\w.-]+)", url) or re.search(r"(YouTube)", "YouTube")).group(1)
        url = youtube_feed(url)
        if not url:
            return False
    elif re.match(r"^https?://[^/]+\.substack\.com$", url) or re.match(r"^https?://[^/]+$", url):
        url += "/feed"  # Substack (and most blogs) publish RSS at /feed
    cfg = load_feed_config()
    if any(f["url"] == url for f in cfg["feeds"]):
        return False
    name = name or re.sub(r"^www\.", "", urllib.parse.urlparse(url).netloc).split(".")[0].title()
    cfg["feeds"].append({"name": name, "url": url})
    FEEDS.write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")
    return True


def parse_date(s):
    if not s:
        return 0
    try:
        return email.utils.parsedate_to_datetime(s).timestamp()
    except Exception:
        try:
            return dt.datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()
        except Exception:
            return 0


def fetch_feed(feed):
    req = urllib.request.Request(feed["url"], headers={"User-Agent": "MyDay/1.0"})
    root = ET.fromstring(urllib.request.urlopen(req, timeout=30).read())
    items = []
    for el in root.iter():
        tag = el.tag.split("}")[-1]
        if tag not in ("item", "entry"):
            continue
        get = {c.tag.split("}")[-1]: c for c in el}
        link = get.get("link")
        href = (link.get("href") or link.text or "") if link is not None else ""
        summary = get.get("description", get.get("summary", get.get("content")))
        date = get.get("pubDate", get.get("published", get.get("updated")))
        items.append({
            "source": feed["name"],
            "title": html.unescape((get["title"].text or "").strip()) if "title" in get else "",
            "link": href.strip(),
            "summary": re.sub(r"<[^>]+>", " ", html.unescape(summary.text or ""))[:600] if summary is not None else "",
            "ts": parse_date(date.text if date is not None else ""),
        })
    return items[:20]


def fetch_all():
    def safe(feed):
        try:
            return fetch_feed(feed)
        except Exception:
            return []  # one dead feed shouldn't empty the list
    with concurrent.futures.ThreadPoolExecutor(8) as pool:
        items = [it for batch in pool.map(safe, load_feed_config()["feeds"]) for it in batch]
    FEED_CACHE.write_text(json.dumps({"fetched": time.time(), "items": items}), encoding="utf-8")
    return items


def rank_reading(items, goals):
    """Score by interests (x2) and distinctive goal words (x1); at most 3 per source;
    newest breaks ties."""
    generic = {"through", "including", "engineering", "learning", "machine", "models", "industry",
               "applied", "complete", "deliver", "deepen", "concentration", "innovation", "measurable",
               "organisational", "building", "systems", "social", "impact", "africa"}
    interests = {t.lower() for t in load_feed_config().get("interests", [])}
    words = {w for g in goals for w in re.findall(r"[a-z]{6,}", g.lower())} - generic - interests
    cutoff = time.time() - 14 * 86400
    scored = []
    for it in items:
        if not it["title"] or not it["link"] or (it["ts"] and it["ts"] < cutoff):
            continue
        hay = (it["title"] + " " + it["summary"]).lower()
        hits = [t for t in interests if re.search(rf"\b{re.escape(t)}", hay)]
        hits += [w for w in words if re.search(rf"\b{w}", hay)]
        score = 2 * sum(h in interests for h in hits) + sum(h in words for h in hits)
        scored.append((score, it["ts"], hits, it))
    scored.sort(key=lambda s: (s[0], s[1]), reverse=True)
    if sum(s[0] > 0 for s in scored) >= 6:  # enough matches: drop the unrelated ones
        scored = [s for s in scored if s[0] > 0]
    # every source gets its best item first, then fill up to 3 per source
    best = {}
    for s in scored:
        best.setdefault(s[3]["source"], s)
    picked = list(best.values())
    per = {src: 1 for src in best}
    for s in scored:
        if len(picked) >= 12:
            break
        if s in picked or per[s[3]["source"]] >= 3:
            continue
        per[s[3]["source"]] += 1
        picked.append(s)
    picked.sort(key=lambda s: (s[0], s[1]), reverse=True)
    return [(it, sorted(hits, key=len, reverse=True)[:1]) for _, _, hits, it in picked[:12]]


# ---------- assistant ----------
# Who answers "?" and Suggest (Settings → Assistant, or "assistant" in the config):
#   auto  — the API agent in "assistant_command" first; if it can't answer (not
#           installed, no key, not logged in, offline), the local model in Ollama
#   api   — only the API agent;  local — only the local model
# A local model can't open files, so the files it needs are pasted into its prompt.
LAST_SOURCE = {"name": ""}  # who answered last, shown under the answer
_api_down_until = [0.0]     # after the API fails, go straight to local for 10 minutes
LAST_MODEL = [""]           # the local model that actually answered
ASK_FILES = ["me/profile.md", "me/goals.md", "todos.md", "calendar.md", "memory.md"]
SUGGEST_FILES = ["me/goals.md", "calendar.md", "todos.md"]


class AssistantUnavailable(Exception):
    pass


def api_name(cfg):
    exe = pathlib.Path(cfg["assistant_command"][0]).name.lower()
    return "DeepSeek Harness" if exe.startswith("dsh") else "Claude Code" if exe.startswith("claude") else exe


def fresh_env():
    """This process's environment plus user variables saved since it started
    (e.g. an API key set with setx), so a new key works without a restart."""
    env = dict(os.environ)
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as k:
            i = 0
            while True:
                try:
                    name, value, _ = winreg.EnumValue(k, i)
                except OSError:
                    break
                if name.upper() != "PATH" and name not in env:
                    env[name] = str(value)
                i += 1
    except Exception:
        pass
    return env


QUICK_DIR = pathlib.Path(tempfile.gettempdir()) / "myday-quick"  # no AGENTS.md here: nothing to read first


def run_api(prompt, tools, quick=False):
    """quick: the prompt already holds everything, so run the agent in an empty
    folder; it skips this folder's start-of-task reading and answers faster."""
    cfg = load_config()
    cmd = [part.replace("{model}", cfg["model"]).replace("{tools}", tools) for part in cfg["assistant_command"]]
    exe = shutil.which(cmd[0])
    if not exe:
        raise AssistantUnavailable(f"{api_name(cfg)} isn't installed")
    if quick:
        QUICK_DIR.mkdir(exist_ok=True)
    try:
        r = subprocess.run([exe] + cmd[1:], input=prompt, capture_output=True, text=True, encoding="utf-8",
                           cwd=QUICK_DIR if quick else ROOT, timeout=180, env=fresh_env(),
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except subprocess.TimeoutExpired:
        raise AssistantUnavailable(f"{api_name(cfg)} took over 3 minutes")
    out, err = (r.stdout or "").strip(), (r.stderr or "").strip()
    if "MISSING_CREDENTIAL" in err or "API key" in err:
        raise AssistantUnavailable(f"{api_name(cfg)} has no API key")
    if re.search(r"not logged in|/login", out, re.I):
        raise AssistantUnavailable(f"{api_name(cfg)} isn't logged in")
    if r.returncode != 0 and not out:
        raise AssistantUnavailable((err.splitlines() or ["failed"])[-1][:120])
    return out or "(no answer)"


def related_notes(text, limit=3):
    """The vault notes that best match the question's words (for the local model)."""
    words = {w for w in re.findall(r"[a-z]{5,}", text.lower())} - {"about", "which", "there", "would", "should"}
    scored = []
    for note in (ROOT / "vault").rglob("*.md"):
        if note.name == "README.md":
            continue
        body = note.read_text(encoding="utf-8", errors="ignore").lower()
        score = sum(body.count(w) + 3 * (w in note.stem) for w in words)
        if score:
            scored.append((score, note))
    return [n for _, n in sorted(scored, reverse=True)[:limit]]


def run_local(prompt, files):
    cfg = load_config()
    installed = local_models()
    if installed and cfg["local_model"] not in installed:  # use what's there rather than fail
        cfg["local_model"] = installed[0]
    parts = []
    for f in files:
        path = f if isinstance(f, pathlib.Path) else ROOT / f
        if path.exists():
            rel = path.relative_to(ROOT).as_posix()
            parts.append(f"=== {rel} ===\n{path.read_text(encoding='utf-8', errors='ignore')[:6000]}")
    system = ("You are a personal assistant. Answer only from the files below; if they don't say, "
              "say so plainly. Never invent facts.\n\n" + "\n\n".join(parts))
    body = json.dumps({"model": cfg["local_model"], "stream": False, "think": False, "keep_alive": "30m",
                       "messages": [{"role": "system", "content": system},
                                    {"role": "user", "content": prompt}]}).encode()
    req = urllib.request.Request(cfg["ollama_url"].rstrip("/") + "/api/chat", data=body,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=240) as resp:
            out = json.loads(resp.read().decode("utf-8"))["message"]["content"]
    except urllib.error.HTTPError as e:
        if e.code == 404:
            raise AssistantUnavailable(f"{cfg['local_model']} isn't installed (ollama pull {cfg['local_model']})")
        raise AssistantUnavailable(f"Ollama error {e.code}")
    except (urllib.error.URLError, OSError):
        raise AssistantUnavailable("Ollama isn't running")
    LAST_MODEL[0] = cfg["local_model"]
    return re.sub(r"(?s)<think>.*?</think>", "", out).strip() or "(no answer)"


def local_models():
    """Models installed in Ollama, or [] if it isn't running."""
    try:
        with urllib.request.urlopen(load_config()["ollama_url"].rstrip("/") + "/api/tags", timeout=1.5) as r:
            return [m["name"] for m in json.loads(r.read().decode("utf-8"))["models"]]
    except Exception:
        return []


AI_LOG = ROOT / "logs" / "ai-calls.log"
SUGGEST_CACHE = HERE / "suggest_cache.json"


def log_ai_call(source, purpose, seconds, ok=True):
    """One line per AI call, so you can see what My Day spends: logs/ai-calls.log."""
    try:
        with AI_LOG.open("a", encoding="utf-8") as f:
            f.write(f"{dt.datetime.now(local_tz()):%Y-%m-%d %H:%M} | {source} | {purpose} | "
                    f"{seconds:.0f}s{'' if ok else ' | failed'}\n")
    except OSError:
        pass


def ai_calls_today():
    """(API calls, local calls) made today."""
    today = dt.datetime.now(local_tz()).strftime("%Y-%m-%d")
    try:
        rows = [l.split(" | ") for l in AI_LOG.read_text(encoding="utf-8").splitlines()
                if l.startswith(today) and not l.endswith("failed")]  # a failed try costs nothing
    except OSError:
        return 0, 0
    local = sum(1 for r in rows if len(r) > 1 and r[1].startswith("local"))
    return len(rows) - local, local


def next_source():
    """Who would answer right now without trying: 'api' or 'local'."""
    mode = load_config()["assistant"]
    return "local" if mode == "local" or (mode == "auto" and time.time() < _api_down_until[0]) else "api"


def run_assistant(prompt, tools, files, quick=False, purpose="ask"):
    cfg = load_config()
    mode, why = cfg["assistant"], []
    if mode == "api" or (mode == "auto" and time.time() >= _api_down_until[0]):
        t0 = time.time()
        try:
            out = run_api(prompt, tools, quick)
            LAST_SOURCE["name"] = api_name(cfg)
            log_ai_call(api_name(cfg), purpose, time.time() - t0)
            return out
        except AssistantUnavailable as e:
            why.append(str(e))
            _api_down_until[0] = time.time() + 600
            log_ai_call(api_name(cfg), purpose, time.time() - t0, ok=False)
    if mode in ("auto", "local"):
        t0 = time.time()
        try:
            out = run_local(prompt, files)
            LAST_SOURCE["name"] = f"local · {LAST_MODEL[0] or cfg['local_model']}"
            log_ai_call(LAST_SOURCE["name"], purpose, time.time() - t0)
            return out
        except AssistantUnavailable as e:
            why.append(str(e))
    LAST_SOURCE["name"] = ""
    return "No assistant could answer: " + "; ".join(why) + ". Change it in ⚙ Settings → Assistant."


def ask_assistant(question, now_local):
    out = run_assistant(f"{question}\n\n(Asked from the My Day window at {now_local:%Y-%m-%d %H:%M}. "
                        "Answer in at most 80 words, plain text, no markdown.)",
                        "Read,Glob,Grep,Edit", ASK_FILES + related_notes(question))
    return f"{out}\n\n— {LAST_SOURCE['name']}" if LAST_SOURCE["name"] else out


def day_brief(now_local, days=7):
    """What a planner needs, already read from the files: today's schedule and
    free time, the next days' events, dated goals and open todos."""
    today, hm = now_local.date(), now_local.strftime("%H:%M")
    start_h, end_h = load_config()["active_hours"]
    lines = [f"Now: {now_local:%A %d %B %Y, %H:%M}.", "", "TODAY'S SCHEDULE:"]
    events = load_events(today)
    for t, title, where in events:
        state = "done" if t and t < hm else "upcoming"
        lines.append(f"- {t or 'all day'}  {title}" + (f" ({where})" if where else "") + f"  [{state}]")
    if not events:
        lines.append("- nothing scheduled")
    # free time between now and the end of the day, assuming events last an hour
    busy = sorted((t, (dt.datetime.combine(today, dt.time.fromisoformat(t)) + dt.timedelta(hours=1)).strftime("%H:%M"))
                  for t, _, _ in events if t)
    free, cur = [], max(hm, start_h)
    for b0, b1 in busy:
        if b0 > cur and (dt.datetime.strptime(b0, "%H:%M") - dt.datetime.strptime(cur, "%H:%M")).seconds >= 1800:
            free.append(f"{cur}-{b0}")
        cur = max(cur, b1)
    if end_h > cur:
        free.append(f"{cur}-{end_h}")
    lines += ["", "FREE TIME LEFT TODAY: " + (", ".join(free) or "none")]
    lines += ["", f"NEXT {days} DAYS:"]
    for n in range(1, days + 1):
        day = today + dt.timedelta(days=n)
        evs = load_events(day)
        if evs:
            lines.append(f"- {day:%a %d %b}: " + "; ".join(f"{t or 'all day'} {title}" for t, title, _ in evs))
    goals = dict(load_goals())
    lines += ["", "SHORT-TERM GOALS (dated, soonest first):"]
    for g in sorted(goals.get("Short term", []), key=lambda g: g.date or dt.date.max):
        when = f" — {g.date:%a %d %b} ({(g.date - today).days} days left)" if g.date else ""
        lines.append(f"- {g.text}{when}")
    lines += ["", "LONG-TERM GOALS (background only; lowest priority):"]
    lines += [f"- {g.text}" for g in goals.get("Long term", [])]
    lines += ["", "OPEN TODOS:"]
    todos = [t for sec in TODO_SECTIONS for t in load_todos()[sec] if not t.done]
    for t in todos:
        lines.append(f"- {tidy(t.text)[0]}" + "".join(f"\n    - step: {s.text}" for s in t.subs if not s.done))
    if not todos:
        lines.append("- none")
    return "\n".join(lines)


def suggest_todos(now_local):
    """Return [(todo, why)] or a string explaining what went wrong."""
    out = run_assistant(
        "Plan my day. Everything you need is in the brief below; don't open any files and don't edit anything.\n\n"
        + day_brief(now_local) + "\n\n"
        "Suggest exactly 3 concrete todos for TODAY that aren't already in OPEN TODOS, in this order:\n"
        "1. one that prepares for an upcoming item in TODAY'S SCHEDULE (or tomorrow's, if today has none left);\n"
        "2. one that moves the soonest SHORT-TERM GOAL forward;\n"
        "3. one for the next most urgent thing: another short-term goal, an event in the next days, or an open todo.\n"
        "Put each in one of today's free slots, before the thing it prepares for. Never pick a long-term goal "
        "while a short-term goal or event needs work. Be specific (what to do, not 'work on X'). "
        "Use only facts from the brief; never invent.\n"
        "Output only lines like:\n"
        "- <todo, under 12 words> || <slot · why, under 12 words>", "Read", [], quick=True, purpose="suggest")
    pairs = []
    for l in out.splitlines():  # small models sometimes use a single | ; accept both
        l = l.strip().lstrip("-*0123456789. ").strip()
        parts = re.split(r"\s*\|\|?\s*", l, maxsplit=1)
        if len(parts) == 2 and parts[0]:
            pairs.append((parts[0].strip("* "), re.sub(r"\s*\|\s*", " · ", parts[1]).strip()))
    return pairs or out



class DayUI:
    def __init__(self, inbox):
        self.inbox = inbox
        self.cfg = load_config()
        self.tab = self.cfg["start_tab"] if self.cfg["start_tab"] in TABS else "Todo"
        self.day_offset = 0
        self.sig = None          # contents of todos/calendar/goals at the last render
        self.undo = None         # (before, after) of the last todo removal, for Ctrl+Z
        self.drag = None         # the todo being dragged, while the mouse is down
        self.pre_pop_size = None # window size before a pop-up grew it
        self.suggestions = None  # None | "loading" | [(todo, why)] | error string
        self.suggest_cache = None  # (files key, time, suggestions, source), also in tools/suggest_cache.json
        self.prefetching = False
        self.reading = None      # None while fetching, else [(item, hits)]
        self.thinking = None
        self.root = tk.Tk()
        self.s = self.root.winfo_fpixels("1i") / 96
        fam = set(tkfont.families())
        body = "Segoe UI Variable Text" if "Segoe UI Variable Text" in fam else "Segoe UI"
        self.f_title = ("Segoe UI Semibold", 17)
        self.f_body = (body, 10)
        self.f_small = (body, 9)
        self.f_bold = ("Segoe UI Semibold", 10)
        self.f_head = ("Segoe UI Semibold", 8)

        r = self.root
        r.title("My Day")
        r.configure(bg=BG)
        side = self.px(440)
        r.geometry(f"{side}x{side}+{self.px(80)}+{self.px(60)}")
        r.minsize(self.px(380), self.px(380))
        self.dark_titlebar()

        # header: date + clock, then a one-line summary
        head = tk.Frame(r, bg=BG)
        head.pack(fill="x", padx=self.px(20), pady=(self.px(16), 0))
        self.date_lbl = tk.Label(head, bg=BG, fg=TEXT, font=self.f_title)
        self.date_lbl.pack(side="left")
        self.clock = tk.Label(head, bg=BG, fg=DIM, font=self.f_body)
        self.clock.pack(side="right", anchor="s", pady=(0, self.px(4)))
        self.summary = tk.Label(r, bg=BG, fg=DIM, font=self.f_small, anchor="w")
        self.summary.pack(fill="x", padx=self.px(20))

        # tabs
        tabs = tk.Frame(r, bg=BG)
        tabs.pack(fill="x", padx=self.px(20), pady=(self.px(12), 0))
        self.tab_widgets = {}
        for name in TABS:
            f = tk.Frame(tabs, bg=BG, cursor="hand2")
            f.pack(side="left", padx=(0, self.px(18)))
            lbl = tk.Label(f, bg=BG, font=self.f_bold, cursor="hand2")
            lbl.pack()
            bar = tk.Frame(f, height=2, bg=BG)
            bar.pack(fill="x", pady=(self.px(3), 0))
            for w in (f, lbl):
                w.bind("<Button-1>", lambda e, n=name: self.switch(n))
            self.tab_widgets[name] = (lbl, bar)
        f = tk.Frame(tabs, bg=BG, cursor="hand2")
        f.pack(side="right")
        lbl = tk.Label(f, text="⚙", bg=BG, font=("Segoe UI Symbol", 12), cursor="hand2")
        lbl.pack()
        bar = tk.Frame(f, height=2, bg=BG)
        bar.pack(fill="x", pady=(self.px(1), 0))
        for w in (f, lbl):
            w.bind("<Button-1>", lambda e: self.switch("Settings"))
        self.tab_widgets["Settings"] = (lbl, bar)
        tk.Frame(r, bg=LINE, height=1).pack(fill="x", padx=self.px(20))

        # input bar (packed before the list so it keeps its space)
        bar_h = self.px(42)
        self.inbar = tk.Canvas(r, bg=BG, height=bar_h, highlightthickness=0)
        self.inbar.pack(side="bottom", fill="x", padx=self.px(16), pady=(self.px(6), self.px(14)))
        self.entry = tk.Entry(self.inbar, bg=SURFACE, fg=DIM, insertbackground=TEXT, relief="flat",
                              font=self.f_body, highlightthickness=0, bd=0)
        self.entry.insert(0, PLACEHOLDERS[self.tab])
        self.entry_win = self.inbar.create_window(self.px(16), bar_h // 2, window=self.entry, anchor="w")
        self.inbar.bind("<Configure>", self.draw_inbar)
        self.entry.bind("<FocusIn>", self.clear_placeholder)
        self.entry.bind("<FocusOut>", self.restore_placeholder)
        self.entry.bind("<Return>", lambda e: self.submit())

        # main list: scrollable, no visible scrollbar
        self.wrap = tk.Frame(r, bg=BG)
        self.wrap.pack(fill="both", expand=True, padx=self.px(12), pady=(self.px(4), 0))
        self.canvas = tk.Canvas(self.wrap, bg=BG, highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)
        self.list = self.new_list()
        self.list_win = self.canvas.create_window(0, 0, window=self.list, anchor="nw")
        self.canvas.bind("<Configure>", self.on_resize)
        r.bind_all("<MouseWheel>", self.on_wheel)

        # assistant answer panel (overlays the list)
        self.panel = tk.Frame(self.wrap, bg=SURFACE)
        top = tk.Frame(self.panel, bg=SURFACE)
        top.pack(fill="x", padx=self.px(14), pady=(self.px(10), 0))
        tk.Label(top, text="Assistant", bg=SURFACE, fg=ACCENT, font=self.f_bold).pack(side="left")
        close = tk.Label(top, text="✕", bg=SURFACE, fg=DIM, font=self.f_body, cursor="hand2")
        close.pack(side="right")
        close.bind("<Button-1>", lambda e: self.hide_panel())
        self.answer = tk.Text(self.panel, bg=SURFACE, fg=TEXT, font=self.f_body, relief="flat", wrap="word",
                              highlightthickness=0, bd=0, padx=self.px(14), pady=self.px(8),
                              spacing2=self.px(3), cursor="arrow")
        self.answer.pack(fill="both", expand=True)

        # pop-up nudge (event reminders and check-ins; overlays the list)
        self.nudge = tk.Frame(self.wrap, bg=SURFACE)
        self.last_checkin = time.time()
        self.quiet_until = 0
        self.alerted = set()
        self.ticks = 0

        r.bind("<Escape>", self.on_escape)
        r.bind("<Control-q>", lambda e: r.destroy())
        r.bind("<Control-z>", self.undo_remove)
        r.protocol("WM_DELETE_WINDOW", r.iconify)  # ✕ minimises: it keeps watching your day
        self.width = 0
        self.sub_target = None
        self.goal_section = None  # "+ Add" on a goals heading: the input adds there
        self.editing = None       # the goal being edited inline
        self.hint_text = "? ask"
        for change in sync_goals():  # catch up on goal edits made while closed
            log_action(*change)
        self.load_reading()
        self.render()
        self.poll()
        self.watch()
        self.load_suggest_cache()
        self.root.after(15000, self.prefetch_suggestions)
        self.canvas.focus_set()  # keep the placeholder visible until clicked
        if self.cfg["pin"]:
            r.attributes("-topmost", True)

    # ---------- helpers ----------
    def px(self, v):
        return int(v * self.s)

    def dark_titlebar(self):
        try:
            self.root.update_idletasks()
            hwnd = ctypes.windll.user32.GetParent(self.root.winfo_id())
            on = ctypes.c_int(1)
            ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 20, ctypes.byref(on), 4)
            colour = ctypes.c_int(int(BG[5:7] + BG[3:5] + BG[1:3], 16))  # COLORREF is 0x00BBGGRR
            ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 35, ctypes.byref(colour), 4)
        except Exception:
            pass

    def now(self):
        return dt.datetime.now(local_tz())

    def background(self, kind, fn):
        threading.Thread(target=lambda: self.inbox.put((kind, fn())), daemon=True).start()

    def draw_inbar(self, e=None):
        c, w, h, rad = self.inbar, self.inbar.winfo_width(), self.inbar.winfo_height(), self.px(12)
        c.delete("bg")
        pts = [rad, 0, w - rad, 0, w, 0, w, rad, w, h - rad, w, h, w - rad, h, rad, h, 0, h, 0, h - rad, 0, rad, 0, 0]
        c.create_polygon(pts, smooth=True, fill=SURFACE, outline=LINE, tags="bg")
        c.tag_lower("bg")
        c.delete("hint")
        right = w - self.px(16)
        if self.sub_target or self.goal_section:  # a way out of "adding steps/goals" mode
            done = c.create_text(right, h // 2, text="Done", fill=TEXT, font=self.f_bold, anchor="e",
                                 tags=("hint", "done"))
            right = c.bbox(done)[0] - self.px(12)
            c.tag_bind("done", "<Button-1>", lambda e: self.on_escape())
            c.tag_bind("done", "<Enter>", lambda e: (c.itemconfigure("done", fill=ACCENT), c.configure(cursor="hand2")))
            c.tag_bind("done", "<Leave>", lambda e: (c.itemconfigure("done", fill=TEXT), c.configure(cursor="")))
        hint = c.create_text(right, h // 2, text=self.hint_text, fill=ACCENT if self.sub_target else FAINT,
                             font=self.f_small, anchor="e", tags="hint")
        x0 = c.bbox(hint)[0] if c.bbox(hint) else w - self.px(64)
        c.itemconfigure(self.entry_win, width=max(self.px(60), x0 - self.px(28)))

    def placeholder(self):
        return PLACEHOLDERS[self.tab]

    def clear_placeholder(self, e=None):
        if self.entry.get() in PLACEHOLDERS.values():
            self.entry.delete(0, "end")
            self.entry.configure(fg=TEXT)

    def restore_placeholder(self, e=None):
        if not self.entry.get() or self.entry.get() in PLACEHOLDERS.values():
            self.entry.delete(0, "end")
            self.entry.insert(0, self.placeholder())
            self.entry.configure(fg=DIM)

    def on_wheel(self, e):
        if self.panel.winfo_ismapped():
            return
        if self.canvas.bbox("all") and self.list.winfo_height() > self.canvas.winfo_height():
            self.canvas.yview_scroll(-1 * (e.delta // 120), "units")

    def on_resize(self, e):
        self.canvas.itemconfigure(self.list_win, width=e.width)
        if abs(e.width - self.width) > 4:
            self.width = e.width
            self.render_list()

    def on_escape(self, e=None):
        if self.nudge.winfo_ismapped():
            self.dismiss()
        elif self.sub_target:
            self.stop_subtask()
        elif self.editing:
            self.stop_edit()
        elif self.goal_section:
            self.stop_goal()
        elif self.panel.winfo_ismapped():
            self.hide_panel()
        else:
            self.root.iconify()

    def show(self):
        self.root.deiconify()
        self.root.lift()
        self.root.attributes("-topmost", True)
        self.root.after(150, lambda: self.root.attributes("-topmost", self.cfg["pin"]))
        self.root.focus_force()
        self.entry.focus_set()
        self.last_checkin = time.time()  # you just looked: restart the check-in clock
        self.render()
        self.prefetch_suggestions()

    def wrap_px(self, indent=64):
        return max(self.px(160), (self.width or self.px(410)) - self.px(indent))

    def new_list(self):
        f = tk.Frame(self.canvas, bg=BG)
        f.bind("<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        return f

    def inside(self, area):
        """Is the pointer over `area` or one of its children? Moving between the
        parts of a row fires Leave then Enter; checking this avoids a flash."""
        try:
            w = self.root.winfo_containing(*self.root.winfo_pointerxy())
        except (KeyError, tk.TclError):
            return False
        a = str(area)
        return w is not None and (str(w) == a or str(w).startswith(a + "."))

    def clickable(self, widgets, on_click, on_hover, area=None):
        area = area or widgets[0]
        for w in widgets:
            w.bind("<Enter>", lambda e: on_hover(True))
            w.bind("<Leave>", lambda e: on_hover(self.inside(area)))
            if on_click:
                w.bind("<Button-1>", lambda e: on_click())

    def heading(self, text, action=None, on_action=None):
        row = tk.Frame(self.list, bg=BG)
        row.pack(fill="x", padx=self.px(8), pady=(self.px(12), self.px(2)))
        tk.Label(row, text=text.upper(), bg=BG, fg=FAINT, font=self.f_head).pack(side="left")
        if action:
            a = tk.Label(row, text=action, bg=BG, fg=ACCENT, font=self.f_small, cursor="hand2")
            a.pack(side="right")
            a.bind("<Button-1>", lambda e: on_action())
        return row

    def note(self, text, colour=FAINT, pady=6):
        tk.Label(self.list, text=text, bg=BG, fg=colour, font=self.f_small, anchor="w", justify="left",
                 wraplength=self.wrap_px(30)).pack(fill="x", padx=self.px(8), pady=self.px(pady))

    def row(self, title, meta="", indent=0, wrap=64):
        """A full-width row; returns (frame, leading-slot, [hoverable widgets])."""
        row = tk.Frame(self.list, bg=BG, cursor="hand2")
        row.pack(fill="x", pady=1)
        lead = tk.Frame(row, bg=BG)
        lead.pack(side="left", anchor="n", padx=(self.px(8) + indent, self.px(10)), pady=self.px(8))
        txt = tk.Frame(row, bg=BG)
        txt.pack(side="left", fill="x", expand=True, pady=self.px(6))
        parts = [row, lead, txt]
        if title is not None:
            t = tk.Label(txt, text=title, bg=BG, fg=TEXT, font=self.f_body, anchor="w", justify="left",
                         wraplength=self.wrap_px(wrap), cursor="hand2")
            t.pack(fill="x")
            parts.append(t)
        if meta:
            m = tk.Label(txt, text=meta, bg=BG, fg=DIM, font=self.f_small, anchor="w", cursor="hand2",
                         justify="left", wraplength=self.wrap_px(wrap))
            m.pack(fill="x")
            parts.append(m)
        return row, lead, txt, parts

    def circle(self, parent, kind, small=False):
        """Drawn 20px marker: 'open', 'done' or 'add'. Returns (canvas, paint(hover))."""
        size = self.px(16 if small else 20)
        c = tk.Canvas(parent, width=size, height=size, bg=BG, highlightthickness=0, cursor="hand2")
        c.pack()
        p, q = self.px(2), size - self.px(3)

        def paint(hover=False):
            c.configure(bg=HOVER if hover else BG)
            c.delete("all")
            if kind == "done":
                c.create_oval(p, p, q, q, fill=ACCENT, outline=ACCENT)
                c.create_line(size * .3, size * .5, size * .45, size * .65, size * .7, size * .37,
                              fill=BG, width=self.px(2), capstyle="round", joinstyle="round")
            else:
                c.create_oval(p, p, q, q, outline=ACCENT if hover else FAINT, width=self.px(1.6),
                              dash=(2, 2) if kind == "add" else None)
                if kind == "add":
                    m = size / 2 - .5
                    c.create_line(m - 4 * self.s, m, m + 4 * self.s, m, fill=ACCENT, width=self.px(1.5))
                    c.create_line(m, m - 4 * self.s, m, m + 4 * self.s, fill=ACCENT, width=self.px(1.5))
        return c, paint

    def hover_paint(self, parts, marker_paint=None):
        state = [None]

        def paint(hover):
            if state[0] == hover:  # only repaint when it actually changes
                return
            state[0] = hover
            for w in parts:
                w.configure(bg=HOVER if hover else BG)
            if marker_paint:
                marker_paint(hover)
        return paint

    # ---------- rendering ----------
    def switch(self, name):
        self.tab = name
        if self.sub_target:
            self.stop_subtask()
        if name != "Goals" and (self.goal_section or self.editing):
            self.editing = None
            self.stop_goal()
        if self.root.focus_get() is not self.entry:
            self.restore_placeholder()
        self.render_list()
        self.canvas.yview_moveto(0)

    def render(self):
        now = self.now()
        self.date_lbl.configure(text=now.strftime("%a %d %b").replace(" 0", " "))
        self.clock.configure(text=now.strftime("%H:%M"))
        hm = now.strftime("%H:%M")
        upcoming = [e for e in load_events(now.date()) if not e[0] or e[0] >= hm]
        self.todos = load_todos()
        today = self.todos["Today"]
        done = sum(t.done for t in today)
        if upcoming:
            nxt = f"Next  {upcoming[0][0] or 'all day'}  {upcoming[0][1]}"
        else:
            tom = load_events(now.date() + dt.timedelta(days=1))
            nxt = f"Tomorrow  {tom[0][0] or 'all day'}  {tom[0][1]}" if tom else "Calendar clear"
        self.summary.configure(text=f"{nxt}   ·   {done}/{len(today)} done" if today else nxt)
        self.render_list()
        self.sig = self.files_sig()  # our own writes are now on screen: the watcher can skip them

    def files_sig(self):
        try:
            return tuple(p.read_text(encoding="utf-8") if p.exists() else "" for p in (TODOS, CAL, GOALS))
        except OSError:
            return self.sig

    def render_list(self):
        if not hasattr(self, "todos"):
            return
        open_today = sum(not t.done for t in self.todos["Today"])
        counts = {"Todo": open_today, "Day": len(load_events(self.now().date())), "Goals": 0}
        for name in TABS + ["Settings"]:
            lbl, bar = self.tab_widgets[name]
            if name in counts:
                lbl.configure(text=f"{name}  {counts[name]}" if counts[name] else name)
            lbl.configure(fg=TEXT if name == self.tab else DIM)
            bar.configure(bg=ACCENT if name == self.tab else BG)
        # build the new list off-screen, then swap it in: no half-drawn frames
        old, self.list = self.list, self.new_list()
        {"Todo": self.render_todo, "Day": self.render_day, "Goals": self.render_goals,
         "Settings": self.render_settings}[self.tab]()
        self.canvas.itemconfigure(self.list_win, window=self.list)
        old.destroy()

    def render_todo(self):
        s = self.suggestions
        if s is None:
            label = "✦ Suggest"
        elif s == "loading":
            label = "✦ Thinking…"
        elif isinstance(s, list):
            label = "Hide"
        else:
            label = "✦ Retry"
        self.todo_rows, self.section_heads = [], {}  # for drag and drop
        for i, section in enumerate(TODO_SECTIONS):
            items = sorted(self.todos[section], key=lambda t: t[0])  # open first, done last
            if i == 0:
                self.section_heads[section] = self.heading(section, label, self.on_suggest)
                self.render_suggestions()
            else:  # shown even when empty, so a todo can be dragged there
                self.section_heads[section] = self.heading(section)
            if not items and i == 0:
                self.note("Nothing for today yet.")
            for t in items:
                self.todo_row(t, section=section)
                for s in t.subs:  # file order: steps usually have a sequence
                    self.todo_row(s, parent=t, section=section)

    def render_suggestions(self):
        s = self.suggestions
        if isinstance(s, str) and s != "loading":
            self.note(s[:200], colour=DIM)
        if not isinstance(s, list):
            return
        if LAST_SOURCE["name"]:
            self.note(f"via {LAST_SOURCE['name']}", pady=2)
        if not s:
            self.note("No new suggestions — you're covered.")
        for todo, why in s:
            row, lead, txt, parts = self.row(todo, why)
            parts[3].configure(fg=DIM)  # suggestions read as ghosts until accepted
            c, mark = self.circle(lead, "add")
            paint = self.hover_paint(parts + [c], mark)
            paint(False)
            self.clickable(parts + [c], lambda t=todo: self.accept_suggestion(t), paint)

    def todo_row(self, todo, parent=None, section=None):
        """A tickable row. Subtasks sit indented under their task, smaller.
        Click ticks it; press and drag moves it (steps move within their task)."""
        title, meta = tidy(todo.text)
        if todo.subs:
            n = sum(s.done for s in todo.subs)
            meta = "  ·  ".join(x for x in (f"{n}/{len(todo.subs)} steps", meta) if x)
        sub = parent is not None
        row, lead, txt, parts = self.row(title, "" if todo.done else meta,
                                         indent=self.px(30) if sub else 0, wrap=110 if sub else 90)
        t = parts[3]
        size = self.f_body[1] - (1 if sub else 0)
        font = tkfont.Font(family=self.f_body[0], size=size, overstrike=todo.done)
        t.configure(font=font, fg=FAINT if todo.done else (DIM if sub else TEXT))
        row._font = font  # keep a reference so the overstrike font isn't collected
        c, mark = self.circle(lead, "done" if todo.done else "open", small=sub)
        hover_parts = parts + [c]
        # ✕ remove: hidden until you hover the row
        x = tk.Label(row, text="✕", bg=BG, fg=BG, font=self.f_small, cursor="hand2")
        x.pack(side="right", anchor="n", padx=(0, self.px(10)), pady=self.px(7))
        x.bind("<Button-1>", lambda e: self.on_remove(todo))
        hover_parts.append(x)
        if not sub:
            active = self.sub_target is not None and self.sub_target.raw == todo.raw
            plus = tk.Label(row, text="Done" if active else "+", bg=BG, fg=ACCENT if active else FAINT,
                            font=self.f_bold if active else (self.f_body[0], 13), cursor="hand2")
            plus.pack(side="right", anchor="n", padx=(0, self.px(10)), pady=self.px(6 if active else 3))
            plus.bind("<Button-1>", lambda e: self.stop_subtask() if active else self.start_subtask(todo))
            hover_parts.append(plus)
        paint = self.hover_paint(hover_parts, lambda h: (mark(h), x.configure(fg=FAINT if h else BG)))
        paint(False)
        self.clickable(parts + [c], None, paint)
        self.todo_rows.append((todo, parent, row, section))
        for w in parts + [c]:
            w.bind("<Button-1>", lambda e: self.drag_start(e, todo, parent, row))
            w.bind("<B1-Motion>", self.drag_move)
            w.bind("<ButtonRelease-1>", self.drag_end)
        x.bind("<Enter>", lambda e: (paint(True), x.configure(fg=ACCENT), self.flash_hint("Remove (archived)")))
        x.bind("<Leave>", lambda e: (x.configure(fg=FAINT), paint(self.inside(row))))
        if not sub:
            plus.bind("<Enter>", lambda e: (paint(True), plus.configure(fg=ACCENT)))
            plus.bind("<Leave>", lambda e: (plus.configure(fg=ACCENT if active else FAINT), paint(self.inside(row))))

    def render_day(self):
        now = self.now()
        day = now.date() + dt.timedelta(days=self.day_offset)
        name = {0: "Today", 1: "Tomorrow", -1: "Yesterday"}.get(self.day_offset, day.strftime("%A"))
        nav = tk.Frame(self.list, bg=BG)
        nav.pack(fill="x", padx=self.px(8), pady=(self.px(10), self.px(4)))
        for text, step, side in (("‹", -1, "left"), ("›", 1, "right")):
            b = tk.Label(nav, text=text, bg=BG, fg=DIM, font=(self.f_title[0], 14), cursor="hand2")
            b.pack(side=side)
            b.bind("<Button-1>", lambda e, st=step: self.move_day(st))
        lbl = tk.Label(nav, text=f"{name}  ·  {day.strftime('%a %d %b').replace(' 0', ' ')}", bg=BG,
                       fg=TEXT, font=self.f_bold, cursor="hand2")
        lbl.pack(side="left", expand=True)
        lbl.bind("<Button-1>", lambda e: self.move_day(-self.day_offset))

        events = load_events(day)
        if not events:
            self.note("Nothing on the calendar.", pady=16)
        hm = now.strftime("%H:%M")
        marked = self.day_offset != 0
        for t, title, loc in events:
            past = self.day_offset < 0 or (self.day_offset == 0 and t is not None and t < hm)
            if not marked and not past:
                line = tk.Frame(self.list, bg=BG)
                line.pack(fill="x", padx=self.px(8), pady=self.px(2))
                tk.Label(line, text=f"now {hm}", bg=BG, fg=NOW, font=self.f_head).pack(side="left")
                tk.Frame(line, bg=NOW, height=1).pack(side="left", fill="x", expand=True, padx=(self.px(6), 0))
                marked = True
            row = tk.Frame(self.list, bg=BG)
            row.pack(fill="x", pady=self.px(3))
            tk.Label(row, text=t or "all day", bg=BG, fg=FAINT if past else ACCENT, font=self.f_bold,
                     width=6, anchor="nw").pack(side="left", anchor="n", padx=(self.px(8), self.px(6)))
            txt = tk.Frame(row, bg=BG)
            txt.pack(side="left", fill="x", expand=True)
            tk.Label(txt, text=title, bg=BG, fg=FAINT if past else TEXT, font=self.f_body, anchor="w",
                     justify="left", wraplength=self.wrap_px(90)).pack(fill="x")
            if loc and not past:
                loc = "online" if loc.startswith("http") else loc
                tk.Label(txt, text=loc, bg=BG, fg=DIM, font=self.f_small, anchor="w").pack(fill="x")
        if not marked and events:
            self.note(f"Done for the day  ·  now {hm}", colour=NOW)

    def render_goals(self):
        for heading, goals in load_goals():
            add = "+ Add" if self.goal_section != heading else "Adding…"
            self.heading(heading, add, lambda h=heading: self.start_goal(h))
            if not goals:
                self.note("Nothing yet. Click + Add, type the goal and press Enter.")
            for g in goals:
                if self.editing and self.editing.raw == g.raw:
                    self.goal_editor(g)
                else:
                    self.goal_row(g, heading)

        self.heading("Reading  ·  matched to your goals", "↻ Refresh", self.refresh_reading)
        if self.reading is None:
            self.note("Fetching articles…")
            return
        if not self.reading:
            self.note("Nothing new. Paste a Substack or blog URL below to add a source.")
        for it, hits in self.reading:
            age = ""
            if it["ts"]:
                days = int((time.time() - it["ts"]) // 86400)
                age = "today" if days == 0 else f"{days}d"
            meta = "  ·  ".join(x for x in (it["source"], age, hits[0] if hits else "") if x)
            title = it["title"] if len(it["title"]) < 110 else it["title"][:107] + "…"
            row, lead, txt, parts = self.row(title, meta)
            dot = tk.Label(lead, text="↗", bg=BG, fg=FAINT, font=self.f_small)
            dot.pack()
            paint = self.hover_paint(parts + [dot])
            self.clickable(parts + [dot], lambda u=it["link"]: webbrowser.open(u), paint)

    def goal_row(self, g, section):
        """Click the text to edit. Hover shows: ↕ move · ✓ achieved · ✕ remove."""
        today = self.now().date()
        row = tk.Frame(self.list, bg=BG)
        row.pack(fill="x", pady=self.px(2))
        dot = tk.Label(row, text="◆", bg=BG, fg=ACCENT, font=(self.f_small[0], 7))
        dot.pack(side="left", anchor="n", padx=(self.px(12), self.px(10)), pady=self.px(5))
        acts = tk.Frame(row, bg=BG)
        acts.pack(side="right", anchor="n", padx=(0, self.px(8)), pady=self.px(2))
        other = GOAL_SECTIONS[1 - GOAL_SECTIONS.index(section)]
        icons = []
        for glyph, tip, fn in (("↕", f"Move to {other}", lambda: self.goal_action(move_goal, g, other)),
                               ("✓", "Achieved", lambda: self.goal_action(move_goal, g, "Achieved")),
                               ("✕", "Remove (archived)", lambda: self.goal_action(remove_goal, g))):
            b = tk.Label(acts, text=glyph, bg=BG, fg=BG, font=self.f_body, cursor="hand2", padx=self.px(4))
            b.pack(side="left")
            b.bind("<Button-1>", lambda e, fn=fn: fn())
            icons.append((b, tip))
        txt = tk.Frame(row, bg=BG, cursor="xterm")
        txt.pack(side="left", fill="x", expand=True)
        parts = [row, dot, acts, txt]
        t = tk.Label(txt, text=g.text, bg=BG, fg=TEXT, font=self.f_body, anchor="w", justify="left",
                     wraplength=self.wrap_px(110), cursor="xterm")
        t.pack(fill="x")
        parts.append(t)
        if g.date:
            days = (g.date - today).days
            when = ("today" if days == 0 else "tomorrow" if days == 1
                    else f"in {days} days" if days > 1 else f"{-days}d ago")
            d = tk.Label(txt, text=f"{g.date.strftime('%a %d %b').replace(' 0', ' ')}  ·  {when}", bg=BG,
                         fg=NOW if 0 <= days <= 7 else DIM, font=self.f_small, anchor="w", cursor="xterm")
            d.pack(fill="x")
            parts.append(d)

        def hover(on):
            for w in parts + [b for b, _ in icons]:
                w.configure(bg=HOVER if on else BG)
            for b, _ in icons:
                b.configure(fg=FAINT if on else BG)
        for b, tip in icons:
            b.bind("<Enter>", lambda e, b=b, tip=tip: (hover(True), b.configure(fg=ACCENT), self.flash_hint(tip)))
            b.bind("<Leave>", lambda e, b=b: (b.configure(fg=FAINT), hover(self.inside(row))))
        for w in parts:
            w.bind("<Enter>", lambda e: hover(True))
            w.bind("<Leave>", lambda e: hover(self.inside(row)))
        for w in (txt, t) + tuple(parts[5:]):
            w.bind("<Button-1>", lambda e: self.start_edit(g))

    def goal_editor(self, g):
        """Inline: goal text and date (YYYY-MM-DD, '4 Dec', or empty). Enter saves, Esc cancels."""
        box = tk.Frame(self.list, bg=SURFACE)
        box.pack(fill="x", padx=self.px(6), pady=self.px(3))
        text = tk.Entry(box, bg=SURFACE, fg=TEXT, insertbackground=TEXT, relief="flat", font=self.f_body,
                        highlightthickness=1, highlightbackground=LINE, highlightcolor=ACCENT, bd=0)
        text.insert(0, g.text)
        text.pack(fill="x", padx=self.px(10), pady=(self.px(10), self.px(6)), ipady=self.px(4))
        row = tk.Frame(box, bg=SURFACE)
        row.pack(fill="x", padx=self.px(10), pady=(0, self.px(10)))
        tk.Label(row, text="Date", bg=SURFACE, fg=DIM, font=self.f_small).pack(side="left")
        date = tk.Entry(row, bg=SURFACE, fg=TEXT, insertbackground=TEXT, relief="flat", font=self.f_body, width=12,
                        highlightthickness=1, highlightbackground=LINE, highlightcolor=ACCENT, bd=0)
        date.insert(0, g.date.isoformat() if g.date else "")
        date.pack(side="left", padx=(self.px(8), 0), ipady=self.px(3))
        tk.Label(row, text="optional", bg=SURFACE, fg=FAINT, font=self.f_small).pack(side="left", padx=self.px(6))

        def save(e=None):
            title = text.get().strip()
            if not title:
                return
            d = date.get().strip()
            when = parse_goal_input("x " + d)[1] if d else None
            if d and not when:
                date.configure(highlightbackground="#f7768e")  # unreadable date: say so, don't guess
                return
            self.editing = None
            self.goal_action(update_goal, g, title, when)
        self.button(row, "Save", save, primary=True).pack(side="right")
        cancel = tk.Label(row, text="Cancel", bg=SURFACE, fg=DIM, font=self.f_small, cursor="hand2")
        cancel.pack(side="right", padx=self.px(10))
        cancel.bind("<Button-1>", lambda e: self.stop_edit())
        for w in (text, date):
            w.bind("<Return>", save)
            w.bind("<Escape>", lambda e: (self.stop_edit(), "break")[1])
        text.focus_set()
        text.icursor("end")

    def render_settings(self):
        c = self.cfg
        self.heading("Pop-ups")
        self.setting("Check-ins", lambda p: self.toggle(p, "checkins"))
        self.setting("Check in every", lambda p: self.stepper(p, "checkin_minutes", 5, 5, 240, "{} min"))
        self.setting("Check-in hours", lambda p: self.hours(p))
        self.setting("Event reminders", lambda p: self.toggle(p, "event_reminders"))
        self.setting("Remind me before events", lambda p: self.stepper(p, "event_lead_minutes", 5, 5, 60, "{} min"))
        self.setting("Sound", lambda p: self.toggle(p, "sound"))
        if time.time() < self.quiet_until:
            left = int((self.quiet_until - time.time()) // 60)
            self.setting(f"Quiet for {left // 60}h {left % 60:02d}m",
                         lambda p: self.link(p, "Resume", lambda: self.set_quiet(0)))
        else:
            self.setting("Pause pop-ups", lambda p: self.link(p, "Quiet 2h", lambda: self.set_quiet(2)))
        self.setting("Try it", lambda p: self.link(
            p, "Show a check-in", lambda: self.pop("Check-in", *self.checkin_content(self.now()))))

        self.heading("Window")
        self.setting("Keep on top", lambda p: self.toggle(p, "pin"))
        self.setting("Open on tab", lambda p: self.cycle(p, "start_tab", TABS))

        self.heading("Assistant")
        self.setting("Answered by", lambda p: self.cycle(p, "assistant", ["auto", "api", "local"]))
        models = local_models()
        if models:
            self.setting("Local model", lambda p: self.cycle(p, "local_model", models))
        else:
            self.setting("Local model", lambda p: tk.Label(p, text="Ollama not running", bg=BG, fg=FAINT,
                                                            font=self.f_small).pack(side="right"), dim=True)
        api_n, local_n = ai_calls_today()
        self.setting("AI calls today", lambda p: tk.Label(p, text=f"{api_n} API · {local_n} local", bg=BG,
                                                          fg=DIM, font=self.f_small).pack(side="right"))
        self.note(f"auto: {api_name(c)} first, then {c['local_model']} on this PC when it can't answer. "
                  "local: private and offline, but it only sees your profile, goals, todos, calendar "
                  "and the notes that match your question. The API is only called when you press "
                  "Suggest or ask with ?; suggestions are kept for 2 h while your files don't change. "
                  "Every call is listed in logs/ai-calls.log.")
        self.setting("Model for ? and Suggest", lambda p: self.cycle(p, "model", ["sonnet", "haiku", "opus"]))

        self.heading("Reading")
        self.setting("Refresh every", lambda p: self.stepper(p, "feed_hours", 1, 1, 24, "{} h"))
        for f in load_feed_config()["feeds"]:
            self.setting(f["name"], lambda p, u=f["url"]: self.link(p, "Remove", lambda: self.drop_feed(u), FAINT),
                         dim=True)
        interests = load_feed_config().get("interests", [])
        self.note("Interests: " + (", ".join(interests) or "none") +
                  "\nType a word below to add it; -word removes it. Paste a URL to add a source.")
        self.note(f"Saved in {UI_CFG.relative_to(ROOT)} and {FEEDS.relative_to(ROOT)}.", pady=10)

    def setting(self, label, build, dim=False):
        row = tk.Frame(self.list, bg=BG)
        row.pack(fill="x", padx=self.px(8), pady=self.px(3))
        tk.Label(row, text=label, bg=BG, fg=DIM if dim else TEXT, font=self.f_body, anchor="w").pack(side="left")
        right = tk.Frame(row, bg=BG)
        right.pack(side="right")
        build(right)

    def save_setting(self, key, value):
        self.cfg[key] = value
        saved = {}
        try:
            saved = json.loads(UI_CFG.read_text(encoding="utf-8"))
        except Exception:
            pass
        saved[key] = value
        UI_CFG.write_text(json.dumps(saved, indent=2) + "\n", encoding="utf-8")
        if key == "pin":
            self.root.attributes("-topmost", value)
        self.render_list()

    def toggle(self, parent, key):
        w, h = self.px(34), self.px(18)
        cv = tk.Canvas(parent, width=w, height=h, bg=BG, highlightthickness=0, cursor="hand2")
        cv.pack()
        on = bool(self.cfg[key])
        r = h / 2
        cv.create_oval(0, 0, h, h, fill=ACCENT if on else LINE, outline="")
        cv.create_oval(w - h, 0, w, h, fill=ACCENT if on else LINE, outline="")
        cv.create_rectangle(r, 0, w - r, h, fill=ACCENT if on else LINE, outline="")
        k = self.px(3)
        x = w - h + k if on else k
        cv.create_oval(x, k, x + h - 2 * k, h - k, fill=BG if on else DIM, outline="")
        cv.bind("<Button-1>", lambda e: self.save_setting(key, not on))

    def stepper(self, parent, key, step, lo, hi, fmt):
        val = self.cfg[key]
        for text, d in (("−", -step), (None, 0), ("+", step)):
            if text is None:
                tk.Label(parent, text=fmt.format(val), bg=BG, fg=TEXT, font=self.f_bold, width=7).pack(side="left")
                continue
            b = tk.Label(parent, text=text, bg=BG, fg=DIM, font=(self.f_body[0], 12), cursor="hand2", padx=self.px(4))
            b.pack(side="left")
            b.bind("<Button-1>", lambda e, d=d: self.save_setting(key, min(hi, max(lo, val + d))))
            b.bind("<Enter>", lambda e, b=b: b.configure(fg=ACCENT))
            b.bind("<Leave>", lambda e, b=b: b.configure(fg=DIM))

    def hours(self, parent):
        """Two half-hour steppers for the check-in window, e.g. 08:00 – 22:00."""
        start, end = self.cfg["active_hours"]
        mins = lambda s: int(s[:2]) * 60 + int(s[3:])
        fmt = lambda m: f"{m // 60:02d}:{m % 60:02d}"
        for i, (val, lo, hi) in enumerate(((mins(start), 0, mins(end) - 30), (mins(end), mins(start) + 30, 24 * 60 - 30))):
            if i:
                tk.Label(parent, text="–", bg=BG, fg=FAINT, font=self.f_body).pack(side="left")
            for text, d in (("‹", -30), (None, 0), ("›", 30)):
                if text is None:
                    tk.Label(parent, text=fmt(val), bg=BG, fg=TEXT, font=self.f_bold).pack(side="left")
                    continue
                b = tk.Label(parent, text=text, bg=BG, fg=DIM, font=(self.f_body[0], 12), cursor="hand2",
                             padx=self.px(3))
                b.pack(side="left")

                def go(e, i=i, val=val, d=d, lo=lo, hi=hi):
                    pair = list(self.cfg["active_hours"])
                    pair[i] = fmt(min(hi, max(lo, val + d)))
                    self.save_setting("active_hours", pair)
                b.bind("<Button-1>", go)

    def cycle(self, parent, key, options):
        val = self.cfg[key]
        nxt = options[(options.index(val) + 1) % len(options)] if val in options else options[0]
        self.link(parent, f"{val}  ›", lambda: self.save_setting(key, nxt), TEXT)

    def link(self, parent, text, command, colour=ACCENT):
        b = tk.Label(parent, text=text, bg=BG, fg=colour, font=self.f_bold, cursor="hand2")
        b.pack(side="left")
        b.bind("<Button-1>", lambda e: command())
        b.bind("<Enter>", lambda e: b.configure(fg=ACCENT if colour != ACCENT else TEXT))
        b.bind("<Leave>", lambda e: b.configure(fg=colour))

    def set_quiet(self, hours):
        self.quiet_until = time.time() + hours * 3600 if hours else 0
        self.render_list()

    def drop_feed(self, url):
        cfg = load_feed_config()
        cfg["feeds"] = [f for f in cfg["feeds"] if f["url"] != url]
        FEEDS.write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")
        self.reading = None
        self.load_reading()
        self.render_list()

    # ---------- actions ----------
    def move_day(self, step):
        self.day_offset += step
        self.render_list()

    def on_toggle(self, todo):
        toggle_todo(todo.idx, todo.raw)
        self.render()

    # ---------- drag to reorder ----------
    def drag_start(self, e, todo, parent, row):
        self.drag = {"todo": todo, "parent": parent, "row": row, "y0": e.y_root, "moving": False}

    def drop_slots(self, todo, parent):
        """Where the dragged row could land: [(y, section, before_raw)] in list coordinates."""
        def top(w):
            return w.winfo_y()

        def bottom(w):
            return w.winfo_y() + w.winfo_height()
        if parent is not None:  # a step: only within its own task
            own = [(t, r) for t, p, r, _ in self.todo_rows if p is not None and p.raw == parent.raw]
            return [(top(r), None, t.raw) for t, r in own] + [(bottom(own[-1][1]), None, None)]
        slots = []
        for section in TODO_SECTIONS:
            blocks = []  # [task, top, bottom including its steps]
            for t, p, r, sec in self.todo_rows:
                if sec != section:
                    continue
                if p is None:
                    blocks.append([t, top(r), bottom(r)])
                elif blocks:
                    blocks[-1][2] = bottom(r)
            slots += [(y0, section, t.raw) for t, y0, _ in blocks]
            head = self.section_heads[section]
            slots.append((blocks[-1][2] if blocks else bottom(head), section, None))
        return slots

    def drag_move(self, e):
        d = self.drag
        if not d:
            return
        if not d["moving"]:
            if abs(e.y_root - d["y0"]) < self.px(6):
                return
            d["moving"] = True
            d["slots"] = self.drop_slots(d["todo"], d["parent"])
            d["line"] = tk.Frame(self.list, bg=ACCENT, height=self.px(2))
        # scroll when dragging near the top or bottom edge
        cy = e.y_root - self.canvas.winfo_rooty()
        if cy < self.px(24):
            self.canvas.yview_scroll(-1, "units")
        elif cy > self.canvas.winfo_height() - self.px(24):
            self.canvas.yview_scroll(1, "units")
        y = e.y_root - self.list.winfo_rooty()
        d["slot"] = min(d["slots"], key=lambda s: abs(s[0] - y))
        indent = self.px(38) if d["parent"] is not None else self.px(8)
        d["line"].place(x=indent, y=d["slot"][0] - self.px(1), relwidth=1, width=-indent - self.px(8))
        d["line"].lift()

    def drag_end(self, e):
        d, self.drag = self.drag, None
        if not d:
            return
        if not d["moving"]:  # a plain click: tick it
            self.on_toggle(d["todo"])
            return
        _, section, before = d.get("slot", (0, None, d["todo"].raw))
        t = d["todo"]
        if d["parent"] is not None:
            move_step(t.idx, t.raw, d["parent"].raw, before)
        elif move_todo(t.idx, t.raw, section, before):
            old = next((sec for x, p, _, sec in self.todo_rows if x.raw == t.raw and p is None), None)
            if old != section:
                log_action("update", "todos.md", f"moved todo to {section}: {tidy(t.text)[0]}")
        self.render()

    def on_remove(self, todo):
        result = remove_todo(todo.idx, todo.raw)
        if not result:
            return
        what, before, after = result
        log_action("update", "todos.md", what)
        self.undo = (before, after)
        if self.sub_target and self.sub_target.raw == todo.raw:
            self.stop_subtask()
        self.render()
        self.flash_hint("Removed · Ctrl+Z undo", 5000)

    def undo_remove(self, e=None):
        if self.undo and restore_todos(*self.undo):
            log_action("update", "todos.md", "restored the last removed todo (Ctrl+Z)")
            self.render()
            self.flash_hint("Restored")
        self.undo = None

    def goal_action(self, fn, *args):
        """Run a goal edit, then propagate it (calendar, event notes, reading) and log it."""
        what = fn(*args)
        if what:
            log_action("update", "me/goals.md", what)
            self.after_goals_change()
        self.render()

    def after_goals_change(self):
        for action, path, why in sync_goals():
            log_action(action, path, why)
        if self.reading is not None:
            self.load_reading(rank_only=True)

    def start_goal(self, section):
        self.switch("Goals")
        self.goal_section = section
        self.hint_text = f"↳ {section}"
        self.draw_inbar()
        self.clear_placeholder()
        self.entry.focus_set()
        self.render_list()

    def start_edit(self, g):
        self.editing = g
        self.render_list()

    def stop_edit(self):
        self.editing = None
        self.render_list()

    def flash_hint(self, text, ms=1500):
        if self.sub_target or self.goal_section:
            return
        self.hint_text = text
        self.draw_inbar()
        self.root.after(ms, lambda: (setattr(self, "hint_text", "? ask"), self.draw_inbar())
                        if self.hint_text == text else None)

    def start_subtask(self, todo):
        """Next Enter in the input adds a step under this task, until you press
        Done (in the input bar or on the task), Enter on an empty line, or Esc."""
        self.sub_target = todo
        self.hint_text = "↳ steps for " + (lambda s: s if len(s) <= 16 else s[:15] + "…")(tidy(todo.text)[0])
        self.clear_placeholder()
        self.draw_inbar()
        self.entry.focus_set()
        self.render_list()

    def stop_goal(self):
        self.goal_section = None
        self.hint_text = "? ask"
        self.draw_inbar()
        self.render_list()

    def stop_subtask(self):
        """Back to normal: Enter adds a new task again."""
        self.sub_target = None
        self.hint_text = "? ask"
        self.draw_inbar()
        if self.tab == "Todo":
            self.render_list()

    def cache_fresh(self):
        c = self.suggest_cache
        return c is not None and c[0] == self.cache_key() and time.time() - c[1] < 7200

    def cache_key(self):
        """Changes when todos, calendar or goals change, or the day does."""
        sig = "\x00".join(self.sig or ()) + self.now().strftime("%Y-%m-%d")
        return __import__("hashlib").sha1(sig.encode("utf-8")).hexdigest()

    def save_suggestions(self, items):
        self.suggest_cache = (self.cache_key(), time.time(), items, LAST_SOURCE["name"])
        try:
            SUGGEST_CACHE.write_text(json.dumps(self.suggest_cache), encoding="utf-8")
        except OSError:
            pass

    def load_suggest_cache(self):
        try:
            key, at, items, source = json.loads(SUGGEST_CACHE.read_text(encoding="utf-8"))
            self.suggest_cache = (key, at, [tuple(i) for i in items], source)
        except Exception:
            self.suggest_cache = None

    def prefetch_suggestions(self):
        """Work out suggestions in the background so ✦ Suggest is instant, but only
        with the free local model and only while the window is open: the API is
        never called without a click."""
        if next_source() != "local" or self.root.state() != "normal":
            return
        if not self.cache_fresh() and not self.prefetching and self.suggestions != "loading":
            self.prefetching = True
            self.background("prefetch", lambda: suggest_todos(self.now()))

    def on_suggest(self):
        if isinstance(self.suggestions, list):
            self.suggestions = None
        elif self.cache_fresh():
            self.suggestions = self.suggest_cache[2]  # files unchanged since last time: no need to ask again
            LAST_SOURCE["name"] = self.suggest_cache[3]
        elif self.prefetching:  # already on its way: show it when it lands
            self.suggestions = "loading"
        elif self.suggestions != "loading":
            self.suggestions = "loading"
            self.background("suggestions", lambda: suggest_todos(self.now()))
        self.render_list()

    def accept_suggestion(self, todo):
        add_todo(todo, "Today")
        self.suggestions = [s for s in self.suggestions if s[0] != todo]
        self.render()

    def load_reading(self, rank_only=False):
        try:
            cache = json.loads(FEED_CACHE.read_text(encoding="utf-8"))
        except Exception:
            cache = {"fetched": 0, "items": []}
        if cache["items"]:
            self.reading = rank_reading(cache["items"], goal_texts())
        if not rank_only and time.time() - cache["fetched"] > self.cfg["feed_hours"] * 3600:
            self.background("reading", fetch_all)

    def refresh_reading(self):
        self.reading = None
        self.render_list()
        self.background("reading", fetch_all)

    def submit(self):
        text = self.entry.get().strip()
        if not text or text in PLACEHOLDERS.values():
            if self.sub_target or self.goal_section:  # Enter on an empty line: done adding
                self.on_escape()
            return
        self.entry.delete(0, "end")
        if self.sub_target and not text.startswith("?"):
            add_subtask(self.sub_target.idx, self.sub_target.raw, text)
            # keep adding steps to the same task until Done; re-find it after the write
            self.todos = load_todos()
            for t in [x for s in self.todos.values() for x in s]:
                if t.text == self.sub_target.text:
                    self.sub_target = t
            self.render()
            return
        if text.startswith("?"):
            q = text.lstrip("? ").strip()
            if q:
                self.show_panel(q)
                self.background("answer", lambda: ask_assistant(q, self.now()))
        elif self.tab == "Settings" and not re.match(r"^https?://", text):
            edit_interest(text)
            self.render_list()
        elif self.tab in ("Goals", "Settings") and re.match(r"^https?://", text):
            if add_feed(text):
                self.refresh_reading()
        elif self.tab == "Goals":
            self.goal_action(add_goal, text, self.goal_section or GOAL_SECTIONS[0])
        else:
            add_todo(text, "Today")
            self.render()

    def show_panel(self, question):
        self.panel.place(in_=self.wrap, x=0, y=0, relwidth=1, relheight=1)
        self.set_answer(f"{question}\n\n", "Thinking")
        self.thinking = 0
        self.animate()

    def animate(self):
        if self.thinking is None or not self.panel.winfo_ismapped():
            return
        self.thinking = (self.thinking + 1) % 4
        self.answer.configure(state="normal")
        if self.answer.tag_ranges("dots"):
            self.answer.delete("dots.first", "end")
        self.answer.insert("end", "Thinking" + "." * self.thinking, "dots")
        self.answer.configure(state="disabled")
        self.root.after(400, self.animate)

    def set_answer(self, question, body):
        self.answer.configure(state="normal")
        self.answer.delete("1.0", "end")
        self.answer.tag_configure("q", foreground=DIM)
        self.answer.tag_configure("dots", foreground=FAINT)
        self.answer.insert("end", question, "q")
        self.answer.insert("end", body, "dots" if body == "Thinking" else ())
        self.answer.configure(state="disabled")

    def hide_panel(self):
        self.thinking = None
        self.panel.place_forget()
        self.entry.focus_set()

    def poll(self):
        try:
            while True:
                kind, payload = self.inbox.get_nowait()
                if kind == "show":
                    self.show()
                elif kind == "answer" and self.panel.winfo_ismapped():
                    self.thinking = None
                    q = self.answer.get("1.0", "end").split("\n\n")[0]
                    self.set_answer(f"{q}\n\n", payload)
                    self.render()  # the assistant may have edited todos.md
                elif kind == "prefetch":
                    self.prefetching = False
                    if isinstance(payload, list):
                        self.save_suggestions(payload)
                    if self.suggestions == "loading":  # you clicked while it was running
                        self.suggestions = payload
                        self.render_list()
                elif kind == "suggestions":
                    self.suggestions = payload
                    if isinstance(payload, list):
                        self.save_suggestions(payload)
                    self.render_list()
                elif kind == "reading":
                    self.reading = rank_reading(payload, goal_texts())
                    self.render_list()
        except queue.Empty:
            pass
        self.root.after(150, self.poll)

    def watch(self):
        """Re-render when the markdown files change, and keep the clock current."""
        sig = self.files_sig()
        if sig != self.sig and not self.drag:  # compare contents, not mtimes: a rewrite with no change doesn't redraw
            if self.sig is not None and sig[2] != self.sig[2]:  # goals.md changed outside My Day
                self.after_goals_change()
            self.render()
        self.clock.configure(text=self.now().strftime("%H:%M"))
        self.ticks += 1
        if self.ticks % 15 == 1:  # every ~30 s
            self.check_nudges()
        self.root.after(2000, self.watch)

    # ---------- pop-ups ----------
    def check_nudges(self):
        """Pop up before timed events, and for a check-in every N minutes."""
        if self.nudge.winfo_ismapped() or time.time() < self.quiet_until:
            return
        now = self.now()
        lead = self.cfg["event_lead_minutes"]
        events = load_events(now.date())
        for t, title, loc in events:
            if not t:
                continue
            start = dt.datetime.combine(now.date(), dt.time.fromisoformat(t), now.tzinfo)
            mins = (start - now).total_seconds() / 60
            key = f"{now.date()}|{t}|{title}"
            if self.cfg["event_reminders"] and 0 <= mins <= lead and key not in self.alerted:
                self.alerted.add(key)
                later = [e for e in events if e[0] and e[0] > t]
                lines = [f"Starts {t}  ·  in {max(1, round(mins))} min"]
                if loc:
                    lines.append("online" if loc.startswith("http") else loc)
                if later:
                    lines.append(f"After that: {later[0][0]}  {later[0][1]}")
                self.pop("Coming up", title, lines)
                return
        start_h, end_h = self.cfg["active_hours"]
        if not (start_h <= now.strftime("%H:%M") < end_h):
            return
        if self.root.focus_get() is not None and self.root.state() == "normal":
            self.last_checkin = time.time()  # you're already looking at it
            return
        if self.cfg["checkins"] and time.time() - self.last_checkin >= self.cfg["checkin_minutes"] * 60:
            self.pop("Check-in", *self.checkin_content(now))

    def checkin_content(self, now):
        open_today = []
        for t in load_todos()["Today"]:
            if t.done:
                continue
            step = next((s for s in t.subs if not s.done), None)
            title = tidy(t.text)[0]
            open_today.append(f"{tidy(step.text)[0]} ({title})" if step else title)
        headline = f"Are you on: {open_today[0]}?" if open_today else "What are you working on right now?"
        lines = []
        if len(open_today) > 1:
            lines.append("Also today: " + "; ".join(open_today[1:3]))
        elif not open_today:
            lines.append("No todos for today — add one below so the next check-in can hold you to it.")
        hm = now.strftime("%H:%M")
        upcoming = [e for e in load_events(now.date()) if e[0] and e[0] >= hm]
        if upcoming:
            t, title, _ = upcoming[0]
            mins = int((dt.datetime.combine(now.date(), dt.time.fromisoformat(t), now.tzinfo)
                        - now).total_seconds() // 60)
            gap = f"{mins // 60}h {mins % 60:02d}m" if mins >= 60 else f"{mins} min"
            lines.append(f"Next: {t}  {title}  ·  in {gap}")
        dated = [(g.date, g.text) for _, goals in load_goals()[:1] for g in goals if g.date and g.date >= now.date()]
        if dated:
            d, g = min(dated)
            days = (d - now.date()).days
            lines.append(f"Goal: {g}  ·  {'today' if days == 0 else 'tomorrow' if days == 1 else f'in {days} days'}")
        return headline, lines

    def pop(self, kind, headline, lines):
        for w in self.nudge.winfo_children():
            w.destroy()
        n, pad = self.nudge, self.px(18)
        colour = NOW if kind == "Check-in" else ACCENT
        # buttons first, at the bottom: they keep their space whatever the text
        row = tk.Frame(n, bg=SURFACE)
        row.pack(side="bottom", fill="x", padx=pad, pady=pad)
        self.button(row, "Got it", self.dismiss, primary=True).pack(side="left")
        self.button(row, "Snooze 10 min", lambda: self.snooze(kind, headline, lines)).pack(
            side="left", padx=(self.px(8), 0))
        quiet = tk.Label(row, text="Quiet 2h", bg=SURFACE, fg=FAINT, font=self.f_small, cursor="hand2")
        quiet.pack(side="right")
        quiet.bind("<Button-1>", lambda e: self.dismiss(quiet_hours=2))
        top = tk.Frame(n, bg=SURFACE)
        top.pack(fill="x", padx=pad, pady=(pad, 0))
        tk.Label(top, text=kind.upper(), bg=SURFACE, fg=colour, font=self.f_head).pack(side="left")
        tk.Label(top, text=self.now().strftime("%H:%M"), bg=SURFACE, fg=DIM, font=self.f_small).pack(side="right")
        tk.Label(n, text=headline, bg=SURFACE, fg=TEXT, font=("Segoe UI Semibold", 14), anchor="w",
                 justify="left", wraplength=self.wrap_px(40)).pack(fill="x", padx=pad, pady=(self.px(8), self.px(6)))
        for line in lines:
            tk.Label(n, text=line, bg=SURFACE, fg=DIM, font=self.f_body, anchor="w", justify="left",
                     wraplength=self.wrap_px(40)).pack(fill="x", padx=pad, pady=self.px(2))

        self.hide_panel()
        n.place(in_=self.wrap, x=0, y=0, relwidth=1, relheight=1)
        n.lift()
        self.last_checkin = time.time()
        self.root.deiconify()
        self.fit_nudge()
        self.root.attributes("-topmost", True)  # stays above everything until you respond
        self.root.lift()
        self.root.focus_force()
        if self.cfg.get("sound") and winsound:
            winsound.MessageBeep(winsound.MB_ICONASTERISK)

    def fit_nudge(self):
        """Grow the window when the pop-up's text needs more room than the list
        area has; dismiss() puts the old size back."""
        self.root.update_idletasks()
        need = self.nudge.winfo_reqheight() - self.wrap.winfo_height()
        if need <= 0:
            return
        if self.pre_pop_size is None:
            self.pre_pop_size = (self.root.winfo_width(), self.root.winfo_height())
        w, h = self.root.winfo_width(), self.root.winfo_height()
        room = self.root.winfo_screenheight() - self.root.winfo_rooty() - self.px(60)  # leave the taskbar
        self.root.geometry(f"{w}x{min(h + need + self.px(8), h + max(0, room - h))}")

    def button(self, parent, text, command, primary=False):
        bg, fg, hover = (ACCENT, BG, "#a5c4ff") if primary else (LINE, TEXT, "#30303b")
        b = tk.Label(parent, text=text, bg=bg, fg=fg, font=self.f_bold, cursor="hand2",
                     padx=self.px(14), pady=self.px(6))
        b.bind("<Button-1>", lambda e: command())
        b.bind("<Enter>", lambda e: b.configure(bg=hover))
        b.bind("<Leave>", lambda e: b.configure(bg=bg))
        return b

    def dismiss(self, quiet_hours=0):
        self.nudge.place_forget()
        if self.pre_pop_size:  # the pop-up made the window taller: shrink it back
            self.root.geometry("%dx%d" % self.pre_pop_size)
            self.pre_pop_size = None
        self.root.attributes("-topmost", self.cfg["pin"])
        self.last_checkin = time.time()
        if quiet_hours:
            self.quiet_until = time.time() + quiet_hours * 3600
        self.root.iconify()

    def snooze(self, kind, headline, lines):
        self.dismiss()
        self.root.after(10 * 60 * 1000, lambda: self.pop(kind, headline, lines))


def serve(lock, inbox):
    """Any later launch connects here; we bring the window forward."""
    lock.listen(4)
    while True:
        try:
            conn, _ = lock.accept()
            conn.close()
            inbox.put(("show", None))
        except OSError:
            return


if __name__ == "__main__":
    lock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        lock.bind(("127.0.0.1", PORT))
    except OSError:
        try:  # already open: ask that window to come forward
            socket.create_connection(("127.0.0.1", PORT), timeout=1).close()
        except OSError:
            pass
        sys.exit(0)
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)  # crisp text on scaled displays
    except Exception:
        pass
    inbox = queue.Queue()
    threading.Thread(target=serve, args=(lock, inbox), daemon=True).start()
    app = DayUI(inbox)
    if "--hidden" in sys.argv:  # started at login: wait minimised until something needs you
        app.root.iconify()
    if "--demo" in sys.argv:  # show what a check-in looks like
        app.root.after(1500, lambda: app.pop("Check-in", *app.checkin_content(app.now())))
    app.root.mainloop()
