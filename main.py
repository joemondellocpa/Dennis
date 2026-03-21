"""
Dennis Agent – entry point.

Starts:
1. The Telegram bot (polling)
2. The autonomous background goal scheduler
3. The webhook server (if WEBHOOK_PORT > 0)
"""
import asyncio
import fcntl
import os
import sys
from pathlib import Path

from loguru import logger
from telegram import Bot

import config

# ── Single-instance lockfile ────────────────────────────────────────────────
# Prevents two Dennis processes from polling Telegram simultaneously (409 error).
# fcntl.flock is released automatically by the OS when the process exits, even
# on crash or SIGKILL, so stale locks are never a problem.
_LOCK_FILE = config.DATA_DIR / "dennis.lock"
_lock_fh = None  # keep reference so the lock isn't GC'd


def _acquire_instance_lock():
    global _lock_fh
    _lock_fh = open(_LOCK_FILE, "w")
    try:
        fcntl.flock(_lock_fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        logger.error(
            "Another Dennis instance is already running – exiting to avoid Telegram 409 conflict.\n"
            f"If this is stale, delete {_LOCK_FILE} and restart."
        )
        sys.exit(1)
    _lock_fh.write(str(os.getpid()))
    _lock_fh.flush()
from agent import Agent, Memory, local_llm
from agent.scheduler import GoalScheduler
from agent.notifier import SmartNotifier
from agent.webhooks import start_webhook_server
from bot.telegram import build_app

# ── Logging ────────────────────────────────────────────────────────────────
logger.remove()
logger.add(sys.stderr, level="INFO", colorize=True)
logger.add(
    str(config.DATA_DIR / "logs" / "dennis.log"),
    rotation="10 MB",
    retention="30 days",
    level="DEBUG",
)


async def main():
    _acquire_instance_lock()
    logger.info(f"Starting {config.AGENT_NAME}...")
    if config.LIGHTWEIGHT_MODE:
        logger.info("Running in LIGHTWEIGHT_MODE (Raspberry Pi / low-RAM device)")

    memory = Memory()
    logger.info("Memory initialized")

    if config.OLLAMA_ENABLED:
        ollama_ok = await local_llm.is_available()
        if ollama_ok:
            logger.info(f"Local LLM ready: {config.LOCAL_MODEL} @ {config.LOCAL_MODEL_URL}")
        else:
            logger.warning(
                f"OLLAMA_ENABLED=true but model '{config.LOCAL_MODEL}' not found at "
                f"{config.LOCAL_MODEL_URL}. Falling back to remote API for all tasks. "
                f"Run: ollama pull {config.LOCAL_MODEL}"
            )

    bot = Bot(token=config.TELEGRAM_BOT_TOKEN)

    async def _raw_notify(message: str):
        for user_id in config.TELEGRAM_ALLOWED_USERS:
            try:
                from telegram import constants
                await bot.send_message(
                    chat_id=user_id,
                    text=message,
                    parse_mode=constants.ParseMode.MARKDOWN,
                )
            except Exception:
                try:
                    await bot.send_message(chat_id=user_id, text=message)
                except Exception as e:
                    logger.warning(f"Failed to notify user {user_id}: {e}")

    # SmartNotifier enforces quiet hours and rate limiting
    notifier = SmartNotifier(memory=memory, raw_notify=_raw_notify)

    agent = Agent(memory=memory, send_message_fn=notifier.send)
    scheduler = GoalScheduler(agent=agent, notify_fn=notifier.send, notifier=notifier)
    scheduler.start()

    # Optional webhook server (background thread)
    start_webhook_server(memory=memory, notifier=notifier)

    app = build_app(agent, scheduler=scheduler)
    logger.info("Dennis is running. Send a message on Telegram to get started.")

    async with app:
        await app.start()
        await app.updater.start_polling(
            drop_pending_updates=True,
            allowed_updates=["message", "callback_query"],
        )
        await asyncio.Event().wait()  # run forever until KeyboardInterrupt
        await app.updater.stop()
        await app.stop()


if __name__ == "__main__":
    asyncio.run(main())
