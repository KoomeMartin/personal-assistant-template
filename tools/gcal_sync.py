#!/usr/bin/env python3
"""Gmail Calendar sync + reminders for the personal assistant.

Pulls the Google Calendar "secret address in iCal format", keeps the Google
section of calendar.md current, and sends reminders through tools/notify.py:

  - a morning summary of today's events (once per day, first run after 06:00)
  - a high-priority nudge N minutes before each timed event (default 15)

Designed to run every 5 minutes from Windows Task Scheduler (pythonw.exe, no
window) and degrades gracefully: without a configured URL it exits quietly;
on a fetch failure it keeps using the last good cache for reminders.

Standard library only. Configure in tools/gcal_sync.config.json.

Usage:
  python gcal_sync.py                 # normal run (fetch, sync, remind)
  python gcal_sync.py --quiet         # no stdout (scheduled runs)
  python gcal_sync.py --dry-run       # show what would happen, change nothing
  python gcal_sync.py --file X.ics    # parse a local file instead of fetching
  python gcal_sync.py --morning       # force the morning summary now
"""
import argparse
import datetime as dt
import json
import pathlib
import subprocess
import sys
import urllib.request
from zoneinfo import ZoneInfo

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent
CONFIG_PATH = HERE / "gcal_sync.config.json"
STATE_PATH = HERE / "gcal_state.json"
CACHE_PATH = HERE / "gcal_cache.json"
LOG_PATH = HERE / "gcal_sync.log"
CAL_MD = ROOT / "calendar.md"

DEFAULTS = {
    "ical_url": "",
    "timezone": "",  # empty: the computer's own time zone
    "lookahead_days": 21,
    "nudge_minutes": 15,
    "show_titles": True,
}
MARK_START = "<!-- gcal:start (managed by tools/gcal_sync.py) -->"
MARK_END = "<!-- gcal:end -->"
WEEKDAYS = {"MO": 0, "TU": 1, "WE": 2, "TH": 3, "FR": 4, "SA": 5, "SU": 6}


def log(msg, quiet=False):
    stamp = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        lines = []
        if LOG_PATH.exists():
            lines = LOG_PATH.read_text(encoding="utf-8").splitlines()
        lines.append(f"{stamp} {msg}")
        LOG_PATH.write_text("\n".join(lines[-200:]) + "\n", encoding="utf-8")
    except OSError:
        pass
    if not quiet:
        print(msg)


