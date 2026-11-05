#!/usr/bin/env python3
"""day — My Day from any terminal.

  day                 open the My Day window (or bring it forward)
  day ls              today's events, your todos (numbered) and nearest goals
  day add TEXT        add a todo to Today   (--week / --later for the other lists)
  day done N          tick todo N, or step N.M (run again to untick)
  day step N TEXT     add a step under todo N
  day rm N            remove todo N (or step N.M); it goes to the archive
  day goals           your short- and long-term goals
  day ask QUESTION    ask the assistant (same as "?" in the window)
  day morning         show the window once a day (run at login and unlock)

Reads and writes the same files as the window (todos.md, calendar.md,
me/goals.md), so changes appear in the window within seconds.
"""
import datetime as dt
import pathlib
import socket
import subprocess
import sys

import day_ui as d

PYTHONW = pathlib.Path(sys.executable).with_name("pythonw.exe")
MORNING_STAMP = d.HERE / "day_morning.stamp"
DIM, BOLD, GREEN, OFF = "\033[2m", "\033[1m", "\033[32m", "\033[0m"


def now():
    return dt.datetime.now(d.local_tz())


def running():
    try:
        socket.create_connection(("127.0.0.1", d.PORT), timeout=1).close()
        return True
    except OSError:
        return False


def open_window(hidden=False):
    """Bring the window forward, or start it (minimised if hidden)."""
    if not hidden and running():  # connecting asks it to come forward
        return
    exe = PYTHONW if PYTHONW.exists() else pathlib.Path(sys.executable)
    cmd = [str(exe), str(d.HERE / "day_ui.py")] + (["--hidden"] if hidden else [])
    if sys.platform != "win32":
        subprocess.Popen(cmd, cwd=d.ROOT, start_new_session=True)
        return
    detached = subprocess.DETACHED_PROCESS
    try:  # leave the Task Scheduler job so the window outlives this command
        subprocess.Popen(cmd, cwd=d.ROOT, creationflags=detached | 0x01000000)
    except OSError:
        subprocess.Popen(cmd, cwd=d.ROOT, creationflags=detached)


def numbered():
    """[(number, section, Todo)] for open and done todos, in file order."""
    n, out = 0, []
    for section, todos in d.load_todos().items():
        for t in todos:
            n += 1
            out.append((n, section, t))
    return out


def pick(arg):
    """'3' -> (todo 3, None); '3.2' -> (todo 3, step 2)."""
    main, _, sub = arg.partition(".")
    todo = next((t for n, _, t in numbered() if str(n) == main), None)
    if todo is None:
        sys.exit(f"No todo {main}. Run `day ls` to see the numbers.")
    if not sub:
        return todo, None
    if not sub.isdigit() or not 1 <= int(sub) <= len(todo.subs):
        sys.exit(f"Todo {main} has no step {sub}.")
    return todo, todo.subs[int(sub) - 1]


def box(done):
    return f"{GREEN}✓{OFF}" if done else "○"


def show_todos():
    section = None
    rows = numbered()
    for n, sec, t in rows:
        if sec != section:
            section = sec
            print(f"\n{BOLD}{sec}{OFF}")
        title, meta = d.tidy(t.text)
        steps = f" {DIM}{sum(s.done for s in t.subs)}/{len(t.subs)} steps{OFF}" if t.subs else ""
        meta = f" {DIM}{meta}{OFF}" if meta else ""
        print(f" {n:>2} {box(t.done)} {DIM if t.done else ''}{title}{OFF}{meta}{steps}")
        for m, s in enumerate(t.subs, 1):
            print(f"      {DIM}{n}.{m}{OFF} {box(s.done)} {DIM if s.done else ''}{d.tidy(s.text)[0]}{OFF}")
    if not rows:
        print(f"\n{DIM}No todos. Add one with: day add \"…\"{OFF}")


