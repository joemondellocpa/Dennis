"""
Telegram bot interface for Dennis.

Features:
- Allowlist-only access (your Telegram user IDs)
- Per-user conversation history (in-memory, last 20 turns)
- Per-user asyncio locks (prevents concurrent message handling)
- Approval flow for sensitive tool calls via inline keyboard
- /goals, /memory, /status, /pause, /resume, /kill_goal, /config, /clear commands
"""
import asyncio
import os
import sys
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

_histories: dict[int, list[dict]] = defaultdict(list)
_pending_approvals: dict[str, asyncio.Future] = {}
_user_locks: dict[int, asyncio.Lock] = {}


def _get_user_lock(user_id: int) -> asyncio.Lock:
    """Return (creating if needed) a per-user lock to serialize message handling."""
    if user_id not in _user_locks:
        _user_locks[user_id] = asyncio.Lock()
    return _user_locks[user_id]


def _is_allowed(user_id: int) -> bool:
    if not config.TELEGRAM_ALLOWED_USERS:
        return True  # No allowlist → allow all (not recommended)
    return user_id in config.TELEGRAM_ALLOWED_USERS


def _trim_history(user_id: int):
    h = _histories[user_id]
    if len(h) > config.MAX_HISTORY_TURNS * 2:
        _histories[user_id] = h[-(config.MAX_HISTORY_TURNS * 2):]


async def _send_long(update: Update, text: str):
    """Split long messages into Telegram-safe chunks, falling back to plain text on parse error."""
    chunk_size = 4000
    for i in range(0, len(text), chunk_size):
        chunk = text[i:i + chunk_size]
        try:
            await update.effective_message.reply_text(
                chunk, parse_mode=constants.ParseMode.MARKDOWN
            )
        except Exception:
            # Markdown parse error (likely split mid-format) – send as plain text
            try:
                await update.effective_message.reply_text(chunk)
            except Exception as e:
                logger.error(f"Failed to send message chunk: {e}")


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not _is_allowed(user_id):
        await update.message.reply_text("Sorry, you're not authorized to use Dennis.")
        return

    user_text = update.message.text or ""
    if not user_text.strip():
        return

    # Check if this is a text reply to a pending approval (fallback path)
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
    lock = _get_user_lock(user_id)

    # Prevent two simultaneous chat() calls for the same user
    if lock.locked():
        await update.message.reply_text("⏳ Still processing your previous message…")
        return

    async with lock:
        await context.bot.send_chat_action(
            chat_id=update.effective_chat.id, action=constants.ChatAction.TYPING
        )

        history = _histories[user_id]

        async def approval_callback(prompt: str) -> bool:
            loop = asyncio.get_running_loop()
            fut: asyncio.Future = loop.create_future()
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
                return await asyncio.wait_for(fut, timeout=120)
            except asyncio.TimeoutError:
                _pending_approvals.pop(approval_id, None)
                context.user_data.pop("pending_approval_id", None)
                await update.effective_message.reply_text("⏱ Approval timed out – action cancelled.")
                return False

        try:
            response = await agent.chat(user_text, history, approval_callback=approval_callback)
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
        # Clear the pending key so a subsequent text message isn't misinterpreted
        # (we can't easily access user_data here without the user_id, so we rely on
        # the Future being resolved – the approval_callback will see it's done)

    suffix = "\n\n✅ **Approved**" if action == "approve" else "\n\n❌ **Cancelled**"
    try:
        await query.edit_message_text(
            (query.message.text or "") + suffix,
            parse_mode=constants.ParseMode.MARKDOWN,
        )
    except Exception:
        pass  # Message may have been deleted or is too old


# ── Commands ───────────────────────────────────────────────────────────────

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_allowed(update.effective_user.id):
        return
    await update.message.reply_text(
        f"👋 Hi! I'm **{config.AGENT_NAME}**, your persistent AI assistant.\n\n"
        "Running 24/7 on your Mac mini, working on your goals in the background.\n\n"
        "**Commands:**\n"
        "/goals – view active goals\n"
        "/memory [query] – search your memory\n"
        "/status – system status\n"
        "/pause – pause background goal execution\n"
        "/resume – resume background goal execution\n"
        "/kill_goal [goal_id] – clear pending tasks for a goal\n"
        "/config – view/set behavioral preferences\n"
        "/budget – API call usage and daily budget\n"
        "/clear – clear conversation history\n\n"
        "Just send me a message to get started.",
        parse_mode=constants.ParseMode.MARKDOWN,
    )


