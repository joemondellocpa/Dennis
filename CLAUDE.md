# Dennis Project — Claude Instructions

## Task Decomposition (Avoid Tool Call Limit)

For any task that involves **3 or more distinct steps**, or that requires reading/editing multiple files, always follow this pattern:

1. **Plan first** — identify all sub-tasks before executing anything.
2. **Delegate to subagents** — use the `Agent` tool to spawn a subagent for each independent sub-task. Each subagent gets its own tool call budget, preventing the per-turn limit from being hit.
3. **Parallelize** — launch independent subagents in a single message (parallel calls) rather than sequentially.
4. **Summarize** — after subagents complete, report results concisely to the user.

### When to use subagents

| Scenario | Action |
|----------|--------|
| Searching the codebase (files, symbols, patterns) | Spawn an `Explore` subagent |
| Multi-file edits across unrelated areas | One subagent per area |
| Research + implementation | Research subagent first, then implement |
| Running tests / builds | Spawn a general-purpose subagent |

### When NOT to use subagents

- Single-file edits
- Simple Q&A with no tool use
- Tasks already scoped to 1–2 tool calls

## General

- Prefer editing existing files over creating new ones.
- Keep changes minimal and focused on what was asked.
