#!/usr/bin/env python3
"""
Force Subscribe Telegram Bot — multi-instance version  v2.0

Features (original):
- Admin can save text, media, and quizzes and receive a private link.
- Users must join the configured channels before receiving content.
- User-facing name uses first/last name only; usernames are never displayed.
- Bot-delivered content is protected from Telegram forwarding/saving where supported.
- Delivered content is deleted automatically (default 5 min, configurable).
- /addbot  — master admin clones the bot with a new token.

NEW in v2.0:
- User tracking — every /start is recorded (needed for broadcast).
- /stats     — total users, files, quizzes, channels, bots.
- /broadcast — send text or media to all users (rate-limited, flood-safe).
- /setwelcome <text> — custom welcome message per bot.
- /toggleprotect    — flip PROTECT_CONTENT on/off at runtime.
- /setttl <seconds> — change auto-delete timer at runtime.
- /refreshlink @ch  — regenerate invite link for a private channel.
- /ban <user_id>    — block a user; they get a refusal on /start.
- /unban <user_id>  — unblock.
- /search <query>   — search your saved files by caption.
- /setcaption <id> <text> — update a file's caption.
- Anti-ban          — broadcast is rate-limited, RetryAfter is handled gracefully.

Install:
    pip install "python-telegram-bot==21.5" aiosqlite==0.19.0

Run:
    python3 adff-2-0.py

Required env var:
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
from telegram.error import RetryAfter, TelegramError
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

MASTER_ADMIN_IDS: list[int] = [8609127164]
CHANNELS: list[str] = ["@umhhhhhhhh", "@sodohuyall0", "@godtonyhun"]

PROTECT_CONTENT = True
CONTENT_TTL_SECONDS = 5 * 60
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "files.db")

# Runtime state
BOT_ADMIN_MAP: dict[str, list[int]] = {}
RUNNING_APPS: dict[str, Application] = {}

# Per-token runtime overrides (populated from DB on startup + updated live)
PROTECT_OVERRIDE: dict[str, bool] = {}   # token -> bool
TTL_OVERRIDE: dict[str, int] = {}        # token -> seconds

# Broadcast rate-limit: Telegram allows ~30 msg/sec; we use 25 to stay safe
_BROADCAST_DELAY = 1 / 25

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
        # --- existing tables ---
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
        # Migrate older DBs — channels columns
        for _col in ("ADD COLUMN invite_link TEXT", "ADD COLUMN is_private INTEGER DEFAULT 0"):
            try:
                await db.execute(f"ALTER TABLE channels {_col}")
            except Exception:
                pass

        # --- NEW tables ---
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                user_id    INTEGER PRIMARY KEY,
                first_name TEXT,
                last_name  TEXT,
                username   TEXT,
                joined_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                is_banned  INTEGER DEFAULT 0
            )
            """
        )
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS settings (
                bot_token TEXT NOT NULL,
                key       TEXT NOT NULL,
                value     TEXT NOT NULL,
                PRIMARY KEY (bot_token, key)
            )
            """
        )

        # Seed hardcoded CHANNELS
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
            "INSERT INTO files (unique_id, file_id, file_type, caption, added_by) VALUES (?, ?, ?, ?, ?)",
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
            "SELECT unique_id, file_type, caption, added_at FROM files WHERE added_by = ? ORDER BY added_at DESC",
            (added_by,),
        ) as cur:
            return await cur.fetchall()


async def delete_file(unique_id: str) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM files WHERE unique_id = ?", (unique_id,))
        await db.commit()


async def search_files_db(query: str, added_by: int) -> list:
    """Search files by caption (case-insensitive) for a given admin."""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            """
            SELECT unique_id, file_type, caption, added_at
            FROM files
            WHERE added_by = ? AND caption LIKE ?
            ORDER BY added_at DESC
            LIMIT 15
            """,
            (added_by, f"%{query}%"),
        ) as cur:
            return await cur.fetchall()


async def update_file_caption(unique_id: str, new_caption: str, added_by: int) -> bool:
    """Update caption. Returns False if file not found or not owned by this admin."""
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "UPDATE files SET caption = ? WHERE unique_id = ? AND added_by = ?",
            (new_caption, unique_id, added_by),
        )
        await db.commit()
        return cur.rowcount > 0


async def get_files_count() -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT COUNT(*) FROM files") as cur:
            row = await cur.fetchone()
    return row[0] if row else 0


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
            INSERT INTO quizzes (unique_id, question, options, correct_option, explanation, added_by)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (unique_id, question, json.dumps(options, ensure_ascii=False), correct_option, explanation or "", added_by),
        )
        await db.commit()


async def get_quiz(unique_id: str) -> dict | None:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT question, options, correct_option, explanation FROM quizzes WHERE unique_id = ?",
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
            "SELECT unique_id, question, added_at FROM quizzes WHERE added_by = ? ORDER BY added_at DESC",
            (added_by,),
        ) as cur:
            return await cur.fetchall()


async def delete_quiz(unique_id: str) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM quizzes WHERE unique_id = ?", (unique_id,))
        await db.commit()


async def get_quizzes_count() -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT COUNT(*) FROM quizzes") as cur:
            row = await cur.fetchone()
    return row[0] if row else 0


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
        async with db.execute("SELECT token, admin_id, username FROM bots") as cur:
            return await cur.fetchall()  # type: ignore[return-value]


async def get_bots_count() -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT COUNT(*) FROM bots") as cur:
            row = await cur.fetchone()
    return row[0] if row else 0


# ---------------------------------------------------------------------------
# Database — channels
# ---------------------------------------------------------------------------

async def get_channels() -> list[str]:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT channel_id FROM channels ORDER BY added_at ASC") as cur:
            rows = await cur.fetchall()
    return [row[0] for row in rows]


async def get_channels_full() -> list[dict]:
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
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                "INSERT INTO channels (channel_id, added_by, invite_link, is_private) VALUES (?, ?, ?, ?)",
                (channel_id, added_by, invite_link, int(is_private)),
            )
            await db.commit()
        return True
    except Exception:
        return False


async def update_channel_invite_link(channel_id: str, invite_link: str) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE channels SET invite_link = ? WHERE channel_id = ?",
            (invite_link, channel_id),
        )
        await db.commit()


async def remove_channel_db(channel_id: str) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("DELETE FROM channels WHERE channel_id = ?", (channel_id,))
        await db.commit()
        return cur.rowcount > 0


# ---------------------------------------------------------------------------
# Database — users (NEW)
# ---------------------------------------------------------------------------

async def track_user(
    user_id: int,
    first_name: str,
    last_name: str | None,
    username: str | None,
) -> None:
    """Upsert user record. Never overwrites is_banned."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            INSERT INTO users (user_id, first_name, last_name, username)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                first_name = excluded.first_name,
                last_name  = excluded.last_name,
                username   = excluded.username
            """,
            (user_id, first_name or "", last_name or "", username or ""),
        )
        await db.commit()


async def is_banned_user(user_id: int) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT is_banned FROM users WHERE user_id = ?", (user_id,)
        ) as cur:
            row = await cur.fetchone()
    return bool(row and row[0])


async def ban_user(user_id: int) -> bool:
    """Returns False if user not found in DB."""
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "UPDATE users SET is_banned = 1 WHERE user_id = ?", (user_id,)
        )
        await db.commit()
        return cur.rowcount > 0


async def unban_user(user_id: int) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "UPDATE users SET is_banned = 0 WHERE user_id = ?", (user_id,)
        )
        await db.commit()
        return cur.rowcount > 0


async def get_all_user_ids() -> list[int]:
    """Return non-banned user IDs for broadcast."""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT user_id FROM users WHERE is_banned = 0"
        ) as cur:
            rows = await cur.fetchall()
    return [r[0] for r in rows]


async def get_user_count() -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT COUNT(*) FROM users WHERE is_banned = 0") as cur:
            row = await cur.fetchone()
    return row[0] if row else 0


async def get_banned_count() -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT COUNT(*) FROM users WHERE is_banned = 1") as cur:
            row = await cur.fetchone()
    return row[0] if row else 0


# ---------------------------------------------------------------------------
# Database — settings (NEW)
# ---------------------------------------------------------------------------

async def get_setting(bot_token: str, key: str, default: str = "") -> str:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT value FROM settings WHERE bot_token = ? AND key = ?",
            (bot_token, key),
        ) as cur:
            row = await cur.fetchone()
    return row[0] if row else default


async def set_setting(bot_token: str, key: str, value: str) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            INSERT INTO settings (bot_token, key, value)
            VALUES (?, ?, ?)
            ON CONFLICT(bot_token, key) DO UPDATE SET value = excluded.value
            """,
            (bot_token, key, value),
        )
        await db.commit()


