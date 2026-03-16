"""
Dennis Agent Core.

Runs DeepSeek with full tool-use loop. Handles:
- Conversation with persistent memory
- Tool dispatch (shell, browser, GitHub, Google, LinkedIn, memory)
- Safety guardrails (approval required for destructive/social actions)
"""
import json
import asyncio
from datetime import datetime, timezone
from typing import Optional, Callable, Awaitable

from openai import AsyncOpenAI
from loguru import logger

import config
from agent.memory import Memory
from tools.registry import TOOL_DEFINITIONS, dispatch_tool

# Tools that require explicit user approval before executing
APPROVAL_REQUIRED_TOOLS = {
    "send_email",
    "linkedin_post",
    "linkedin_send_connection",
    "run_shell",  # Will prompt for approval on first use per session
}

SYSTEM_PROMPT = """You are Dennis, a highly capable personal AI assistant running persistently on a Mac mini.

Your owner communicates with you via Telegram from their phone. You have access to their Mac system, Google accounts (Gmail, Calendar, Drive), GitHub, LinkedIn, and the web.

## Core capabilities
- **Memory**: You remember everything. Store important facts with remember_fact. Search past conversations with search_memory.
- **Goals**: You autonomously pursue stated goals in the background. Create goals with create_goal, track progress with update_goal.
- **Web research**: Search and read web pages for any research task.
- **Email & Calendar**: Read, draft, and send emails; manage calendar events.
- **LinkedIn**: Research prospects, draft posts, and send connection requests (with user approval).
- **GitHub**: Read and manage code repositories.
- **Mac system**: Run shell commands on the Mac mini.

## Behavioral rules
1. **Proactive**: Don't wait to be asked. If you notice something important (urgent email, upcoming meeting, new BD opportunity), flag it.
2. **Memory-first**: Before answering any question, search your memory for relevant context. Store what you learn.
3. **Goal-driven**: When given a goal, break it into tasks and work on them autonomously between conversations.
4. **Approval before action**: ALWAYS ask for explicit approval before sending emails, posting to LinkedIn, sending connection requests, or running shell commands that modify system state.
5. **Concise by default**: Keep responses short unless detail is explicitly requested. Use bullet points.
6. **Business focus**: Your owner runs a business. Prioritize tasks related to BD, outreach, LinkedIn, market research, and productivity.

## Current context
- Timezone: {timezone}
- Current time: {current_time}
- Active goals: {active_goals}
"""


