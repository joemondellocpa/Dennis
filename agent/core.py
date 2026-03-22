"""
Dennis Agent Core.

Runs DeepSeek with full tool-use loop. Handles:
- Conversation with persistent memory
- Tool dispatch (shell, browser, GitHub, Google, LinkedIn, memory)
- Safety guardrails (approval required for destructive/social actions)
"""
import re
import json
import asyncio
from datetime import datetime, timezone
from typing import Optional, Callable, Awaitable

from openai import AsyncOpenAI
from loguru import logger

import config
from agent import local_llm
from agent.memory import Memory
from tools.registry import TOOL_DEFINITIONS, dispatch_tool

# Tools that require explicit user approval before executing (always, no session bypass)
APPROVAL_REQUIRED_TOOLS = {
    "send_email",
    "linkedin_post",
    "linkedin_send_connection",
    "run_shell",
}

# Tools blocked entirely in autonomous (unattended) mode
AUTONOMOUS_BLOCKED_TOOLS = {
    "send_email",
    "linkedin_post",
    "linkedin_send_connection",
    "run_shell",  # No shell in background – no user present to supervise
}

# Shell operator characters that make a command non-read-only
_SHELL_OPERATORS = (";", "&&", "||", "|", ">", ">>", "<", "`", "$(", "&")

# Binaries that have meaningful subcommands worth trusting as a pair
_SUBCOMMAND_BINARIES = frozenset({
    "git", "brew", "pip", "pip3", "npm", "docker", "systemctl",
    "launchctl", "defaults", "diskutil", "osascript",
})

# Read-only shell commands that never need approval
_READONLY_CMDS = frozenset({
    # filesystem / inspection
    "ls", "cat", "echo", "pwd", "find", "stat", "file", "du", "df",
    "head", "tail", "wc", "grep", "diff", "less", "more",
    # process / system info
    "ps", "top", "date", "whoami", "uname", "uptime", "id",
    "which", "type", "sw_vers", "system_profiler", "diskutil",
    # network / info (read-only)
    # Note: curl/wget excluded – they can write files with -o/-O flags without shell operators
    "ping", "nslookup", "dig", "netstat", "ifconfig", "hostname",
    # python / pip (read-only queries)
    "python", "python3", "pip", "pip3",
    # sqlite read queries
    "sqlite3",
    # git read operations
    "git",
    # package managers (list/info only — write ops use operators so still caught)
    "brew", "npm", "node",
    # misc safe
    "open", "pbpaste", "pbcopy", "say", "env", "printenv", "history",
})

# Cap tool result size before stuffing into the message context (token saving)
TOOL_RESULT_MAX_CHARS = 2000

SYSTEM_PROMPT = """You are Dennis, a highly capable personal AI assistant running persistently on a Mac mini.

Your owner communicates with you via Telegram from their phone. You have access to their Mac system, Google accounts (Gmail, Calendar, Drive), GitHub, LinkedIn, and the web.

## Core capabilities
- **Memory**: You remember everything. Store important facts with remember_fact. Search past conversations with search_memory.
- **Goals**: You autonomously pursue stated goals in the background. Create goals with create_goal, track progress with update_goal.
- **Web research**: Search and read web pages for any research task.
- **Email & Calendar**: Read, draft, and send emails; manage calendar events.
- **LinkedIn**: Research prospects, draft posts, and send connection requests (with user approval).
- **GitHub**: Read and manage code repositories.
- **Mac system**: Run shell commands on the Mac mini. Read-only commands run freely. Write/destructive commands require approval unless the pattern is on the trusted list. When asking approval, offer the "always" option to let the user add a blanket approval for that command type.

## Behavioral rules
1. **Proactive**: Don't wait to be asked. If you notice something important (urgent email, upcoming meeting, new BD opportunity), flag it.
2. **Memory-first**: Before answering any question, search your memory for relevant context. Store what you learn.
3. **Goal-driven**: When given a goal, break it into tasks and work on them autonomously between conversations.
4. **Approval before action**: ALWAYS ask for explicit approval before sending emails, posting to LinkedIn, sending connection requests, or running shell commands that modify system state. For shell commands, always offer the "always" option so the user can grant blanket approval for that command type.
5. **Concise by default**: Keep responses short unless detail is explicitly requested. Use bullet points.
6. **Business focus**: Your owner runs a business. Prioritize tasks related to BD, outreach, LinkedIn, market research, and productivity.
7. **Behavior updates**: When the owner asks you to change how you work (e.g. "focus on X", "be more concise"), use the update_behavior tool to persist that preference.

## Current context
- Timezone: {timezone}
- Current time: {current_time}
- Active goals: {active_goals}
{behavior_section}"""


