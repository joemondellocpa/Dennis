"""
Telegram bot interface for Dennis.

Features:
- Allowlist-only access
- Per-user conversation history (last MAX_HISTORY_TURNS turns)
- Per-user asyncio locks (prevents concurrent message handling)
- Approval flow for sensitive tool calls via text reply (yes/no)
- Draft review queue: /drafts, /approve_draft <id>, /reject_draft <id>
- Voice message transcription (faster-whisper, on-device)
- File attachment handling (PDF, text, images)
- Commands: /start, /goals, /memory, /status, /pause, /resume,
            /kill_goal, /config, /budget, /drafts, /approve_draft, /reject_draft,
            /export, /clear, /restart, /shell
"""
import asyncio
import json
import os
import sys
import tempfile
from collections import defaultdict
from typing import Optional
from pathlib import Path

from telegram import Update, constants, Document, PhotoSize
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
)
from loguru import logger

import config
from agent import Agent, Memory

_histories: dict[int, list[dict]] = defaultdict(list)
_pending_approvals: dict[str, asyncio.Future] = {}
_user_locks: dict[int, asyncio.Lock] = {}


def _get_user_lock(user_id: int) -> asyncio.Lock:
    if user_id not in _user_locks:
        _user_locks[user_id] = asyncio.Lock()
    return _user_locks[user_id]


def _is_allowed(user_id: int) -> bool:
    if not config.TELEGRAM_ALLOWED_USERS:
        return True
    return user_id in config.TELEGRAM_ALLOWED_USERS


def _trim_history(user_id: int):
    h = _histories[user_id]
    if len(h) > config.MAX_HISTORY_TURNS * 2:
        _histories[user_id] = h[-(config.MAX_HISTORY_TURNS * 2):]


async def _send_long(update: Update, text: str):
    chunk_size = 4000
    for i in range(0, len(text), chunk_size):
        chunk = text[i:i + chunk_size]
        try:
            await update.effective_message.reply_text(
                chunk, parse_mode=constants.ParseMode.MARKDOWN
            )
        except Exception:
            try:
                await update.effective_message.reply_text(chunk)
            except Exception as e:
                logger.error(f"Failed to send message chunk: {e}")


# ── Core message handler ───────────────────────────────────────────────────

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not _is_allowed(user_id):
        await update.message.reply_text("Sorry, you're not authorized to use Dennis.")
        return

    user_text = update.message.text or ""
    if not user_text.strip():
        return

    # Check if user is editing a draft
    editing_draft_id = context.user_data.get("editing_draft_id")
    if editing_draft_id:
        context.user_data.pop("editing_draft_id")
        agent: Agent = context.bot_data["agent"]
        agent.memory.update_draft_content(editing_draft_id, user_text)
        draft = agent.memory.get_draft(editing_draft_id)
        if draft:
            short_id = editing_draft_id[:8]
            await update.message.reply_text(
                f"📝 **Draft updated:**\n\n{user_text[:800]}\n\n"
                f"Reply `/approve_draft {short_id}` to send or `/reject_draft {short_id}` to discard.",
                parse_mode=constants.ParseMode.MARKDOWN,
            )
        return

    # Check if this is a text reply to a pending approval (fallback for non-button users)
    pending_key = context.user_data.get("pending_approval_id")
    if pending_key and pending_key in _pending_approvals:
        fut = _pending_approvals.pop(pending_key)
        context.user_data.pop("pending_approval_id", None)
        token = user_text.lower().strip()
        if token in ("always", "always allow", "trust", "remember", "always yes"):
            decision = "always"
            label = "✅ Approved (always allowed)"
        elif token in ("yes", "y", "ok", "approve", "confirm", "go ahead"):
            decision = "yes"
            label = "✅ Approved"
        else:
            decision = "no"
            label = "❌ Cancelled"
        if not fut.done():
            fut.set_result(decision)
        await update.message.reply_text(label)
        return

    agent: Agent = context.bot_data["agent"]
    lock = _get_user_lock(user_id)

    if lock.locked():
        await update.message.reply_text("⏳ Still processing your previous message…")
        return

    async with lock:
        await context.bot.send_chat_action(
            chat_id=update.effective_chat.id, action=constants.ChatAction.TYPING
        )
        history = _histories[user_id]

        async def approval_callback(prompt: str) -> str:
            """Returns 'yes', 'always', or 'no'."""
            loop = asyncio.get_running_loop()
            fut: asyncio.Future = loop.create_future()
            approval_id = f"approval_{user_id}_{id(fut)}"
            _pending_approvals[approval_id] = fut
            context.user_data["pending_approval_id"] = approval_id
            # Strip internal metadata marker before showing to user
            import re as _re
            display_prompt = _re.sub(r"\s*\[trust_pattern:[^\]]+\]", "", prompt)
            await update.effective_message.reply_text(
                display_prompt,
                parse_mode=constants.ParseMode.MARKDOWN,
            )
            try:
                return await asyncio.wait_for(fut, timeout=120)
            except asyncio.TimeoutError:
                _pending_approvals.pop(approval_id, None)
                context.user_data.pop("pending_approval_id", None)
                await update.effective_message.reply_text("⏱ Approval timed out – action cancelled.")
                return "no"

        try:
            response = await agent.chat(user_text, history, approval_callback=approval_callback)
            history.append({"role": "user", "content": user_text})
            history.append({"role": "assistant", "content": response})
            _trim_history(user_id)
            await _send_long(update, response)

            # If the agent created a draft, notify
            pending_drafts = agent.memory.get_pending_drafts()
            if pending_drafts:
                newest = pending_drafts[0]
                if newest.get("created_at", "") > (history[-2].get("content", "") or ""):
                    pass  # Already mentioned in response; don't double-notify

        except Exception as e:
            logger.exception("Error in handle_message")
            await update.message.reply_text(f"⚠️ Error: {e}")


