#!/usr/bin/env python3
"""
Force Subscribe Telegram Bot — multi-instance version.

Features:
- Admin can save text, media, and quizzes and receive a private link.
- Users must join the configured channels before receiving content.
- User-facing name uses first/last name only; usernames are never displayed.
- Bot-delivered content is protected from Telegram forwarding/saving where supported.
- Delivered content is deleted automatically after five minutes.

NEW: /addbot <token>
  Master admin ek naya bot token paste kare.
  Bot validate hota hai, confirm button aata hai.
  OK dabao — woh bot spawn ho jata hai same features ke saath.
  Jo add karta hai woh us clone ka admin ban jata hai.

Install:
    pip install "python-telegram-bot==21.5" aiosqlite==0.19.0

Run:
    python3 adff.py

Required secret/environment variable:
    TELEGRAM_BOT_TOKEN
"""

from __future__ import annotations

import asyncio
import html
import json
import logging
import os
import uuid

import aiosqlite
from telegram import (
    Bot,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    Update,
)
from telegram.error import TelegramError
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    ChatJoinRequestHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

BOT_TOKEN: str = os.environ.get(
    "TELEGRAM_BOT_TOKEN",
    "8711629277:AAGjNYxONgiQSnPb_WUb5bs8kUX__UjAAgI",
).strip()

# Master admins: ye log /addbot use kar sakte hain aur main bot ke admin hain.
MASTER_ADMIN_IDS: list[int] = [8609127164]
CHANNELS: list[str] = ["@umhhhhhhhh", "@sodohuyall0", "@godtonyhun"]

PROTECT_CONTENT = True
CONTENT_TTL_SECONDS = 5 * 60
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "files.db")

# Runtime state — populated on startup and when bots are added dynamically.
# token -> [admin_id, ...]
BOT_ADMIN_MAP: dict[str, list[int]] = {}
# token -> running Application instance
RUNNING_APPS: dict[str, Application] = {}

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Database — files
# ---------------------------------------------------------------------------