class Agent:
    def __init__(self, memory: Memory, send_message_fn: Callable[[str], Awaitable[None]]):
        self.memory = memory
        self.send_message = send_message_fn
        self.client = AsyncOpenAI(
            api_key=config.DEEPSEEK_API_KEY,
            base_url=config.DEEPSEEK_BASE_URL,
        )

    async def _build_system_prompt(self) -> str:
        goals = self.memory.get_active_goals()
        goals_str = "\n".join(
            f"- [{g['priority']}] {g['title']}: {g['description'][:100]}" for g in goals
        ) or "None"

        behavior = self.memory.get_behavior_config()
        if behavior:
            behavior_section = "\n## Behavioral preferences (set by owner)\n" + "\n".join(
                f"- {k}: {v}" for k, v in behavior.items()
            )
        else:
            behavior_section = ""

        return SYSTEM_PROMPT.format(
            timezone=config.AGENT_TIMEZONE,
            current_time=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
            active_goals=goals_str,
            behavior_section=behavior_section,
        )

    @staticmethod
    def _extract_trust_pattern(cmd: str) -> str:
        """Return the most meaningful prefix to use as a trust pattern."""
        words = cmd.strip().split()
        if not words:
            return cmd
        first = words[0].split("/")[-1]
        if len(words) >= 2 and first in _SUBCOMMAND_BINARIES:
            return f"{first} {words[1]}"
        return first

    def _is_readonly_shell(self, cmd: str) -> bool:
        """Return True only if a shell command is provably read-only (no operators, known safe cmd)."""
        if any(op in cmd for op in _SHELL_OPERATORS):
            return False
        first_word = cmd.strip().split()[0].split("/")[-1] if cmd.strip() else ""
        return first_word in _READONLY_CMDS

    def _is_readonly_pipe(self, cmd: str) -> bool:
        """Return True if command is a pipe of only read-only commands with no other dangerous operators."""
        dangerous_ops = (";", "&&", "||", ">", ">>", "<", "`", "$(", "&")
        if any(op in cmd for op in dangerous_ops):
            return False
        if "|" not in cmd:
            return False
        for part in cmd.split("|"):
            part = part.strip()
            first_word = part.split()[0].split("/")[-1] if part.split() else ""
            if first_word not in _READONLY_CMDS:
                return False
        return True

    def _assess_shell_risk(self, cmd: str) -> str:
        """Return a human-readable explanation of the risks of running a shell command."""
        risks = []

        if re.search(r"\brm\b", cmd):
            if re.search(r"-[^- ]*[rf]|--(recursive|force)", cmd):
                risks.append("Recursive/force delete — permanently removes files or directories, no undo")
            else:
                risks.append("Deletes files permanently (no Trash)")

        if re.search(r"\bsudo\b|\bsu\b", cmd):
            risks.append("Runs with root/admin privileges — can modify any part of the system")

        if re.search(r"\bchmod\b|\bchown\b|\bchgrp\b", cmd):
            risks.append("Changes file permissions or ownership")

        if re.search(r"\bkill\b|\bpkill\b|\bkillall\b", cmd):
            risks.append("Terminates running processes, possibly causing data loss")

        if re.search(r"\bdd\b\s", cmd):
            risks.append("Low-level disk write — can corrupt or overwrite storage if wrong target")

        if re.search(r"\bmkfs\b|\bfdisk\b|\bdiskutil\s+erase\b", cmd):
            risks.append("Disk formatting — irreversible data loss")

        if re.search(r"\bdefaults\s+write\b|\blaunchctl\b|\bsystemctl\b|\bsystemsetup\b", cmd):
            risks.append("Modifies macOS system or app configuration")

        if re.search(r"\bcrontab\b", cmd):
            risks.append("Modifies scheduled tasks (cron jobs)")

        if re.search(r"\bbrew\s+install\b|\bpip\s+install\b|\bnpm\s+install\b|\bapt\b|\byum\b", cmd):
            risks.append("Installs software — modifies system packages")

        if re.search(r"\bgit\s+(push|commit|reset|rebase|checkout|branch\s+-[Dd])\b", cmd):
            risks.append("Git write operation — modifies repository state")

        if re.search(r"\bcurl\b.*\s-[^' ]*[oO]|\bwget\b", cmd):
            risks.append("Downloads files from the internet")

        if ">>" in cmd:
            risks.append("Appends output to a file")
        elif ">" in cmd:
            risks.append("Overwrites file content — existing data will be lost")

        if re.search(r"[;]|&&|\|\|", cmd):
            risks.append("Chains multiple commands — each runs in sequence")

        if "`" in cmd or "$(" in cmd:
            risks.append("Contains command substitution — executes nested commands")

        if not risks:
            risks.append("Modifies system state (not a read-only operation)")

        return "\n".join(f"• {r}" for r in risks)

    async def _needs_approval(self, tool_name: str, args: dict) -> Optional[str]:
        """Return an approval prompt string if tool needs approval, else None."""
        if tool_name not in APPROVAL_REQUIRED_TOOLS:
            return None
        if tool_name == "run_shell":
            cmd = args.get("command", "")
            if self._is_readonly_shell(cmd):
                return None  # Safe read-only command, no approval needed
            if self._is_readonly_pipe(cmd):
                return None  # Safe pipe of read-only commands, no approval needed
            if self.memory.is_trusted_shell(cmd):
                return None  # User previously granted blanket approval for this pattern
            risk_explanation = self._assess_shell_risk(cmd)
            pattern = self._extract_trust_pattern(cmd)
            return (
                f"⚠️ Shell command needs approval\n"
                f"```\n{cmd}\n```\n"
                f"**Risks:**\n{risk_explanation}\n\n"
                f"Reply **yes** (once), **always** (always allow `{pattern}` commands), "
                f"or **no** to cancel.\n"
                f"[trust_pattern:{pattern}]"
            )
        return (
            f"⚠️ Approval needed: **{tool_name}**\n"
            f"```\n{json.dumps(args, indent=2)}\n```\n"
            f"Reply **yes** to confirm or **no** to cancel."
        )

    def _truncate_tool_result(self, result: dict) -> dict:
        """Truncate large string fields in a tool result to keep context small."""
        result_str = json.dumps(result)
        if len(result_str) <= TOOL_RESULT_MAX_CHARS:
            return result
        # Truncate the content/stdout/body fields which tend to be large
        truncated = {}
        for k, v in result.items():
            if isinstance(v, str) and len(v) > 800:
                truncated[k] = v[:800] + f"... [truncated, {len(v) - 800} chars omitted]"
            else:
                truncated[k] = v
        truncated["_truncated"] = True
        return truncated

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
        memory_hits = self.memory.recall_relevant(user_message, n=3)
        memory_context = ""
        if memory_hits:
            memory_context = "\n\n[Relevant memory]\n" + "\n---\n".join(
                f"[{h['metadata'].get('role','?')} @ {h['metadata'].get('timestamp','?')[:10]}]: {h['content'][:200]}"
                for h in memory_hits
            )

        system = await self._build_system_prompt()
        if memory_context:
            system += memory_context

        # Keep only the last 10 turns to avoid blowing the context window
        trimmed_history = conversation_history[-(config.MAX_HISTORY_TURNS * 2):]
        messages = [{"role": "system", "content": system}] + trimmed_history
        messages.append({"role": "user", "content": user_message})

        tool_call_count = 0
        final_response = ""
        _SAFETY_CAP = 500  # absolute runaway guard; never shown to user

        while True:
            # Budget guard
            if config.DAILY_API_CALL_BUDGET > 0:
                used = self.memory.get_api_calls_today()
                if used >= config.DAILY_API_CALL_BUDGET:
                    logger.warning(f"Daily API budget of {config.DAILY_API_CALL_BUDGET} calls reached")
                    return (
                        f"⚠️ Daily API call budget ({config.DAILY_API_CALL_BUDGET}) reached. "
                        "I'll resume tomorrow, or you can raise DAILY_API_CALL_BUDGET in settings."
                    )

            if tool_call_count >= _SAFETY_CAP:
                logger.error(f"Safety cap of {_SAFETY_CAP} tool calls reached — aborting to prevent runaway loop")
                break

            response = await self.client.chat.completions.create(
                model=config.DEEPSEEK_MODEL,
                messages=messages,
                tools=TOOL_DEFINITIONS,
                tool_choice="auto",
                max_tokens=4096,
            )
            self.memory.record_api_call(config.DEEPSEEK_MODEL, call_type="chat")
            msg = response.choices[0].message

            if not msg.tool_calls:
                final_response = msg.content or ""
                break

            messages.append(msg)

            for tc in msg.tool_calls:
                tool_name = tc.function.name
                try:
                    args = json.loads(tc.function.arguments)
                except json.JSONDecodeError:
                    args = {}

                # Check approval for each call individually (no session-wide bypass)
                approval_prompt = await self._needs_approval(tool_name, args)
                if approval_prompt:
                    if approval_callback:
                        decision = await approval_callback(approval_prompt)
                    else:
                        decision = "no"
                    if decision == "always" and tool_name == "run_shell":
                        import re as _re
                        m = _re.search(r"\[trust_pattern:(.+?)\]", approval_prompt)
                        pattern = m.group(1) if m else self._extract_trust_pattern(
                            args.get("command", "")
                        )
                        self.memory.add_trusted_shell(pattern)
                        logger.info(f"Trusted shell pattern added: '{pattern}'")
                    approved = decision in ("yes", "always")
                    if not approved:
                        result = {"success": False, "error": "User declined this action."}
                        messages.append({
                            "role": "tool",
                            "tool_call_id": tc.id,
                            "content": json.dumps(result),
                        })
                        tool_call_count += 1
                        continue

                logger.info(f"Tool: {tool_name}({json.dumps(args)[:100]})")
                result = await dispatch_tool(tool_name, args, memory=self.memory)
                logger.debug(f"Tool result: {str(result)[:200]}")

                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": json.dumps(self._truncate_tool_result(result)),
                })
                tool_call_count += 1

        # Store exchange in memory
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

        # Separate goals that need planning from those ready to execute
        to_plan = []
        to_execute = []
        for goal in goals:
            pending_tasks = self.memory.get_goal_tasks(goal["id"], status="pending")
            if not pending_tasks:
                to_plan.append(goal)
            else:
                to_execute.append((goal, pending_tasks[0]))

        # Plan goals that have no pending tasks (sequential, low cost)
        for goal in to_plan:
            await self._plan_goal_tasks(goal)

        # Execute all ready tasks concurrently — each gets its own tool call budget
        if to_execute:
            results = await asyncio.gather(
                *[self._execute_goal_task(goal, task) for goal, task in to_execute],
                return_exceptions=True,
            )
            for result in results:
                if isinstance(result, Exception):
                    logger.error(f"Autonomous task error: {result}")
                elif result and notify_fn:
                    await notify_fn(result)

    async def _plan_goal_tasks(self, goal: dict):
        """Ask DeepSeek to break a goal into concrete tasks using the create_goal_task tool."""
        # Guard 1: don't pile on if tasks are already waiting to run
        pending_tasks = self.memory.get_goal_tasks(goal["id"], status="pending")
        if len(pending_tasks) >= 3:
            logger.debug(
                f"Goal '{goal['title']}' already has {len(pending_tasks)} pending tasks – "
                "skipping planning until they're worked through"
            )
            return

        # Guard 2: time-based loop detection – too many tasks created recently
        today_count = self.memory.get_task_count_today(goal["id"])
        if today_count >= 20:
            logger.warning(
                f"Goal '{goal['title']}' has {today_count} tasks created in the last 24h – "
                "skipping planning to prevent runaway loop"
            )
            return

        # Only expose the task-creation tool so the LLM can't go off on a tangent
        planning_tools = [t for t in TOOL_DEFINITIONS if t["function"]["name"] == "create_goal_task"]

        system = await self._build_system_prompt()
        recent_tasks = self.memory.get_goal_tasks(goal["id"])[-5:]
        recent_str = "\n".join(
            f"- [{t['status']}] {t['description'][:80]}" for t in recent_tasks
        ) or "None yet"

        messages = [
            {"role": "system", "content": system},
            {
                "role": "user",
                "content": (
                    f"Plan the next 2–3 concrete, actionable tasks for this goal.\n\n"
                    f"Goal: {goal['title']}\n"
                    f"Description: {goal['description']}\n"
                    f"Recent tasks: {recent_str}\n\n"
                    f"Use create_goal_task for each task. Be very specific – "
                    f"each task should be completable in one autonomous iteration."
                ),
            },
        ]

        try:
            if config.DAILY_API_CALL_BUDGET > 0:
                used = self.memory.get_api_calls_today()
                if used >= config.DAILY_API_CALL_BUDGET:
                    logger.warning("Daily API budget reached – skipping goal planning")
                    return

            response = await self.client.chat.completions.create(
                model=config.DEEPSEEK_MODEL,
                messages=messages,
                tools=planning_tools,
                tool_choice={"type": "function", "function": {"name": "create_goal_task"}},
                max_tokens=1024,
            )
            self.memory.record_api_call(config.DEEPSEEK_MODEL, call_type="plan")
            msg = response.choices[0].message
            tasks_created = 0
            if msg.tool_calls:
                for tc in msg.tool_calls:
                    if tc.function.name == "create_goal_task":
                        try:
                            args = json.loads(tc.function.arguments)
                            self.memory.add_goal_task(goal["id"], args["description"])
                            tasks_created += 1
                        except (json.JSONDecodeError, KeyError) as e:
                            logger.warning(f"Bad create_goal_task args: {e}")

            if tasks_created == 0:
                # LLM didn't create tasks (e.g. said the goal is done) – add one fallback
                self.memory.add_goal_task(
                    goal["id"],
                    f"Review progress and determine next step for: {goal['title']}",
                )
                logger.info(f"Goal '{goal['title']}': LLM planned 0 tasks, added fallback")
            else:
                logger.info(f"Goal '{goal['title']}': planned {tasks_created} tasks")

        except Exception:
            logger.exception(f"Error planning tasks for goal '{goal['title']}'")

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
                    f"Execute this task using available tools. "
                    f"Do NOT send emails, post to LinkedIn, send connection requests, "
                    f"or run shell commands – these require user presence. "
                    f"If you find something important, summarize it so the user can be notified. "
                    f"If the task involves drafting, save the draft via save_knowledge and report it."
                ),
            },
        ]

        tool_calls_made = 0
        result_summary = None
        _AUTONOMOUS_SAFETY_CAP = 150  # hard runaway guard for background tasks

        while True:
            if config.DAILY_API_CALL_BUDGET > 0:
                used = self.memory.get_api_calls_today()
                if used >= config.DAILY_API_CALL_BUDGET:
                    logger.warning("Daily API budget reached – stopping autonomous task mid-execution")
                    break

            if tool_calls_made >= _AUTONOMOUS_SAFETY_CAP:
                logger.error(
                    f"Autonomous safety cap ({_AUTONOMOUS_SAFETY_CAP}) hit for task "
                    f"'{task['description'][:60]}' – aborting"
                )
                break

            response = await self.client.chat.completions.create(
                model=config.DEEPSEEK_MODEL,
                messages=messages,
                tools=TOOL_DEFINITIONS,
                tool_choice="auto",
                max_tokens=2048,
            )
            self.memory.record_api_call(config.DEEPSEEK_MODEL, call_type="autonomous")
            msg = response.choices[0].message
            if not msg.tool_calls:
                result_summary = msg.content
                break

            messages.append(msg)
            for tc in msg.tool_calls:
                try:
                    args = json.loads(tc.function.arguments)
                except json.JSONDecodeError:
                    args = {}

                if tc.function.name in AUTONOMOUS_BLOCKED_TOOLS:
                    result = {"success": False, "error": "Requires user presence – skipped in autonomous mode"}
                else:
                    result = await dispatch_tool(tc.function.name, args, memory=self.memory)

                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": json.dumps(self._truncate_tool_result(result)),
                })
                tool_calls_made += 1

        # Mark task complete only if the model naturally concluded; otherwise leave pending
        if result_summary:
            self.memory.complete_goal_task(task["id"], result_summary)
        else:
            self.memory.complete_goal_task(task["id"], "Completed")
        self.memory.update_goal_progress(goal["id"], f"Task completed: {task['description'][:100]}")

        if result_summary and len(result_summary) > 50:
            # Use local LLM to decide if this warrants an immediate notification,
            # reducing noise from routine progress updates.
            should_notify = True
            if config.OLLAMA_ENABLED:
                score = await local_llm.classify(
                    f"Does this agent finding genuinely warrant an immediate user notification?\n\n"
                    f"Goal: {goal['title']}\n"
                    f"Finding: {result_summary[:400]}\n\n"
                    f"Consider: Is this actionable, time-sensitive, or significant? "
                    f"Or is it just routine/incremental progress?\n\nAnswer YES or NO.",
                    max_tokens=5,
                )
                if score is not None and score.strip().upper().startswith("NO"):
                    should_notify = False
                    logger.debug(f"Local LLM filtered notification for '{goal['title']}'")

            if should_notify:
                return f"🤖 **Background update** – *{goal['title']}*\n\n{result_summary}"
        return None
