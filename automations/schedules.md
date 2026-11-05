# Automations (optional)

My Day already handles the things that must happen on time without an AI:
event reminders, check-ins and showing your day each morning. The jobs below
need your agent. Schedule them however your agent supports it (scheduled
tasks, cron, Windows Task Scheduler running your agent's CLI), using these
prompts. Replace the times with yours.

| Job | When | Prompt |
|---|---|---|
| Morning digest | daily 07:00 | Run the morning-digest skill. |
| Inbox | hourly 08:00–20:00 | Run the ingest skill. If the inbox is empty, do nothing and don't notify me. |
| Evening check-in | daily 21:00 | Run the evening-check-in skill. |
| Weekly review | Sunday 18:00 | Run the weekly-review skill. |
| Deadline alert | daily 08:00 | Read calendar.md. For each deadline within 24 hours, send a high-priority notify push. |

Example with Claude Code and Windows Task Scheduler (morning digest):

```
schtasks /Create /TN "Assistant morning digest" /SC DAILY /ST 07:00 ^
  /TR "cmd /c cd /d C:\Users\<you>\assistant && claude -p \"Run the morning-digest skill.\" --allowedTools Read,Write,Edit,Glob,Grep,Bash"
```

## Calendar sync (no AI needed)

`tools/gcal_sync.py` pulls your Google Calendar through its secret iCal
address and keeps the Google section of `calendar.md` current. Run it every
5 minutes (use `pythonw.exe` so no window flashes):

```
schtasks /Create /TN "Assistant calendar sync" /SC MINUTE /MO 5 ^
  /TR "\"C:\path\to\pythonw.exe\" \"C:\Users\<you>\assistant\tools\gcal_sync.py\" --quiet"
```

Test the parser first: `python tools/gcal_sync.py --file tools/gcal_sync.sample.ics --dry-run`
