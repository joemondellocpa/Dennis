"""
Smart notification wrapper that enforces quiet hours and rate limiting.

- During quiet hours: messages are queued and delivered at QUIET_HOURS_END
- Outside quiet hours: if under MAX_NOTIFICATIONS_PER_HOUR, sent immediately;
  if over limit, queued for delivery at the next full hour
"""
import asyncio
from datetime import datetime, timezone, timedelta
from typing import Callable, Awaitable
from zoneinfo import ZoneInfo

from loguru import logger

import config
from agent.memory import Memory


def _now_local() -> datetime:
    return datetime.now(ZoneInfo(config.AGENT_TIMEZONE))


def _is_quiet_hours() -> bool:
    hour = _now_local().hour
    s, e = config.QUIET_HOURS_START, config.QUIET_HOURS_END
    if s > e:  # Wraps midnight (e.g. 22 -> 7)
        return hour >= s or hour < e
    return s <= hour < e


def _next_quiet_end() -> datetime:
    """Return the next datetime when quiet hours end (local tz, converted to UTC)."""
    now_local = _now_local()
    end_today = now_local.replace(hour=config.QUIET_HOURS_END, minute=0, second=0, microsecond=0)
    if end_today <= now_local:
        end_today += timedelta(days=1)
    return end_today.astimezone(timezone.utc)


class SmartNotifier:
    """Wraps a raw notify callable with quiet-hours and rate-limit logic."""

    def __init__(self, memory: Memory, raw_notify: Callable[[str], Awaitable[None]]):
        self._memory = memory
        self._raw = raw_notify
        self._sent_this_hour: list[datetime] = []

    def _prune_hour_window(self):
        cutoff = datetime.now(timezone.utc) - timedelta(hours=1)
        self._sent_this_hour = [t for t in self._sent_this_hour if t > cutoff]

    def _over_rate_limit(self) -> bool:
        self._prune_hour_window()
        return len(self._sent_this_hour) >= config.MAX_NOTIFICATIONS_PER_HOUR

    async def send(self, message: str, source: str = "system", force: bool = False):
        """
        Send a notification, respecting quiet hours and rate limits.

        force=True: always send immediately (used for approval prompts, errors).
        """
        if force:
            await self._raw(message)
            return

        if _is_quiet_hours():
            deliver_at = _next_quiet_end()
            self._memory.queue_notification(message, deliver_at, source)
            logger.debug(f"Notification queued (quiet hours) for {deliver_at.isoformat()}")
            return

        if self._over_rate_limit():
            # Queue for next hour
            deliver_at = datetime.now(timezone.utc) + timedelta(hours=1)
            deliver_at = deliver_at.replace(minute=0, second=0, microsecond=0)
            self._memory.queue_notification(message, deliver_at, source)
            logger.debug("Notification queued (rate limit)")
            return

        await self._raw(message)
        self._sent_this_hour.append(datetime.now(timezone.utc))

    async def flush_queued(self):
        """Deliver all due queued notifications. Called at quiet-hours-end."""
        due = self._memory.get_due_notifications()
        if not due:
            return
        logger.info(f"Flushing {len(due)} queued notifications")
        for notif in due:
            try:
                await self._raw(notif["message"])
                self._memory.delete_notification(notif["id"])
                self._sent_this_hour.append(datetime.now(timezone.utc))
            except Exception as e:
                logger.warning(f"Failed to deliver queued notification: {e}")
