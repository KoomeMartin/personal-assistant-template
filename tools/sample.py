#!/usr/bin/env python3
"""Try the assistant with a fictional person, then clear it for your own data.

  python tools/sample.py load    copy examples/alex/ into place, dated from today
  python tools/sample.py inbox   drop the demo files (chat, brief, job post…) into inbox/ to ingest live
  python tools/sample.py clear   move the sample into archive/ and restore the blank templates

`load` refuses to run once you've started filling in me/profile.md, so it can
never overwrite your data. `clear` deletes nothing: the sample files move to
archive/sample-YYYY-MM-DD/.
"""
import datetime as dt
import pathlib
import re
import shutil
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
SAMPLE = ROOT / "examples" / "alex"
BLANK = ROOT / "examples" / "blank"
DEMO_INBOX = ROOT / "examples" / "demo-inbox"
GRAPH = ROOT / "examples" / "obsidian" / "graph.json"
TOKEN = re.compile(r"\{\{([DY])([+-]\d+)?\}\}")


def fill(text, today):
    def sub(m):
        n = int(m.group(2) or 0)
        if m.group(1) == "D":
            return (today + dt.timedelta(days=n)).isoformat()
        return str(today.year + n)
    return TOKEN.sub(sub, text)


def log(action, path, why):
    stamp = dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    with (ROOT / "logs" / "actions.md").open("a", encoding="utf-8") as f:
        f.write(f"{stamp} | {action} | {path} | {why}\n")


def sample_files():
    return [p.relative_to(SAMPLE) for p in SAMPLE.rglob("*") if p.is_file()]


def load():
    profile = ROOT / "me" / "profile.md"
    if profile.read_text(encoding="utf-8") != (BLANK / "me" / "profile.md").read_text(encoding="utf-8") \
            and "--force" not in sys.argv:
        sys.exit("me/profile.md is no longer the blank template, so the sample would overwrite your data.\n"
                 "Nothing was changed. (Use --force only if you're sure.)")
    today = dt.date.today()
    for rel in sample_files():
        dest = ROOT / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(fill((SAMPLE / rel).read_text(encoding="utf-8"), today), encoding="utf-8")
    log("create", "examples/alex → me/, vault/, todos.md, calendar.md", "loaded the fictional sample person")
    graph = ROOT / ".obsidian" / "graph.json"
    if not graph.exists():  # colour the Obsidian graph by note type (yours wins if you have one)
        graph.parent.mkdir(exist_ok=True)
        shutil.copy(GRAPH, graph)
        log("create", ".obsidian/graph.json", "Obsidian graph coloured by note type")
    print(f"Loaded Alex, the sample person ({len(sample_files())} files). Open My Day with `day`, or ask your\n"
          "assistant: \"What's on today?\" or \"Tailor my CV for the Brightpath internship.\"\n"
          "When you're ready for your own data: python tools/sample.py clear")


def inbox():
    today = dt.date.today()
    names = []
    for src in sorted(DEMO_INBOX.iterdir()):
        dest = ROOT / "inbox" / src.name
        if dest.exists():
            continue  # already there from an earlier run
        dest.write_text(fill(src.read_text(encoding="utf-8"), today), encoding="utf-8")
        names.append(src.name)
    if names:
        log("create", "inbox/ (" + ", ".join(names) + ")", "demo files to ingest")
    print(f"Put {len(names)} demo files in inbox/: " + (", ".join(names) or "none (already there)") +
          "\nNow ask your assistant: \"Process my inbox.\"")


def clear():
    dest_root = ROOT / "archive" / f"sample-{dt.date.today().isoformat()}"
    moved = 0
    for rel in sample_files():
        src = ROOT / rel
        if src.exists():
            (dest_root / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(src), str(dest_root / rel))
            moved += 1
    for blank in BLANK.rglob("*"):
        if blank.is_file():
            target = ROOT / blank.relative_to(BLANK)
            if not target.exists():
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy(blank, target)
    log("move", f"sample files → {dest_root.relative_to(ROOT).as_posix()}/", "cleared the sample person; blank templates restored")
    print(f"Moved {moved} sample files to {dest_root.relative_to(ROOT).as_posix()}/ and restored the blank templates.\n"
          "Now fill in me/ (or ask your assistant to interview you).")


if __name__ == "__main__":
    {"load": load, "inbox": inbox, "clear": clear}.get((sys.argv[1:] or ["help"])[0], lambda: print(__doc__))()
