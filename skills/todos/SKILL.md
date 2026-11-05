---
name: todos
description: Add, complete, reprioritize or review todos. Use when the user mentions a task, says they finished something, asks what to do next, or asks to plan their day or week.
---
# Todos

`todos.md` is the single list. Keep it in its four sections: Today, This week, Later, Done (last 7 days).

- **Add:** `- [ ] task — due YYYY-MM-DD — [[source-note]]`. Create a `task` note in `vault/tasks/` if it has a deadline or belongs to a course or project.
- **Complete:** tick it, move it to Done with today's date, update the task note's `status: done`.
- **What next / plan my day:** read `todos.md`, `calendar.md` and `me/goals.md`. Pick at most 3 things for today: deadlines first, then goal-related work. Explain each pick in one line. Move anything overdue to the top and say so plainly.
- Every Monday, move Done items older than 7 days into `archive/YYYY-MM/done.md`.
- Log changes in `logs/actions.md`.