def load_json(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def save_json(path, data):
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


# ---------------------------------------------------------------- iCal parsing

def unfold(text):
    out, prev = [], None
    for raw in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if raw[:1] in (" ", "\t") and prev is not None:
            prev += raw[1:]
            continue
        out.append(raw)
        prev = raw
    return out


def split_name_value(line):
    """Split 'NAME;PARAM=V:value' at the first ':' outside double quotes."""
    in_quote = False
    for i, ch in enumerate(line):
        if ch == '"':
            in_quote = not in_quote
        elif ch == ":" and not in_quote:
            return line[:i], line[i + 1:]
    return line, ""


def parse_property(line):
    head, value = split_name_value(line)
    parts, buf, in_quote = [], "", False
    for ch in head:
        if ch == '"':
            in_quote = not in_quote
            buf += ch
        elif ch == ";" and not in_quote:
            parts.append(buf)
            buf = ""
        else:
            buf += ch
    parts.append(buf)
    name = parts[0].upper()
    params = {}
    for p in parts[1:]:
        if "=" in p:
            k, v = p.split("=", 1)
            params[k.upper()] = v.strip('"')
    return name, params, value


def ical_dt(value, params, fallback_tz):
    """Return (aware datetime, is_all_day)."""
    value = value.strip()
    if "T" not in value:  # all-day: YYYYMMDD
        d = dt.datetime.strptime(value, "%Y%m%d")
        return d.replace(tzinfo=fallback_tz), True
    tz = fallback_tz
    if value.endswith("Z"):
        value = value[:-1]
        tz = dt.timezone.utc
    elif "TZID" in params:
        try:
            tz = ZoneInfo(params["TZID"])
        except Exception:
            pass
    naive = dt.datetime.strptime(value, "%Y%m%dT%H%M%S")
    return naive.replace(tzinfo=tz), False


def unescape(text):
    out, i = [], 0
    while i < len(text):
        if text[i] == "\\" and i + 1 < len(text):
            nxt = text[i + 1]
            out.append("\n" if nxt in "nN" else nxt)
            i += 2
        else:
            out.append(text[i])
            i += 1
    return "".join(out)


def parse_rrule(value):
    rule = {}
    for part in value.split(";"):
        if "=" in part:
            k, v = part.split("=", 1)
            rule[k.upper()] = v
    return rule


def expand_rrule(master, rule, window_start, window_end):
    """Expand simple RRULEs. Complex rules fall back to the first occurrence.

    master["start"] is DTSTART in the event's own zone (aware, with its TZID).
    Stepping happens on that local wall clock, so a 09:00 meeting stays at
    09:00 across daylight-saving changes and BYDAY uses the local weekday.
    Results keep that zone; the caller converts them to UTC.
    """
    freq = rule.get("FREQ", "").upper()
    try:
        interval = int(rule.get("INTERVAL", "1"))
    except ValueError:
        interval = 1
    count = int(rule["COUNT"]) if "COUNT" in rule else None
    until = None
    if "UNTIL" in rule:
        until, _ = ical_dt(rule["UNTIL"], {}, dt.timezone.utc)
    byday = [d for d in rule.get("BYDAY", "").split(",") if d in WEEKDAYS]

    occ = []
    cur = master["start"]
    total = master.get("count_base", 0)  # occurrences already consumed
    guard = 0
    while guard < 800:
        guard += 1
        if freq == "DAILY":
            candidates = [cur]
            nxt = cur + dt.timedelta(days=interval)
        elif freq == "WEEKLY":
            if byday:
                week_start = cur - dt.timedelta(days=cur.weekday())
                candidates = []
                for d in byday:
                    day = week_start + dt.timedelta(days=WEEKDAYS[d])
                    if day >= cur:
                        candidates.append(day)
                nxt = week_start + dt.timedelta(weeks=interval)
            else:
                candidates = [cur]
                nxt = cur + dt.timedelta(weeks=interval)
        elif freq == "MONTHLY":
            candidates = [cur]
            m = cur
            for _ in range(60):
                total_months = m.year * 12 + (m.month - 1) + interval
                y, mo = divmod(total_months, 12)
                try:
                    m = m.replace(year=y, month=mo + 1)
                except ValueError:  # e.g. day 31 in a 30-day month
                    total_months += interval
                    y, mo = divmod(total_months, 12)
                    m = m.replace(year=y, month=mo + 1)
                break
            nxt = m
        elif freq == "YEARLY":
            candidates = [cur]
            try:
                nxt = cur.replace(year=cur.year + interval)
            except ValueError:  # Feb 29
                nxt = cur.replace(year=cur.year + interval, day=28)
        else:
            return [master["start"]]  # unsupported rule: master only

        for c in candidates:
            if c > window_end:
                return occ
            if until and c > until:
                return occ
            if count is not None and total + len(occ) >= count:
                return occ
            if c >= window_start:
                occ.append(c)
        cur = nxt
    return occ


def parse_ics(text, tz):
    lines = unfold(text)
    events, overrides = [], {}
    inside = False
    props = []
    for line in lines:
        name, params, value = parse_property(line) if ":" in line or ";" in line else (line.upper(), {}, "")
        if name == "BEGIN" and value.strip().upper() == "VEVENT":
            inside, props = True, []
            continue
        if name == "END" and value.strip().upper() == "VEVENT":
            inside = False
            ev = {}
            for pname, pparams, pvalue in props:
                if pname == "SUMMARY":
                    ev["summary"] = unescape(pvalue)
                elif pname == "LOCATION":
                    ev["location"] = unescape(pvalue)
                elif pname == "UID":
                    ev["uid"] = pvalue
                elif pname == "STATUS":
                    ev["status"] = pvalue.upper()
                elif pname == "RRULE":
                    ev["rrule"] = parse_rrule(pvalue)
                elif pname == "EXDATE":  # single occurrences deleted from a series
                    for value in pvalue.split(","):
                        try:
                            when, allday = ical_dt(value, pparams, tz)
                        except ValueError:
                            continue
                        ex = ev.setdefault("exdates", {"at": set(), "days": set()})
                        if allday:
                            ex["days"].add(when.date())
                        else:
                            ex["at"].add(when.astimezone(dt.timezone.utc))
                elif pname == "RECURRENCE-ID":
                    ev["recurrence_id"], _ = ical_dt(pvalue, pparams, tz)
                elif pname in ("DTSTART", "DTEND"):
                    try:
                        parsed, allday = ical_dt(pvalue, pparams, tz)
                        ev[pname.lower()] = parsed
                        if pname == "DTSTART":
                            ev["allday"] = allday
                    except ValueError:
                        pass
            if ev.get("summary") and ev.get("dtstart") and ev.get("status") != "CANCELLED":
                events.append(ev)
            continue
        if inside:
            props.append((name, params, value))

    # separate overridden instances from masters
    masters, over = [], {}
    for ev in events:
        if "recurrence_id" in ev:
            over.setdefault(ev.get("uid", ""), {})[ev["recurrence_id"].date()] = ev
        else:
            masters.append(ev)

    window_start = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=2)
    result = []
    for ev in masters:
        start_utc = ev["dtstart"].astimezone(dt.timezone.utc)
        end_utc = (ev.get("dtend") or ev["dtstart"]).astimezone(dt.timezone.utc)
        base = {"uid": ev.get("uid", ev["summary"]), "summary": ev["summary"],
                "location": ev.get("location", ""), "allday": bool(ev.get("allday")),
                "start_utc": start_utc, "end_utc": end_utc}
        if "rrule" in ev:
            window_end = dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=60)
            # expand on the event's own wall clock, then convert each start to UTC
            starts = expand_rrule({"start": ev["dtstart"]}, ev["rrule"], window_start, window_end)
        else:
            starts = [ev["dtstart"]]
        ov = over.get(ev.get("uid", ""), {})
        duration = end_utc - start_utc
        ex = ev.get("exdates", {"at": set(), "days": set()})
        for s in starts:
            if s.date() in ov:  # replaced by an overridden instance (local date)
                continue
            s_utc = s.astimezone(dt.timezone.utc)
            if s_utc in ex["at"] or s.date() in ex["days"]:  # deleted occurrence
                continue
            result.append({**base, "start_utc": s_utc, "end_utc": s_utc + duration})
    for by_date in over.values():
        for ev in by_date.values():
            result.append({"uid": ev.get("uid", ev["summary"]), "summary": ev["summary"],
                           "location": ev.get("location", ""), "allday": bool(ev.get("allday")),
                           "start_utc": ev["dtstart"].astimezone(dt.timezone.utc),
                           "end_utc": (ev.get("dtend") or ev["dtstart"]).astimezone(dt.timezone.utc)})
    # dedupe by (uid, start)
    seen, unique = set(), []
    for ev in result:
        key = (ev["uid"], ev["start_utc"])
        if key not in seen:
            seen.add(key)
            unique.append(ev)
    return unique