def cmd_ls():
    t = now()
    print(f"{BOLD}{t:%A %d %B}{OFF}  {DIM}{t:%H:%M}{OFF}")
    events = d.load_events(t.date())
    print(f"\n{BOLD}Today{OFF}" if events else f"\n{DIM}Nothing on the calendar today.{OFF}")
    for time_, title, where in events:
        past = time_ and time_ < f"{t:%H:%M}"
        where = f" {DIM}— {where}{OFF}" if where else ""
        print(f"  {DIM if past else ''}{time_ or 'all day':>7}  {title}{OFF}{where}")
    show_todos()
    dated = sorted((g for g in dict(d.load_goals()).get("Short term", []) if g.date and g.date >= t.date()),
                   key=lambda g: g.date)
    if dated:
        g = dated[0]
        days = (g.date - t.date()).days
        when = "today" if days == 0 else "tomorrow" if days == 1 else f"in {days} days"
        print(f"\n{DIM}Next goal:{OFF} {g.text} {DIM}— {when}{OFF}")


def cmd_goals():
    for section, goals in d.load_goals():
        print(f"\n{BOLD}{section}{OFF}")
        for g in goals:
            date = f" {DIM}{g.date:%d %b %Y}{OFF}" if g.date else ""
            print(f"  · {g.text}{date}")
        if not goals:
            print(f"  {DIM}(none){OFF}")
    print(f"\n{DIM}Edit goals in the window (day) or in me/goals.md.{OFF}")


def cmd_add(args):
    section = "Today"
    for flag, name in (("--week", "This week"), ("--later", "Later")):
        if flag in args:
            args.remove(flag)
            section = name
    text = " ".join(args).strip()
    if not text:
        sys.exit('Usage: day add "text" [--week | --later]')
    d.add_todo(text, section)
    print(f"Added to {section}: {text}")


def cmd_done(args):
    if not args:
        sys.exit("Usage: day done N   (or N.M for a step)")
    for arg in args:
        todo, step = pick(arg)
        target = step or todo
        d.toggle_todo(target.idx, target.raw)
        print(f"{'Reopened' if target.done else 'Ticked'}: {d.tidy(target.text)[0]}")


def cmd_step(args):
    if len(args) < 2:
        sys.exit('Usage: day step N "text"')
    todo, _ = pick(args[0])
    d.add_subtask(todo.idx, todo.raw, " ".join(args[1:]))
    print(f"Added a step to: {d.tidy(todo.text)[0]}")


def cmd_rm(args):
    if not args:
        sys.exit("Usage: day rm N   (or N.M for a step)")
    todo, step = pick(args[0])
    target = step or todo
    what, _, _ = d.remove_todo(target.idx, target.raw)
    d.log_action("update", "todos.md", what.replace("(archived)", "(archived, day CLI)"))
    print(f"Removed: {d.tidy(target.text)[0]}  (kept in archive/{dt.date.today():%Y-%m}/todos-removed.md)")


def cmd_ask(args):
    if not args:
        sys.exit('Usage: day ask "question"')
    print(f"{DIM}Asking…{OFF}", flush=True)
    print(d.ask_assistant(" ".join(args), now()))


def cmd_morning():
    """Run at login and unlock: show the window the first time each day (after
    04:00); otherwise just make sure it is running, minimised, for pop-ups."""
    t = now()
    today = t.date().isoformat()
    try:
        last = MORNING_STAMP.read_text(encoding="utf-8").strip()
    except OSError:
        last = ""
    if last != today and t.hour >= 4:
        MORNING_STAMP.write_text(today, encoding="utf-8")
        open_window()
    elif not running():
        open_window(hidden=True)


def main(argv):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    if not (sys.stdout and sys.stdout.isatty()):  # no colour codes when piped (or under pythonw)
        global DIM, BOLD, GREEN, OFF
        DIM = BOLD = GREEN = OFF = ""
    cmd, args = (argv[0].lower(), argv[1:]) if argv else ("open", [])
    commands = {
        "open": lambda: open_window(), "ls": cmd_ls, "list": cmd_ls, "today": cmd_ls,
        "goals": cmd_goals, "morning": cmd_morning,
        "add": lambda: cmd_add(args), "done": lambda: cmd_done(args), "tick": lambda: cmd_done(args),
        "step": lambda: cmd_step(args), "rm": lambda: cmd_rm(args), "ask": lambda: cmd_ask(args),
    }
    if cmd.startswith("?"):  # day ? what's next
        return cmd_ask([cmd[1:]] + args if cmd[1:] else args)
    if cmd not in commands:
        if cmd not in ("help", "-h", "--help"):
            print(f"Unknown command: {cmd}\n")
        print(__doc__.split("\n\n")[1])
        return
    commands[cmd]()


if __name__ == "__main__":
    main(sys.argv[1:])