# ── Voice message handler ──────────────────────────────────────────────────

async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not _is_allowed(user_id):
        return

    await context.bot.send_chat_action(
        chat_id=update.effective_chat.id, action=constants.ChatAction.TYPING
    )
    await update.message.reply_text("🎙 Transcribing…")

    voice = update.message.voice
    try:
        # Download voice file (OGG format from Telegram)
        voice_file = await context.bot.get_file(voice.file_id)
        with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as tmp:
            await voice_file.download_to_drive(tmp.name)
            audio_path = tmp.name

        from tools.whisper_tool import transcribe
        result = await transcribe(audio_path)

        if not result["success"]:
            await update.message.reply_text(f"❌ Transcription failed: {result['error']}")
            return

        transcript = result["text"]
        if not transcript.strip():
            await update.message.reply_text("❌ Could not understand the audio.")
            return

        await update.message.reply_text(f"🎙 _Heard:_ {transcript}", parse_mode=constants.ParseMode.MARKDOWN)

        # Process the transcript as a regular message
        agent: Agent = context.bot_data["agent"]
        lock = _get_user_lock(user_id)
        async with lock:
            history = _histories[user_id]

            async def noop_approval(_prompt):
                return False  # No inline approvals for voice (user not present for async)

            response = await agent.chat(transcript, history, approval_callback=noop_approval)
            history.append({"role": "user", "content": f"[Voice] {transcript}"})
            history.append({"role": "assistant", "content": response})
            _trim_history(user_id)
            await _send_long(update, response)

    except Exception as e:
        logger.exception("Error handling voice message")
        await update.message.reply_text(f"⚠️ Voice processing error: {e}")


# ── File/document handler ──────────────────────────────────────────────────

async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not _is_allowed(user_id):
        return

    doc: Document = update.message.document
    caption = update.message.caption or "Summarize or extract key information from this file."

    await context.bot.send_chat_action(
        chat_id=update.effective_chat.id, action=constants.ChatAction.TYPING
    )

    try:
        file = await context.bot.get_file(doc.file_id)
        suffix = Path(doc.file_name or "upload").suffix.lower()

        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            await file.download_to_drive(tmp.name)
            file_path = tmp.name

        text = await _extract_file_text(file_path, suffix)
        os.unlink(file_path)

        if not text:
            await update.message.reply_text("❌ Could not extract text from this file type.")
            return

        user_msg = f"{caption}\n\n[Attached file: {doc.file_name}]\n\n{text[:3000]}"
        agent: Agent = context.bot_data["agent"]
        lock = _get_user_lock(user_id)
        async with lock:
            history = _histories[user_id]
            response = await agent.chat(user_msg, history)
            history.append({"role": "user", "content": user_msg})
            history.append({"role": "assistant", "content": response})
            _trim_history(user_id)
            await _send_long(update, response)

    except Exception as e:
        logger.exception("Error handling document")
        await update.message.reply_text(f"⚠️ File processing error: {e}")