# ---------------------------------------------------------------- sync + remind

def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": "personal-assistant-gcal-sync"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read().decode("utf-8", errors="replace")


def render_calendar_md(events, tz, now_local):
    lines = ["## From Google Calendar", ""]
    if not events:
        lines += ["_(no upcoming events in the feed)_"]
    for ev in events:
        s = ev["start_utc"].astimezone(tz)
        if ev["allday"]:
            when = s.strftime("%Y-%m-%d — all day")
        else:
            when = s.strftime("%Y-%m-%d %H:%M")
            if s.date() == now_local.date():
                when += " (today)"
            elif s.date() == now_local.date() + dt.timedelta(days=1):
                when += " (tomorrow)"
        entry = f"- {when} — {ev['summary']}"
        if ev["location"]:
            entry += f" — {ev['location']}"
        lines.append(entry + "  ")
    lines.append("")
    return "\n".join(lines)


def update_calendar_md(section_text):
    header = (
        "# Calendar\n\n"
        "Upcoming events and deadlines, soonest first. Kept current by the assistant.\n"
        "Format: `- YYYY-MM-DD HH:MM — what — where — [[note]]`\n\n"
        f"{MARK_START}\n"
    )
    if CAL_MD.exists():
        old = CAL_MD.read_text(encoding="utf-8")
        if MARK_START in old and MARK_END in old:
            before = old.split(MARK_START)[0]
            after = old.split(MARK_END)[1]
            CAL_MD.write_text(before + MARK_START + "\n" + section_text + "\n" + MARK_END + after,
                              encoding="utf-8")
            return
    body = header + section_text + "\n" + MARK_END + "\n\n## Added by me\n\n"
    CAL_MD.write_text(body, encoding="utf-8")