async def load_settings() -> None:
    """Load all persisted settings into PROTECT_OVERRIDE and TTL_OVERRIDE on startup."""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT bot_token, key, value FROM settings") as cur:
            rows = await cur.fetchall()
    for token, key, value in rows:
        if key == "ttl":
            try:
                TTL_OVERRIDE[token] = int(value)
            except ValueError:
                pass
        elif key == "protect_content":
            PROTECT_OVERRIDE[token] = value == "1"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def is_admin(user_id: int, bot_token: str | None = None) -> bool:
    if bot_token and bot_token in BOT_ADMIN_MAP:
        return user_id in BOT_ADMIN_MAP[bot_token]
    return user_id in MASTER_ADMIN_IDS


def _token(context: ContextTypes.DEFAULT_TYPE) -> str | None:
    try:
        return context.bot.token
    except Exception:
        return None


def _get_protect(bot_token: str | None) -> bool:
    """Runtime PROTECT_CONTENT for a given bot token."""
    if bot_token and bot_token in PROTECT_OVERRIDE:
        return PROTECT_OVERRIDE[bot_token]
    return PROTECT_CONTENT


def _get_ttl(bot_token: str | None) -> int:
    """Runtime TTL in seconds for a given bot token."""
    if bot_token and bot_token in TTL_OVERRIDE:
        return TTL_OVERRIDE[bot_token]
    return CONTENT_TTL_SECONDS


def protect_for_user(user_id: int, bot_token: str | None = None) -> bool:
    return _get_protect(bot_token) and not is_admin(user_id, bot_token)


def display_name(user) -> str:
    name = " ".join(part for part in (user.first_name, user.last_name) if part).strip()
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
            logger.warning("Membership check failed for %s user %s: %s", channel, user_id, exc)
            not_joined.append(channel)
    return not_joined