async def cmd_goals(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_allowed(update.effective_user.id):
        return
    import json
    agent: Agent = context.bot_data["agent"]
    goals = agent.memory.get_active_goals()
    if not goals:
        await update.message.reply_text("No active goals. Tell me what you want me to work on!")
        return

    lines = ["**Active Goals:**\n"]
    for g in goals:
        notes = json.loads(g.get("progress_notes", "[]"))
        last_note = notes[-1]["note"] if notes else "No updates yet"
        pending = agent.memory.get_goal_tasks(g["id"], status="pending")
        lines.append(
            f"🎯 **{g['title']}** (priority {g['priority']}, id: `{g['id'][:8]}`)\n"
            f"{g['description'][:100]}...\n"
            f"_Last: {last_note[:80]}_\n"
            f"_Pending tasks: {len(pending)}_\n"
        )
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
    scheduler = context.bot_data.get("scheduler")
    goals = agent.memory.get_active_goals()
    paused_str = " ⏸ PAUSED" if (scheduler and scheduler.is_paused) else ""
    msg = (
        f"**{config.AGENT_NAME} Status**\n\n"
        f"⏰ Time: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}\n"
        f"🎯 Active goals: {len(goals)}\n"
        f"🧠 Model: {config.DEEPSEEK_MODEL}\n"
        f"🔄 Background loop: every {config.AUTONOMOUS_LOOP_INTERVAL}s{paused_str}\n"
        f"🖥️ Host: {platform.node()}\n"
    )
    await update.message.reply_text(msg, parse_mode=constants.ParseMode.MARKDOWN)


async def cmd_pause(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_allowed(update.effective_user.id):
        return
    scheduler = context.bot_data.get("scheduler")
    if scheduler:
        scheduler.pause()
        await update.message.reply_text("⏸ Background goal execution paused. Use /resume to restart.")
    else:
        await update.message.reply_text("Scheduler not available.")


async def cmd_resume(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_allowed(update.effective_user.id):
        return
    scheduler = context.bot_data.get("scheduler")
    if scheduler:
        scheduler.resume()
        await update.message.reply_text("▶️ Background goal execution resumed.")
    else:
        await update.message.reply_text("Scheduler not available.")


async def cmd_kill_goal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Clear all pending tasks for a goal (stops a runaway goal without deleting it)."""
    if not _is_allowed(update.effective_user.id):
        return
    agent: Agent = context.bot_data["agent"]

    if not context.args:
        # List goals with their short IDs so the user can pick one
        goals = agent.memory.get_active_goals()
        if not goals:
            await update.message.reply_text("No active goals.")
            return
        lines = ["**Pick a goal ID to kill its pending tasks:**\n"]
        for g in goals:
            pending = agent.memory.get_goal_tasks(g["id"], status="pending")
            lines.append(f"`{g['id'][:8]}` – {g['title']} ({len(pending)} pending tasks)")
        await _send_long(update, "\n".join(lines))
        return

    goal_prefix = context.args[0].lower()
    goals = agent.memory.get_active_goals()
    matched = [g for g in goals if g["id"].lower().startswith(goal_prefix)]

    if not matched:
        await update.message.reply_text(f"No active goal found with ID starting with `{goal_prefix}`.")
        return
    if len(matched) > 1:
        await update.message.reply_text("Ambiguous ID – please use more characters.")
        return

    goal = matched[0]
    agent.memory.delete_goal_tasks(goal["id"], status="pending")
    await update.message.reply_text(
        f"✅ Cleared all pending tasks for goal: **{goal['title']}**\n"
        "The next scheduler tick will re-plan fresh tasks.",
        parse_mode=constants.ParseMode.MARKDOWN,
    )


async def cmd_config(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """View or delete behavioral config entries."""
    if not _is_allowed(update.effective_user.id):
        return
    agent: Agent = context.bot_data["agent"]
    behavior = agent.memory.get_behavior_config()

    if not behavior:
        await update.message.reply_text(
            "No behavioral preferences set yet.\n\n"
            "Tell me how you want me to behave (e.g. 'Focus on LinkedIn outreach' or "
            "'Only notify me for high-priority findings') and I'll remember it."
        )
        return

    lines = ["**Behavioral Preferences:**\n"]
    for k, v in behavior.items():
        lines.append(f"• **{k}**: {v}")
    lines.append("\n_Tell me to change or remove any of these._")
    await _send_long(update, "\n".join(lines))


async def cmd_clear(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_allowed(update.effective_user.id):
        return
    _histories[update.effective_user.id] = []
    await update.message.reply_text("✅ Conversation history cleared.")


async def cmd_budget(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show API call usage for today and the past week."""
    if not _is_allowed(update.effective_user.id):
        return
    agent: Agent = context.bot_data["agent"]
    today_count = agent.memory.get_api_calls_today()
    weekly = agent.memory.get_api_call_stats(days=7)
    budget = config.DAILY_API_CALL_BUDGET

    budget_str = f"{today_count}/{budget}" if budget > 0 else f"{today_count} (no limit)"
    pct = int(today_count / budget * 100) if budget > 0 else 0
    bar_filled = pct // 10
    bar = "█" * bar_filled + "░" * (10 - bar_filled)

    lines = [
        f"**API Call Budget**\n",
        f"Today: `{budget_str}` [{bar}] {pct}%\n",
        "**Last 7 days:**",
    ]
    for row in weekly:
        lines.append(f"  {row['date']}: {row['calls']} calls")

    if budget > 0 and today_count >= budget:
        lines.append("\n⛔ Budget exhausted – autonomous tasks are paused until midnight UTC.")

    await _send_long(update, "\n".join(lines))


async def cmd_restart(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Restart the Dennis process in-place."""
    if not _is_allowed(update.effective_user.id):
        return
    await update.message.reply_text("🔄 Restarting Dennis…")
    logger.info("Restart requested via Telegram")
    # Re-exec the current Python process (LaunchAgent will restart if this fails)
    os.execv(sys.executable, [sys.executable] + sys.argv)


# ── App builder ────────────────────────────────────────────────────────────

def build_app(agent: Agent, scheduler=None) -> Application:
    app = Application.builder().token(config.TELEGRAM_BOT_TOKEN).build()
    app.bot_data["agent"] = agent
    app.bot_data["scheduler"] = scheduler  # May be None until scheduler is started

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("goals", cmd_goals))
    app.add_handler(CommandHandler("memory", cmd_memory))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("pause", cmd_pause))
    app.add_handler(CommandHandler("resume", cmd_resume))
    app.add_handler(CommandHandler("kill_goal", cmd_kill_goal))
    app.add_handler(CommandHandler("config", cmd_config))
    app.add_handler(CommandHandler("budget", cmd_budget))
    app.add_handler(CommandHandler("clear", cmd_clear))
    app.add_handler(CommandHandler("restart", cmd_restart))
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    return app