def send_notify(title, message, priority, tags, dry, quiet, click_url=None):
    if dry:
        log(f"[dry-run] notify: {title} | {message} (priority {priority})", quiet)
        return True
    cmd = [sys.executable, str(HERE / "notify.py"), "--title", title, "--message", message,
           "--priority", str(priority), "--tags", ",".join(tags)]
    if click_url:
        cmd += ["--click-url", click_url]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        if r.returncode != 0:
            log(f"notify failed: {r.stdout} {r.stderr}", quiet)
            return False
        return True
    except Exception as exc:
        log(f"notify error: {exc}", quiet)
        return False


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--quiet", action="store_true", help="no stdout output")
    ap.add_argument("--dry-run", action="store_true", help="no writes, no notifications")
    ap.add_argument("--file", help="parse a local .ics file instead of fetching")
    ap.add_argument("--morning", action="store_true", help="force the morning summary now")
    args = ap.parse_args()
    quiet = args.quiet

    cfg = {**DEFAULTS, **load_json(CONFIG_PATH, {})}
    tz = ZoneInfo(cfg["timezone"]) if cfg.get("timezone") else dt.datetime.now().astimezone().tzinfo
    now = dt.datetime.now(dt.timezone.utc)
    now_local = now.astimezone(tz)

    if not args.file and not cfg["ical_url"].strip():
        log("not configured: set ical_url in tools/gcal_sync.config.json", quiet)
        return 0

    # --- get events ---
    events = None
    if args.file:
        events = parse_ics(pathlib.Path(args.file).read_text(encoding="utf-8"), tz)
    else:
        try:
            text = fetch(cfg["ical_url"].strip())
            events = parse_ics(text, tz)
            if not args.dry_run:
                save_json(CACHE_PATH, {"fetched": now.isoformat(), "events": [
                    {k: (v.isoformat() if isinstance(v, dt.datetime) else v) for k, v in ev.items()}
                    for ev in events]})
        except Exception as exc:
            log(f"fetch failed ({exc}); using last good cache", quiet)
            cached = load_json(CACHE_PATH, {})
            events = []
            for ev in cached.get("events", []):
                e = dict(ev)
                e["start_utc"] = dt.datetime.fromisoformat(e["start_utc"])
                e["end_utc"] = dt.datetime.fromisoformat(e["end_utc"])
                events.append(e)
            if not events:
                return 1

    horizon = now + dt.timedelta(days=cfg["lookahead_days"])
    upcoming = sorted((e for e in events if now - dt.timedelta(hours=6) <= e["start_utc"] <= horizon),
                      key=lambda e: e["start_utc"])

    # --- calendar.md ---
    section = render_calendar_md(upcoming, tz, now_local)
    if args.dry_run:
        log("[dry-run] calendar.md section:\n" + section, quiet)
    else:
        update_calendar_md(section)

    # --- reminders ---
    state = load_json(STATE_PATH, {"notified": {}, "morning": {}})
    nudged = state.setdefault("notified", {})
    mornings = state.setdefault("morning", {})
    cutoff = (now - dt.timedelta(days=7)).date().isoformat()
    # rebuild (update() could only add keys), keeping the last 7 days of records
    nudged = state["notified"] = {k: v for k, v in nudged.items() if isinstance(v, str) and v >= cutoff}

    nudge_min = int(cfg["nudge_minutes"])
    for ev in upcoming:
        if ev["allday"]:
            continue
        s_local = ev["start_utc"].astimezone(tz)
        fire_at = ev["start_utc"] - dt.timedelta(minutes=nudge_min)
        key = f'{ev["uid"]}@{ev["start_utc"].isoformat()}'
        if now < fire_at or now > ev["start_utc"] or key in nudged:
            continue
        title = f'Upcoming: {s_local.strftime("%H:%M")}'
        if cfg["show_titles"] and ev["summary"]:
            msg = f'In {nudge_min} min — {ev["summary"]}'
            if ev["location"]:
                msg += f' — {ev["location"]}'
        else:
            msg = f"Event at {s_local.strftime('%H:%M')} — check the assistant"
        if send_notify(title, msg[:160], 4, ["calendar", "alarm"], args.dry_run, quiet,
                       cfg.get("assistant_url", "http://127.0.0.1:64804")):
            nudged[key] = now.date().isoformat()

    today = [e for e in upcoming if not e["allday"] and e["start_utc"].astimezone(tz).date() == now_local.date()]
    should_morning = (args.morning or 6 <= now_local.hour < 12) and now_local.date().isoformat() not in mornings
    if should_morning:
        if today:
            first = today[0]["start_utc"].astimezone(tz).strftime("%H:%M")
            if cfg["show_titles"]:
                msg = f'{len(today)} event{"s" if len(today) != 1 else ""} today, first at {first}: {today[0]["summary"]}'
            else:
                msg = f'{len(today)} event{"s" if len(today) != 1 else ""} today, first at {first} — check the assistant'
            send_notify("Your day", msg[:160], 3, ["calendar"], args.dry_run, quiet,
                        cfg.get("assistant_url", "http://127.0.0.1:64804"))
        else:
            send_notify("Your day", "No events scheduled for today.", 1, ["calendar"], args.dry_run, quiet,
                        cfg.get("assistant_url", "http://127.0.0.1:64804"))
        if not args.dry_run:
            mornings[now_local.date().isoformat()] = True

    # prune old morning marks
    for d in [d for d in mornings if d < (now_local.date() - dt.timedelta(days=14)).isoformat()]:
        del mornings[d]

    if not args.dry_run:
        save_json(STATE_PATH, state)
    log(f"sync ok: {len(upcoming)} upcoming events", quiet)
    return 0


if __name__ == "__main__":
    sys.exit(main())
