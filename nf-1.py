#!/usr/bin/env python3
"""
Force Subscribe Telegram Bot — protected delivery version.

Features:
- Admin can save text, media, and quizzes and receive a private link.
- Users must join the configured channels before receiving content.
- User-facing name uses first/last name only; usernames are never displayed.
- Bot-delivered content is protected from Telegram forwarding/saving where supported.
- Delivered content is deleted automatically after five minutes.

Install:
    pip install "python-telegram-bot==21.5" aiosqlite==0.19.0

Run:
    python3 forcebot_1784778309613.py

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
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    Update,
)
from telegram.error import TelegramError
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# Local hosting ke liye chahein to neeche placeholder ki jagah NEW token paste
# kar sakte hain. Public code/repository mein token commit na karein.
BOT_TOKEN = os.environ.get(
    "TELEGRAM_BOT_TOKEN",
    "8601021110:AAHz2RfA--5YgurH51TvJnGWikKwsA8q-D8",
).strip()
ADMIN_IDS = [8502412097]
CHANNELS = ["@umhhhhhhhh", "@sodohuyall0", "@godtonyhun"]

# Telegram's protected-content flag prevents forwarding/saving in supported
# Telegram clients. The Bot API cannot guarantee screenshot blocking.
PROTECT_CONTENT = True
CONTENT_TTL_SECONDS = 5 * 60
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "files.db")


logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Database
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
            """
            SELECT file_id, file_type, caption
            FROM files
            WHERE unique_id = ?
            """,
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
            FROM files
            WHERE added_by = ?
            ORDER BY added_at DESC
            """,
            (added_by,),
        ) as cur:
            return await cur.fetchall()


async def delete_file(unique_id: str) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM files WHERE unique_id = ?", (unique_id,))
        await db.commit()


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
            )
            VALUES (?, ?, ?, ?, ?, ?)
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
            FROM quizzes
            WHERE unique_id = ?
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
            FROM quizzes
            WHERE added_by = ?
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
# Helpers
# ---------------------------------------------------------------------------

def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


def protect_for_user(user_id: int) -> bool:
    """Admins receive normal messages; other users receive protected content."""
    return PROTECT_CONTENT and not is_admin(user_id)


def display_name(user) -> str:
    """Return a safe first/last name, never a Telegram username."""
    name = " ".join(
        part for part in (user.first_name, user.last_name) if part
    ).strip()
    return html.escape(name or "User")


async def check_joined(bot, user_id: int) -> list[str]:
    """Return channels that the user still needs to join."""
    not_joined = []
    for channel in CHANNELS:
        try:
            member = await bot.get_chat_member(channel, user_id)
            if member.status in ("left", "kicked", "banned"):
                not_joined.append(channel)
        except TelegramError as exc:
            # A bot without admin/member-read access cannot verify a channel.
            # Log the exact Telegram reason instead of silently hiding it.
            logger.warning(
                "Membership check failed for %s and user %s: %s",
                channel,
                user_id,
                exc,
            )
            not_joined.append(channel)
    return not_joined


async def join_keyboard(
    bot,
    not_joined: list[str],
    payload: str = "",
) -> InlineKeyboardMarkup:
    buttons = []
    for index, channel in enumerate(not_joined, start=1):
        # Keep the @username out of the visible button label. The URL still
        # has to point to the actual channel so the user can join it.
        try:
            chat = await bot.get_chat(channel)
            channel_label = chat.title or f"Channel {index}"
        except TelegramError:
            channel_label = f"Channel {index}"
        buttons.append(
            [
                InlineKeyboardButton(
                    f"➕ {channel_label}",
                    url=f"https://t.me/{channel.lstrip('@')}",
                )
            ]
        )
    check_data = f"verify|{payload}" if payload else "verify|"
    buttons.append(
        [
            InlineKeyboardButton(
                "🔄 Try Again / Verify",
                callback_data=check_data,
            )
        ]
    )
    return InlineKeyboardMarkup(buttons)


async def get_bot_username(bot) -> str:
    me = await bot.get_me()
    return me.username or ""


async def delete_message_later(
    bot,
    chat_id: int,
    message_id: int,
) -> None:
    await asyncio.sleep(CONTENT_TTL_SECONDS)
    try:
        await bot.delete_message(chat_id=chat_id, message_id=message_id)
    except TelegramError as exc:
        # It may already have been deleted or the bot may have lost rights.
        logger.info(
            "Message %s/%s could not be deleted after expiry: %s",
            chat_id,
            message_id,
            exc,
        )


