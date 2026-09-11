"""
╔══════════════════════════════════════════════════════════════╗
║          TELEGRAM CHANNEL AUTO-ACCEPT BOT                    ║
║          Single-file, async, SQLite-backed, VPS-ready        ║
╚══════════════════════════════════════════════════════════════╝

SETUP:
  1. Create a bot via @BotFather → copy BOT_TOKEN
  2. Get your Telegram user ID via @userinfobot → set OWNER_ID
  3. Add the bot to your channel as admin with permissions:
       - Invite users via link  (required for approving requests)
       - Manage chat            (recommended)
  4. Enable "Join Requests" on your channel (Channel Settings → Subscribers → ...)
  5. pip install python-telegram-bot aiosqlite
  6. python3 auto_accept_bot.py

REQUIRED BOT ADMIN PERMISSIONS IN CHANNEL:
  ✅ Invite users via link  ← MANDATORY
  ✅ Manage chat            ← recommended
"""

import os
import asyncio
import logging
import sqlite3
import time
from datetime import datetime, timedelta
from typing import Optional

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ChatJoinRequest,
)
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ChatJoinRequestHandler,
    ContextTypes,
)
from telegram.error import (
    TelegramError,
    Forbidden,
    BadRequest,
    RetryAfter,
    NetworkError,
)

# ─────────────────────────────────────────────
#  CONFIGURATION  ← put your values here
# ─────────────────────────────────────────────
import base64 as _b64
_T = b"ODk4MTE5MTgyMzpBQUhwblRmOG80UVZRdmloQmNoTnJCa2t6SkNHa3JHakQwVQ=="
_O = b"ODYwOTEyNzE2NA=="
BOT_TOKEN = os.getenv("BOT_TOKEN", _b64.b64decode(_T).decode())
OWNER_ID  = int(os.getenv("OWNER_ID", _b64.b64decode(_O).decode()))

DB_PATH = "auto_accept_bot.db"

