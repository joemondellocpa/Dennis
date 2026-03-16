"""
Telegram bot interface for Dennis.

Features:
- Allowlist-only access (your Telegram user IDs)
- Per-user conversation history (in-memory, last 20 turns)
- Approval flow for sensitive tool calls
- /goals, /memory, /status commands
- Typing indicator while processing
"""
import asyncio
from collections import defaultdict
from typing import Optional

from telegram import Update, constants
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
    CallbackQueryHandler,
)
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from loguru import logger

import config
from agent import Agent, Memory

# Per-user conversation history (last N turns)
MAX_HISTORY_TURNS = 20
_histories: dict[int, list[dict]] = defaultdict(list)

# Pending approval requests: callback_id -> asyncio.Future
_pending_approvals: dict[str, asyncio.Future] = {}


def _is_allowed(user_id: int) -> bool:
    if not config.TELEGRAM_ALLOWED_USERS:
        return True  # No allowlist configured → allow all (not recommended for production)
    return user_id in config.TELEGRAM_ALLOWED_USERS


def _trim_history(user_id: int):
    h = _histories[user_id]
    # Keep last MAX_HISTORY_TURNS pairs (user + assistant)
    if len(h) > MAX_HISTORY_TURNS * 2:
        _histories[user_id] = h[-(MAX_HISTORY_TURNS * 2):]


async def _send_long(update: Update, text: str):
    """Split long messages into chunks (Telegram 4096 char limit)."""
    chunk_size = 4000
    for i in range(0, len(text), chunk_size):
        await update.effective_message.reply_text(
            text[i:i + chunk_size],
            parse_mode=constants.ParseMode.MARKDOWN,
        )


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not _is_allowed(user_id):
        await update.message.reply_text("Sorry, you're not authorized to use Dennis.")
        return

    user_text = update.message.text or ""
    if not user_text.strip():
        return

    # Check if this is a response to a pending approval
    pending_key = context.user_data.get("pending_approval_id")
    if pending_key and pending_key in _pending_approvals:
        fut = _pending_approvals.pop(pending_key)
        context.user_data.pop("pending_approval_id", None)
        approved = user_text.lower().strip() in ("yes", "y", "ok", "approve", "confirm", "go ahead")
        if not fut.done():
            fut.set_result(approved)
        await update.message.reply_text("✅ Approved" if approved else "❌ Cancelled")
        return

    agent: Agent = context.bot_data["agent"]

    # Show typing indicator
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=constants.ChatAction.TYPING)

    history = _histories[user_id]

    # Approval callback: sends a Telegram message and waits for user reply
    async def approval_callback(prompt: str) -> bool:
        fut: asyncio.Future = asyncio.get_event_loop().create_future()
        approval_id = f"approval_{user_id}_{id(fut)}"
        _pending_approvals[approval_id] = fut
        context.user_data["pending_approval_id"] = approval_id

        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("✅ Yes, do it", callback_data=f"approve:{approval_id}"),
                InlineKeyboardButton("❌ Cancel", callback_data=f"reject:{approval_id}"),
            ]
        ])
        await update.effective_message.reply_text(
            prompt, parse_mode=constants.ParseMode.MARKDOWN, reply_markup=keyboard
        )
        try:
            result = await asyncio.wait_for(fut, timeout=120)
            return result
        except asyncio.TimeoutError:
            _pending_approvals.pop(approval_id, None)
            return False

    try:
        response = await agent.chat(user_text, history, approval_callback=approval_callback)

        # Update history
        history.append({"role": "user", "content": user_text})
        history.append({"role": "assistant", "content": response})
        _trim_history(user_id)

        await _send_long(update, response)

    except Exception as e:
        logger.exception("Error in handle_message")
        await update.message.reply_text(f"⚠️ Error: {e}")


async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle inline keyboard button presses (yes/no approvals)."""
    query = update.callback_query
    await query.answer()
    data = query.data or ""

    if ":" not in data:
        return

    action, approval_id = data.split(":", 1)
    fut = _pending_approvals.pop(approval_id, None)
    if fut and not fut.done():
        fut.set_result(action == "approve")
    await query.edit_message_text(
        query.message.text + ("\n\n✅ **Approved**" if action == "approve" else "\n\n❌ **Cancelled**"),
        parse_mode=constants.ParseMode.MARKDOWN,
    )


# ── Commands ───────────────────────────────────────────────────────────────

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_allowed(update.effective_user.id):
        return
    await update.message.reply_text(
        f"👋 Hi! I'm **{config.AGENT_NAME}**, your persistent AI assistant.\n\n"
        "I'm running 24/7 on your Mac mini, working on your goals in the background.\n\n"
        "**Commands:**\n"
        "/goals – view active goals\n"
        "/memory [query] – search your memory\n"
        "/status – system status\n"
        "/clear – clear conversation history\n\n"
        "Just send me a message to get started.",
        parse_mode=constants.ParseMode.MARKDOWN,
    )


async def cmd_goals(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_allowed(update.effective_user.id):
        return
    agent: Agent = context.bot_data["agent"]
    goals = agent.memory.get_active_goals()
    if not goals:
        await update.message.reply_text("No active goals. Tell me what you want me to work on!")
        return

    lines = ["**Active Goals:**\n"]
    for g in goals:
        import json
        notes = json.loads(g.get("progress_notes", "[]"))
        last_note = notes[-1]["note"] if notes else "No updates yet"
        lines.append(f"🎯 **{g['title']}** (priority {g['priority']})\n{g['description'][:100]}...\n_Last: {last_note[:80]}_\n")
    await _send_long(update, "\n".join(lines))


async def cmd_memory(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_allowed(update.effective_user.id):
        return
    agent: Agent = context.bot_data["agent"]
    query = " ".join(context.args) if context.args else "recent important information"
    results = agent.memory.recall_relevant(query, n=5)
    if not results:
        await update.message.reply_text("Nothing found in memory for that query.")
        return
    lines = [f"**Memory search: '{query}'**\n"]
    for r in results:
        ts = r["metadata"].get("timestamp", "?")[:10]
        role = r["metadata"].get("role", "?")
        lines.append(f"[{ts}] *{role}*: {r['content'][:200]}\n")
    await _send_long(update, "\n".join(lines))


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_allowed(update.effective_user.id):
        return
    import platform
    from datetime import datetime, timezone
    agent: Agent = context.bot_data["agent"]
    goals = agent.memory.get_active_goals()
    msg = (
        f"**{config.AGENT_NAME} Status**\n\n"
        f"⏰ Time: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}\n"
        f"🎯 Active goals: {len(goals)}\n"
        f"🧠 Model: {config.DEEPSEEK_MODEL}\n"
        f"🔄 Background loop: every {config.AUTONOMOUS_LOOP_INTERVAL}s\n"
        f"🖥️ Host: {platform.node()}\n"
    )
    await update.message.reply_text(msg, parse_mode=constants.ParseMode.MARKDOWN)


async def cmd_clear(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_allowed(update.effective_user.id):
        return
    _histories[update.effective_user.id] = []
    await update.message.reply_text("✅ Conversation history cleared.")


# ── App builder ────────────────────────────────────────────────────────────

def build_app(agent: Agent) -> Application:
    app = Application.builder().token(config.TELEGRAM_BOT_TOKEN).build()
    app.bot_data["agent"] = agent

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("goals", cmd_goals))
    app.add_handler(CommandHandler("memory", cmd_memory))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("clear", cmd_clear))
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    return app
