# Subagent Spawning — Implementation Plan

## Overview

Add a `run_subagent` tool that Dennis can call to delegate self-contained subtasks
to a child agent. The child runs its own tool-use loop with a restricted tool set,
then returns a result string. This fits naturally into the existing tool-use paradigm
with no changes to the main agent loop.

---

## Architecture

```
User message
    │
    ▼
Agent.chat() [main loop, max 10 tool calls]
    │
    ├── tool: web_search(...)         ← existing tools
    ├── tool: run_subagent(task, tools=[...])   ← NEW
    │           │
    │           ▼
    │       SubagentRunner.run()
    │           ├── tool: web_search(...)
    │           ├── tool: fetch_page(...)
    │           └── returns result string
    │
    └── final response to user
```

Key properties:
- **No recursion**: subagents cannot call `run_subagent`
- **Tool isolation**: each subagent only receives the tools it's given
- **Shared budget**: subagent API calls count against the same daily budget
- **Shared approvals**: approval prompts bubble up to the same Telegram callback
- **Depth limit**: hardcoded max depth of 1 (subagents of subagents blocked)

---

## Files to Create / Modify

| File | Change |
|------|--------|
| `agent/subagent.py` | **New** — `SubagentRunner` class |
| `tools/subagent_tool.py` | **New** — `run_subagent()` async function |
| `tools/registry.py` | Add tool definition + dispatcher entry |
| `config.py` | Add `MAX_SUBAGENT_TOOL_CALLS` (default 8) |

---

## Phase 1 — Core Infrastructure (MVP)

### 1a. `agent/subagent.py`

A trimmed-down version of `Agent.chat()` with:
- Same `AsyncOpenAI` client pointing at DeepSeek
- Same `dispatch_tool()` dispatcher
- `is_subagent=True` flag injected so `run_subagent` is excluded from available tools
- Separate system prompt: "You are a subagent of Dennis. Complete the given task
  using only the tools provided. Return a concise result."
- Returns a plain string (the final assistant message)
- `approval_callback` wired to the same callback as the parent (approval prompts
  reach the user)

### 1b. `tools/subagent_tool.py`

```python
async def run_subagent(
    task: str,
    tools: list[str],          # names of tools to allow, e.g. ["web_search", "fetch_page"]
    context: str = "",         # optional extra context/facts to inject
    approval_callback = None,
) -> dict:
```

- Validates `tools` against a whitelist (all tools except `run_subagent` and
  destructive ones like `run_shell` unless explicitly requested)
- Instantiates `SubagentRunner` and calls `.run(task, tools, context)`
- Returns `{"result": "...", "tool_calls_used": N}`

### 1c. `tools/registry.py` additions

Tool definition:
```json
{
  "type": "function",
  "function": {
    "name": "run_subagent",
    "description": "Delegate a self-contained subtask to a child agent. The subagent runs its own tool-use loop with only the tools you specify, then returns a result. Use this to parallelize research, isolate risky subtasks, or keep the main conversation focused.",
    "parameters": {
      "type": "object",
      "properties": {
        "task": {
          "type": "string",
          "description": "Complete description of what the subagent should do and return."
        },
        "tools": {
          "type": "array",
          "items": {"type": "string"},
          "description": "List of tool names the subagent may use (e.g. ['web_search','fetch_page'])."
        },
        "context": {
          "type": "string",
          "description": "Optional background facts or constraints to give the subagent."
        }
      },
      "required": ["task", "tools"]
    }
  }
}
```

Dispatcher addition (in `dispatch_tool`):
```python
"run_subagent": lambda: subagent_tool.run_subagent(
    approval_callback=approval_callback, **args
),
```

Note: `approval_callback` must be threaded through `dispatch_tool()` — requires
a small signature change to pass it in.

### 1d. `config.py`

```python
MAX_SUBAGENT_TOOL_CALLS: int = int(os.getenv("MAX_SUBAGENT_TOOL_CALLS", "8"))
```

---

## Phase 2 — Parallel Subagents

The main agent can already call `run_subagent` multiple times in one turn (the
LLM issues multiple tool calls in a single response). To make these run in
parallel rather than sequentially, update `Agent.chat()` to detect when the
response contains multiple tool calls and `asyncio.gather` them.

This is a one-function change in `agent/core.py` (the tool dispatch section of
`chat()`), and has broad benefit even without subagents.

---

## Phase 3 — Safety & Limits

- **Tool whitelist enforcement**: `run_subagent` validates the `tools` list
  against `SAFE_SUBAGENT_TOOLS` (everything except `run_subagent`, `run_shell`,
  `linkedin_post`, `linkedin_send_connection`, `send_email` — these still require
  parent-level approval flow).
- **Timeout**: `SubagentRunner.run()` wrapped in `asyncio.wait_for(timeout=120)`
- **Depth guard**: `SubagentRunner` passes a stripped `TOOL_DEFINITIONS` that
  omits `run_subagent`, making recursion impossible without special handling.
- **Budget tracking**: subagent calls increment the same `api_calls` counter in
  SQLite, so the daily budget cap is respected end-to-end.

---

## Phase 4 — UX (Telegram)

- When a subagent is running, the bot sends a status message:
  `"[subagent] Working on: {task[:60]}..."` (ephemeral, edited when done)
- If a subagent triggers an approval, the approval prompt is prefixed with
  `[subagent]` so the user knows it's from a child task.
- `/status` command updated to show active subagent count.

---

## What Changes, What Doesn't

| Aspect | Status |
|--------|--------|
| Main agent loop (`Agent.chat`) | Minimal change: parallel tool dispatch + thread `approval_callback` into `dispatch_tool` |
| Tool definitions format | Unchanged (OpenAI schema) |
| Memory / ChromaDB | Unchanged — subagents don't write to memory |
| Telegram bot | Minor: status message for running subagents |
| Scheduler / goals | Unchanged in Phase 1; could use subagents in Phase 2+ |
| Approval flow | Unchanged — same callback, subagents reuse it |

---

## Rollout Order

1. **Phase 1** — `subagent.py` + `subagent_tool.py` + registry wiring + config key
2. **Phase 2** — Parallel tool dispatch in `agent/core.py`
3. **Phase 3** — Safety hardening (whitelist, timeout, depth guard)
4. **Phase 4** — Telegram UX polish

Each phase is independently mergeable and testable.