async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not _is_allowed(user_id):
        return

    caption = update.message.caption or "What is in this image? Describe it and extract any useful information."
    await context.bot.send_chat_action(
        chat_id=update.effective_chat.id, action=constants.ChatAction.TYPING
    )

    try:
        # Get largest photo variant
        photo: PhotoSize = update.message.photo[-1]
        file = await context.bot.get_file(photo.file_id)

        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
            await file.download_to_drive(tmp.name)
            file_path = tmp.name

        import base64
        with open(file_path, "rb") as f:
            img_b64 = base64.b64encode(f.read()).decode()
        os.unlink(file_path)

        agent: Agent = context.bot_data["agent"]

        # Use vision-capable model if available; fall back to text description
        messages_with_image = [
            {"role": "system", "content": await agent._build_system_prompt()},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": caption},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{img_b64}"}},
                ],
            },
        ]

        if config.DAILY_API_CALL_BUDGET > 0:
            used = agent.memory.get_api_calls_today()
            if used >= config.DAILY_API_CALL_BUDGET:
                await update.message.reply_text("⚠️ Daily API budget reached.")
                return

        response = await agent.client.chat.completions.create(
            model=config.DEEPSEEK_MODEL,
            messages=messages_with_image,
            max_tokens=1024,
        )
        agent.memory.record_api_call(config.DEEPSEEK_MODEL, "vision")
        reply = response.choices[0].message.content or "Could not describe the image."
        await _send_long(update, reply)

    except Exception as e:
        logger.exception("Error handling photo")
        # Vision may not be supported on this model – fall back gracefully
        await update.message.reply_text(
            "⚠️ Image analysis failed (the current DeepSeek model may not support vision). "
            f"Error: {e}"
        )


async def _extract_file_text(file_path: str, suffix: str) -> str:
    """Extract text content from various file types."""
    if suffix == ".pdf":
        try:
            import pypdf
            reader = pypdf.PdfReader(file_path)
            return "\n".join(page.extract_text() or "" for page in reader.pages[:20])
        except ImportError:
            return "[pypdf not installed – install it to read PDFs]"
    elif suffix in (".txt", ".md", ".csv", ".log", ".py", ".js", ".json", ".yaml", ".yml"):
        with open(file_path, "r", errors="replace") as f:
            return f.read()
    elif suffix in (".docx",):
        try:
            import docx
            doc = docx.Document(file_path)
            return "\n".join(p.text for p in doc.paragraphs)
        except ImportError:
            return "[python-docx not installed – install it to read DOCX files]"
    return ""


# ── Draft approval commands ─────────────────────────────────────────────────

async def _execute_draft(draft: dict, agent: Agent) -> str:
    """Execute an approved draft and return a status string."""
    metadata = json.loads(draft.get("metadata", "{}"))
    try:
        from tools import dispatch_tool
        if draft["type"] == "email":
            result = await dispatch_tool("send_email", {
                "to": metadata.get("to", ""),
                "subject": metadata.get("subject", draft["title"]),
                "body": draft["content"],
            }, memory=agent.memory)
        elif draft["type"] == "linkedin_post":
            result = await dispatch_tool("linkedin_post", {
                "content": draft["content"],
            }, memory=agent.memory)
        else:
            result = {"success": False, "error": f"Unknown draft type: {draft['type']}"}
        return "✅ Sent!" if result.get("success") else f"❌ Failed: {result.get('error')}"
    except Exception as e:
        return f"❌ Error executing draft: {e}"


def _find_draft_by_prefix(agent: Agent, id_prefix: str):
    """Return the first pending draft whose ID starts with id_prefix, or None."""
    for draft in agent.memory.get_pending_drafts():
        if draft["id"].startswith(id_prefix):
            return draft
    return None