def schedule_delete(
    application: Application,
    sent_message: Message | None,
) -> None:
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
        await deliver_file_content(
            message,
            bot,
            unique_id,
            application,
            protected,
            edit,
        )


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
            sent = await message.reply_text(
                text,
                protect_content=protected,
            )
            schedule_delete(application, sent)
        return

    file_id = record["file_id"]
    file_type = record["file_type"]
    caption = record["caption"] or ""

    if edit:
        await message.edit_text("📥 File bhej raha hoon...")

    send_map = {
        "photo": bot.send_photo,
        "video": bot.send_video,
        "document": bot.send_document,
        "audio": bot.send_audio,
        "voice": bot.send_voice,
        "animation": bot.send_animation,
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
            kwargs = {
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
            sent = await message.reply_text(
                text,
                protect_content=protected,
            )
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
# Handlers
# ---------------------------------------------------------------------------

async def start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    if not update.message or not update.effective_user:
        return

    user = update.effective_user
    payload = context.args[0] if context.args else ""
    not_joined = await check_joined(context.bot, user.id)

    if not_joined:
        await update.message.reply_html(
            f"👋 <b>Swagat hai, {display_name(user)}!</b>\n\n"
            "❗ Is bot ka use karne ke liye pehle "
            "<b>neeche diye channels join karo</b>.\n\n"
            "Join karne ke baad <b>✅ Maine Join Kar Liya</b> button dabao.",
            reply_markup=await join_keyboard(
                context.bot,
                not_joined,
                payload,
            ),
            protect_content=protect_for_user(user.id),
        )
        return

    if payload:
        await deliver_content(
            update.message,
            context.bot,
            payload,
            context.application,
            protected=protect_for_user(user.id),
        )
    else:
        await update.message.reply_html(
            f"✅ <b>{display_name(user)}, aap sab channels mein hain!</b>\n\n"
            "Admin se file/quiz ka link maango aur us link ko click karo.",
            protect_content=protect_for_user(user.id),
        )


async def verify_callback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    query = update.callback_query
    if not query or not query.message:
        return

    user = query.from_user
    payload = query.data.split("|", 1)[1] if "|" in query.data else ""
    not_joined = await check_joined(context.bot, user.id)

    if not_joined:
        await query.answer(
            "❌ Abhi bhi kuch channels join nahi kiye!",
            show_alert=True,
        )
        await query.edit_message_reply_markup(
            reply_markup=await join_keyboard(
                context.bot,
                not_joined,
                payload,
            )
        )
        return

    await query.answer("✅ Verification successful!")
    if payload:
        await deliver_content(
            query.message,
            context.bot,
            payload,
            context.application,
            protected=protect_for_user(user.id),
            edit=True,
        )
        # Remove the verification/status message too, so only the delivered
        # item is visible during the five-minute access window.
        schedule_delete(context.application, query.message)
    else:
        await query.edit_message_text(
            f"✅ <b>{display_name(user)}, verified!</b>\n"
            "Ab aap bot use kar sakte ho. File ka link admin se maango.",
            parse_mode="HTML",
        )


async def add_msg(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    if not update.message or not update.effective_user:
        return
    if not is_admin(update.effective_user.id):
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
            protect_content=protect_for_user(update.effective_user.id),
        )
        return

    unique_id = str(uuid.uuid4())[:12]
    await save_file(
        unique_id,
        text_body,
        "text",
        text_body,
        update.effective_user.id,
    )
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
        protect_content=protect_for_user(update.effective_user.id),
    )


async def handle_admin_quiz(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    if not update.message or not update.effective_user or not update.message.poll:
        return
    if not is_admin(update.effective_user.id):
        return

    poll = update.message.poll
    if poll.type != "quiz":
        await update.message.reply_html(
            "⚠️ Yeh regular poll hai, quiz nahi.\n"
            "Poll banate waqt <b>Quiz Mode</b> on karo aur sahi jawab select karo.",
            protect_content=protect_for_user(update.effective_user.id),
        )
        return

    unique_id = "q_" + str(uuid.uuid4())[:10]
    options = [option.text for option in poll.options]
    correct = poll.correct_option_id
    explanation = poll.explanation or ""
    await save_quiz(
        unique_id,
        poll.question,
        options,
        correct,
        explanation,
        update.effective_user.id,
    )

    bot_username = await get_bot_username(context.bot)
    share_link = f"https://t.me/{bot_username}?start={unique_id}"
    options_text = "\n".join(
        f"  {'✅' if index == correct else '◦'} {option}"
        for index, option in enumerate(options)
    )

    await update.message.reply_html(
        f"✅ <b>Quiz save ho gaya!</b>\n\n"
        f"❓ <b>Question:</b> {html.escape(poll.question)}\n"
        f"<b>Options:</b>\n{html.escape(options_text)}\n\n"
        f"🆔 <b>ID:</b> <code>{unique_id}</code>\n\n"
        f"🔗 <b>Share Link:</b>\n<code>{share_link}</code>\n\n"
        "<i>User pehle channel join karega, phir quiz milega.</i>",
        disable_web_page_preview=True,
        protect_content=protect_for_user(update.effective_user.id),
    )


async def handle_admin_file(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    if not update.message or not update.effective_user:
        return
    if not is_admin(update.effective_user.id):
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

    caption = message.caption or (
        message.text if file_type == "text" else ""
    ) or ""
    await save_file(
        unique_id,
        file_id,
        file_type,
        caption,
        update.effective_user.id,
    )
    bot_username = await get_bot_username(context.bot)
    share_link = f"https://t.me/{bot_username}?start={unique_id}"

    await message.reply_html(
        f"✅ <b>File save ho gayi!</b>\n\n"
        f"📎 <b>Type:</b> {file_type}\n"
        f"🆔 <b>ID:</b> <code>{unique_id}</code>\n\n"
        f"🔗 <b>Share Link:</b>\n<code>{share_link}</code>\n\n"
        "<i>User pehle channel join karega, phir file milegi.</i>",
        disable_web_page_preview=True,
        protect_content=protect_for_user(update.effective_user.id),
    )


async def my_files(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    if not update.message or not update.effective_user:
        return
    if not is_admin(update.effective_user.id):
        await update.message.reply_text(
            "❌ Sirf admin ke liye hai.",
            protect_content=protect_for_user(update.effective_user.id),
        )
        return

    rows = await get_all_files(update.effective_user.id)
    if not rows:
        await update.message.reply_text(
            "📂 Abhi koi file save nahi hai.",
            protect_content=protect_for_user(update.effective_user.id),
        )
        return

    bot_username = await get_bot_username(context.bot)
    lines = [f"📂 <b>Aapki Files ({len(rows)} total):</b>\n"]
    for unique_id, file_type, caption, _ in rows[:20]:
        link = f"https://t.me/{bot_username}?start={unique_id}"
        title = (
            caption[:30] + "…" if caption and len(caption) > 30 else caption
        ) or "—"
        lines.append(
            f"\n• <b>{file_type}</b> | <code>{unique_id}</code>\n"
            f"  📝 {html.escape(title)}\n  🔗 <code>{link}</code>"
        )
    await update.message.reply_html(
        "\n".join(lines),
        disable_web_page_preview=True,
        protect_content=protect_for_user(update.effective_user.id),
    )


async def my_quizzes(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    if not update.message or not update.effective_user:
        return
    if not is_admin(update.effective_user.id):
        await update.message.reply_text(
            "❌ Sirf admin ke liye hai.",
            protect_content=protect_for_user(update.effective_user.id),
        )
        return

    rows = await get_all_quizzes(update.effective_user.id)
    if not rows:
        await update.message.reply_text(
            "📋 Abhi koi quiz save nahi hai.",
            protect_content=protect_for_user(update.effective_user.id),
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
        protect_content=protect_for_user(update.effective_user.id),
    )


async def delete_cmd(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    if not update.message or not update.effective_user:
        return
    if not is_admin(update.effective_user.id):
        await update.message.reply_text(
            "❌ Sirf admin ke liye hai.",
            protect_content=protect_for_user(update.effective_user.id),
        )
        return

    if not context.args:
        await update.message.reply_html(
            "Usage:\n"
            "/delete &lt;file_id&gt;  — file delete karo\n"
            "/delete &lt;q_id&gt;     — quiz delete karo",
            protect_content=protect_for_user(update.effective_user.id),
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
        protect_content=protect_for_user(update.effective_user.id),
    )


async def help_cmd(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    if not update.message or not update.effective_user:
        return

    if is_admin(update.effective_user.id):
        text = (
            "🤖 <b>Admin Commands:</b>\n\n"
            "📤 <b>File/Photo/Video bhejo</b> → link milega\n"
            "📋 <b>Quiz poll bhejo</b> (Quiz Mode on karke) → link milega\n"
            "/addmsg &lt;text&gt; — text message ka link banao\n\n"
            "/myfiles — saari files dekho\n"
            "/myquizzes — saare quizzes dekho\n"
            "/delete &lt;id&gt; — file ya quiz delete karo\n"
            "/help — yeh message\n\n"
            "Jo bhi link share karo — user pehle channel join karega, "
            "tabhi protected content milega."
        )
    else:
        text = (
            "👋 <b>Is bot ka use kaise karein:</b>\n\n"
            "1️⃣ Admin se file/quiz ka link maango\n"
            "2️⃣ Link click karo\n"
            "3️⃣ Channel join karo\n"
            "4️⃣ ✅ Join karne ke baad content mil jaayega\n\n"
            "Content 5 minute baad automatically delete ho jaayega."
        )
    await update.message.reply_html(
        text,
        protect_content=protect_for_user(update.effective_user.id),
    )


# ---------------------------------------------------------------------------
# Startup
# ---------------------------------------------------------------------------

async def post_init(application: Application) -> None:
    await init_db()
    logger.info("Database initialized")


def main() -> None:
    if not BOT_TOKEN or BOT_TOKEN == "PASTE_NEW_BOT_TOKEN_HERE":
        raise RuntimeError(
            "Bot token set nahi hai. TELEGRAM_BOT_TOKEN environment variable "
            "set karein ya code mein PASTE_NEW_BOT_TOKEN_HERE ko replace karein."
        )

    app = (
        Application.builder()
        .token(BOT_TOKEN)
        .post_init(post_init)
        .build()
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("addmsg", add_msg))
    app.add_handler(CommandHandler("myfiles", my_files))
    app.add_handler(CommandHandler("myquizzes", my_quizzes))
    app.add_handler(CommandHandler("delete", delete_cmd))
    app.add_handler(
        CallbackQueryHandler(verify_callback, pattern=r"^verify\|")
    )
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

    logger.info("Bot chal raha hai")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()