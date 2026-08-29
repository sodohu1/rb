import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ChatType
from telegram.error import TelegramError
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ChatMemberHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

# Load .env from the SAME folder as this script, regardless of which
# folder it's launched from (fixes ".env not found" on some phones/apps).
BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

# Hardcoded fallbacks (used only if .env is missing/not found) so the bot
# still runs even without a working .env file. A real .env value, if found,
# always wins over these.
BOT_TOKEN = os.getenv("BOT_TOKEN", "8982922702:AAEuSWzlp_de_WymFxja_HSNwph9AXLNT5Y").strip()
OWNER_ID = int(os.getenv("OWNER_ID", "8609127164"))
RETENTION_LIMIT = max(1, int(os.getenv("RETENTION_LIMIT", "2")))
MAX_CHANNELS = max(1, int(os.getenv("MAX_CHANNELS", "3")))
DB_PATH = os.getenv("DB_PATH", "channel_posts.db")

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN is missing — set it in .env or hardcode it above")
if not OWNER_ID:
    raise RuntimeError("OWNER_ID is missing — set it in .env or hardcode it above")


# ---------- Database ----------

def db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS channels (
            channel_id TEXT PRIMARY KEY,
            title TEXT,
            added_at TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS posts (
            channel_id TEXT NOT NULL,
            message_id INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            PRIMARY KEY (channel_id, message_id)
        )
    """)
    conn.commit()
    return conn


def add_channel(channel_id: str, title: str, added_at: str):
    conn = db()
    conn.execute(
        "INSERT OR REPLACE INTO channels(channel_id, title, added_at) VALUES(?, ?, ?)",
        (channel_id, title, added_at),
    )
    conn.commit()
    conn.close()


def remove_channel(channel_id: str):
    conn = db()
    conn.execute("DELETE FROM channels WHERE channel_id = ?", (channel_id,))
    conn.execute("DELETE FROM posts WHERE channel_id = ?", (channel_id,))
    conn.commit()
    conn.close()


def get_channels():
    conn = db()
    rows = conn.execute(
        "SELECT channel_id, title FROM channels ORDER BY added_at ASC"
    ).fetchall()
    conn.close()
    return rows


def is_registered(channel_id: str) -> bool:
    channel_id = str(channel_id)
    return any(c[0] == channel_id for c in get_channels())


def add_post(channel_id: str, message_id: int, created_at: str):
    conn = db()
    conn.execute(
        "INSERT OR IGNORE INTO posts(channel_id, message_id, created_at) VALUES(?, ?, ?)",
        (channel_id, message_id, created_at),
    )
    conn.commit()
    conn.close()


def remove_post(channel_id: str, message_id: int):
    conn = db()
    conn.execute(
        "DELETE FROM posts WHERE channel_id = ? AND message_id = ?",
        (channel_id, message_id),
    )
    conn.commit()
    conn.close()


def get_posts(channel_id: str):
    conn = db()
    rows = conn.execute(
        "SELECT message_id, created_at FROM posts WHERE channel_id = ? "
        "ORDER BY created_at ASC, message_id ASC",
        (channel_id,),
    ).fetchall()
    conn.close()
    return rows


# ---------- Retention logic (per channel) ----------

async def delete_oldest_if_needed(context: ContextTypes.DEFAULT_TYPE, channel_id: str):
    posts = get_posts(channel_id)
    if len(posts) <= RETENTION_LIMIT:
        return

    excess = posts[: max(0, len(posts) - RETENTION_LIMIT)]
    for message_id, _ in excess:
        try:
            await context.bot.delete_message(chat_id=channel_id, message_id=message_id)
        except TelegramError as e:
            # Already deleted/not accessible/etc. is harmless.
            print(f"[cleanup] {channel_id}/{message_id}: {e}")
        finally:
            remove_post(channel_id, message_id)


async def channel_post(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.channel_post
    if not message:
        return

    channel_id = str(message.chat.id)
    if not is_registered(channel_id):
        return  # bot can see this post but isn't managing this channel

    created_at = message.date
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)

    add_post(
        channel_id,
        message.message_id,
        created_at.astimezone(timezone.utc).isoformat(),
    )

    await delete_oldest_if_needed(context, channel_id)


# ---------- Auto register/deregister channels via admin promotion ----------

async def track_my_chat_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cmu = update.my_chat_member
    if not cmu or cmu.chat.type != ChatType.CHANNEL:
        return

    channel_id = str(cmu.chat.id)
    title = cmu.chat.title or channel_id
    old_status = cmu.old_chat_member.status
    new_status = cmu.new_chat_member.status

    became_admin = new_status == "administrator" and old_status != "administrator"
    lost_admin = old_status == "administrator" and new_status != "administrator"

    if became_admin:
        if not is_registered(channel_id) and len(get_channels()) >= MAX_CHANNELS:
            try:
                await context.bot.leave_chat(channel_id)
            except TelegramError:
                pass
            await context.bot.send_message(
                OWNER_ID,
                f"⚠️ Already managing {MAX_CHANNELS} channels (the limit).\n"
                f"Remove one from /start first, then re-add \"{title}\".",
            )
            return

        now = datetime.now(timezone.utc).isoformat()
        add_channel(channel_id, title, now)

        can_delete = getattr(cmu.new_chat_member, "can_delete_messages", False)
        note = "" if can_delete else "\n⚠️ Grant it the \"Delete Messages\" admin right or cleanup won't work."
        await context.bot.send_message(
            OWNER_ID,
            f"✅ Now managing: {title}\nKeeping the latest {RETENTION_LIMIT} posts.{note}",
        )

    elif lost_admin and is_registered(channel_id):
        remove_channel(channel_id)
        await context.bot.send_message(
            OWNER_ID,
            f"ℹ️ No longer admin in \"{title}\" — stopped tracking it.",
        )


# ---------- Owner panel ----------

def owner_only(update: Update) -> bool:
    user = update.effective_user
    return bool(user and user.id == OWNER_ID)


async def show_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    channels = get_channels()
    me = await context.bot.get_me()
    add_url = f"https://t.me/{me.username}?startchannel&admin=delete_messages"

    lines = [
        "🛡️ CHANNEL RETENTION PANEL",
        "",
        f"📌 Retention limit: {RETENTION_LIMIT} posts/channel",
        f"📡 Channels managed: {len(channels)}/{MAX_CHANNELS}",
        "",
    ]

    keyboard = []
    if channels:
        for channel_id, title in channels:
            posts = get_posts(channel_id)
            warn = ""
            try:
                member = await context.bot.get_chat_member(channel_id, me.id)
                if not getattr(member, "can_delete_messages", False):
                    warn = " ⚠️"
            except TelegramError:
                warn = " ❌"
            lines.append(f"• {title}{warn} — {len(posts)} tracked")

            short = title if len(title) <= 18 else title[:17] + "…"
            keyboard.append([
                InlineKeyboardButton(f"🧹 {short}", callback_data=f"cleanup:{channel_id}"),
                InlineKeyboardButton("❌ Remove", callback_data=f"remove:{channel_id}"),
            ])
    else:
        lines.append("No channels yet — tap below to add one.")

    keyboard.append([InlineKeyboardButton("➕ Add Bot to a Channel", url=add_url)])
    keyboard.append([InlineKeyboardButton("🔄 Refresh", callback_data="refresh")])

    text = "\n".join(lines)
    markup = InlineKeyboardMarkup(keyboard)

    if update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=markup)
    else:
        await update.effective_message.reply_text(text, reply_markup=markup)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not owner_only(update):
        await update.effective_message.reply_text("⛔ Access Denied")
        return
    await show_panel(update, context)


async def panel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query

    if query.from_user.id != OWNER_ID:
        await query.answer("⛔ Access Denied", show_alert=True)
        return

    await query.answer()
    data = query.data

    if data == "refresh":
        await show_panel(update, context)

    elif data.startswith("cleanup:"):
        channel_id = data.split(":", 1)[1]
        await delete_oldest_if_needed(context, channel_id)
        await show_panel(update, context)

    elif data.startswith("remove:"):
        channel_id = data.split(":", 1)[1]
        try:
            await context.bot.leave_chat(channel_id)
        except TelegramError:
            pass
        remove_channel(channel_id)
        await show_panel(update, context)


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    print(f"[error] {context.error}")


async def post_init(application: Application):
    db()
    # Startup reconcile: in case posts piled up while the bot was offline.
    for channel_id, _ in get_channels():
        try:
            await delete_oldest_if_needed(application, channel_id)
        except TelegramError as e:
            print(f"[startup reconcile] {channel_id}: {e}")


def main():
    app = (
        Application.builder()
        .token(BOT_TOKEN)
        .post_init(post_init)
        .build()
    )

    # Channel posts, independent of private-panel access.
    app.add_handler(MessageHandler(filters.UpdateType.CHANNEL_POST, channel_post))

    # Fires when the bot is promoted/demoted in a channel -> auto add/remove it.
    app.add_handler(ChatMemberHandler(track_my_chat_member, ChatMemberHandler.MY_CHAT_MEMBER))

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(panel_callback))
    app.add_error_handler(error_handler)

    print("✅ Multi-channel retention bot started.")
    print(f"Retention limit: {RETENTION_LIMIT} posts/channel | Max channels: {MAX_CHANNELS}")

    app.run_polling(
        allowed_updates=["message", "callback_query", "channel_post", "my_chat_member"]
    )


if __name__ == "__main__":
    main()