async def cmd_approve_draft(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Approve and send a pending draft: /approve_draft <id>"""
    if not _is_allowed(update.effective_user.id):
        return
    if not context.args:
        await update.message.reply_text("Usage: /approve_draft <draft-id>")
        return
    agent: Agent = context.bot_data["agent"]
    draft = _find_draft_by_prefix(agent, context.args[0])
    if not draft:
        await update.message.reply_text("Draft not found. Use /drafts to see pending drafts.")
        return
    agent.memory.resolve_draft(draft["id"], "approved")
    await update.message.reply_text(f"✅ Approved — sending _{draft['title']}_…",
                                    parse_mode=constants.ParseMode.MARKDOWN)
    status = await _execute_draft(draft, agent)
    await update.message.reply_text(status)


async def cmd_reject_draft(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Reject and discard a pending draft: /reject_draft <id>"""
    if not _is_allowed(update.effective_user.id):
        return
    if not context.args:
        await update.message.reply_text("Usage: /reject_draft <draft-id>")
        return
    agent: Agent = context.bot_data["agent"]
    draft = _find_draft_by_prefix(agent, context.args[0])
    if not draft:
        await update.message.reply_text("Draft not found. Use /drafts to see pending drafts.")
        return
    agent.memory.resolve_draft(draft["id"], "rejected")
    await update.message.reply_text(f"❌ Draft rejected: _{draft['title']}_",
                                    parse_mode=constants.ParseMode.MARKDOWN)


# ── Commands ───────────────────────────────────────────────────────────────

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_allowed(update.effective_user.id):
        return
    await update.message.reply_text(
        f"👋 Hi! I'm **{config.AGENT_NAME}**, your persistent AI assistant.\n\n"
        "Running 24/7 on your Mac mini, working on your goals in the background.\n\n"
        "**Commands:**\n"
        "/goals – view active goals\n"
        "/drafts – review pending email/post drafts\n"
        "/approve_draft <id> – approve and send a draft\n"
        "/reject_draft <id> – discard a draft\n"
        "/memory [query] – search your memory\n"
        "/status – system status\n"
        "/budget – API call usage\n"
        "/config – behavioral preferences\n"
        "/pause – pause background tasks\n"
        "/resume – resume background tasks\n"
        "/kill_goal [id] – clear pending tasks for a goal\n"
        "/export – export memory to markdown\n"
        "/clear – clear conversation history\n"
        "/reset_budget – reset today's API call counter\n"
        "/restart – restart the agent\n"
        "/shell <cmd> – run a shell command directly\n"
        "/trusted – list trusted shell command patterns\n"
        "/untrust <pattern> – remove a trusted pattern\n\n"
        "You can also send voice messages, PDFs, or images.",
        parse_mode=constants.ParseMode.MARKDOWN,
    )


async def cmd_drafts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show all pending drafts with text commands to approve or reject."""
    if not _is_allowed(update.effective_user.id):
        return
    agent: Agent = context.bot_data["agent"]
    drafts = agent.memory.get_pending_drafts()

    if not drafts:
        await update.message.reply_text("📭 No pending drafts.")
        return

    for draft in drafts[:5]:  # Show max 5 at a time
        preview = draft["content"][:400]
        metadata = json.loads(draft.get("metadata", "{}"))
        meta_str = ""
        if draft["type"] == "email":
            meta_str = f"\n**To:** {metadata.get('to', '?')}\n**Subject:** {metadata.get('subject', '?')}"
        elif draft["type"] == "linkedin_post":
            meta_str = "\n_LinkedIn post_"

        short_id = draft["id"][:8]
        text = (
            f"📝 **{draft['title']}**{meta_str}\n\n"
            f"{preview}{'…' if len(draft['content']) > 400 else ''}\n\n"
            f"`/approve_draft {short_id}` · `/reject_draft {short_id}`"
        )
        try:
            await update.message.reply_text(text, parse_mode=constants.ParseMode.MARKDOWN)
        except Exception:
            await update.message.reply_text(text)

    if len(drafts) > 5:
        await update.message.reply_text(f"_...and {len(drafts) - 5} more drafts._",
                                         parse_mode=constants.ParseMode.MARKDOWN)


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
        notes = json.loads(g.get("progress_notes", "[]"))
        last_note = notes[-1]["note"] if notes else "No updates yet"
        pending = agent.memory.get_goal_tasks(g["id"], status="pending")
        schedule_str = f" 🔁 {g.get('schedule', '')}" if g.get("schedule") else ""
        lines.append(
            f"🎯 **{g['title']}** (priority {g['priority']}, `{g['id'][:8]}`{schedule_str})\n"
            f"{g['description'][:100]}...\n"
            f"_Last: {last_note[:80]}_  |  Pending tasks: {len(pending)}\n"
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
    conv_count = agent.memory.get_conversation_count()
    msg = (
        f"**{config.AGENT_NAME} Status**\n\n"
        f"⏰ {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}\n"
        f"🎯 Active goals: {len(goals)}\n"
        f"🧠 Model: {config.DEEPSEEK_MODEL}\n"
        f"🔄 Background loop: every {config.AUTONOMOUS_LOOP_INTERVAL}s{paused_str}\n"
        f"💬 Conversation turns in memory: {conv_count}\n"
        f"🖥️ Host: {platform.node()}\n"
        f"🔇 Quiet hours: {config.QUIET_HOURS_START:02d}:00 – {config.QUIET_HOURS_END:02d}:00\n"
    )
    if config.LIGHTWEIGHT_MODE:
        msg += "🥧 Mode: Lightweight (Raspberry Pi)\n"
    await update.message.reply_text(msg, parse_mode=constants.ParseMode.MARKDOWN)


async def cmd_export(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Export memory contents to a markdown file and send it."""
    if not _is_allowed(update.effective_user.id):
        return
    agent: Agent = context.bot_data["agent"]
    await update.message.reply_text("📦 Generating memory export…")

    try:
        lines = [f"# {config.AGENT_NAME} Memory Export\n"]
        from datetime import datetime, timezone
        lines.append(f"_Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}_\n")

        # Facts
        facts = agent.memory.get_all_facts()
        if facts:
            lines.append("\n## Stored Facts\n")
            current_cat = None
            for f in facts:
                if f["category"] != current_cat:
                    current_cat = f["category"]
                    lines.append(f"\n### {current_cat}\n")
                lines.append(f"- **{f['key']}**: {f['value']}")

        # Active goals
        goals = agent.memory.get_active_goals()
        if goals:
            lines.append("\n\n## Active Goals\n")
            for g in goals:
                lines.append(f"\n### {g['title']} (priority {g['priority']})")
                lines.append(f"{g['description']}")
                notes = json.loads(g.get("progress_notes", "[]"))
                if notes:
                    lines.append(f"\n**Progress notes:**")
                    for n in notes[-5:]:
                        lines.append(f"- {n['timestamp'][:10]}: {n['note']}")

        # Knowledge base
        knowledge = agent.memory.get_all_knowledge(limit=50)
        if knowledge:
            lines.append("\n\n## Knowledge Base (recent 50 items)\n")
            for k in knowledge:
                lines.append(f"\n### {k['source']} ({k['created_at'][:10]})")
                lines.append(k["summary"])

        md_content = "\n".join(lines)
        with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False, prefix="dennis_export_") as f:
            f.write(md_content)
            export_path = f.name

        await update.message.reply_document(
            document=open(export_path, "rb"),
            filename=f"dennis_memory_{datetime.now(timezone.utc).strftime('%Y%m%d')}.md",
            caption=f"Memory export: {len(facts)} facts, {len(goals)} active goals, {len(knowledge)} knowledge items",
        )
        os.unlink(export_path)

    except Exception as e:
        logger.exception("Error in /export")
        await update.message.reply_text(f"❌ Export failed: {e}")


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
    if not _is_allowed(update.effective_user.id):
        return
    agent: Agent = context.bot_data["agent"]
    if not context.args:
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
        f"✅ Cleared pending tasks for **{goal['title']}**. Next tick will re-plan.",
        parse_mode=constants.ParseMode.MARKDOWN,
    )


