"""
Autonomous background goal scheduler.

Jobs:
- goal_loop        : every AUTONOMOUS_LOOP_INTERVAL seconds
- email_triage     : every PRIORITY_EMAIL_CHECK_INTERVAL seconds
- webhook_processor: every 60 seconds
- morning_briefing : daily at 8am
- quiet_hours_flush: daily at QUIET_HOURS_END (deliver queued notifications)
- goal_completion  : weekly check, inside goal_loop
- self_evaluation  : weekly on Sunday at 21:00
- memory_prune     : daily at 03:00
"""
import asyncio
import json
from datetime import datetime, timezone
from typing import Callable, Awaitable, Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from loguru import logger

import config
from agent import local_llm
from agent.core import Agent


class GoalScheduler:
    def __init__(
        self,
        agent: Agent,
        notify_fn: Callable[[str], Awaitable[None]],
        notifier=None,
    ):
        self.agent = agent
        # notify_fn should be a SmartNotifier.send or equivalent
        self.notify_fn = notify_fn
        # notifier is the SmartNotifier instance (for flush_queued access)
        self._notifier = notifier
        self._scheduler = AsyncIOScheduler(timezone=config.AGENT_TIMEZONE)
        self._running = False
        self._paused = False

    def start(self):
        if self._running:
            return

        self._scheduler.add_job(
            self._tick, IntervalTrigger(seconds=config.AUTONOMOUS_LOOP_INTERVAL),
            id="goal_loop", replace_existing=True, max_instances=1,
        )

        if config.PRIORITY_EMAIL_CHECK_INTERVAL > 0:
            self._scheduler.add_job(
                self._email_triage, IntervalTrigger(seconds=config.PRIORITY_EMAIL_CHECK_INTERVAL),
                id="email_triage", replace_existing=True, max_instances=1,
            )

        self._scheduler.add_job(
            self._process_webhook_events, IntervalTrigger(seconds=60),
            id="webhook_processor", replace_existing=True, max_instances=1,
        )

        self._scheduler.add_job(
            self._morning_briefing,
            trigger="cron", hour=8, minute=0,
            timezone=config.AGENT_TIMEZONE,
            id="morning_briefing", replace_existing=True,
        )

        self._scheduler.add_job(
            self._flush_quiet_queue,
            trigger="cron", hour=config.QUIET_HOURS_END, minute=1,
            timezone=config.AGENT_TIMEZONE,
            id="quiet_flush", replace_existing=True,
        )

        self._scheduler.add_job(
            self._self_evaluation,
            trigger="cron", day_of_week="sun", hour=21, minute=0,
            timezone=config.AGENT_TIMEZONE,
            id="self_evaluation", replace_existing=True,
        )

        self._scheduler.add_job(
            self._memory_prune,
            trigger="cron", hour=3, minute=0,
            timezone=config.AGENT_TIMEZONE,
            id="memory_prune", replace_existing=True,
        )

        self._scheduler.start()
        self._running = True
        logger.info(f"Scheduler started – ticking every {config.AUTONOMOUS_LOOP_INTERVAL}s")

    def stop(self):
        self._scheduler.shutdown(wait=False)
        self._running = False

    def pause(self):
        self._paused = True
        logger.info("Autonomous scheduler paused")

    def resume(self):
        self._paused = False
        logger.info("Autonomous scheduler resumed")

    @property
    def is_paused(self) -> bool:
        return self._paused

    # ── Core tick ──────────────────────────────────────────────────────────

    async def _tick(self):
        if self._paused:
            return
        try:
            await self._process_recurring_goals()
            await self.agent.autonomous_run(notify_fn=self.notify_fn)
            await self._check_goal_completion()
        except Exception:
            logger.exception("Error in autonomous tick")

    # ── Morning briefing ───────────────────────────────────────────────────

    async def _morning_briefing(self):
        try:
            logger.info("Generating morning briefing...")
            from tools import dispatch_tool

            cal_result, email_result = await asyncio.gather(
                dispatch_tool("list_calendar_events", {"days_ahead": 2, "max_results": 5}, memory=self.agent.memory),
                dispatch_tool("list_emails", {"query": "is:unread", "max_results": 5}, memory=self.agent.memory),
            )
            goals = self.agent.memory.get_active_goals()
            drafts = self.agent.memory.get_pending_drafts()

            lines = ["☀️ **Good morning! Here's your briefing:**\n"]

            events = cal_result.get("events", []) if cal_result.get("success") else []
            if events:
                lines.append("📅 **Upcoming:**")
                for e in events:
                    lines.append(f"  • {e['summary']} – {e['start']}")

            emails = email_result.get("emails", []) if email_result.get("success") else []
            if emails:
                lines.append(f"\n📬 **{len(emails)} unread emails**, including:")
                for e in emails[:3]:
                    lines.append(f"  • {e['subject']} (from {e['from'][:40]})")

            if goals:
                lines.append(f"\n🎯 **{len(goals)} active goals** – working on them in the background.")
            else:
                lines.append("\n💡 No active goals. Send me a goal to work on!")

            if drafts:
                lines.append(f"\n📝 **{len(drafts)} draft(s) awaiting review** – use /drafts to review.")

            await self.notify_fn("\n".join(lines))
        except Exception:
            logger.exception("Error in morning briefing")

    # ── Flush queued notifications ─────────────────────────────────────────

    async def _flush_quiet_queue(self):
        try:
            if self._notifier is not None:
                await self._notifier.flush_queued()
            else:
                # Fallback: check memory directly
                due = self.agent.memory.get_due_notifications()
                for notif in due:
                    await self.notify_fn(notif["message"])
                    self.agent.memory.delete_notification(notif["id"])
        except Exception:
            logger.exception("Error flushing quiet queue")

    # ── Proactive email triage ─────────────────────────────────────────────

    async def _email_triage(self):
        if self._paused:
            return
        try:
            from tools import dispatch_tool
            result = await dispatch_tool(
                "list_emails",
                {"query": "is:unread", "max_results": 20},
                memory=self.agent.memory,
            )
            if not result.get("success"):
                return

            for email in result.get("emails", []):
                msg_id = email.get("id", "")
                if self.agent.memory.is_email_triaged(msg_id):
                    continue

                subject = email.get("subject", "").lower()
                sender = email.get("from", "").lower()
                is_priority = (
                    any(kw.lower() in subject for kw in config.PRIORITY_EMAIL_KEYWORDS)
                    or any(ps.lower() in sender for ps in config.PRIORITY_EMAIL_SENDERS)
                )

                if is_priority:
                    self.agent.memory.mark_email_triaged(msg_id, email.get("subject", ""), email.get("from", ""))
                    msg = (
                        f"📬 **Priority email detected:**\n"
                        f"From: {email.get('from', '')[:60]}\n"
                        f"Subject: {email.get('subject', '')}\n"
                        f"Date: {email.get('date', '')}"
                    )
                    await self.notify_fn(msg)
                    logger.info(f"Priority email alert sent: {email.get('subject', '')}")

        except Exception:
            logger.exception("Error in email triage")

    # ── Recurring goals ────────────────────────────────────────────────────

    async def _process_recurring_goals(self):
        """Re-trigger recurring goals when their schedule is due."""
        try:
            from datetime import timedelta
            recurring = self.agent.memory.get_recurring_goals()
            now = datetime.now(timezone.utc)

            for goal in recurring:
                schedule = json.loads(goal.get("schedule") or "{}")
                if not schedule:
                    continue

                last = goal.get("last_triggered")
                last_dt = datetime.fromisoformat(last) if last else None

                due = False
                stype = schedule.get("type", "")
                if stype == "daily":
                    due = last_dt is None or (now - last_dt).days >= 1
                elif stype == "weekly":
                    due = last_dt is None or (now - last_dt).days >= 7
                elif stype == "interval_days":
                    days = int(schedule.get("days", 7))
                    due = last_dt is None or (now - last_dt).days >= days
                elif stype == "cron_weekday":
                    # e.g. {"type": "cron_weekday", "day": "monday"}
                    target_day = schedule.get("day", "monday").lower()
                    day_map = {"monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
                               "friday": 4, "saturday": 5, "sunday": 6}
                    target = day_map.get(target_day, 0)
                    today_weekday = now.weekday()
                    due = (
                        today_weekday == target
                        and (last_dt is None or (now - last_dt).days >= 6)
                    )

                if due:
                    # Clear old pending tasks and let the planner create fresh ones
                    self.agent.memory.delete_goal_tasks(goal["id"], status="pending")
                    self.agent.memory.update_goal_last_triggered(goal["id"])
                    self.agent.memory.update_goal_progress(
                        goal["id"], f"Recurring trigger: {now.strftime('%Y-%m-%d')}"
                    )
                    logger.info(f"Recurring goal triggered: '{goal['title']}'")

        except Exception:
            logger.exception("Error processing recurring goals")

    # ── Goal completion detection ──────────────────────────────────────────

    async def _check_goal_completion(self):
        """Periodically ask the LLM if any goal looks complete."""
        try:
            from datetime import timedelta
            goals = self.agent.memory.get_active_goals()
            now = datetime.now(timezone.utc)

            for goal in goals:
                # Only check goals with substantial task history
                completed_tasks = self.agent.memory.get_goal_tasks(goal["id"], status="done")
                if len(completed_tasks) < 3:
                    continue

                # Don't re-check within 7 days
                last_check = goal.get("last_completion_check")
                if last_check:
                    last_dt = datetime.fromisoformat(last_check)
                    if (now - last_dt).days < 7:
                        continue

                self.agent.memory.mark_goal_completion_checked(goal["id"])

                completed_summary = "\n".join(
                    f"- {t['description'][:80]}: {(t['result'] or '')[:60]}"
                    for t in completed_tasks[-10:]
                )
                eval_prompt = (
                    f"Evaluate whether this goal has been achieved:\n\n"
                    f"Goal: {goal['title']}\n"
                    f"Description: {goal['description']}\n\n"
                    f"Completed tasks:\n{completed_summary}\n\n"
                    f"Reply with COMPLETE if the goal is clearly achieved, "
                    f"or ONGOING if more work is needed. "
                    f"Then briefly explain why in one sentence."
                )

                # Try local LLM first (free) – fall back to remote DeepSeek
                verdict = await local_llm.classify(
                    eval_prompt,
                    system="You are an AI assistant evaluating whether goals have been achieved.",
                    max_tokens=150,
                )

                if verdict is None:
                    # Local LLM unavailable – use remote API
                    if config.DAILY_API_CALL_BUDGET > 0:
                        if self.agent.memory.get_api_calls_today() >= config.DAILY_API_CALL_BUDGET:
                            continue

                    system = await self.agent._build_system_prompt()
                    response = await self.agent.client.chat.completions.create(
                        model=config.DEEPSEEK_MODEL,
                        messages=[
                            {"role": "system", "content": system},
                            {"role": "user", "content": eval_prompt},
                        ],
                        max_tokens=150,
                    )
                    self.agent.memory.record_api_call(config.DEEPSEEK_MODEL, "completion_check")
                    verdict = response.choices[0].message.content or ""
                else:
                    logger.debug(f"Goal completion check via local LLM: {verdict[:60]}")

                if verdict.strip().upper().startswith("COMPLETE"):
                    await self.notify_fn(
                        f"🎯 **Goal may be complete:** *{goal['title']}*\n\n"
                        f"{verdict}\n\n"
                        f"Use `/goals` to review or tell me to mark it done."
                    )
                    logger.info(f"Goal completion suggested: '{goal['title']}'")

        except Exception:
            logger.exception("Error in goal completion check")

    # ── Weekly self-evaluation ─────────────────────────────────────────────

    async def _self_evaluation(self):
        """Sunday night: review the week's work and save strategic conclusions."""
        try:
            logger.info("Running weekly self-evaluation...")
            recent_tasks = self.agent.memory.get_recent_completed_tasks(days=7)
            if not recent_tasks:
                return

            task_summary = "\n".join(
                f"- [{t['goal_title']}] {t['description'][:80]}: {(t['result'] or 'no result')[:60]}"
                for t in recent_tasks[:30]
            )

            system = await self.agent._build_system_prompt()
            messages = [
                {"role": "system", "content": system},
                {
                    "role": "user",
                    "content": (
                        f"Weekly self-evaluation. Review the work from the past 7 days:\n\n"
                        f"{task_summary}\n\n"
                        f"Identify:\n"
                        f"1. What's working well (tools, strategies that produce results)\n"
                        f"2. What's failing or stuck (errors, repeated failures)\n"
                        f"3. One strategic adjustment to make next week\n\n"
                        f"Be specific and actionable. 3-5 bullet points max."
                    ),
                },
            ]

            if config.DAILY_API_CALL_BUDGET > 0:
                if self.agent.memory.get_api_calls_today() >= config.DAILY_API_CALL_BUDGET:
                    return

            response = await self.agent.client.chat.completions.create(
                model=config.DEEPSEEK_MODEL,
                messages=messages,
                max_tokens=500,
            )
            self.agent.memory.record_api_call(config.DEEPSEEK_MODEL, "self_eval")
            evaluation = response.choices[0].message.content or ""

            # Save to knowledge base
            self.agent.memory.add_knowledge(
                evaluation,
                source=f"weekly_self_eval_{datetime.now(timezone.utc).strftime('%Y-%m-%d')}",
                tags=["self_evaluation", "strategy"],
            )

            await self.notify_fn(
                f"📊 **Weekly self-evaluation:**\n\n{evaluation}"
            )
            logger.info("Weekly self-evaluation complete")

        except Exception:
            logger.exception("Error in self-evaluation")

    # ── Memory pruning ─────────────────────────────────────────────────────

    async def _memory_prune(self):
        """Daily 3am: summarise and prune old conversation turns."""
        try:
            old_ids = self.agent.memory.get_old_conversation_ids(config.MEMORY_RETENTION_DAYS)
            if not old_ids:
                return

            logger.info(f"Pruning {len(old_ids)} old conversation turns...")
            docs = self.agent.memory.get_conversation_docs(old_ids)
            if not docs:
                return

            # Summarise in batches of 50
            batch_size = 50
            for i in range(0, len(docs), batch_size):
                batch = docs[i:i + batch_size]
                text = "\n".join(
                    f"[{d['metadata'].get('role','?')}]: {d['content'][:200]}"
                    for d in batch
                )
                summarise_prompt = f"Summarize these conversation turns in 3-5 sentences:\n\n{text}"
                summarise_system = (
                    "You are a memory summarizer. Compress conversations into "
                    "compact, factual summaries preserving key information."
                )

                # Try local LLM first (free) – fall back to remote
                summary = await local_llm.classify(
                    summarise_prompt,
                    system=summarise_system,
                    max_tokens=300,
                )

                if summary is None:
                    if config.DAILY_API_CALL_BUDGET > 0:
                        if self.agent.memory.get_api_calls_today() >= config.DAILY_API_CALL_BUDGET:
                            break

                    response = await self.agent.client.chat.completions.create(
                        model=config.DEEPSEEK_MODEL,
                        messages=[
                            {"role": "system", "content": summarise_system},
                            {"role": "user", "content": summarise_prompt},
                        ],
                        max_tokens=300,
                    )
                    self.agent.memory.record_api_call(config.DEEPSEEK_MODEL, "memory_prune")
                    summary = response.choices[0].message.content or ""

                ts_start = batch[0]["metadata"].get("timestamp", "?")[:10]
                ts_end = batch[-1]["metadata"].get("timestamp", "?")[:10]
                self.agent.memory.add_knowledge(
                    summary,
                    source=f"conversation_summary_{ts_start}_to_{ts_end}",
                    tags=["memory_summary", "pruned"],
                )

            # Delete the originals from ChromaDB
            batch_ids = old_ids[:len(docs)]
            self.agent.memory.delete_conversation_docs(batch_ids)
            logger.info(f"Pruned {len(batch_ids)} old conversation turns, saved {len(old_ids) // batch_size + 1} summaries")

        except Exception:
            logger.exception("Error in memory pruning")

    # ── Webhook event processor ────────────────────────────────────────────

    async def _process_webhook_events(self):
        """Process queued webhook events and notify the user."""
        try:
            events = self.agent.memory.get_unprocessed_webhook_events()
            for event in events:
                payload = json.loads(event["payload"])
                source = event["source"]
                event_type = event["event_type"]

                msg = self._format_webhook_event(source, event_type, payload)
                if msg:
                    await self.notify_fn(msg)

                self.agent.memory.mark_webhook_processed(event["id"])

        except Exception:
            logger.exception("Error processing webhook events")

    def _format_webhook_event(self, source: str, event_type: str, payload: dict) -> Optional[str]:
        """Format a webhook payload into a human-readable Telegram message."""
        if source == "github":
            repo = payload.get("repository", {}).get("full_name", "unknown repo")
            if event_type == "push":
                pusher = payload.get("pusher", {}).get("name", "someone")
                commits = payload.get("commits", [])
                n = len(commits)
                msg = f"🔀 **GitHub push** to `{repo}` by {pusher}\n"
                for c in commits[:3]:
                    msg += f"  • {c.get('message', '')[:80]}\n"
                if n > 3:
                    msg += f"  _...and {n - 3} more commits_"
                return msg
            elif event_type == "pull_request":
                action = payload.get("action", "")
                pr = payload.get("pull_request", {})
                title = pr.get("title", "")
                user = pr.get("user", {}).get("login", "someone")
                url = pr.get("html_url", "")
                return f"🔧 **GitHub PR {action}** in `{repo}` by {user}\n_{title}_\n{url}"
            elif event_type == "issues":
                action = payload.get("action", "")
                issue = payload.get("issue", {})
                title = issue.get("title", "")
                return f"📋 **GitHub issue {action}** in `{repo}`\n_{title}_"
            else:
                return f"🔔 **GitHub event** `{event_type}` in `{repo}`"

        elif source == "generic":
            title = payload.get("title", event_type)
            body = payload.get("body", "")
            return f"🔔 **{title}**\n{body[:300]}" if body else f"🔔 **{title}**"

        return f"🔔 **Webhook** from {source}: `{event_type}`"
