---
name: ask-my-notes
description: Answer questions about the user's own life, studies, work, people or plans from the knowledge base, with citations. Use for any question that starts with what/when/who/where about their own things, or "what do I know about...", "search my notes".
---
# Ask my notes (hybrid retrieval)

1. **Find entry points.**
   - If vector search tools are available (`mcp__chroma__...`), query the `vault` collection with the question and take the top 5 notes.
   - Otherwise (or as well), search `vault/`, `todos.md` and `calendar.md` for the key words, their aliases from `schema.md`, and likely synonyms.
2. **Expand through the graph.** Open each entry note, then follow its `[[links]]` and relations one hop (two hops if the question is about connections, e.g. "who could help me with…").
3. **Answer** only from what you read. Cite each fact with `[[note-name]]`.
4. If the notes don't contain the answer, say so plainly and ask whether to search the web or whether the person can tell you (then use `capture`).
5. If notes contradict each other, show both and ask which is right.