async def init_db() -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS files (
                id        INTEGER PRIMARY KEY AUTOINCREMENT,
                unique_id TEXT UNIQUE NOT NULL,
                file_id   TEXT NOT NULL,
                file_type TEXT NOT NULL,
                caption   TEXT,
                added_by  INTEGER NOT NULL,
                added_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS quizzes (
                id             INTEGER PRIMARY KEY AUTOINCREMENT,
                unique_id      TEXT UNIQUE NOT NULL,
                question       TEXT NOT NULL,
                options        TEXT NOT NULL,
                correct_option INTEGER NOT NULL,
                explanation    TEXT,
                added_by       INTEGER NOT NULL,
                added_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS bots (
                id        INTEGER PRIMARY KEY AUTOINCREMENT,
                token     TEXT UNIQUE NOT NULL,
                admin_id  INTEGER NOT NULL,
                username  TEXT,
                added_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS channels (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                channel_id  TEXT UNIQUE NOT NULL,
                added_by    INTEGER NOT NULL,
                invite_link TEXT,
                is_private  INTEGER DEFAULT 0,
                added_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        # Migrate older DBs that are missing the new columns
        for _col in ("ADD COLUMN invite_link TEXT", "ADD COLUMN is_private INTEGER DEFAULT 0"):
            try:
                await db.execute(f"ALTER TABLE channels {_col}")
            except Exception:
                pass
        # Seed hardcoded CHANNELS list into DB if not already present
        for ch in CHANNELS:
            await db.execute(
                "INSERT OR IGNORE INTO channels (channel_id, added_by, is_private) VALUES (?, ?, 0)",
                (ch, MASTER_ADMIN_IDS[0] if MASTER_ADMIN_IDS else 0),
            )
        await db.commit()


async def save_file(
    unique_id: str,
    file_id: str,
    file_type: str,
    caption: str,
    added_by: int,
) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            INSERT INTO files (unique_id, file_id, file_type, caption, added_by)
            VALUES (?, ?, ?, ?, ?)
            """,
            (unique_id, file_id, file_type, caption, added_by),
        )
        await db.commit()


async def get_file(unique_id: str) -> dict | None:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT file_id, file_type, caption FROM files WHERE unique_id = ?",
            (unique_id,),
        ) as cur:
            row = await cur.fetchone()
    if not row:
        return None
    return {"file_id": row[0], "file_type": row[1], "caption": row[2]}


async def get_all_files(added_by: int) -> list:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            """
            SELECT unique_id, file_type, caption, added_at
            FROM files WHERE added_by = ?
            ORDER BY added_at DESC
            """,
            (added_by,),
        ) as cur:
            return await cur.fetchall()


async def delete_file(unique_id: str) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM files WHERE unique_id = ?", (unique_id,))
        await db.commit()


# ---------------------------------------------------------------------------
# Database — quizzes
# ---------------------------------------------------------------------------

async def save_quiz(
    unique_id: str,
    question: str,
    options: list[str],
    correct_option: int,
    explanation: str,
    added_by: int,
) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            INSERT INTO quizzes (
                unique_id, question, options, correct_option, explanation, added_by
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                unique_id,
                question,
                json.dumps(options, ensure_ascii=False),
                correct_option,
                explanation or "",
                added_by,
            ),
        )
        await db.commit()


async def get_quiz(unique_id: str) -> dict | None:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            """
            SELECT question, options, correct_option, explanation
            FROM quizzes WHERE unique_id = ?
            """,
            (unique_id,),
        ) as cur:
            row = await cur.fetchone()
    if not row:
        return None
    return {
        "question": row[0],
        "options": json.loads(row[1]),
        "correct_option": row[2],
        "explanation": row[3],
    }


async def get_all_quizzes(added_by: int) -> list:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            """
            SELECT unique_id, question, added_at
            FROM quizzes WHERE added_by = ?
            ORDER BY added_at DESC
            """,
            (added_by,),
        ) as cur:
            return await cur.fetchall()


async def delete_quiz(unique_id: str) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM quizzes WHERE unique_id = ?", (unique_id,))
        await db.commit()


# ---------------------------------------------------------------------------
# Database — bots
# ---------------------------------------------------------------------------

async def save_bot_record(token: str, admin_id: int, username: str) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR IGNORE INTO bots (token, admin_id, username) VALUES (?, ?, ?)",
            (token, admin_id, username),
        )
        await db.commit()


async def get_all_bot_records() -> list[tuple[str, int, str]]:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT token, admin_id, username FROM bots"
        ) as cur:
            return await cur.fetchall()  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# Database — channels (dynamic add/remove)
# ---------------------------------------------------------------------------

async def get_channels() -> list[str]:
    """Return channel_id list only (for membership check loops)."""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT channel_id FROM channels ORDER BY added_at ASC"
        ) as cur:
            rows = await cur.fetchall()
    return [row[0] for row in rows]


async def get_channels_full() -> list[dict]:
    """Return full channel rows including invite_link and is_private."""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT channel_id, invite_link, is_private FROM channels ORDER BY added_at ASC"
        ) as cur:
            rows = await cur.fetchall()
    return [
        {"channel_id": r[0], "invite_link": r[1], "is_private": bool(r[2])}
        for r in rows
    ]


async def add_channel_db(
    channel_id: str,
    added_by: int,
    invite_link: str | None = None,
    is_private: bool = False,
) -> bool:
    """Insert channel. Returns False if already exists."""
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                """
                INSERT INTO channels (channel_id, added_by, invite_link, is_private)
                VALUES (?, ?, ?, ?)
                """,
                (channel_id, added_by, invite_link, int(is_private)),
            )
            await db.commit()
        return True
    except Exception:
        return False


async def update_channel_invite_link(channel_id: str, invite_link: str) -> None:
    """Refresh stored invite link for a channel."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE channels SET invite_link = ? WHERE channel_id = ?",
            (invite_link, channel_id),
        )
        await db.commit()


async def remove_channel_db(channel_id: str) -> bool:
    """Delete channel. Returns False if it did not exist."""
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "DELETE FROM channels WHERE channel_id = ?", (channel_id,)
        )
        await db.commit()
        return cur.rowcount > 0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def is_admin(user_id: int, bot_token: str | None = None) -> bool:
    """
    Spawned bot ke liye us bot ka admin check karo.
    Main bot ya unknown token ke liye MASTER_ADMIN_IDS check karo.
    """
    if bot_token and bot_token in BOT_ADMIN_MAP:
        return user_id in BOT_ADMIN_MAP[bot_token]
    return user_id in MASTER_ADMIN_IDS


def _token(context: ContextTypes.DEFAULT_TYPE) -> str | None:
    """Extract the bot's token from context for admin checks."""
    try:
        return context.bot.token
    except Exception:
        return None


def protect_for_user(user_id: int, bot_token: str | None = None) -> bool:
    return PROTECT_CONTENT and not is_admin(user_id, bot_token)


def display_name(user) -> str:
    name = " ".join(
        part for part in (user.first_name, user.last_name) if part
    ).strip()
    return html.escape(name or "User")


async def check_joined(bot, user_id: int) -> list[str]:
    channels = await get_channels()
    not_joined = []
    for channel in channels:
        try:
            member = await bot.get_chat_member(channel, user_id)
            if member.status in ("left", "kicked", "banned"):
                not_joined.append(channel)
        except TelegramError as exc:
            logger.warning(
                "Membership check failed for %s and user %s: %s",
                channel, user_id, exc,
            )
            not_joined.append(channel)
    return not_joined


async def join_keyboard(
    bot,
    not_joined: list[str],
    payload: str = "",
) -> InlineKeyboardMarkup:
    """
    Build the join button list for channels the user hasn't joined.
    Private channels: uses stored invite link (bot generates one if missing).
    Public channels: uses t.me/@handle link.
    """
    # Fetch full info so we have invite_link and is_private per channel
    all_full = {ch["channel_id"]: ch for ch in await get_channels_full()}

    buttons = []
    for index, channel in enumerate(not_joined, start=1):
        # Get channel title from Telegram if possible
        try:
            chat = await bot.get_chat(channel)
            channel_label = chat.title or f"Channel {index}"
        except TelegramError:
            chat = None
            channel_label = f"Channel {index}"

        info = all_full.get(channel, {})
        is_priv = info.get("is_private", False)
        stored_link = info.get("invite_link")

        if is_priv:
            # Private channel — need invite link
            ch_url = stored_link
            if not ch_url:
                # Generate one now and persist it
                try:
                    inv = await bot.create_chat_invite_link(channel)
                    ch_url = inv.invite_link
                    await update_channel_invite_link(channel, ch_url)
                except TelegramError:
                    ch_url = None  # bot lacks permission — show disabled button text

            if ch_url:
                buttons.append([
                    InlineKeyboardButton(
                        f"🔒 {index}. {channel_label}  →  Join",
                        url=ch_url,
                    )
                ])
            else:
                # Can't produce link — tell user channel is private
                buttons.append([
                    InlineKeyboardButton(
                        f"🔒 {index}. {channel_label}  (invite required)",
                        callback_data="noop",
                    )
                ])
        else:
            # Public channel
            if channel.startswith("@"):
                ch_url = f"https://t.me/{channel.lstrip('@')}"
            else:
                ch_url = f"https://t.me/c/{str(channel).lstrip('-').lstrip('100')}"
            buttons.append([
                InlineKeyboardButton(
                    f"📢 {index}. {channel_label}  →  Join",
                    url=ch_url,
                )
            ])

    check_data = f"verify|{payload}" if payload else "verify|"
    buttons.append([
        InlineKeyboardButton("✅ Maine Join Kar Liya — Check Karo", callback_data=check_data)
    ])
    return InlineKeyboardMarkup(buttons)


async def get_bot_username(bot) -> str:
    me = await bot.get_me()
    return me.username or ""


async def delete_message_later(bot, chat_id: int, message_id: int) -> None:
    await asyncio.sleep(CONTENT_TTL_SECONDS)
    try:
        await bot.delete_message(chat_id=chat_id, message_id=message_id)
    except TelegramError as exc:
        logger.info(
            "Message %s/%s could not be deleted after expiry: %s",
            chat_id, message_id, exc,
        )


def schedule_delete(application: Application, sent_message: Message | None) -> None:
    if sent_message is None:
        return
    application.create_task(
        delete_message_later(
            application.bot,
            sent_message.chat_id,
            sent_message.message_id,
        )
    )


# ---------------------------------------------------------------------------
# Content delivery
# ---------------------------------------------------------------------------

async def deliver_content(
    message: Message,
    bot,
    unique_id: str,
    application: Application,
    protected: bool,
    edit: bool = False,
) -> None:
    if unique_id.startswith("q_"):
        await deliver_quiz(message, bot, unique_id, application, protected, edit)
    else:
        await deliver_file_content(message, bot, unique_id, application, protected, edit)


async def deliver_file_content(
    message: Message,
    bot,
    unique_id: str,
    application: Application,
    protected: bool,
    edit: bool = False,
) -> None:
    record = await get_file(unique_id)
    if not record:
        text = "❌ Yeh file exist nahi karti ya delete ho gayi hai."
        if edit:
            await message.edit_text(text)
        else:
            sent = await message.reply_text(text, protect_content=protected)
            schedule_delete(application, sent)
        return

    file_id = record["file_id"]
    file_type = record["file_type"]
    caption = record["caption"] or ""

    if edit:
        await message.edit_text("📥 File bhej raha hoon...")

    send_map = {
        "photo":      bot.send_photo,
        "video":      bot.send_video,
        "document":   bot.send_document,
        "audio":      bot.send_audio,
        "voice":      bot.send_voice,
        "animation":  bot.send_animation,
        "video_note": bot.send_video_note,
    }

    try:
        if file_type == "text":
            sent = await bot.send_message(
                chat_id=message.chat_id,
                text=caption or file_id,
                protect_content=protected,
            )
        elif file_type in send_map:
            kwargs: dict = {
                file_type: file_id,
                "chat_id": message.chat_id,
                "protect_content": protected,
            }
            if caption and file_type not in ("voice", "video_note"):
                kwargs["caption"] = caption
            sent = await send_map[file_type](**kwargs)
        else:
            sent = await bot.send_message(
                chat_id=message.chat_id,
                text=f"File: {file_id}\n{caption}",
                protect_content=protected,
            )
        schedule_delete(application, sent)
    except TelegramError as exc:
        await bot.send_message(
            chat_id=message.chat_id,
            text=f"❌ File send karne mein error: {exc}",
            protect_content=protected,
        )


async def deliver_quiz(
    message: Message,
    bot,
    unique_id: str,
    application: Application,
    protected: bool,
    edit: bool = False,
) -> None:
    record = await get_quiz(unique_id)
    if not record:
        text = "❌ Yeh quiz exist nahi karta ya delete ho gaya hai."
        if edit:
            await message.edit_text(text)
        else:
            sent = await message.reply_text(text, protect_content=protected)
            schedule_delete(application, sent)
        return

    if edit:
        await message.edit_text("📝 Test bhej raha hoon...")

    try:
        sent = await bot.send_poll(
            chat_id=message.chat_id,
            question=record["question"],
            options=record["options"],
            type="quiz",
            correct_option_id=record["correct_option"],
            explanation=record["explanation"] or None,
            is_anonymous=False,
            protect_content=protected,
        )
        schedule_delete(application, sent)
    except TelegramError as exc:
        await bot.send_message(
            chat_id=message.chat_id,
            text=f"❌ Quiz send karne mein error: {exc}",
            protect_content=protected,
        )


# ---------------------------------------------------------------------------
# Handlers — start & verify
# ---------------------------------------------------------------------------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.effective_user:
        return

    tok = _token(context)
    user = update.effective_user
    payload = context.args[0] if context.args else ""
    not_joined = await check_joined(context.bot, user.id)

    if not_joined:
        total = len(await get_channels())
        remaining = len(not_joined)
        await update.message.reply_html(
            f"👋 <b>Swagat hai, {display_name(user)}!</b>\n\n"
            f"🔒 Content unlock karne ke liye <b>{remaining}/{total} channel{'s' if remaining != 1 else ''}</b> "
            "abhi bhi join karne baaki hain.\n\n"
            "Neeche ke buttons se join karo, phir\n"
            "<b>✅ Maine Join Kar Liya</b> dabao.",
            reply_markup=await join_keyboard(context.bot, not_joined, payload),
            protect_content=protect_for_user(user.id, tok),
        )
        return

    if payload:
        await deliver_content(
            update.message,
            context.bot,
            payload,
            context.application,
            protected=protect_for_user(user.id, tok),
        )
    else:
        await update.message.reply_html(
            f"✅ <b>{display_name(user)}</b>, aap sab channels mein hain!\n\n"
            "🎉 Admin se file ya quiz ka link maango aur click karo — "
            "content seedha aa jaayega.",
            protect_content=protect_for_user(user.id, tok),
        )


async def verify_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    query = update.callback_query
    if not query or not query.message:
        return

    tok = _token(context)
    user = query.from_user
    payload = query.data.split("|", 1)[1] if "|" in query.data else ""
    not_joined = await check_joined(context.bot, user.id)

    if not_joined:
        await query.answer("❌ Abhi bhi kuch channels join nahi kiye!", show_alert=True)
        await query.edit_message_reply_markup(
            reply_markup=await join_keyboard(context.bot, not_joined, payload)
        )
        return

    await query.answer("✅ Verification successful!")
    if payload:
        await deliver_content(
            query.message,
            context.bot,
            payload,
            context.application,
            protected=protect_for_user(user.id, tok),
            edit=True,
        )
        schedule_delete(context.application, query.message)
    else:
        await query.edit_message_text(
            f"✅ <b>{display_name(user)}, verified!</b>\n"
            "Ab aap bot use kar sakte ho. File ka link admin se maango.",
            parse_mode="HTML",
        )


# ---------------------------------------------------------------------------
# Handlers — admin content commands
# ---------------------------------------------------------------------------

async def add_msg(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.effective_user:
        return
    tok = _token(context)
    if not is_admin(update.effective_user.id, tok):
        return

    text_body = " ".join(context.args).strip() if context.args else ""
    if not text_body and update.message.reply_to_message:
        text_body = update.message.reply_to_message.text or ""

    if not text_body:
        await update.message.reply_html(
            "📝 <b>Usage:</b>\n"
            "<code>/addmsg Aapka message yahan likho</code>\n\n"
            "Ya kisi message ko reply karke:\n"
            "<code>/addmsg</code>",
            protect_content=protect_for_user(update.effective_user.id, tok),
        )
        return

    unique_id = str(uuid.uuid4())[:12]
    await save_file(unique_id, text_body, "text", text_body, update.effective_user.id)
    bot_username = await get_bot_username(context.bot)
    share_link = f"https://t.me/{bot_username}?start={unique_id}"
    preview = text_body[:60] + "…" if len(text_body) > 60 else text_body

    await update.message.reply_html(
        f"✅ <b>Text message save ho gaya!</b>\n\n"
        f"📝 <b>Message:</b> {html.escape(preview)}\n"
        f"🆔 <b>ID:</b> <code>{unique_id}</code>\n\n"
        f"🔗 <b>Share Link:</b>\n<code>{share_link}</code>\n\n"
        "<i>User pehle channel join karega, phir yeh message milega.</i>",
        disable_web_page_preview=True,
        protect_content=protect_for_user(update.effective_user.id, tok),
    )


async def handle_admin_quiz(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    if not update.message or not update.effective_user or not update.message.poll:
        return
    tok = _token(context)
    if not is_admin(update.effective_user.id, tok):
        return

    poll = update.message.poll
    if poll.type != "quiz":
        await update.message.reply_html(
            "⚠️ Yeh regular poll hai, quiz nahi.\n"
            "Poll banate waqt <b>Quiz Mode</b> on karo aur sahi jawab select karo.",
            protect_content=protect_for_user(update.effective_user.id, tok),
        )
        return

    unique_id = "q_" + str(uuid.uuid4())[:10]
    options = [option.text for option in poll.options]
    correct = poll.correct_option_id
    explanation = poll.explanation or ""
    await save_quiz(
        unique_id, poll.question, options, correct, explanation, update.effective_user.id
    )

    bot_username = await get_bot_username(context.bot)
    share_link = f"https://t.me/{bot_username}?start={unique_id}"
    options_text = "\n".join(
        f"  {'✅' if i == correct else '◦'} {opt}"
        for i, opt in enumerate(options)
    )

    await update.message.reply_html(
        f"✅ <b>Quiz save ho gaya!</b>\n\n"
        f"❓ <b>Question:</b> {html.escape(poll.question)}\n"
        f"<b>Options:</b>\n{html.escape(options_text)}\n\n"
        f"🆔 <b>ID:</b> <code>{unique_id}</code>\n\n"
        f"🔗 <b>Share Link:</b>\n<code>{share_link}</code>\n\n"
        "<i>User pehle channel join karega, phir quiz milega.</i>",
        disable_web_page_preview=True,
        protect_content=protect_for_user(update.effective_user.id, tok),
    )


async def handle_admin_file(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    if not update.message or not update.effective_user:
        return
    tok = _token(context)
    if not is_admin(update.effective_user.id, tok):
        return

    message = update.message
    unique_id = str(uuid.uuid4())[:12]
    file_id = None
    file_type = None

    if message.photo:
        file_id, file_type = message.photo[-1].file_id, "photo"
    elif message.video:
        file_id, file_type = message.video.file_id, "video"
    elif message.document:
        file_id, file_type = message.document.file_id, "document"
    elif message.audio:
        file_id, file_type = message.audio.file_id, "audio"
    elif message.voice:
        file_id, file_type = message.voice.file_id, "voice"
    elif message.animation:
        file_id, file_type = message.animation.file_id, "animation"
    elif message.video_note:
        file_id, file_type = message.video_note.file_id, "video_note"
    elif message.text and not message.text.startswith("/"):
        file_id, file_type = message.text, "text"

    if file_id is None or file_type is None:
        return

    caption = message.caption or (message.text if file_type == "text" else "") or ""
    await save_file(unique_id, file_id, file_type, caption, update.effective_user.id)
    bot_username = await get_bot_username(context.bot)
    share_link = f"https://t.me/{bot_username}?start={unique_id}"

    await message.reply_html(
        f"✅ <b>File save ho gayi!</b>\n\n"
        f"📎 <b>Type:</b> {file_type}\n"
        f"🆔 <b>ID:</b> <code>{unique_id}</code>\n\n"
        f"🔗 <b>Share Link:</b>\n<code>{share_link}</code>\n\n"
        "<i>User pehle channel join karega, phir file milegi.</i>",
        disable_web_page_preview=True,
        protect_content=protect_for_user(update.effective_user.id, tok),
    )


async def my_files(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.effective_user:
        return
    tok = _token(context)
    if not is_admin(update.effective_user.id, tok):
        await update.message.reply_text(
            "❌ Sirf admin ke liye hai.",
            protect_content=protect_for_user(update.effective_user.id, tok),
        )
        return

    rows = await get_all_files(update.effective_user.id)
    if not rows:
        await update.message.reply_text(
            "📂 Abhi koi file save nahi hai.",
            protect_content=protect_for_user(update.effective_user.id, tok),
        )
        return

    bot_username = await get_bot_username(context.bot)
    lines = [f"📂 <b>Aapki Files ({len(rows)} total):</b>\n"]
    for unique_id, file_type, caption, _ in rows[:20]:
        link = f"https://t.me/{bot_username}?start={unique_id}"
        title = (caption[:30] + "…" if caption and len(caption) > 30 else caption) or "—"
        lines.append(
            f"\n• <b>{file_type}</b> | <code>{unique_id}</code>\n"
            f"  📝 {html.escape(title)}\n  🔗 <code>{link}</code>"
        )
    await update.message.reply_html(
        "\n".join(lines),
        disable_web_page_preview=True,
        protect_content=protect_for_user(update.effective_user.id, tok),
    )


async def my_quizzes(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.effective_user:
        return
    tok = _token(context)
    if not is_admin(update.effective_user.id, tok):
        await update.message.reply_text(
            "❌ Sirf admin ke liye hai.",
            protect_content=protect_for_user(update.effective_user.id, tok),
        )
        return

    rows = await get_all_quizzes(update.effective_user.id)
    if not rows:
        await update.message.reply_text(
            "📋 Abhi koi quiz save nahi hai.",
            protect_content=protect_for_user(update.effective_user.id, tok),
        )
        return

    bot_username = await get_bot_username(context.bot)
    lines = [f"📋 <b>Aapke Quizzes ({len(rows)} total):</b>\n"]
    for unique_id, question, _ in rows[:20]:
        link = f"https://t.me/{bot_username}?start={unique_id}"
        title = question[:40] + "…" if len(question) > 40 else question
        lines.append(
            f"\n• ❓ <code>{unique_id}</code>\n"
            f"  📝 {html.escape(title)}\n  🔗 <code>{link}</code>"
        )
    await update.message.reply_html(
        "\n".join(lines),
        disable_web_page_preview=True,
        protect_content=protect_for_user(update.effective_user.id, tok),
    )


async def delete_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.effective_user:
        return
    tok = _token(context)
    if not is_admin(update.effective_user.id, tok):
        await update.message.reply_text(
            "❌ Sirf admin ke liye hai.",
            protect_content=protect_for_user(update.effective_user.id, tok),
        )
        return

    if not context.args:
        await update.message.reply_html(
            "Usage:\n"
            "/delete &lt;file_id&gt;  — file delete karo\n"
            "/delete &lt;q_id&gt;     — quiz delete karo",
            protect_content=protect_for_user(update.effective_user.id, tok),
        )
        return

    unique_id = context.args[0]
    if unique_id.startswith("q_"):
        await delete_quiz(unique_id)
        text = f"🗑️ Quiz <code>{html.escape(unique_id)}</code> delete ho gaya."
    else:
        await delete_file(unique_id)
        text = f"🗑️ File <code>{html.escape(unique_id)}</code> delete ho gayi."
    await update.message.reply_html(
        text,
        protect_content=protect_for_user(update.effective_user.id, tok),
    )


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.effective_user:
        return
    tok = _token(context)

    if is_admin(update.effective_user.id, tok):
        is_master = update.effective_user.id in MASTER_ADMIN_IDS

        channel_section = ""
        if is_master:
            channel_section = (
                "\n\n<b>📢 Channel Management:</b>\n"
                "/addchannel <code>@handle</code> — force-sub list mein channel add karo\n"
                "/removechannel <code>@handle</code> — channel hatao (button menu bhi milega)\n"
                "/listchannels — abhi ke saare channels dekho\n"
            )
        else:
            channel_section = "\n\n/listchannels — abhi ke force-sub channels dekho\n"

        addbot_section = ""
        if is_master:
            addbot_section = (
                "\n<b>🤖 Bot Management:</b>\n"
                "/addbot <code>&lt;token&gt;</code> — naya bot clone karo\n"
            )

        text = (
            "╔══════════════════════╗\n"
            "║  🤖  <b>Admin Panel</b>        ║\n"
            "╚══════════════════════╝\n\n"
            "<b>📤 Content Upload:</b>\n"
            "• File / Photo / Video bhejo → protected link milega\n"
            "• Quiz poll bhejo (Quiz Mode on karke) → quiz link milega\n"
            "/addmsg <code>&lt;text&gt;</code> — text message ka link banao\n\n"
            "<b>📂 Content Management:</b>\n"
            "/myfiles — saari saved files dekho\n"
            "/myquizzes — saare quizzes dekho\n"
            "/delete <code>&lt;id&gt;</code> — file ya quiz delete karo"
            f"{channel_section}"
            f"{addbot_section}"
            "\n/help — yeh message\n\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            "<i>🔒 Users ko content milne se pehle saare channels join karne honge.</i>"
        )
    else:
        channels = await get_channels()
        ch_count = len(channels)
        text = (
            "╔══════════════════════╗\n"
            "║  👋  <b>Bot Guide</b>          ║\n"
            "╚══════════════════════╝\n\n"
            "<b>Content kaise milega:</b>\n\n"
            f"1️⃣ Admin se file/quiz ka link maango\n"
            f"2️⃣ Link click karo\n"
            f"3️⃣ <b>{ch_count} channel{'s' if ch_count != 1 else ''}</b> join karo\n"
            f"4️⃣ ✅ <b>Maine Join Kar Liya</b> button dabao\n"
            f"5️⃣ Content automatically aa jaayega\n\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            "⏳ <i>Content 5 minute baad automatically delete ho jaata hai.</i>"
        )

    await update.message.reply_html(
        text,
        protect_content=protect_for_user(update.effective_user.id, tok),
    )


# ---------------------------------------------------------------------------
# Handlers — /addchannel  /removechannel  /listchannels  (master admin only)
# ---------------------------------------------------------------------------

async def addchannel_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /addchannel @username  OR  /addchannel -100xxxxxxxxxx

    Public aur private dono channels add ho sakte hain.
    Bot ko us channel ka admin hona chahiye (Invite Users permission bhi).
    Private channel ke liye bot automatically invite link generate karega.
    Sirf master admin ke liye.
    """
    if not update.message or not update.effective_user:
        return

    if update.effective_user.id not in MASTER_ADMIN_IDS:
        await update.message.reply_text("❌ Sirf master admin ke liye hai.")
        return

    if not context.args:
        await update.message.reply_html(
            "📢 <b>Channel Add Karo</b>\n\n"
            "<b>Usage:</b>\n"
            "  <code>/addchannel @publichandle</code>\n"
            "  <code>/addchannel -100xxxxxxxxxx</code>  ← private channel ke liye\n\n"
            "<b>Bot ko channel ka admin banana zaroori hai</b> warna kaam nahi karega.\n"
            "Private channel ke liye bot ko <b>Invite Users</b> permission bhi chahiye.\n\n"
            "/listchannels — abhi ke channels dekho"
        )
        return

    raw = context.args[0].strip()
    if not raw.startswith("@") and not raw.lstrip("-").isdigit():
        raw = "@" + raw

    checking_msg = await update.message.reply_text("🔍 Channel verify ho raha hai...")

    try:
        chat = await context.bot.get_chat(raw)
        chat_title = chat.title or raw
        # Normalize: prefer @username, fall back to numeric id
        channel_id = f"@{chat.username}" if chat.username else str(chat.id)
        is_private = not chat.username  # no public username → private channel
    except TelegramError as exc:
        await checking_msg.edit_text(
            f"❌ Channel access nahi hua:\n<code>{html.escape(str(exc))}</code>\n\n"
            "Make sure bot is already an admin in that channel.",
            parse_mode="HTML",
        )
        return

    # For private channels, generate and store an invite link now
    invite_link: str | None = None
    if is_private:
        await checking_msg.edit_text(
            "🔗 Private channel detect hua — invite link generate ho raha hai..."
        )
        try:
            inv = await context.bot.create_chat_invite_link(
                chat.id,
                name="Force-Sub Link",
                creates_join_request=True,  # users send join request → auto-approved
            )
            invite_link = inv.invite_link
        except TelegramError as exc:
            await checking_msg.edit_text(
                f"⚠️ Channel add ho sakta hai lekin invite link generate nahi hua:\n"
                f"<code>{html.escape(str(exc))}</code>\n\n"
                "Bot ko <b>Invite Users</b> permission do, phir /addchannel dobara karo.",
                parse_mode="HTML",
            )
            # Still add channel, just without invite link
            invite_link = None

    added = await add_channel_db(
        channel_id, update.effective_user.id, invite_link=invite_link, is_private=is_private
    )

    if not added:
        await checking_msg.edit_text(
            f"⚠️ <b>{html.escape(chat_title)}</b> (<code>{channel_id}</code>) "
            "pehle se list mein hai!",
            parse_mode="HTML",
        )
        return

    channels = await get_channels()
    privacy_badge = "🔒 Private" if is_private else "🌐 Public"
    link_status = (
        f"\n🔗 <b>Invite Link:</b> <code>{invite_link}</code>" if invite_link
        else "\n⚠️ Invite link missing — bot ko Invite Users permission do."
    )
    await checking_msg.edit_text(
        f"✅ <b>Channel add ho gaya!</b>\n\n"
        f"📢 <b>{html.escape(chat_title)}</b>\n"
        f"🏷️ {privacy_badge}  |  <code>{channel_id}</code>"
        f"{link_status}\n\n"
        f"📋 <b>Total channels ab:</b> {len(channels)}\n\n"
        "<i>Ab se yeh channel bhi join karana zaroori hoga.</i>",
        parse_mode="HTML",
    )


async def removechannel_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /removechannel @username  OR  /removechannel -100xxxxxxxxxx

    Channel ko force-subscribe list se hataao.
    Sirf master admin ke liye.
    """
    if not update.message or not update.effective_user:
        return

    if update.effective_user.id not in MASTER_ADMIN_IDS:
        await update.message.reply_text("❌ Sirf master admin ke liye hai.")
        return

    channels = await get_channels()

    if not context.args:
        if not channels:
            await update.message.reply_html(
                "📋 Abhi koi channel list mein nahi hai.\n\n"
                "/addchannel se channel add karo."
            )
            return

        # Show inline buttons for each channel so he can tap to remove
        buttons = [
            [InlineKeyboardButton(
                f"🗑️ {ch}",
                callback_data=f"rmch|{ch}",
            )]
            for ch in channels
        ]
        buttons.append([InlineKeyboardButton("❌ Cancel", callback_data="rmch_cancel")])
        await update.message.reply_html(
            "📋 <b>Kaunsa channel hatana hai?</b>\n\n"
            "Neeche se select karo:",
            reply_markup=InlineKeyboardMarkup(buttons),
        )
        return

    raw = context.args[0].strip()
    if not raw.startswith("@") and not raw.lstrip("-").isdigit():
        raw = "@" + raw

    removed = await remove_channel_db(raw)
    if not removed:
        # Try alternate form (numeric id vs @handle mismatch)
        await update.message.reply_html(
            f"❌ <code>{html.escape(raw)}</code> list mein nahi mila.\n\n"
            "/listchannels se exact ID dekho phir dobara try karo.",
        )
        return

    channels_now = await get_channels()
    await update.message.reply_html(
        f"🗑️ <b>Channel hata diya!</b>\n\n"
        f"<code>{html.escape(raw)}</code> ab list mein nahi hai.\n\n"
        f"📋 <b>Baaki channels:</b> {len(channels_now)}",
    )


async def removechannel_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Handles inline button taps from /removechannel (no args) menu."""
    query = update.callback_query
    if not query:
        return
    await query.answer()

    if query.data == "rmch_cancel":
        await query.edit_message_text("❌ Cancel ho gaya.")
        return

    if not query.data.startswith("rmch|"):
        return

    channel_id = query.data.split("|", 1)[1]
    removed = await remove_channel_db(channel_id)

    if not removed:
        await query.edit_message_text(
            f"⚠️ <code>{html.escape(channel_id)}</code> already hata diya gaya tha.",
            parse_mode="HTML",
        )
        return

    channels_now = await get_channels()
    await query.edit_message_text(
        f"🗑️ <b>Hata diya!</b>\n\n"
        f"<code>{html.escape(channel_id)}</code> ab list mein nahi hai.\n\n"
        f"📋 <b>Baaki channels:</b> {len(channels_now)}",
        parse_mode="HTML",
    )


async def listchannels_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /listchannels

    Active force-subscribe channels ki list dekho.
    Sirf admin ke liye.
    """
    if not update.message or not update.effective_user:
        return
    tok = _token(context)
    if not is_admin(update.effective_user.id, tok):
        await update.message.reply_text("❌ Sirf admin ke liye hai.")
        return

    full_channels = await get_channels_full()

    if not full_channels:
        await update.message.reply_html(
            "📋 <b>Force-Subscribe Channels</b>\n\n"
            "❌ Abhi koi channel configure nahi hai.\n\n"
            "<i>Master admin /addchannel se add kar sakta hai.</i>"
        )
        return

    is_master = update.effective_user.id in MASTER_ADMIN_IDS
    lines = [f"📋 <b>Force-Subscribe Channels ({len(full_channels)} total):</b>\n"]

    for i, info in enumerate(full_channels, 1):
        ch = info["channel_id"]
        is_priv = info["is_private"]
        has_link = bool(info["invite_link"])

        try:
            chat = await context.bot.get_chat(ch)
            title = html.escape(chat.title or ch)
        except TelegramError:
            title = html.escape(ch)

        badge = "🔒" if is_priv else "🌐"
        link_note = ""
        if is_priv and is_master:
            link_note = "  ✅ link ready" if has_link else "  ⚠️ <b>no invite link!</b>"

        lines.append(f"  {i}. {badge} <b>{title}</b> — <code>{html.escape(ch)}</code>{link_note}")

    if is_master:
        lines.append(
            "\n\n<i>➕ /addchannel @handle — channel add karo\n"
            "➖ /removechannel — channel hatao\n"
            "🔒 = private channel  |  🌐 = public channel</i>"
        )

    await update.message.reply_html(
        "\n".join(lines),
        disable_web_page_preview=True,
        protect_content=protect_for_user(update.effective_user.id, tok),
    )


# ---------------------------------------------------------------------------
# Handler — /addbot  (master admin only)
# ---------------------------------------------------------------------------

async def addbot_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /addbot <token>

    Master admin use kare. Bot validate hota hai, confirm button aata hai.
    OK dabao → clone spawn hota hai, add karne wala us bot ka admin banta hai.
    """
    if not update.message or not update.effective_user:
        return

    # Only MASTER_ADMIN_IDS can add bots — not just any spawned-bot admin.
    if update.effective_user.id not in MASTER_ADMIN_IDS:
        await update.message.reply_text("❌ Sirf master admin ke liye hai.")
        return

    if not context.args:
        await update.message.reply_html(
            "🤖 <b>Bot Clone Karo</b>\n\n"
            "<b>Usage:</b>\n"
            "<code>/addbot &lt;bot_token&gt;</code>\n\n"
            "BotFather se naya token lo aur yahan paste karo.\n"
            "Woh bot is bot ki tarah kaam karega — same features, same channels.\n"
            "Aap uske admin ban jaoge.",
        )
        return

    new_token = context.args[0].strip()

    if new_token == BOT_TOKEN:
        await update.message.reply_text("❌ Yeh to main bot ka token hai!")
        return

    if new_token in RUNNING_APPS:
        await update.message.reply_text("⚠️ Yeh bot pehle se chal raha hai.")
        return

    validating_msg = await update.message.reply_text("🔍 Token verify ho raha hai...")

    try:
        async with Bot(token=new_token) as test_bot:
            me = await test_bot.get_me()
            bot_username = me.username or "unknown_bot"
            bot_name = me.full_name or bot_username
    except TelegramError as exc:
        await validating_msg.edit_text(
            f"❌ Invalid token ya Telegram error:\n{str(exc)}"
        )
        return

    # Store pending confirmation in bot_data keyed by a short random key
    confirm_key = str(uuid.uuid4())[:10]
    context.bot_data[f"addbot_{confirm_key}"] = {
        "token": new_token,
        "admin_id": update.effective_user.id,
        "username": bot_username,
    }

    kb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Haan, Add Karo", callback_data=f"addbot_yes|{confirm_key}"),
            InlineKeyboardButton("❌ Cancel", callback_data="addbot_no"),
        ]
    ])

    await validating_msg.edit_text(
        f"🤖 <b>Bot mila!</b>\n\n"
        f"👤 <b>Name:</b> {html.escape(bot_name)}\n"
        f"🔹 <b>Username:</b> @{html.escape(bot_username)}\n\n"
        f"Confirm karo — woh bot spawn ho jaayega aur aap uske admin ban jaoge.\n"
        f"Same channels, same features.",
        parse_mode="HTML",
        reply_markup=kb,
    )


async def addbot_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    query = update.callback_query
    if not query:
        return
    await query.answer()

    if query.data == "addbot_no":
        await query.edit_message_text("❌ Cancel ho gaya. Koi bot add nahi hua.")
        return

    if not query.data.startswith("addbot_yes|"):
        return

    confirm_key = query.data.split("|", 1)[1]
    data = context.bot_data.pop(f"addbot_{confirm_key}", None)

    if not data:
        await query.edit_message_text(
            "❌ Session expire ho gaya. /addbot dobara run karo."
        )
        return

    new_token: str = data["token"]
    admin_id: int = data["admin_id"]
    bot_username: str = data["username"]

    await query.edit_message_text(f"⚙️ @{bot_username} start ho raha hai...")

    if new_token in RUNNING_APPS:
        await query.edit_message_text(
            f"⚠️ @{bot_username} pehle se chal raha hai."
        )
        return

    try:
        await save_bot_record(new_token, admin_id, bot_username)
        await _spawn_bot(new_token, admin_id)
        await query.edit_message_text(
            f"✅ @{bot_username} ab chal raha hai!\n\n"
            f"🔑 Aap us bot ke admin hain.\n"
            f"Us bot mein /start karke use karo.",
            parse_mode="HTML",
        )
        logger.info("Bot @%s spawned by admin %s", bot_username, admin_id)
    except Exception as exc:
        logger.error("Failed to spawn @%s: %s", bot_username, exc)
        await query.edit_message_text(
            f"❌ Bot start nahi hua:\n{html.escape(str(exc))}"
        )


# ---------------------------------------------------------------------------
# Handler — auto-approve join requests for private channels
# ---------------------------------------------------------------------------

async def approve_join_request(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """
    Jab bhi koi user kisi channel mein join request bheje —
    bot automatically approve kar deta hai.

    Yeh zaroori hai kyunki:
    - Private channel mein join request mode on ho sakta hai.
    - Telegram API mein pending request ka status get_chat_member se
      'left' aata hai, member nahi.
    - Auto-approve ke baad user turant member ban jaata hai aur
      check_joined() sahi kaam karta hai.

    Bot ko channel ka admin hona chahiye with 'Add Members' permission.
    """
    join_req = update.chat_join_request
    if not join_req:
        return

    # Only act on channels that are in our force-sub list
    channel_ids = await get_channels()
    chat_id = join_req.chat.id

    # Match by numeric id or @username
    chat_username = join_req.chat.username
    is_our_channel = (
        str(chat_id) in channel_ids
        or (chat_username and f"@{chat_username}" in channel_ids)
    )
    if not is_our_channel:
        return

    try:
        await context.bot.approve_chat_join_request(
            chat_id=chat_id,
            user_id=join_req.from_user.id,
        )
        logger.info(
            "Auto-approved join request: user %s in chat %s",
            join_req.from_user.id, chat_id,
        )
    except TelegramError as exc:
        logger.warning(
            "Could not approve join request for user %s in %s: %s",
            join_req.from_user.id, chat_id, exc,
        )


# ---------------------------------------------------------------------------
# Bot spawning
# ---------------------------------------------------------------------------

def _build_application(token: str) -> Application:
    """Build a fully-wired Application for the given token."""
    app = Application.builder().token(token).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("addmsg", add_msg))
    app.add_handler(CommandHandler("myfiles", my_files))
    app.add_handler(CommandHandler("myquizzes", my_quizzes))
    app.add_handler(CommandHandler("delete", delete_cmd))
    app.add_handler(CommandHandler("addbot", addbot_cmd))
    app.add_handler(CommandHandler("addchannel", addchannel_cmd))
    app.add_handler(CommandHandler("removechannel", removechannel_cmd))
    app.add_handler(CommandHandler("listchannels", listchannels_cmd))
    app.add_handler(CallbackQueryHandler(verify_callback, pattern=r"^verify\|"))
    app.add_handler(CallbackQueryHandler(addbot_callback, pattern=r"^addbot_"))
    app.add_handler(CallbackQueryHandler(removechannel_callback, pattern=r"^rmch"))
    # Auto-approve join requests for private channels
    app.add_handler(ChatJoinRequestHandler(approve_join_request))
    app.add_handler(MessageHandler(filters.POLL, handle_admin_quiz))
    app.add_handler(
        MessageHandler(
            filters.PHOTO
            | filters.VIDEO
            | filters.Document.ALL
            | filters.AUDIO
            | filters.VOICE
            | filters.ANIMATION
            | filters.VIDEO_NOTE
            | (filters.TEXT & ~filters.COMMAND),
            handle_admin_file,
        )
    )
    return app


async def _spawn_bot(token: str, admin_id: int) -> None:
    """
    Initialize and start polling for a new bot instance.
    Runs alongside the main bot in the same event loop.
    """
    BOT_ADMIN_MAP[token] = [admin_id]
    app = _build_application(token)
    RUNNING_APPS[token] = app

    await app.initialize()
    await app.start()
    await app.updater.start_polling(drop_pending_updates=True)
    logger.info("Bot token=%s... started for admin %s", token[:20], admin_id)


# ---------------------------------------------------------------------------
# Startup
# ---------------------------------------------------------------------------

async def run_all() -> None:
    """
    Main async entry point.
    1. Init DB
    2. Restore saved bot clones from DB
    3. Start main bot
    4. Run forever (until Ctrl+C)
    """
    await init_db()
    logger.info("Database initialized.")

    # Restore previously added bots.
    saved_bots = await get_all_bot_records()
    for token, admin_id, username in saved_bots:
        if token == BOT_TOKEN:
            continue
        try:
            logger.info("Restoring bot @%s ...", username)
            await _spawn_bot(token, admin_id)
        except Exception as exc:
            logger.error("Could not restore @%s: %s", username, exc)

    # Start main bot.
    BOT_ADMIN_MAP[BOT_TOKEN] = list(MASTER_ADMIN_IDS)
    main_app = _build_application(BOT_TOKEN)
    RUNNING_APPS[BOT_TOKEN] = main_app

    await main_app.initialize()
    await main_app.start()
    await main_app.updater.start_polling(drop_pending_updates=True)
    logger.info(
        "Main bot running. %d clone(s) loaded. Press Ctrl+C to stop.",
        len(saved_bots),
    )

    try:
        await asyncio.Event().wait()   # block until cancelled
    except (KeyboardInterrupt, SystemExit, asyncio.CancelledError):
        pass
    finally:
        logger.info("Shutting down all bots...")
        for tok, app in list(RUNNING_APPS.items()):
            try:
                await app.updater.stop()
                await app.stop()
                await app.shutdown()
            except Exception as exc:
                logger.warning("Error shutting down %s...: %s", tok[:20], exc)


def main() -> None:
    if not BOT_TOKEN or BOT_TOKEN == "PASTE_MAIN_BOT_TOKEN_HERE":
        raise RuntimeError(
            "Main bot token set nahi hai.\n"
            "TELEGRAM_BOT_TOKEN environment variable set karein\n"
            "ya code mein PASTE_MAIN_BOT_TOKEN_HERE replace karein."
        )
    asyncio.run(run_all())


if __name__ == "__main__":
    main()