async def join_keyboard(bot, not_joined: list[str], payload: str = "") -> InlineKeyboardMarkup:
    all_full = {ch["channel_id"]: ch for ch in await get_channels_full()}
    buttons = []
    for index, channel in enumerate(not_joined, start=1):
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
            ch_url = stored_link
            if not ch_url:
                try:
                    inv = await bot.create_chat_invite_link(channel)
                    ch_url = inv.invite_link
                    await update_channel_invite_link(channel, ch_url)
                except TelegramError:
                    ch_url = None
            if ch_url:
                buttons.append([InlineKeyboardButton(f"🔒 {index}. {channel_label}  →  Join", url=ch_url)])
            else:
                buttons.append([InlineKeyboardButton(f"🔒 {index}. {channel_label}  (invite required)", callback_data="noop")])
        else:
            if channel.startswith("@"):
                ch_url = f"https://t.me/{channel.lstrip('@')}"
            else:
                ch_url = f"https://t.me/c/{str(channel).lstrip('-').lstrip('100')}"
            buttons.append([InlineKeyboardButton(f"📢 {index}. {channel_label}  →  Join", url=ch_url)])

    check_data = f"verify|{payload}" if payload else "verify|"
    buttons.append([InlineKeyboardButton("✅ Maine Join Kar Liya — Check Karo", callback_data=check_data)])
    return InlineKeyboardMarkup(buttons)


async def get_bot_username(bot) -> str:
    me = await bot.get_me()
    return me.username or ""


async def delete_message_later(bot, chat_id: int, message_id: int, ttl: int) -> None:
    await asyncio.sleep(ttl)
    try:
        await bot.delete_message(chat_id=chat_id, message_id=message_id)
    except TelegramError as exc:
        logger.info("Message %s/%s could not be deleted after expiry: %s", chat_id, message_id, exc)


def schedule_delete(
    application: Application,
    sent_message: Message | None,
    ttl: int | None = None,
) -> None:
    if sent_message is None:
        return
    effective_ttl = ttl if ttl is not None else CONTENT_TTL_SECONDS
    application.create_task(
        delete_message_later(application.bot, sent_message.chat_id, sent_message.message_id, effective_ttl)
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
    ttl: int | None = None,
) -> None:
    if unique_id.startswith("q_"):
        await deliver_quiz(message, bot, unique_id, application, protected, edit, ttl)
    else:
        await deliver_file_content(message, bot, unique_id, application, protected, edit, ttl)


async def deliver_file_content(
    message: Message,
    bot,
    unique_id: str,
    application: Application,
    protected: bool,
    edit: bool = False,
    ttl: int | None = None,
) -> None:
    record = await get_file(unique_id)
    if not record:
        text = "❌ Yeh file exist nahi karti ya delete ho gayi hai."
        if edit:
            await message.edit_text(text)
        else:
            sent = await message.reply_text(text, protect_content=protected)
            schedule_delete(application, sent, ttl)
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
        schedule_delete(application, sent, ttl)
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
    ttl: int | None = None,
) -> None:
    record = await get_quiz(unique_id)
    if not record:
        text = "❌ Yeh quiz exist nahi karta ya delete ho gaya hai."
        if edit:
            await message.edit_text(text)
        else:
            sent = await message.reply_text(text, protect_content=protected)
            schedule_delete(application, sent, ttl)
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
        schedule_delete(application, sent, ttl)
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
    ttl = _get_ttl(tok)

    # Track user (non-blocking — runs before ban check so banned users are at least recorded)
    await track_user(user.id, user.first_name or "", user.last_name, user.username)

    # Ban check
    if await is_banned_user(user.id):
        await update.message.reply_text(
            "🚫 Aap ban hain. Admin se contact karein.",
            protect_content=_get_protect(tok),
        )
        return

    not_joined = await check_joined(context.bot, user.id)

    if not_joined:
        total = len(await get_channels())
        remaining = len(not_joined)

        # Custom welcome message
        welcome = await get_setting(tok or "", "welcome_msg", "")
        if not welcome:
            welcome = (
                f"👋 <b>Swagat hai, {display_name(user)}!</b>\n\n"
                f"🔒 Content unlock karne ke liye <b>{remaining}/{total} channel"
                f"{'s' if remaining != 1 else ''}</b> abhi bhi join karne baaki hain.\n\n"
                "Neeche ke buttons se join karo, phir\n"
                "<b>✅ Maine Join Kar Liya</b> dabao."
            )
        else:
            welcome = welcome.replace("{name}", display_name(user)) \
                             .replace("{remaining}", str(remaining)) \
                             .replace("{total}", str(total))

        await update.message.reply_html(
            welcome,
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
            ttl=ttl,
        )
    else:
        await update.message.reply_html(
            f"✅ <b>{display_name(user)}</b>, aap sab channels mein hain!\n\n"
            "🎉 Admin se file ya quiz ka link maango aur click karo — "
            "content seedha aa jaayega.",
            protect_content=protect_for_user(user.id, tok),
        )


