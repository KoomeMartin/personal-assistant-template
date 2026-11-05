# Schema — the semantic layer

This file defines what things *mean* in this assistant. Every note in `vault/`
follows it, every skill reads it, and the knowledge graph (`[[links]]`) is
built on it. Edit it in plain language; the agent follows whatever is
written here. "You" below means the person this assistant works for.

## Note types

Each note is one markdown file in the folder for its type, with frontmatter.

| Type | Folder | Required fields | Optional fields |
|---|---|---|---|
| person | `vault/people/` | `type`, `name`, `relation_to_me` | `aliases`, `contact`, `notes` |
| course | `vault/courses/` | `type`, `name`, `code` | `lecturer`, `schedule`, `room`, `aliases` |
| project | `vault/projects/` | `type`, `name`, `status` (idea / active / paused / done) | `deadline`, `collaborators`, `aliases` |
| task | `vault/tasks/` | `type`, `title`, `due`, `status` (todo / doing / done) | `course`, `project`, `source` |
| event | `vault/events/` | `type`, `title`, `date` | `time`, `place`, `course`, `source` |
| idea | `vault/ideas/` | `type`, `title`, `captured` | `inspired_by`, `related` |
| opportunity | `vault/opportunities/` | `type`, `title`, `kind` (job / internship / scholarship / competition), `deadline` | `link`, `requirements`, `status` |
| document | `vault/documents/` | `type`, `title`, `original` (path in `archive/`) | `course`, `project`, `summary` |

Dates are `YYYY-MM-DD`. Times are 24-hour `HH:MM` in your time zone.

Any note may carry `unconfirmed:` — a comma-separated list of its fields or
facts that are inferred rather than stated by you or a source (e.g.
`unconfirmed: status, dates`). Never present those as fact; remove a field
from the list once you confirm it.

## Relations

Write relations as a line in the note body: `relation:: [[other-note]]`.
These are the only relations allowed; add new ones here first.

| Relation | From → To | Meaning |
|---|---|---|
| `teaches` | person → course | Lecturer or TA of the course |
| `takes` | me → course | You are enrolled |
| `works_on` | person → project | Collaborator on a project |
| `part_of` | task / event / document → course or project | Belongs to |
| `due_for` | task → course or project | Deliverable for |
| `mentioned_in` | anything → document | Where a fact came from |
| `inspired_by` | idea → anything | What sparked the idea |
| `related` | idea → idea / project | Loose connection |
| `requires` | opportunity → document or skill | What it asks for |

Any other link in a note body (`[[name]]`) means "related, unspecified".

## Aliases

When you or a source use one of these names, treat it as the canonical note.
Replace the examples with your own shorthand.

| Alias | Canonical note |
|---|---|
| DS, Data Structures | [[data-structures]] |
| the app, capstone | [[study-buddy-app]] |
| your own name and nicknames | `me/profile.md` |

## Ownership — who may write what

| File | Who writes it |
|---|---|
| `me/goals.md` | You only. The assistant reads it; it edits it only when you dictate the exact change. |
| — sync | Any change to `me/goals.md` (in My Day or by hand) propagates automatically: each dated goal gets a line in `calendar.md` → "Added by me" tagged `<!-- from goals -->` (added, re-dated, renamed or dropped to match), and a linked event note's `date:` follows the goal. Achieved goals move to `## Achieved`; removed ones go to `archive/YYYY-MM/goals-removed.md`. Never edit tagged calendar lines directly — edit the goal. |
| `todos.md` | You add todos. The assistant may *suggest* (My Day's ✦ Suggest) but never adds one on its own, and never turns its own open questions about the knowledge base into your todos. |
| `vault/`, `calendar.md` | The assistant, following this schema. |

## Minimisation and reliability

- Keep only what serves your goals, work and applications. Don't import
  everything a source contains.
- A `person` note only for someone you deal with on an ongoing basis
  (lecturer, referee, manager, current collaborator). One-off teammates are
  named in the project's `collaborators` field as plain text, not as notes.
- No contact details except for people you actively need to reach.
- Every fact carries its source (`source:` field or `mentioned_in::`). If a
  fact is a guess, mark it `unconfirmed` and ask. Don't log it as a todo.
- Your own statements beat older documents: when you correct something, the
  note is updated and cites "me, YYYY-MM-DD".

## Naming

- File names: lowercase, words separated by hyphens, no dates in the name except for events and digests (`2026-11-04-midterm.md`).
- One subject per note. If a note already exists for a subject, update it; never create a duplicate.
- Every note links to at least one other note, so nothing floats outside the graph.

## Example

```markdown
---
type: task
title: Data structures assignment 3
due: 2026-11-07
status: todo
course: data-structures
source: inbox/class-group.txt
---
Implement a hash table with chaining and write a one-page report.

due_for:: [[data-structures]]
mentioned_in:: [[class-group-2026-10]]
```