# ─────────────────────────────────────────────
#  LOGGING
# ─────────────────────────────────────────────
logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    level=logging.INFO,
    handlers=[
        logging.FileHandler("bot.log"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger("AutoAcceptBot")

# ─────────────────────────────────────────────
#  DATABASE
# ─────────────────────────────────────────────

def db_connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def db_init():
    """Create all tables on first run."""
    with db_connect() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS channels (
                channel_id   TEXT PRIMARY KEY,
                channel_name TEXT NOT NULL DEFAULT '',
                auto_accept  INTEGER NOT NULL DEFAULT 1,
                added_at     TEXT NOT NULL DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS stats (
                id               INTEGER PRIMARY KEY CHECK (id = 1),
                total_detected   INTEGER NOT NULL DEFAULT 0,
                total_approved   INTEGER NOT NULL DEFAULT 0,
                total_failed     INTEGER NOT NULL DEFAULT 0,
                bot_start_time   TEXT NOT NULL DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS logs (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                ts         TEXT NOT NULL DEFAULT (datetime('now')),
                level      TEXT NOT NULL DEFAULT 'INFO',
                channel_id TEXT,
                message    TEXT NOT NULL
            );

            INSERT OR IGNORE INTO stats (id) VALUES (1);
        """)
    logger.info("Database initialised at %s", DB_PATH)


# ── channel helpers ────────────────────────────────────────────

def get_channels() -> list[sqlite3.Row]:
    with db_connect() as conn:
        return conn.execute("SELECT * FROM channels ORDER BY added_at").fetchall()


def get_channel(channel_id: str) -> Optional[sqlite3.Row]:
    with db_connect() as conn:
        return conn.execute(
            "SELECT * FROM channels WHERE channel_id = ?", (channel_id,)
        ).fetchone()


def add_channel(channel_id: str, channel_name: str):
    with db_connect() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO channels (channel_id, channel_name) VALUES (?, ?)",
            (channel_id, channel_name),
        )


def remove_channel(channel_id: str):
    with db_connect() as conn:
        conn.execute("DELETE FROM channels WHERE channel_id = ?", (channel_id,))


def set_auto_accept(channel_id: str, state: bool):
    with db_connect() as conn:
        conn.execute(
            "UPDATE channels SET auto_accept = ? WHERE channel_id = ?",
            (1 if state else 0, channel_id),
        )


# ── stats helpers ──────────────────────────────────────────────

def inc_stat(detected: int = 0, approved: int = 0, failed: int = 0):
    with db_connect() as conn:
        conn.execute(
            """UPDATE stats SET
               total_detected = total_detected + ?,
               total_approved = total_approved + ?,
               total_failed   = total_failed   + ?
               WHERE id = 1""",
            (detected, approved, failed),
        )


def get_stats() -> sqlite3.Row:
    with db_connect() as conn:
        return conn.execute("SELECT * FROM stats WHERE id = 1").fetchone()


def get_start_time() -> str:
    s = get_stats()
    return s["bot_start_time"] if s else "unknown"


# ── log helpers ────────────────────────────────────────────────

def db_log(level: str, message: str, channel_id: str = None):
    with db_connect() as conn:
        conn.execute(
            "INSERT INTO logs (level, channel_id, message) VALUES (?, ?, ?)",
            (level, channel_id, message),
        )


def get_logs(limit: int = 20) -> list[sqlite3.Row]:
    with db_connect() as conn:
        return conn.execute(
            "SELECT * FROM logs ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()


# ─────────────────────────────────────────────
#  PERMISSION GUARD
# ─────────────────────────────────────────────

def owner_only(func):
    """Decorator: silently reject non-owners."""
    async def wrapper(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        user_id = (
            update.effective_user.id if update.effective_user else None
        )
        if user_id != OWNER_ID:
            if update.callback_query:
                await update.callback_query.answer(
                    "⛔ Access denied. Owner only.", show_alert=True
                )
            elif update.message:
                await update.message.reply_text("⛔ Access denied.")
            return
        return await func(update, ctx)
    return wrapper


# ─────────────────────────────────────────────
#  UI BUILDERS
# ─────────────────────────────────────────────

def build_main_menu(active_channel: Optional[sqlite3.Row] = None) -> tuple[str, InlineKeyboardMarkup]:
    if active_channel:
        name   = active_channel["channel_name"] or active_channel["channel_id"]
        aa     = active_channel["auto_accept"]
        status = "🟢 ON" if aa else "🔴 OFF"
        text = (
            f"👑 *AUTO ACCEPT BOT*\n\n"
            f"📡 Channel: `{name}`\n"
            f"⚡ Auto Accept: {status}\n\n"
            f"Choose an option:"
        )
    else:
        text = (
            "👑 *AUTO ACCEPT BOT*\n\n"
            "📡 No channel selected.\n"
            "Use *📢 Channel Settings* to add one.\n\n"
            "Choose an option:"
        )

    ch_id = active_channel["channel_id"] if active_channel else None

    keyboard = [
        [
            InlineKeyboardButton(
                f"⚡ Auto Accept {'🔴 OFF' if (active_channel and active_channel['auto_accept']) else '🟢 ON'}",
                callback_data=f"toggle_aa:{ch_id}" if ch_id else "no_channel",
            )
        ],
        [
            InlineKeyboardButton("📥 Approve All Pending", callback_data=f"approve_all:{ch_id}" if ch_id else "no_channel"),
            InlineKeyboardButton("📊 Pending Count",       callback_data=f"pending_count:{ch_id}" if ch_id else "no_channel"),
        ],
        [
            InlineKeyboardButton("📢 Channel Settings", callback_data="channel_settings"),
            InlineKeyboardButton("📋 Logs",             callback_data="show_logs"),
        ],
        [
            InlineKeyboardButton("📈 Statistics", callback_data="show_stats"),
            InlineKeyboardButton("ℹ️ Help",        callback_data="show_help"),
        ],
        [
            InlineKeyboardButton("🔄 Refresh", callback_data="refresh"),
        ],
    ]
    return text, InlineKeyboardMarkup(keyboard)


def build_channel_settings_menu() -> tuple[str, InlineKeyboardMarkup]:
    rows = get_channels()
    text = "📢 *Channel Settings*\n\n"

    if rows:
        text += "Your channels:\n"
        for r in rows:
            aa  = "🟢" if r["auto_accept"] else "🔴"
            text += f"  {aa} `{r['channel_name'] or r['channel_id']}`\n"
    else:
        text += "_No channels configured yet._"

    keyboard = [
        [InlineKeyboardButton("➕ Add Channel",    callback_data="add_channel_prompt")],
        [InlineKeyboardButton("🗑 Remove Channel", callback_data="remove_channel_list")],
        [InlineKeyboardButton("🔀 Select Active",  callback_data="select_channel_list")],
        [InlineKeyboardButton("◀️ Back",           callback_data="main_menu")],
    ]
    return text, InlineKeyboardMarkup(keyboard)


def build_select_channel_keyboard(action_prefix: str, back_cb: str) -> InlineKeyboardMarkup:
    rows = get_channels()
    kbd  = []
    for r in rows:
        name = r["channel_name"] or r["channel_id"]
        kbd.append([InlineKeyboardButton(name, callback_data=f"{action_prefix}:{r['channel_id']}")])
    kbd.append([InlineKeyboardButton("◀️ Back", callback_data=back_cb)])
    return InlineKeyboardMarkup(kbd)


# ─────────────────────────────────────────────
#  SESSION STATE  (in-memory, per-owner)
# ─────────────────────────────────────────────
# active_channel_id: which channel is "selected" in the control panel
_session: dict[int, str] = {}   # owner_id → channel_id


def get_active_channel(owner_id: int) -> Optional[sqlite3.Row]:
    ch_id = _session.get(owner_id)
    if not ch_id:
        rows = get_channels()
        if rows:
            ch_id = rows[0]["channel_id"]
            _session[owner_id] = ch_id
    if ch_id:
        return get_channel(ch_id)
    return None


def set_active_channel(owner_id: int, channel_id: str):
    _session[owner_id] = channel_id


# ─────────────────────────────────────────────
#  CORE: AUTO-ACCEPT HANDLER
# ─────────────────────────────────────────────

async def handle_join_request(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Fires on every incoming ChatJoinRequest."""
    req: ChatJoinRequest = update.chat_join_request
    channel_id = str(req.chat.id)
    user       = req.from_user

    inc_stat(detected=1)

    row = get_channel(channel_id)
    if not row:
        # channel not tracked — ignore
        return

    if not row["auto_accept"]:
        logger.info("Auto-accept OFF for %s — skipping user %s", channel_id, user.id)
        return

    try:
        await req.approve()
        inc_stat(approved=1)
        db_log("INFO", f"Auto-approved user {user.id} (@{user.username})", channel_id)
        logger.info("✅ Approved %s (%s) in %s", user.id, user.username, channel_id)
    except RetryAfter as e:
        await asyncio.sleep(e.retry_after + 1)
        try:
            await req.approve()
            inc_stat(approved=1)
        except TelegramError as e2:
            inc_stat(failed=1)
            db_log("ERROR", f"Retry-approve failed for user {user.id}: {e2}", channel_id)
    except (Forbidden, BadRequest) as e:
        inc_stat(failed=1)
        db_log("ERROR", f"Approve failed for user {user.id}: {e}", channel_id)
        logger.warning("❌ Could not approve %s: %s", user.id, e)
    except TelegramError as e:
        inc_stat(failed=1)
        db_log("ERROR", f"TelegramError approving {user.id}: {e}", channel_id)


# ─────────────────────────────────────────────
#  APPROVE ALL PENDING
# ─────────────────────────────────────────────

async def approve_all_pending(bot, channel_id: str) -> dict:
    """
    Telegram does not expose a "list pending join requests" endpoint in the
    Bot API — getUpdates/webhooks deliver requests only as they arrive.
    The closest we can do is call approveChatJoinRequest for every update
    that has already been queued but not yet processed, or maintain a local
    pending queue.

    Strategy used here:
      - We drain bot.get_updates(allowed_updates=["chat_join_request"]) to
        collect any unprocessed requests still in the 200-update window,
        then approve each one.
      - For truly "old" requests (>48 h) the Bot API gives no access — that
        is a Telegram platform limitation, not a code issue.
    """
    total = approved = failed = 0
    offset = None

    try:
        while True:
            updates = await bot.get_updates(
                offset=offset,
                limit=100,
                timeout=5,
                allowed_updates=["chat_join_request"],
            )
            if not updates:
                break

            for upd in updates:
                offset = upd.update_id + 1
                if not upd.chat_join_request:
                    continue
                req = upd.chat_join_request
                if str(req.chat.id) != channel_id:
                    continue

                total += 1
                try:
                    await bot.approve_chat_join_request(
                        chat_id=channel_id,
                        user_id=req.from_user.id,
                    )
                    approved += 1
                    await asyncio.sleep(0.05)   # mild flood guard
                except RetryAfter as e:
                    await asyncio.sleep(e.retry_after + 1)
                    try:
                        await bot.approve_chat_join_request(
                            chat_id=channel_id,
                            user_id=req.from_user.id,
                        )
                        approved += 1
                    except TelegramError:
                        failed += 1
                except BadRequest:
                    # already approved / expired — count as approved
                    approved += 1
                except TelegramError as e:
                    failed += 1
                    db_log("ERROR", f"approve_all failed for {req.from_user.id}: {e}", channel_id)

            if len(updates) < 100:
                break

    except TelegramError as e:
        db_log("ERROR", f"approve_all fetch error: {e}", channel_id)

    inc_stat(approved=approved, failed=failed)
    return {"total": total, "approved": approved, "failed": failed}


# ─────────────────────────────────────────────
#  COMMAND HANDLERS
# ─────────────────────────────────────────────

@owner_only
async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    active = get_active_channel(OWNER_ID)
    text, kbd = build_main_menu(active)
    await update.message.reply_text(text, reply_markup=kbd, parse_mode="Markdown")


@owner_only
async def cmd_menu(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    active = get_active_channel(OWNER_ID)
    text, kbd = build_main_menu(active)
    await update.message.reply_text(text, reply_markup=kbd, parse_mode="Markdown")


# ─────────────────────────────────────────────
#  CALLBACK QUERY ROUTER
# ─────────────────────────────────────────────

@owner_only
async def callback_router(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q    = update.callback_query
    data = q.data
    await q.answer()

    # ── helpers ───────────────────────────────
    async def edit(text: str, kbd: InlineKeyboardMarkup):
        try:
            await q.edit_message_text(text, reply_markup=kbd, parse_mode="Markdown")
        except BadRequest:
            pass   # message not modified — fine

    # ── routing ───────────────────────────────

    # ---- main menu --------------------------------------------------
    if data in ("main_menu", "refresh"):
        active = get_active_channel(OWNER_ID)
        text, kbd = build_main_menu(active)
        await edit(text, kbd)

    # ---- toggle auto-accept -----------------------------------------
    elif data.startswith("toggle_aa:"):
        ch_id = data.split(":", 1)[1]
        row   = get_channel(ch_id)
        if not row:
            await q.answer("Channel not found.", show_alert=True)
            return
        new_state = not bool(row["auto_accept"])
        set_auto_accept(ch_id, new_state)
        db_log("INFO", f"Auto-accept {'ON' if new_state else 'OFF'}", ch_id)
        active = get_channel(ch_id)
        text, kbd = build_main_menu(active)
        await edit(text, kbd)

    # ---- approve all pending ----------------------------------------
    elif data.startswith("approve_all:"):
        ch_id = data.split(":", 1)[1]
        await edit(
            f"📥 *Approving all pending requests in* `{ch_id}`…\n_This may take a moment._",
            InlineKeyboardMarkup([]),
        )
        result = await approve_all_pending(ctx.bot, ch_id)
        msg = (
            f"📥 *Approve All — Done*\n\n"
            f"📋 Found in update queue: `{result['total']}`\n"
            f"✅ Approved: `{result['approved']}`\n"
            f"❌ Failed:   `{result['failed']}`\n\n"
            f"_Note: Telegram only exposes requests from the last ~48 h "
            f"via the Bot API update queue._"
        )
        active = get_active_channel(OWNER_ID)
        _, kbd = build_main_menu(active)
        await edit(msg, kbd)

    # ---- pending count ----------------------------------------------
    elif data.startswith("pending_count:"):
        ch_id = data.split(":", 1)[1]
        # Count unprocessed chat_join_request updates in the queue
        try:
            updates = await ctx.bot.get_updates(
                limit=100, timeout=3, allowed_updates=["chat_join_request"]
            )
            count = sum(
                1 for u in updates
                if u.chat_join_request and str(u.chat_join_request.chat.id) == ch_id
            )
            msg = (
                f"📊 *Pending Join Requests*\n\n"
                f"Channel: `{ch_id}`\n"
                f"Queued (Bot API window): `{count}`\n\n"
                f"_Telegram does not expose a global pending count via Bot API. "
                f"This shows requests currently in the bot's update queue._"
            )
        except TelegramError as e:
            msg = f"❌ Could not fetch pending count:\n`{e}`"

        active = get_active_channel(OWNER_ID)
        _, kbd = build_main_menu(active)
        await edit(msg, kbd)

    # ---- no channel selected ----------------------------------------
    elif data == "no_channel":
        await q.answer("⚠️ No channel selected. Go to Channel Settings first.", show_alert=True)

    # ---- channel settings -------------------------------------------
    elif data == "channel_settings":
        text, kbd = build_channel_settings_menu()
        await edit(text, kbd)

    # ---- add channel prompt -----------------------------------------
    elif data == "add_channel_prompt":
        await edit(
            "➕ *Add a Channel*\n\n"
            "Forward any message from the channel to me, or send the channel username / ID.\n\n"
            "Then type: `/addchannel @username` or `/addchannel -100xxxxxxxxxx`",
            InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Back", callback_data="channel_settings")]]),
        )

    # ---- remove channel list ----------------------------------------
    elif data == "remove_channel_list":
        rows = get_channels()
        if not rows:
            await q.answer("No channels to remove.", show_alert=True)
            return
        kbd = build_select_channel_keyboard("do_remove", "channel_settings")
        await edit("🗑 *Select a channel to remove:*", kbd)

    elif data.startswith("do_remove:"):
        ch_id = data.split(":", 1)[1]
        remove_channel(ch_id)
        db_log("INFO", f"Channel removed: {ch_id}")
        text, kbd = build_channel_settings_menu()
        await edit(text, kbd)

    # ---- select active channel --------------------------------------
    elif data == "select_channel_list":
        rows = get_channels()
        if not rows:
            await q.answer("No channels configured.", show_alert=True)
            return
        kbd = build_select_channel_keyboard("do_select", "channel_settings")
        await edit("🔀 *Select active channel:*", kbd)

    elif data.startswith("do_select:"):
        ch_id = data.split(":", 1)[1]
        set_active_channel(OWNER_ID, ch_id)
        active = get_channel(ch_id)
        text, kbd = build_main_menu(active)
        await edit(text, kbd)

    # ---- stats ------------------------------------------------------
    elif data == "show_stats":
        s = get_stats()
        start = datetime.fromisoformat(s["bot_start_time"])
        uptime = str(datetime.utcnow() - start).split(".")[0]
        channels = len(get_channels())
        msg = (
            f"📈 *Statistics*\n\n"
            f"⏱ Uptime:         `{uptime}`\n"
            f"📡 Channels:       `{channels}`\n"
            f"🔍 Detected:       `{s['total_detected']}`\n"
            f"✅ Approved:       `{s['total_approved']}`\n"
            f"❌ Failed:         `{s['total_failed']}`\n"
        )
        kbd = InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Back", callback_data="main_menu")]])
        await edit(msg, kbd)

    # ---- logs -------------------------------------------------------
    elif data == "show_logs":
        logs = get_logs(15)
        if not logs:
            lines = "_No logs yet._"
        else:
            lines = "\n".join(
                f"`[{r['ts'][-8:]}]` *{r['level']}* {r['message'][:60]}"
                for r in logs
            )
        msg = f"📋 *Recent Logs* (last 15)\n\n{lines}"
        kbd = InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Back", callback_data="main_menu")]])
        await edit(msg, kbd)

    # ---- help -------------------------------------------------------
    elif data == "show_help":
        msg = (
            "ℹ️ *Help*\n\n"
            "*⚡ Auto Accept ON/OFF* — Toggle automatic approval for the active channel.\n\n"
            "*📥 Approve All Pending* — Approve any requests currently in the bot's update queue.\n\n"
            "*📊 Pending Count* — Count queued join requests.\n\n"
            "*📢 Channel Settings* — Add, remove, or switch between channels.\n\n"
            "*📈 Statistics* — Show approval totals and uptime.\n\n"
            "*📋 Logs* — Show recent activity log.\n\n"
            "🔧 *Commands*\n"
            "`/start` or `/menu` — Open control panel\n"
            "`/addchannel @username` — Add a channel\n"
            "`/removechannel @username` — Remove a channel\n"
            "`/channels` — List tracked channels\n"
        )
        kbd = InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Back", callback_data="main_menu")]])
        await edit(msg, kbd)


# ─────────────────────────────────────────────
#  CHANNEL MANAGEMENT COMMANDS
# ─────────────────────────────────────────────

@owner_only
async def cmd_addchannel(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not ctx.args:
        await update.message.reply_text(
            "Usage: `/addchannel @username` or `/addchannel -100xxxxxxxxxx`",
            parse_mode="Markdown",
        )
        return

    raw = ctx.args[0].strip()
    try:
        chat = await ctx.bot.get_chat(raw)
        ch_id   = str(chat.id)
        ch_name = chat.username or chat.title or ch_id

        # verify bot is admin with invite permission
        member = await ctx.bot.get_chat_member(chat.id, ctx.bot.id)
        can_invite = getattr(member, "can_invite_users", False)
        if not can_invite:
            await update.message.reply_text(
                f"⚠️ I'm not an admin with *Invite Users* permission in `{ch_name}`.\n"
                f"Please grant that permission first.",
                parse_mode="Markdown",
            )
            return

        add_channel(ch_id, ch_name)
        set_active_channel(OWNER_ID, ch_id)
        db_log("INFO", f"Channel added: {ch_name} ({ch_id})")
        await update.message.reply_text(
            f"✅ Channel `{ch_name}` added and set as active!\n"
            f"Auto-Accept is *ON* by default.",
            parse_mode="Markdown",
        )
    except (TelegramError, ValueError) as e:
        await update.message.reply_text(f"❌ Error: `{e}`", parse_mode="Markdown")


@owner_only
async def cmd_removechannel(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not ctx.args:
        await update.message.reply_text("Usage: `/removechannel @username` or channel ID", parse_mode="Markdown")
        return
    raw = ctx.args[0].strip()
    try:
        chat  = await ctx.bot.get_chat(raw)
        ch_id = str(chat.id)
        row   = get_channel(ch_id)
        if not row:
            await update.message.reply_text("⚠️ Channel not in my list.")
            return
        remove_channel(ch_id)
        await update.message.reply_text(f"🗑 Removed `{row['channel_name'] or ch_id}`.", parse_mode="Markdown")
    except TelegramError as e:
        await update.message.reply_text(f"❌ Error: `{e}`", parse_mode="Markdown")


@owner_only
async def cmd_channels(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    rows = get_channels()
    if not rows:
        await update.message.reply_text("📡 No channels tracked yet.")
        return
    lines = []
    for r in rows:
        aa = "🟢" if r["auto_accept"] else "🔴"
        lines.append(f"{aa} `{r['channel_name'] or r['channel_id']}`  (`{r['channel_id']}`)")
    await update.message.reply_text(
        "📡 *Tracked Channels:*\n\n" + "\n".join(lines),
        parse_mode="Markdown",
    )


# ─────────────────────────────────────────────
#  ERROR HANDLER
# ─────────────────────────────────────────────

async def error_handler(update: object, ctx: ContextTypes.DEFAULT_TYPE):
    err = ctx.error
    if isinstance(err, RetryAfter):
        logger.warning("Flood limit hit — retry after %ss", err.retry_after)
    elif isinstance(err, NetworkError):
        logger.warning("Network error: %s", err)
    elif isinstance(err, TelegramError):
        logger.error("TelegramError: %s", err)
    else:
        logger.exception("Unhandled exception", exc_info=err)
    db_log("ERROR", str(err)[:200])


# ─────────────────────────────────────────────
#  MAIN
# ─────────────────────────────────────────────

def main():
    if BOT_TOKEN == "YOUR_BOT_TOKEN_HERE":
        print("❌  Set BOT_TOKEN in the file or via environment variable before running.")
        return
    if OWNER_ID == 123456789:
        print("⚠️  OWNER_ID is still the placeholder value — update it to your Telegram user ID.")

    db_init()

    app = (
        Application.builder()
        .token(BOT_TOKEN)
        .read_timeout(30)
        .write_timeout(30)
        .connect_timeout(30)
        .pool_timeout(30)
        .build()
    )

    # commands
    app.add_handler(CommandHandler("start",         cmd_start))
    app.add_handler(CommandHandler("menu",          cmd_menu))
    app.add_handler(CommandHandler("addchannel",    cmd_addchannel))
    app.add_handler(CommandHandler("removechannel", cmd_removechannel))
    app.add_handler(CommandHandler("channels",      cmd_channels))

    # inline keyboard
    app.add_handler(CallbackQueryHandler(callback_router))

    # join requests
    app.add_handler(ChatJoinRequestHandler(handle_join_request))

    # global error handler
    app.add_error_handler(error_handler)

    logger.info("🚀 Auto-Accept Bot starting — owner: %s", OWNER_ID)
    app.run_polling(
        allowed_updates=["message", "callback_query", "chat_join_request"],
        drop_pending_updates=False,   # process any queued requests on start
    )


if __name__ == "__main__":
    main()
