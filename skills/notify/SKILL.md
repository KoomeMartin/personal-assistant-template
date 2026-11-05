---
name: notify
description: Send a push notification to the user's desktop and phone. Use when a skill or automation needs to alert, remind or check in with the user, or when asked to remind them about something.
---
# Notify

Run:

```
python tools/notify.py --title "<title>" --message "<message>" [--priority 3] [--tags <tag,tag>]
```

- Keep the title under 40 characters and the message under 160.
- Priority: 1 = min, 3 = default, 4 = high (deadline within 24 h), 5 = urgent (only if the person asked).
- Never include private details in a notification: no health, money, grades, passwords, or other people's messages. Say "check the assistant" instead.
- Respect quiet hours in `me/preferences.md`; outside them, write the reminder into today's digest instead.
- If the command fails, say so and show the error. Don't silently skip it.
- For a one-off reminder at a specific time ("remind me at 17:00 to…"), create a one-time automation task that runs this skill at that time.