async def cmd_config(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_allowed(update.effective_user.id):
        return
    agent: Agent = context.bot_data["agent"]
    behavior = agent.memory.get_behavior_config()
    if not behavior:
        await update.message.reply_text(
            "No behavioral preferences set yet.\n\n"
            "Tell me how you'd like me to behave and I'll remember it."
        )
        return
    lines = ["**Behavioral Preferences:**\n"]
    for k, v in behavior.items():
        lines.append(f"• **{k}**: {v}")
    lines.append("\n_Tell me to change or remove any of these._")
    await _send_long(update, "\n".join(lines))


async def cmd_budget(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_allowed(update.effective_user.id):
        return
    agent: Agent = context.bot_data["agent"]
    today_count = agent.memory.get_api_calls_today()
    weekly = agent.memory.get_api_call_stats(days=7)
    budget = config.DAILY_API_CALL_BUDGET
    budget_str = f"{today_count}/{budget}" if budget > 0 else f"{today_count} (no limit)"
    pct = int(today_count / budget * 100) if budget > 0 else 0
    bar = "█" * (pct // 10) + "░" * (10 - pct // 10)
    lines = [f"**API Call Budget**\n", f"Today: `{budget_str}` [{bar}] {pct}%\n", "**Last 7 days:**"]
    for row in weekly:
        lines.append(f"  {row['date']}: {row['calls']} calls")
    if budget > 0 and today_count >= budget:
        lines.append("\n⛔ Budget exhausted – autonomous tasks paused until midnight UTC.")
    await _send_long(update, "\n".join(lines))


async def cmd_clear(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_allowed(update.effective_user.id):
        return
    _histories[update.effective_user.id] = []
    await update.message.reply_text("✅ Conversation history cleared.")


async def cmd_reset_budget(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Reset today's API call counter so the budget limit is lifted immediately."""
    if not _is_allowed(update.effective_user.id):
        return
    agent: Agent = context.bot_data["agent"]
    before = agent.memory.get_api_calls_today()
    agent.memory.reset_api_calls_today()
    budget = config.DAILY_API_CALL_BUDGET

    # Pause the scheduler so background tasks don't immediately re-consume the budget
    scheduler = context.bot_data.get("scheduler")
    paused_scheduler = False
    if scheduler and not scheduler.is_paused:
        scheduler.pause()
        paused_scheduler = True

    pause_note = (
        "\n⏸ Background tasks paused so they don't re-hit the limit. Use /resume when ready."
        if paused_scheduler
        else ""
    )
    await update.message.reply_text(
        f"✅ Budget reset. Cleared {before} calls recorded today.\n"
        f"Current limit: {budget if budget > 0 else 'unlimited'} calls/day."
        f"{pause_note}"
    )


async def cmd_restart(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_allowed(update.effective_user.id):
        return
    await update.message.reply_text("🔄 Restarting Dennis…")
    logger.info("Restart requested via Telegram")
    os.execv(sys.executable, [sys.executable] + sys.argv)


async def cmd_shell(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Execute a shell command directly and return the output. No API call."""
    if not _is_allowed(update.effective_user.id):
        return

    if not context.args:
        await update.message.reply_text(
            "Usage: `/shell <command>`\nExample: `/shell ls -la`",
            parse_mode=constants.ParseMode.MARKDOWN,
        )
        return

    command = " ".join(context.args)
    await context.bot.send_chat_action(
        chat_id=update.effective_chat.id, action=constants.ChatAction.TYPING
    )

    try:
        proc = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            cwd=Path(__file__).parent.parent,
        )
        try:
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=60)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.communicate()
            await update.message.reply_text(
                f"⏱ Command timed out after 60s:\n`{command}`",
                parse_mode=constants.ParseMode.MARKDOWN,
            )
            return

        output = stdout.decode(errors="replace")
        exit_code = proc.returncode
        max_output = 3800
        truncated = len(output) > max_output
        output = output[-max_output:] if truncated else output

        header = f"$ {command}\n"
        footer = f"\n[exit {exit_code}]" + (" (truncated)" if truncated else "")
        reply = f"```\n{header}{output}{footer}\n```"

        try:
            await update.message.reply_text(reply, parse_mode=constants.ParseMode.MARKDOWN)
        except Exception:
            # Fallback without markdown if output breaks formatting
            await update.message.reply_text(f"$ {command}\n\n{output}\n[exit {exit_code}]")

    except Exception as e:
        logger.exception("Error in /shell")
        await update.message.reply_text(f"❌ Failed to run command: {e}")


# ── Trusted shell commands ──────────────────────────────────────────────────

async def cmd_trusted(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """List trusted shell command patterns: /trusted"""
    if not _is_allowed(update.effective_user.id):
        return
    agent: Agent = context.bot_data["agent"]
    patterns = agent.memory.get_trusted_shell_patterns()
    if not patterns:
        await update.message.reply_text(
            "No trusted shell patterns yet.\n\n"
            "When Dennis asks for shell approval, reply **always** to add that command to the list.\n"
            "Or say: _trust brew install_ / _always allow git commit_ in chat."
        )
        return
    lines = ["**Trusted Shell Patterns** (run without approval):\n"]
    for pattern, note in sorted(patterns.items()):
        lines.append(f"• `{pattern}` — _{note}_")
    lines.append("\nUse `/untrust <pattern>` to remove one.")
    await _send_long(update, "\n".join(lines))


async def cmd_untrust(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Remove a trusted shell pattern: /untrust <pattern>"""
    if not _is_allowed(update.effective_user.id):
        return
    if not context.args:
        await update.message.reply_text(
            "Usage: `/untrust <pattern>`\nExample: `/untrust brew install`",
            parse_mode=constants.ParseMode.MARKDOWN,
        )
        return
    agent: Agent = context.bot_data["agent"]
    pattern = " ".join(context.args)
    removed = agent.memory.remove_trusted_shell(pattern)
    if removed:
        await update.message.reply_text(
            f"✅ Removed `{pattern}` from trusted list.",
            parse_mode=constants.ParseMode.MARKDOWN,
        )
    else:
        patterns = agent.memory.get_trusted_shell_patterns()
        if patterns:
            opts = ", ".join(f"`{p}`" for p in sorted(patterns))
            await update.message.reply_text(
                f"Pattern `{pattern}` not found.\nTrusted patterns: {opts}",
                parse_mode=constants.ParseMode.MARKDOWN,
            )
        else:
            await update.message.reply_text("No trusted patterns to remove.")


# ── Startup message ─────────────────────────────────────────────────────────

async def _send_startup_message(app: Application) -> None:
    """Send a status summary to all allowed users when Dennis comes online."""
    if not config.TELEGRAM_ALLOWED_USERS:
        return
    import platform
    from datetime import datetime, timezone
    agent: Agent = app.bot_data["agent"]
    scheduler = app.bot_data.get("scheduler")
    goals = agent.memory.get_active_goals()
    paused_str = " ⏸ PAUSED" if (scheduler and scheduler.is_paused) else ""

    lines = [
        f"✅ *{config.AGENT_NAME} is online*\n",
        f"⏰ {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
        f"🖥️ Host: {platform.node()}",
        f"🔄 Background loop: every {config.AUTONOMOUS_LOOP_INTERVAL}s{paused_str}",
        f"🎯 Active goals: {len(goals)}",
    ]

    if goals:
        lines.append("")
        for g in goals:
            notes = json.loads(g.get("progress_notes", "[]"))
            last_note = notes[-1]["note"] if notes else "No updates yet"
            pending = agent.memory.get_goal_tasks(g["id"], status="pending")
            lines.append(
                f"• *{g['title']}* (priority {g['priority']})\n"
                f"  _{last_note[:100]}_\n"
                f"  Pending tasks: {len(pending)}"
            )

    msg = "\n".join(lines)
    for uid in config.TELEGRAM_ALLOWED_USERS:
        try:
            await app.bot.send_message(uid, msg, parse_mode=constants.ParseMode.MARKDOWN)
        except Exception:
            logger.warning(f"Could not send startup message to user {uid}")


# ── App builder ────────────────────────────────────────────────────────────

def build_app(agent: Agent, scheduler=None) -> Application:
    app = Application.builder().token(config.TELEGRAM_BOT_TOKEN).concurrent_updates(True).post_init(_send_startup_message).build()
    app.bot_data["agent"] = agent
    app.bot_data["scheduler"] = scheduler

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("goals", cmd_goals))
    app.add_handler(CommandHandler("drafts", cmd_drafts))
    app.add_handler(CommandHandler("memory", cmd_memory))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("budget", cmd_budget))
    app.add_handler(CommandHandler("config", cmd_config))
    app.add_handler(CommandHandler("pause", cmd_pause))
    app.add_handler(CommandHandler("resume", cmd_resume))
    app.add_handler(CommandHandler("kill_goal", cmd_kill_goal))
    app.add_handler(CommandHandler("export", cmd_export))
    app.add_handler(CommandHandler("clear", cmd_clear))
    app.add_handler(CommandHandler("reset_budget", cmd_reset_budget))
    app.add_handler(CommandHandler("restart", cmd_restart))
    app.add_handler(CommandHandler("shell", cmd_shell))
    app.add_handler(CommandHandler("trusted", cmd_trusted))
    app.add_handler(CommandHandler("untrust", cmd_untrust))
    app.add_handler(CommandHandler("approve_draft", cmd_approve_draft))
    app.add_handler(CommandHandler("reject_draft", cmd_reject_draft))
    app.add_handler(MessageHandler(filters.VOICE, handle_voice))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    return app
