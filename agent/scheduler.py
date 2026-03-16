"""
Autonomous background goal scheduler.

Runs on a configurable interval and executes one goal task per cycle.
Notifications are sent back to the user via Telegram.
"""
import asyncio
from typing import Callable, Awaitable, Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from loguru import logger

import config
from agent.core import Agent


class GoalScheduler:
    def __init__(self, agent: Agent, notify_fn: Callable[[str], Awaitable[None]]):
        """
        agent: the Agent instance
        notify_fn: async function to send a message to the user (e.g. Telegram send_message)
        """
        self.agent = agent
        self.notify_fn = notify_fn
        self._scheduler = AsyncIOScheduler(timezone=config.AGENT_TIMEZONE)
        self._running = False

    def start(self):
        if self._running:
            return
        self._scheduler.add_job(
            self._tick,
            trigger=IntervalTrigger(seconds=config.AUTONOMOUS_LOOP_INTERVAL),
            id="goal_loop",
            replace_existing=True,
            max_instances=1,
        )
        # Also run a daily morning briefing
        self._scheduler.add_job(
            self._morning_briefing,
            trigger="cron",
            hour=8,
            minute=0,
            timezone=config.AGENT_TIMEZONE,
            id="morning_briefing",
            replace_existing=True,
        )
        self._scheduler.start()
        self._running = True
        logger.info(f"Goal scheduler started – ticking every {config.AUTONOMOUS_LOOP_INTERVAL}s")

    def stop(self):
        self._scheduler.shutdown(wait=False)
        self._running = False

    async def _tick(self):
        """Run one background autonomous iteration."""
        try:
            logger.debug("Autonomous tick: checking goals...")
            await self.agent.autonomous_run(notify_fn=self.notify_fn)
        except Exception:
            logger.exception("Error in autonomous goal tick")

    async def _morning_briefing(self):
        """
        Daily 8 AM briefing: upcoming calendar, unread emails summary, goal progress.
        """
        try:
            logger.info("Generating morning briefing...")
            from tools import dispatch_tool
            from agent.memory import Memory

            # Fetch calendar and email in parallel
            cal_result, email_result, goals = await asyncio.gather(
                dispatch_tool("list_calendar_events", {"days_ahead": 2, "max_results": 5}, memory=self.agent.memory),
                dispatch_tool("list_emails", {"query": "is:unread", "max_results": 5}, memory=self.agent.memory),
                asyncio.coroutine(lambda: self.agent.memory.get_active_goals())(),
            )

            lines = [f"☀️ **Good morning! Here's your briefing:**\n"]

            # Calendar
            events = cal_result.get("events", []) if cal_result.get("success") else []
            if events:
                lines.append("📅 **Upcoming:**")
                for e in events:
                    lines.append(f"  • {e['summary']} – {e['start']}")

            # Email
            emails = email_result.get("emails", []) if email_result.get("success") else []
            if emails:
                lines.append(f"\n📬 **{len(emails)} unread emails**, including:")
                for e in emails[:3]:
                    lines.append(f"  • {e['subject']} (from {e['from'][:40]})")

            # Goals
            if goals:
                lines.append(f"\n🎯 **{len(goals)} active goals** – I'll keep working on them.")

            await self.notify_fn("\n".join(lines))
        except Exception:
            logger.exception("Error in morning briefing")