class Agent:
    def __init__(self, memory: Memory, send_message_fn: Callable[[str], Awaitable[None]]):
        """
        memory: the Memory instance
        send_message_fn: async callable to send a message back to the user (e.g. Telegram send)
        """
        self.memory = memory
        self.send_message = send_message_fn
        self.client = AsyncOpenAI(
            api_key=config.DEEPSEEK_API_KEY,
            base_url=config.DEEPSEEK_BASE_URL,
        )
        # Tracks tools approved this session (shell approval, etc.)
        self._approved_tools: set[str] = set()

    async def _build_system_prompt(self) -> str:
        goals = self.memory.get_active_goals()
        goals_str = "\n".join(f"- [{g['priority']}] {g['title']}: {g['description'][:100]}" for g in goals) or "None"
        return SYSTEM_PROMPT.format(
            timezone=config.AGENT_TIMEZONE,
            current_time=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
            active_goals=goals_str,
        )

    async def _needs_approval(self, tool_name: str, args: dict) -> Optional[str]:
        """Return an approval prompt string if tool needs approval, else None."""
        if tool_name not in APPROVAL_REQUIRED_TOOLS:
            return None
        if tool_name == "run_shell":
            cmd = args.get("command", "")
            # Allow read-only commands without approval
            readonly_prefixes = ("ls", "cat", "echo", "pwd", "date", "whoami", "ps", "df", "du", "find", "grep")
            if any(cmd.strip().startswith(p) for p in readonly_prefixes):
                return None
            if tool_name in self._approved_tools:
                return None
        return f"⚠️ Approval needed to run: **{tool_name}**\nArgs: `{json.dumps(args, indent=2)}`\n\nReply **yes** to confirm or **no** to cancel."

    async def chat(
        self,
        user_message: str,
        conversation_history: list[dict],
        approval_callback: Callable[[str], Awaitable[bool]] = None,
    ) -> str:
        """
        Process a user message and return the agent's final response.

        conversation_history: list of {"role": ..., "content": ...} dicts (maintained by caller)
        approval_callback: async fn(prompt: str) -> bool, called when a tool needs approval
        """
        # Retrieve relevant memory
        memory_hits = self.memory.recall_relevant(user_message, n=5)
        memory_context = ""
        if memory_hits:
            memory_context = "\n\n[Relevant memory]\n" + "\n---\n".join(
                f"[{h['metadata'].get('role','?')} @ {h['metadata'].get('timestamp','?')}]: {h['content'][:300]}"
                for h in memory_hits
            )

        system = await self._build_system_prompt()
        if memory_context:
            system += memory_context

        messages = [{"role": "system", "content": system}] + conversation_history

        # Add user message
        messages.append({"role": "user", "content": user_message})

        # Tool-use loop
        tool_call_count = 0
        final_response = ""

        while tool_call_count < config.MAX_TOOL_CALLS_PER_TURN:
            response = await self.client.chat.completions.create(
                model=config.DEEPSEEK_MODEL,
                messages=messages,
                tools=TOOL_DEFINITIONS,
                tool_choice="auto",
                max_tokens=4096,
            )
            msg = response.choices[0].message

            # No tool call – final response
            if not msg.tool_calls:
                final_response = msg.content or ""
                break

            # Append assistant turn with tool calls
            messages.append(msg)

            # Process each tool call
            for tc in msg.tool_calls:
                tool_name = tc.function.name
                try:
                    args = json.loads(tc.function.arguments)
                except json.JSONDecodeError:
                    args = {}

                # Check approval
                approval_prompt = await self._needs_approval(tool_name, args)
                if approval_prompt and approval_callback:
                    approved = await approval_callback(approval_prompt)
                    if not approved:
                        result = {"success": False, "error": "User declined this action."}
                        messages.append({
                            "role": "tool",
                            "tool_call_id": tc.id,
                            "content": json.dumps(result),
                        })
                        tool_call_count += 1
                        continue
                    if tool_name == "run_shell":
                        self._approved_tools.add(tool_name)

                logger.info(f"Calling tool: {tool_name}({args})")
                result = await dispatch_tool(tool_name, args, memory=self.memory)
                logger.info(f"Tool result: {str(result)[:200]}")

                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": json.dumps(result),
                })
                tool_call_count += 1

        else:
            final_response = "I've reached the tool call limit for this turn. Please ask me to continue."

        # Store this exchange in memory
        self.memory.save_conversation_turn("user", user_message)
        if final_response:
            self.memory.save_conversation_turn("assistant", final_response)

        return final_response

    async def autonomous_run(self, notify_fn: Callable[[str], Awaitable[None]] = None):
        """
        Run one autonomous background iteration:
        - Review active goals
        - Pick the highest-priority goal with pending tasks
        - Execute one step
        - Notify user of findings if relevant
        """
        goals = self.memory.get_active_goals()
        if not goals:
            return

        for goal in goals:
            pending_tasks = self.memory.get_goal_tasks(goal["id"], status="pending")
            if not pending_tasks:
                # Ask the agent to plan next tasks for this goal
                await self._plan_goal_tasks(goal)
                continue

            task = pending_tasks[0]
            result = await self._execute_goal_task(goal, task)

            if result and notify_fn:
                await notify_fn(result)
            break  # One goal per iteration

    async def _plan_goal_tasks(self, goal: dict):
        """Ask DeepSeek to break a goal into executable tasks."""
        system = await self._build_system_prompt()
        messages = [
            {"role": "system", "content": system},
            {
                "role": "user",
                "content": (
                    f"I need you to plan the next 3 concrete tasks for this goal:\n"
                    f"Goal: {goal['title']}\nDescription: {goal['description']}\n"
                    f"Progress so far: {goal.get('progress_notes', '[]')}\n\n"
                    f"Use the create_goal_task tool or just list tasks. For each task, be very specific and actionable."
                ),
            },
        ]
        response = await self.client.chat.completions.create(
            model=config.DEEPSEEK_MODEL,
            messages=messages,
            tools=TOOL_DEFINITIONS,
            tool_choice="auto",
            max_tokens=1024,
        )
        msg = response.choices[0].message
        if msg.tool_calls:
            for tc in msg.tool_calls:
                args = json.loads(tc.function.arguments)
                if tc.function.name in ("create_goal",):
                    # Extract task descriptions and add them
                    pass
        # Fallback: create a generic research task
        self.memory.add_goal_task(goal["id"], f"Research and make progress on: {goal['title']}")

    async def _execute_goal_task(self, goal: dict, task: dict) -> Optional[str]:
        """Execute a single goal task autonomously. Returns a user notification if significant."""
        system = await self._build_system_prompt()
        messages = [
            {"role": "system", "content": system},
            {
                "role": "user",
                "content": (
                    f"[AUTONOMOUS BACKGROUND TASK]\n"
                    f"Goal: {goal['title']}\n"
                    f"Task: {task['description']}\n\n"
                    f"Execute this task using available tools. Do NOT send emails, post to LinkedIn, "
                    f"or send connection requests without explicit user approval. "
                    f"If you find something important, prepare a summary to notify the user. "
                    f"If the task involves drafting (emails, posts), save the draft and report it."
                ),
            },
        ]

        tool_calls_made = 0
        result_summary = None

        while tool_calls_made < 5:
            response = await self.client.chat.completions.create(
                model=config.DEEPSEEK_MODEL,
                messages=messages,
                tools=TOOL_DEFINITIONS,
                tool_choice="auto",
                max_tokens=2048,
            )
            msg = response.choices[0].message
            if not msg.tool_calls:
                result_summary = msg.content
                break

            messages.append(msg)
            for tc in msg.tool_calls:
                args = json.loads(tc.function.arguments)
                # Block actions that need approval in autonomous mode
                if tc.function.name in {"send_email", "linkedin_post", "linkedin_send_connection"}:
                    result = {"success": False, "error": "Requires user approval – will present draft to user"}
                else:
                    result = await dispatch_tool(tc.function.name, args, memory=self.memory)
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": json.dumps(result),
                })
                tool_calls_made += 1

        # Mark task complete
        self.memory.complete_goal_task(task["id"], result_summary or "Completed")
        self.memory.update_goal_progress(goal["id"], f"Task completed: {task['description'][:100]}")

        # Only notify if there's a meaningful result
        if result_summary and len(result_summary) > 50:
            return f"🤖 **Background update** – *{goal['title']}*\n\n{result_summary}"
        return None