async def verify_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query or not query.message:
        return

    tok = _token(context)
    user = query.from_user
    payload = query.data.split("|", 1)[1] if "|" in query.data else ""
    ttl = _get_ttl(tok)

    # Ban check on verify too
    if await is_banned_user(user.id):
        await query.answer("🚫 Aap ban hain.", show_alert=True)
        return

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
            ttl=ttl,
        )
        schedule_delete(context.application, query.message, ttl)
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


async def handle_admin_quiz(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
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
    await save_quiz(unique_id, poll.question, options, correct, explanation, update.effective_user.id)

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


async def handle_admin_file(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
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


# ---------------------------------------------------------------------------
# Handler — /stats  (NEW)
# ---------------------------------------------------------------------------

async def stats_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.effective_user:
        return
    tok = _token(context)
    if not is_admin(update.effective_user.id, tok):
        await update.message.reply_text("❌ Sirf admin ke liye hai.")
        return

    users   = await get_user_count()
    banned  = await get_banned_count()
    files   = await get_files_count()
    quizzes = await get_quizzes_count()
    channels = len(await get_channels())
    bots    = await get_bots_count()
    ttl_now = _get_ttl(tok)
    protect_now = _get_protect(tok)

    await update.message.reply_html(
        "╔══════════════════════╗\n"
        "║  📊  <b>Bot Stats</b>          ║\n"
        "╚══════════════════════╝\n\n"
        f"👥 <b>Users:</b> {users}  |  🚫 Banned: {banned}\n"
        f"📁 <b>Files:</b> {files}  |  ❓ Quizzes: {quizzes}\n"
        f"📢 <b>Channels:</b> {channels}  |  🤖 Bots: {bots}\n\n"
        f"⏳ <b>Auto-delete TTL:</b> {ttl_now}s ({ttl_now // 60}m {ttl_now % 60}s)\n"
        f"🔒 <b>Protect Content:</b> {'✅ ON' if protect_now else '❌ OFF'}",
        protect_content=protect_for_user(update.effective_user.id, tok),
    )


# ---------------------------------------------------------------------------
# Handler — /broadcast  (NEW)
# ---------------------------------------------------------------------------

async def _safe_send_one(bot, user_id: int, reply_msg: Message | None, text: str | None) -> bool:
    """
    Send one broadcast message. Returns True on success, False on permanent failure.
    Handles RetryAfter by sleeping and retrying once.
    """
    async def _do_send():
        if reply_msg:
            await bot.copy_message(
                chat_id=user_id,
                from_chat_id=reply_msg.chat_id,
                message_id=reply_msg.message_id,
            )
        else:
            await bot.send_message(chat_id=user_id, text=text)

    try:
        await _do_send()
        return True
    except RetryAfter as e:
        await asyncio.sleep(e.retry_after + 1)
        try:
            await _do_send()
            return True
        except TelegramError:
            return False
    except TelegramError:
        return False


async def broadcast_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /broadcast <text>
    OR reply to any message and send /broadcast

    Sends to all non-banned users. Rate-limited at 25 msg/sec.
    """
    if not update.message or not update.effective_user:
        return
    tok = _token(context)
    if not is_admin(update.effective_user.id, tok):
        await update.message.reply_text("❌ Sirf admin ke liye hai.")
        return

    # Determine what to send
    reply_msg: Message | None = update.message.reply_to_message
    text_msg: str | None = " ".join(context.args).strip() if context.args else None

    if not reply_msg and not text_msg:
        await update.message.reply_html(
            "📣 <b>Broadcast Usage:</b>\n\n"
            "Text broadcast:\n"
            "  <code>/broadcast Yeh message sab ko jaayega</code>\n\n"
            "Media broadcast (kisi bhi message ko reply karke):\n"
            "  <code>/broadcast</code>  ← reply to a photo/video/document/text\n\n"
            "<i>Sabhi non-banned users ko jaayega. Rate: 25 msg/sec.</i>"
        )
        return

    user_ids = await get_all_user_ids()
    total = len(user_ids)

    if total == 0:
        await update.message.reply_text("👥 Koi user nahi mila.")
        return

    status_msg = await update.message.reply_html(
        f"📣 <b>Broadcast shuru ho raha hai...</b>\n"
        f"👥 Target users: <b>{total}</b>"
    )

    sent = 0
    failed = 0

    for i, uid in enumerate(user_ids):
        success = await _safe_send_one(context.bot, uid, reply_msg, text_msg)
        if success:
            sent += 1
        else:
            failed += 1

        # Update progress every 50 users
        if (i + 1) % 50 == 0 or (i + 1) == total:
            try:
                await status_msg.edit_text(
                    f"📣 <b>Broadcasting...</b>\n"
                    f"✅ Sent: {sent}  |  ❌ Failed: {failed}  |  📊 Total: {total}",
                    parse_mode="HTML",
                )
            except TelegramError:
                pass

        await asyncio.sleep(_BROADCAST_DELAY)

    await status_msg.edit_text(
        f"✅ <b>Broadcast Complete!</b>\n\n"
        f"📤 Sent: <b>{sent}</b>\n"
        f"❌ Failed: <b>{failed}</b>\n"
        f"👥 Total: <b>{total}</b>",
        parse_mode="HTML",
    )


# ---------------------------------------------------------------------------
# Handler — /setwelcome  (NEW)
# ---------------------------------------------------------------------------

async def setwelcome_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /setwelcome <message>

    Custom welcome message jab user join nahi kiya hota.
    Placeholders: {name} {remaining} {total}
    """
    if not update.message or not update.effective_user:
        return
    tok = _token(context)
    if not is_admin(update.effective_user.id, tok):
        await update.message.reply_text("❌ Sirf admin ke liye hai.")
        return

    text = " ".join(context.args).strip() if context.args else ""

    if not text:
        current = await get_setting(tok or "", "welcome_msg", "")
        await update.message.reply_html(
            "👋 <b>Welcome Message Settings</b>\n\n"
            "<b>Usage:</b>\n"
            "<code>/setwelcome Tumhara message yahan</code>\n\n"
            "<b>Placeholders:</b>\n"
            "  <code>{name}</code> — user ka naam\n"
            "  <code>{remaining}</code> — baaki channels count\n"
            "  <code>{total}</code> — total channels count\n\n"
            f"<b>Current:</b>\n{html.escape(current) if current else '<i>(default)</i>'}\n\n"
            "Reset ke liye:\n<code>/setwelcome reset</code>"
        )
        return

    if text.lower() == "reset":
        await set_setting(tok or "", "welcome_msg", "")
        await update.message.reply_text("✅ Welcome message reset ho gaya (default chalega).")
        return

    await set_setting(tok or "", "welcome_msg", text)
    await update.message.reply_html(
        f"✅ <b>Welcome message set ho gaya!</b>\n\n"
        f"<b>Preview:</b>\n{html.escape(text)}\n\n"
        "<i>Naya welcome message ab se active hai.</i>"
    )


# ---------------------------------------------------------------------------
# Handler — /toggleprotect  (NEW)
# ---------------------------------------------------------------------------

async def toggleprotect_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /toggleprotect
    Flip PROTECT_CONTENT on/off at runtime for this bot.
    """
    if not update.message or not update.effective_user:
        return
    tok = _token(context)
    if not is_admin(update.effective_user.id, tok):
        await update.message.reply_text("❌ Sirf admin ke liye hai.")
        return

    current = _get_protect(tok)
    new_val = not current

    # Persist
    PROTECT_OVERRIDE[tok or ""] = new_val
    await set_setting(tok or "", "protect_content", "1" if new_val else "0")

    state = "✅ ON" if new_val else "❌ OFF"
    await update.message.reply_html(
        f"🔒 <b>Protect Content</b> ab <b>{state}</b> hai.\n\n"
        "<i>Ab se deliver hone wala content "
        f"{'protect hoga (forward/save band).' if new_val else 'protect nahi hoga (forward/save allow).'}</i>"
    )


# ---------------------------------------------------------------------------
# Handler — /setttl  (NEW)
# ---------------------------------------------------------------------------

async def setttl_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /setttl <seconds>
    Change auto-delete timer. Min: 30s. Max: 86400s (24h).
    """
    if not update.message or not update.effective_user:
        return
    tok = _token(context)
    if not is_admin(update.effective_user.id, tok):
        await update.message.reply_text("❌ Sirf admin ke liye hai.")
        return

    if not context.args:
        current = _get_ttl(tok)
        await update.message.reply_html(
            "⏳ <b>Auto-Delete Timer</b>\n\n"
            "<b>Usage:</b> <code>/setttl &lt;seconds&gt;</code>\n\n"
            f"<b>Current TTL:</b> {current}s ({current // 60}m {current % 60}s)\n\n"
            "<b>Examples:</b>\n"
            "  <code>/setttl 60</code>   — 1 minute\n"
            "  <code>/setttl 300</code>  — 5 minutes (default)\n"
            "  <code>/setttl 3600</code> — 1 hour\n\n"
            "<i>Range: 30s – 86400s (24h)</i>"
        )
        return

    try:
        new_ttl = int(context.args[0])
    except ValueError:
        await update.message.reply_text("❌ Valid number do. Example: /setttl 300")
        return

    if new_ttl < 30:
        await update.message.reply_text("❌ Minimum 30 seconds hona chahiye.")
        return
    if new_ttl > 86400:
        await update.message.reply_text("❌ Maximum 86400 seconds (24 ghante) hai.")
        return

    TTL_OVERRIDE[tok or ""] = new_ttl
    await set_setting(tok or "", "ttl", str(new_ttl))

    await update.message.reply_html(
        f"⏳ <b>Auto-delete TTL set ho gaya!</b>\n\n"
        f"⏱️ <b>New TTL:</b> {new_ttl}s ({new_ttl // 60}m {new_ttl % 60}s)\n\n"
        "<i>Ab se deliver hone wale content itne time baad delete honge.</i>"
    )


# ---------------------------------------------------------------------------
# Handler — /refreshlink  (NEW)
# ---------------------------------------------------------------------------

async def refreshlink_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /refreshlink @channel  OR  /refreshlink -100xxxxxxxxxx
    Regenerate invite link for a private channel.
    """
    if not update.message or not update.effective_user:
        return
    tok = _token(context)
    if not is_admin(update.effective_user.id, tok):
        await update.message.reply_text("❌ Sirf admin ke liye hai.")
        return

    if not context.args:
        await update.message.reply_html(
            "🔗 <b>Invite Link Refresh</b>\n\n"
            "<b>Usage:</b>\n"
            "  <code>/refreshlink @channel</code>\n"
            "  <code>/refreshlink -100xxxxxxxxxx</code>\n\n"
            "<i>Sirf private channels ke liye kaam karta hai.</i>"
        )
        return

    raw = context.args[0].strip()
    if not raw.startswith("@") and not raw.lstrip("-").isdigit():
        raw = "@" + raw

    processing = await update.message.reply_text("🔄 Link regenerate ho raha hai...")

    try:
        inv = await context.bot.create_chat_invite_link(
            raw,
            name="Force-Sub Refreshed",
            creates_join_request=True,
        )
        new_link = inv.invite_link
        await update_channel_invite_link(raw, new_link)
        await processing.edit_text(
            f"✅ <b>Invite link refresh ho gaya!</b>\n\n"
            f"📢 <b>Channel:</b> <code>{html.escape(raw)}</code>\n"
            f"🔗 <b>New Link:</b> <code>{html.escape(new_link)}</code>",
            parse_mode="HTML",
        )
    except TelegramError as exc:
        await processing.edit_text(
            f"❌ Link generate nahi hua:\n<code>{html.escape(str(exc))}</code>\n\n"
            "Bot ko us channel ka admin (Invite Users permission) hona chahiye.",
            parse_mode="HTML",
        )


# ---------------------------------------------------------------------------
# Handlers — /ban  /unban  (NEW)
# ---------------------------------------------------------------------------

async def ban_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /ban <user_id>
    Block a user. They get a refusal message on /start.
    """
    if not update.message or not update.effective_user:
        return
    tok = _token(context)
    if not is_admin(update.effective_user.id, tok):
        await update.message.reply_text("❌ Sirf admin ke liye hai.")
        return

    if not context.args:
        await update.message.reply_html(
            "🚫 <b>Usage:</b> <code>/ban &lt;user_id&gt;</code>\n\n"
            "<i>User ID /stats ya forward karke milta hai.</i>"
        )
        return

    try:
        target_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("❌ Valid user ID do (numbers only).")
        return

    if target_id in MASTER_ADMIN_IDS:
        await update.message.reply_text("❌ Master admin ko ban nahi kar sakte.")
        return

    found = await ban_user(target_id)
    if found:
        await update.message.reply_html(
            f"🚫 <b>User ban ho gaya!</b>\n\n"
            f"🆔 <b>User ID:</b> <code>{target_id}</code>\n"
            "<i>Ab woh bot ka content access nahi kar sakta.</i>"
        )
    else:
        # User not in DB yet — insert them as banned directly
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                "INSERT OR IGNORE INTO users (user_id, first_name, is_banned) VALUES (?, ?, 1)",
                (target_id, f"User_{target_id}"),
            )
            await db.execute(
                "UPDATE users SET is_banned = 1 WHERE user_id = ?",
                (target_id,),
            )
            await db.commit()
        await update.message.reply_html(
            f"🚫 <b>User ban ho gaya!</b>\n\n"
            f"🆔 <b>User ID:</b> <code>{target_id}</code>\n"
            "<i>(User pehle bot use nahi kiya tha, phir bhi ban add ho gaya.)</i>"
        )


async def unban_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /unban <user_id>
    """
    if not update.message or not update.effective_user:
        return
    tok = _token(context)
    if not is_admin(update.effective_user.id, tok):
        await update.message.reply_text("❌ Sirf admin ke liye hai.")
        return

    if not context.args:
        await update.message.reply_html(
            "✅ <b>Usage:</b> <code>/unban &lt;user_id&gt;</code>"
        )
        return

    try:
        target_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("❌ Valid user ID do (numbers only).")
        return

    found = await unban_user(target_id)
    if found:
        await update.message.reply_html(
            f"✅ <b>User unban ho gaya!</b>\n\n"
            f"🆔 <b>User ID:</b> <code>{target_id}</code>\n"
            "<i>Ab woh bot fir se use kar sakta hai.</i>"
        )
    else:
        await update.message.reply_html(
            f"⚠️ User <code>{target_id}</code> DB mein nahi mila.\n"
            "<i>Woh pehle se ban nahi tha ya kabhi bot use nahi kiya.</i>"
        )


# ---------------------------------------------------------------------------
# Handler — /search  (NEW)
# ---------------------------------------------------------------------------

async def search_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /search <query>
    Search your saved files by caption.
    """
    if not update.message or not update.effective_user:
        return
    tok = _token(context)
    if not is_admin(update.effective_user.id, tok):
        await update.message.reply_text("❌ Sirf admin ke liye hai.")
        return

    query = " ".join(context.args).strip() if context.args else ""
    if not query:
        await update.message.reply_html(
            "🔍 <b>Usage:</b> <code>/search &lt;query&gt;</code>\n\n"
            "<i>Aapki saved files ke captions mein search karta hai.</i>"
        )
        return

    rows = await search_files_db(query, update.effective_user.id)

    if not rows:
        await update.message.reply_html(
            f"🔍 <b>'{html.escape(query)}'</b> ke liye koi file nahi mili."
        )
        return

    bot_username = await get_bot_username(context.bot)
    lines = [f"🔍 <b>Search Results for '{html.escape(query)}' ({len(rows)} mili):</b>\n"]
    for unique_id, file_type, caption, _ in rows:
        link = f"https://t.me/{bot_username}?start={unique_id}"
        title = (caption[:40] + "…" if caption and len(caption) > 40 else caption) or "—"
        lines.append(
            f"\n• <b>{file_type}</b> | <code>{unique_id}</code>\n"
            f"  📝 {html.escape(title)}\n  🔗 <code>{link}</code>"
        )

    await update.message.reply_html(
        "\n".join(lines),
        disable_web_page_preview=True,
        protect_content=protect_for_user(update.effective_user.id, tok),
    )


# ---------------------------------------------------------------------------
# Handler — /setcaption  (NEW)
# ---------------------------------------------------------------------------

async def setcaption_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /setcaption <unique_id> <new caption text>
    Update a saved file's caption.
    """
    if not update.message or not update.effective_user:
        return
    tok = _token(context)
    if not is_admin(update.effective_user.id, tok):
        await update.message.reply_text("❌ Sirf admin ke liye hai.")
        return

    if not context.args or len(context.args) < 2:
        await update.message.reply_html(
            "📝 <b>Usage:</b>\n"
            "<code>/setcaption &lt;file_id&gt; &lt;new caption&gt;</code>\n\n"
            "<i>File ID /myfiles se dekho.</i>"
        )
        return

    unique_id = context.args[0]
    new_caption = " ".join(context.args[1:]).strip()

    updated = await update_file_caption(unique_id, new_caption, update.effective_user.id)

    if updated:
        await update.message.reply_html(
            f"✅ <b>Caption update ho gaya!</b>\n\n"
            f"🆔 <b>File:</b> <code>{html.escape(unique_id)}</code>\n"
            f"📝 <b>New Caption:</b> {html.escape(new_caption)}"
        )
    else:
        await update.message.reply_html(
            f"❌ File <code>{html.escape(unique_id)}</code> nahi mili ya aapki nahi hai.\n"
            "<i>/myfiles se correct ID dekho.</i>"
        )


# ---------------------------------------------------------------------------
# Handler — /help
# ---------------------------------------------------------------------------

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.effective_user:
        return
    tok = _token(context)

    if is_admin(update.effective_user.id, tok):
        is_master = update.effective_user.id in MASTER_ADMIN_IDS
        ttl_now = _get_ttl(tok)
        protect_now = _get_protect(tok)

        channel_section = ""
        if is_master:
            channel_section = (
                "\n\n<b>📢 Channel Management:</b>\n"
                "/addchannel <code>@handle</code> — force-sub list mein channel add karo\n"
                "/removechannel <code>@handle</code> — channel hatao\n"
                "/listchannels — abhi ke saare channels dekho\n"
                "/refreshlink <code>@ch</code> — private channel ka invite link regenerate karo\n"
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
            "║  🤖  <b>Admin Panel v2</b>     ║\n"
            "╚══════════════════════╝\n\n"
            "<b>📤 Content Upload:</b>\n"
            "• File / Photo / Video bhejo → protected link milega\n"
            "• Quiz poll bhejo (Quiz Mode on karke) → quiz link milega\n"
            "/addmsg <code>&lt;text&gt;</code> — text message ka link banao\n\n"
            "<b>📂 Content Management:</b>\n"
            "/myfiles — saari saved files dekho\n"
            "/myquizzes — saare quizzes dekho\n"
            "/delete <code>&lt;id&gt;</code> — file ya quiz delete karo\n"
            "/search <code>&lt;query&gt;</code> — files caption mein search karo\n"
            "/setcaption <code>&lt;id&gt; &lt;text&gt;</code> — file ka caption update karo\n\n"
            "<b>📣 Broadcast:</b>\n"
            "/broadcast <code>&lt;text&gt;</code> — sabhi users ko message bhejo\n"
            "/broadcast <i>(reply to media)</i> — media broadcast karo\n\n"
            "<b>👥 User Management:</b>\n"
            "/stats — bot stats dekho\n"
            "/ban <code>&lt;user_id&gt;</code> — user block karo\n"
            "/unban <code>&lt;user_id&gt;</code> — user unblock karo\n\n"
            "<b>⚙️ Settings:</b>\n"
            f"/toggleprotect — protect content [now: {'✅ ON' if protect_now else '❌ OFF'}]\n"
            f"/setttl <code>&lt;seconds&gt;</code> — auto-delete timer [now: {ttl_now}s]\n"
            "/setwelcome <code>&lt;text&gt;</code> — custom welcome message set karo"
            f"{channel_section}"
            f"{addbot_section}"
            "\n/help — yeh message\n\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            "<i>🔒 Users ko content milne se pehle saare channels join karne honge.</i>"
        )
    else:
        channels = await get_channels()
        ch_count = len(channels)
        ttl_now = _get_ttl(tok)
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
            f"⏳ <i>Content {ttl_now // 60}m {ttl_now % 60}s baad automatically delete ho jaata hai.</i>"
        )

    await update.message.reply_html(
        text,
        protect_content=protect_for_user(update.effective_user.id, tok),
    )


# ---------------------------------------------------------------------------
# Handlers — /addchannel  /removechannel  /listchannels  (master admin only)
# ---------------------------------------------------------------------------

async def addchannel_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
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
        channel_id = f"@{chat.username}" if chat.username else str(chat.id)
        is_private = not chat.username
    except TelegramError as exc:
        await checking_msg.edit_text(
            f"❌ Channel access nahi hua:\n<code>{html.escape(str(exc))}</code>\n\n"
            "Make sure bot is already an admin in that channel.",
            parse_mode="HTML",
        )
        return

    invite_link: str | None = None
    if is_private:
        await checking_msg.edit_text(
            "🔗 Private channel detect hua — invite link generate ho raha hai..."
        )
        try:
            inv = await context.bot.create_chat_invite_link(
                chat.id,
                name="Force-Sub Link",
                creates_join_request=True,
            )
            invite_link = inv.invite_link
        except TelegramError as exc:
            await checking_msg.edit_text(
                f"⚠️ Channel add ho sakta hai lekin invite link generate nahi hua:\n"
                f"<code>{html.escape(str(exc))}</code>\n\n"
                "Bot ko <b>Invite Users</b> permission do, phir /addchannel dobara karo.",
                parse_mode="HTML",
            )
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
    if not update.message or not update.effective_user:
        return
    if update.effective_user.id not in MASTER_ADMIN_IDS:
        await update.message.reply_text("❌ Sirf master admin ke liye hai.")
        return

    channels = await get_channels()

    if not context.args:
        if not channels:
            await update.message.reply_html(
                "📋 Abhi koi channel list mein nahi hai.\n\n/addchannel se channel add karo."
            )
            return
        buttons = [
            [InlineKeyboardButton(f"🗑️ {ch}", callback_data=f"rmch|{ch}")]
            for ch in channels
        ]
        buttons.append([InlineKeyboardButton("❌ Cancel", callback_data="rmch_cancel")])
        await update.message.reply_html(
            "📋 <b>Kaunsa channel hatana hai?</b>\n\nNeeche se select karo:",
            reply_markup=InlineKeyboardMarkup(buttons),
        )
        return

    raw = context.args[0].strip()
    if not raw.startswith("@") and not raw.lstrip("-").isdigit():
        raw = "@" + raw

    removed = await remove_channel_db(raw)
    if not removed:
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


async def removechannel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
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
    if not update.message or not update.effective_user:
        return
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
        await validating_msg.edit_text(f"❌ Invalid token ya Telegram error:\n{str(exc)}")
        return

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


async def addbot_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
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
        await query.edit_message_text("❌ Session expire ho gaya. /addbot dobara run karo.")
        return

    new_token: str = data["token"]
    admin_id: int = data["admin_id"]
    bot_username: str = data["username"]

    await query.edit_message_text(f"⚙️ @{bot_username} start ho raha hai...")

    if new_token in RUNNING_APPS:
        await query.edit_message_text(f"⚠️ @{bot_username} pehle se chal raha hai.")
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
        await query.edit_message_text(f"❌ Bot start nahi hua:\n{html.escape(str(exc))}")


# ---------------------------------------------------------------------------
# Handler — auto-approve join requests for private channels
# ---------------------------------------------------------------------------

async def approve_join_request(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    join_req = update.chat_join_request
    if not join_req:
        return

    channel_ids = await get_channels()
    chat_id = join_req.chat.id
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
        logger.info("Auto-approved join request: user %s in chat %s", join_req.from_user.id, chat_id)
    except TelegramError as exc:
        logger.warning(
            "Could not approve join request for user %s in %s: %s",
            join_req.from_user.id, chat_id, exc,
        )


# ---------------------------------------------------------------------------
# Bot spawning
# ---------------------------------------------------------------------------

def _build_application(token: str) -> Application:
    app = Application.builder().token(token).build()

    # Original handlers
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

    # NEW handlers
    app.add_handler(CommandHandler("stats", stats_cmd))
    app.add_handler(CommandHandler("broadcast", broadcast_cmd))
    app.add_handler(CommandHandler("setwelcome", setwelcome_cmd))
    app.add_handler(CommandHandler("toggleprotect", toggleprotect_cmd))
    app.add_handler(CommandHandler("setttl", setttl_cmd))
    app.add_handler(CommandHandler("refreshlink", refreshlink_cmd))
    app.add_handler(CommandHandler("ban", ban_cmd))
    app.add_handler(CommandHandler("unban", unban_cmd))
    app.add_handler(CommandHandler("search", search_cmd))
    app.add_handler(CommandHandler("setcaption", setcaption_cmd))

    # Callbacks
    app.add_handler(CallbackQueryHandler(verify_callback, pattern=r"^verify\|"))
    app.add_handler(CallbackQueryHandler(addbot_callback, pattern=r"^addbot_"))
    app.add_handler(CallbackQueryHandler(removechannel_callback, pattern=r"^rmch"))

    # Join request auto-approve
    app.add_handler(ChatJoinRequestHandler(approve_join_request))

    # Media handlers (admin)
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
    await init_db()
    logger.info("Database initialized.")

    # Load persisted settings into memory
    await load_settings()
    logger.info("Settings loaded.")

    # Restore saved bot clones
    saved_bots = await get_all_bot_records()
    for token, admin_id, username in saved_bots:
        if token == BOT_TOKEN:
            continue
        try:
            logger.info("Restoring bot @%s ...", username)
            await _spawn_bot(token, admin_id)
        except Exception as exc:
            logger.error("Could not restore @%s: %s", username, exc)

    # Start main bot
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
        await asyncio.Event().wait()
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
