"""
Dennis Agent – entry point.

Starts:
1. The Telegram bot (polling)
2. The autonomous background goal scheduler
"""
import asyncio
import sys
from pathlib import Path

from loguru import logger
from telegram import Bot

import config
from agent import Agent, Memory
from agent.scheduler import GoalScheduler
from bot.telegram import build_app

# ── Logging setup ──────────────────────────────────────────────────────────
logger.remove()
logger.add(sys.stderr, level="INFO", colorize=True)
logger.add(
    str(config.DATA_DIR / "logs" / "dennis.log"),
    rotation="10 MB",
    retention="30 days",
    level="DEBUG",
)


async def main():
    logger.info(f"Starting {config.AGENT_NAME}...")

    # Initialize memory
    memory = Memory()
    logger.info("Memory initialized")

    # Bot for proactive outbound notifications
    bot = Bot(token=config.TELEGRAM_BOT_TOKEN)

    async def notify_all_users(message: str):
        for user_id in config.TELEGRAM_ALLOWED_USERS:
            try:
                from telegram import constants
                await bot.send_message(
                    chat_id=user_id,
                    text=message,
                    parse_mode=constants.ParseMode.MARKDOWN,
                )
            except Exception as e:
                logger.warning(f"Failed to notify user {user_id}: {e}")

    # Initialize agent
    agent = Agent(memory=memory, send_message_fn=notify_all_users)

    # Background scheduler (pause/resume available via /pause and /resume)
    scheduler = GoalScheduler(agent=agent, notify_fn=notify_all_users)
    scheduler.start()

    # Build Telegram app – pass scheduler so /pause, /resume, /status work
    app = build_app(agent, scheduler=scheduler)

    logger.info("Dennis is running. Send a message on Telegram to get started.")

    # Run bot (blocking)
    await app.run_polling(
        drop_pending_updates=True,
        allowed_updates=["message", "callback_query"],
    )


if __name__ == "__main__":
    asyncio.run(main())
