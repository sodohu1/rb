#!/usr/bin/env python3
"""
╔══════════════════════════════════════════╗
   🤖 AUTO GUARD BOT — SINGLE FILE EDITION
╚══════════════════════════════════════════╝
Poora bot ek hi file mein! (Approval, Filters, Auto-Delete,
Hosting Panel + Auto Modules, Backup, Broadcast... sab kuch)

SETUP:
  pip install -r requirements.txt
  python bot.py

⚠️ TOKEN BADALNA HO TOH: niche CONFIG section me jao
   aur BOT_TOKEN ki line update kar do. Bas!
"""

# ═══════════════════════════════════════════════════════
# IMPORTS
# ═══════════════════════════════════════════════════════
import asyncio
import ast
import hashlib
import importlib.util
import io
import json
import logging
import os
import re
import sys
import time
from collections import OrderedDict, defaultdict, deque
from contextlib import asynccontextmanager
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from enum import Enum
from functools import wraps

import aiosqlite
import psutil
from telegram import (BotCommand, InlineKeyboardButton,
                      InlineKeyboardMarkup, Update)
from telegram.constants import ChatType
from telegram.ext import (Application, ApplicationHandlerStop,
                          CallbackQueryHandler, ChatMemberHandler,
                          CommandHandler, ContextTypes, MessageHandler,
                          filters)

# ═══════════════════════════════════════════════════════
# ⚙️ CONFIG — HARDCODED (matlab .env ki zaroorat nahi)
# ═══════════════════════════════════════════════════════
# ⚠️⚠️⚠️  YE TOKEN SECRET HAI — kisi ko share/submit mat karna!
#          Leak ho jaye toh @BotFather → /mybots → Revoke Token
# ═══════════════════════════════════════════════════════
BOT_TOKEN = "7861849557:AAGo5TU1hDuoRvOvqXz6bZAS-_t6VFFCI9o"   # 👈 TOKEN YAHAN CHANGE KARO (naya wala)
OWNER_ID = 8609127164                                          # 👈 Tumhari Owner ID

DB_PATH = os.environ.get("DB_PATH", "autoguard.db")
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO")
SANDBOX_DIR = os.environ.get("SANDBOX_DIR", "./sandbox")
MAX_UPLOAD_MB = int(os.environ.get("MAX_UPLOAD_MB", "20"))
HOST_CPU_SEC = int(os.environ.get("HOST_CPU_SEC", "120"))
HOST_RAM_MB = int(os.environ.get("HOST_RAM_MB", "256"))
START_TIME = time.time()

logging.basicConfig(level=getattr(logging, LOG_LEVEL, logging.INFO),
                    format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logging.getLogger("httpx").setLevel(logging.WARNING)
log = logging.getLogger("bot")

# ═══════════════════════════════════════════════════════
# CONSTANTS
# ═══════════════════════════════════════════════════════
FILTERS = [
    "keyword", "links", "media", "forward", "bot", "duplicate", "caps",
    "domain", "document", "gif", "filesize", "length", "flood",
    "smartspam", "hashtag",
]

DEFAULTS = {
    "auto_delete": {"enabled": False, "seconds": 300},
    "filters": {f: False for f in FILTERS},
    "keyword_blacklist": [],
    "blocked_domains": [],
    "max_length": 4096,
    "max_file_mb": 100,
    "caps_percent": 70,
    "edit_detect": False,
    "dry_run": False,
    "notify": True,
    "caption": {"enabled": False, "mode": "replace", "text": ""},
    "quiet_hours": {"enabled": False, "start": "23:00", "end": "07:00"},
    "rate_limit": {"enabled": False, "per_minute": 20},
}

# ═══════════════════════════════════════════════════════
# DATABASE — SQLite, restart-safe
# ═══════════════════════════════════════════════════════
SCHEMA = """
CREATE TABLE IF NOT EXISTS users(
  user_id INTEGER PRIMARY KEY,
  username TEXT, first_name TEXT,
  status TEXT DEFAULT 'pending',
  requested_at TEXT, decided_at TEXT);
CREATE TABLE IF NOT EXISTS channels(
  channel_id INTEGER PRIMARY KEY,
  title TEXT, added_by INTEGER, settings TEXT DEFAULT '{}');
CREATE TABLE IF NOT EXISTS kv(key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS logs(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts TEXT, level TEXT, category TEXT, user_id INTEGER, chat_id INTEGER, text TEXT);
CREATE TABLE IF NOT EXISTS custom_commands(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER, name TEXT, response TEXT);
CREATE TABLE IF NOT EXISTS scheduled(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  chat_id INTEGER, text TEXT, run_at TEXT, created_by INTEGER, done INTEGER DEFAULT 0);
"""


def _now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")


@asynccontextmanager
async def _cx():
    conn = await aiosqlite.connect(DB_PATH)
    conn.row_factory = aiosqlite.Row
    try:
        yield conn
        await conn.commit()
    finally:
        await conn.close()


async def db_init():
    async with _cx() as cx:
        await cx.executescript(SCHEMA)


async def db_exec(sql, params=()):
    async with _cx() as cx:
        cur = await cx.execute(sql, params)
        return cur.lastrowid


async def db_all(sql, params=()):
    async with _cx() as cx:
        cur = await cx.execute(sql, params)
        return [dict(r) for r in await cur.fetchall()]


async def db_one(sql, params=()):
    rows = await db_all(sql, params)
    return rows[0] if rows else None


async def get_kv(key, default=None):
    row = await db_one("SELECT value FROM kv WHERE key=?", (key,))
    return row["value"] if row else default


async def set_kv(key, value):
    await db_exec(
        "INSERT INTO kv(key,value) VALUES(?,?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, str(value)))


async def ensure_user(user_id, username, first_name):
    await db_exec(
        "INSERT OR IGNORE INTO users(user_id,username,first_name,status,requested_at) "
        "VALUES(?,?,?,'pending',?)",
        (user_id, username, first_name, _now()))


async def get_user(user_id):
    return await db_one("SELECT * FROM users WHERE user_id=?", (user_id,))


async def set_status(user_id, status):
    await ensure_user(user_id, None, None)
    await db_exec("UPDATE users SET status=?, decided_at=? WHERE user_id=?",
                  (status, _now(), user_id))


async def delete_user(user_id):
    await db_exec("DELETE FROM users WHERE user_id=?", (user_id,))


async def users_by_status(status):
    return await db_all("SELECT * FROM users WHERE status=? ORDER BY user_id", (status,))


async def count_users(status=None):
    if status:
        row = await db_one("SELECT COUNT(*) c FROM users WHERE status=?", (status,))
    else:
        row = await db_one("SELECT COUNT(*) c FROM users")
    return row["c"]


async def add_channel(channel_id, title, added_by):
    await db_exec(
        "INSERT OR IGNORE INTO channels(channel_id,title,added_by,settings) VALUES(?,?,?,'{}')",
        (channel_id, title, added_by))


async def remove_channel(channel_id):
    await db_exec("DELETE FROM channels WHERE channel_id=?", (channel_id,))


async def get_channel(channel_id):
    return await db_one("SELECT * FROM channels WHERE channel_id=?", (channel_id,))


async def all_channels():
    return await db_all("SELECT * FROM channels ORDER BY channel_id")


async def my_channels(user_id):
    if user_id == OWNER_ID:
        return await all_channels()
    return await db_all("SELECT * FROM channels WHERE added_by=? ORDER BY channel_id", (user_id,))


def _merge(base, extra):
    out = deepcopy(base)
    for k, v in (extra or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k].update(v)
        else:
            out[k] = v
    return out


async def channel_settings(channel_id):
    ch = await get_channel(channel_id)
    try:
        extra = json.loads(ch["settings"]) if ch else {}
    except Exception:
        extra = {}
    return _merge(DEFAULTS, extra)


async def save_channel_settings(channel_id, settings):
    await db_exec("UPDATE channels SET settings=? WHERE channel_id=?",
                  (json.dumps(settings, ensure_ascii=False), channel_id))


async def add_log(level, category, user_id, chat_id, text):
    await db_exec(
        "INSERT INTO logs(ts,level,category,user_id,chat_id,text) VALUES(?,?,?,?,?,?)",
        (_now(), level, user_id, chat_id, (text or "")[:500]))


async def recent_logs(limit=30, category=None, chat_id=None, user_id=None):
    sql, params = "SELECT * FROM logs WHERE 1=1", []
    if category:
        sql += " AND category=?"; params.append(category)
    if chat_id:
        sql += " AND chat_id=?"; params.append(chat_id)
    if user_id:
        sql += " AND user_id=?"; params.append(user_id)
    sql += " ORDER BY id DESC LIMIT ?"
    params.append(limit)
    return await db_all(sql, params)


async def count_logs(category=None, chat_id=None, today=False, errors=False):
    sql, params = "SELECT COUNT(*) c FROM logs WHERE 1=1", []
    if category:
        sql += " AND category=?"; params.append(category)
    if chat_id:
        sql += " AND chat_id=?"; params.append(chat_id)
    if today:
        sql += " AND ts>=?"; params.append(datetime.now(timezone.utc).strftime("%Y-%m-%d"))
    if errors:
        sql += " AND level='ERROR'"
    row = await db_one(sql, params)
    return row["c"]


async def clear_logs():
    await db_exec("DELETE FROM logs")


async def add_command(user_id, name, response):
    await db_exec("INSERT INTO custom_commands(user_id,name,response) VALUES(?,?,?)",
                  (user_id, name, response))


async def my_commands(user_id):
    return await db_all("SELECT * FROM custom_commands WHERE user_id=? ORDER BY id", (user_id,))


async def get_command(user_id, name):
    return await db_one("SELECT * FROM custom_commands WHERE user_id=? AND name=?", (user_id, name))


async def del_command(user_id, cmd_id):
    await db_exec("DELETE FROM custom_commands WHERE user_id=? AND id=?", (user_id, cmd_id))


async def add_scheduled(chat_id, text, run_at, created_by):
    return await db_exec(
        "INSERT INTO scheduled(chat_id,text,run_at,created_by) VALUES(?,?,?,?)",
        (chat_id, text, run_at, created_by))


async def pending_scheduled():
    return await db_all("SELECT * FROM scheduled WHERE done=0")


async def get_scheduled(sid):
    return await db_one("SELECT * FROM scheduled WHERE id=?", (sid,))


async def my_scheduled(user_id):
    return await db_all(
        "SELECT * FROM scheduled WHERE created_by=? AND done=0 ORDER BY id", (user_id,))


async def finish_scheduled(sid):
    await db_exec("UPDATE scheduled SET done=1 WHERE id=?", (sid,))


async def del_scheduled(user_id, sid):
    await db_exec("DELETE FROM scheduled WHERE created_by=? AND id=? AND done=0", (user_id, sid))

# ═══════════════════════════════════════════════════════
# AUTH — server-side security, har action pe check
# ═══════════════════════════════════════════════════════
class Role(str, Enum):
    OWNER = "owner"
    APPROVED = "approved"
    PENDING = "pending"
    BLOCKED = "blocked"


async def role_of(user_id: int) -> Role:
    if user_id == OWNER_ID:
        return Role.OWNER
    u = await get_user(user_id)
    status = u["status"] if u else "pending"
    try:
        return Role(status)
    except ValueError:
        return Role.PENDING


async def owns_channel(user_id: int, channel_id: int) -> bool:
    ch = await get_channel(channel_id)
    return bool(ch) and (ch["added_by"] == user_id or user_id == OWNER_ID)


async def _deny(update, context, text: str):
    q = update.callback_query if update else None
    try:
        if q is not None:
            await q.answer(f"⛔ {text}"[:190], show_alert=True)
        elif update and update.effective_message:
            await update.effective_message.reply_text(f"⛔ {text}")
    except Exception:
        pass
    raise ApplicationHandlerStop()


async def auth_gate(update, context):
    """Global server-side gate (group -1). Har user-action yahan verify
    hota hai — hidden buttons ya guessed callback data se koi bypass nahi."""
    if update is None or update.channel_post or update.edited_channel_post:
        return
    user = update.effective_user
    if user is None:
        return
    if user.id == OWNER_ID:
        return  # owner bypass
    await ensure_user(user.id, user.username, user.first_name)
    if await get_kv("kill_switch") == "1":
        await _deny(update, context, "🧠 Kill switch active. Try again later.")
    if await get_kv("lockdown") == "1":
        await _deny(update, context, "🔒 Emergency lockdown active.")
    role = await role_of(user.id)
    if role == Role.BLOCKED:
        await _deny(update, context, "🚫 You are blocked.")
    if role != Role.APPROVED:
        if await get_kv("maintenance") == "1":
            await _deny(update, context, "🌙 Maintenance mode active.")
        await _deny(update, context, "⏳ Approval pending. You'll be notified once approved.")


def require(*roles):
    """Defense-in-depth: har handler apna auth khud bhi re-check karta hai."""
    def deco(fn):
        @wraps(fn)
        async def wrapper(update, context, *args, **kwargs):
            user = update.effective_user if update else None
            if user is None:
                return await fn(update, context, *args, **kwargs)
            role = await role_of(user.id)
            if role not in roles:
                await _deny(update, context, "Not authorized.")
            if role != Role.OWNER and await get_kv("kill_switch") == "1":
                await _deny(update, context, "🧠 Kill switch active.")
            return await fn(update, context, *args, **kwargs)
        return wrapper
    return deco

# ═══════════════════════════════════════════════════════
# KEYBOARD HELPERS — inline keyboards + Back/Home/Refresh
# ═══════════════════════════════════════════════════════
def kb(rows):
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton(text, callback_data=data) for text, data in row] for row in rows])


def nav(back=None):
    row = []
    if back:
        row.append(InlineKeyboardButton("⬅️ Back", callback_data=back))
    row.append(InlineKeyboardButton("🏠 Home", callback_data="home"))
    row.append(InlineKeyboardButton("🔄 Refresh", callback_data="refresh"))
    return row


def t(value: bool) -> str:
    return "🟢 ON" if value else "🔴 OFF"


async def show(update, context, text, markup, edit=True):
    context.user_data["last"] = (text, markup)
    q = update.callback_query if update else None
    if q is not None and edit:
        try:
            await q.edit_message_text(text, reply_markup=markup)
        except Exception:
            await q.message.reply_text(text, reply_markup=markup)
        try:
            await q.answer()
        except Exception:
            pass
    else:
        await update.effective_message.reply_text(text, reply_markup=markup)

# ═══════════════════════════════════════════════════════
# UTIL
# ═══════════════════════════════════════════════════════
def clip(s, n=3800):
    s = str(s)
    return s if len(s) <= n else s[:n] + "\n… (truncated)"


def uptime():
    s = int(time.time() - START_TIME)
    d, s = divmod(s, 86400)
    h, s = divmod(s, 3600)
    m, _ = divmod(s, 60)
    return f"{d}d {h}h {m}m"

# ═══════════════════════════════════════════════════════
# START — /start, role-based welcome menu
# ═══════════════════════════════════════════════════════
WELCOME = "🤖 AutoGuard Bot\n🛡️ Smart Channel Management System\n\n"

ROLE_NOTE = {
    "owner": "👑 Owner mode: full access.",
    "approved": "✅ Approved: Control Panel unlocked.",
    "pending": "⏳ Your access request is pending approval.",
    "blocked": "🚫 You are blocked.",
}


def main_menu(role_value: str):
    if role_value == "owner":
        rows = [
            [("🎛️ Control Panel", "u:menu")],
            [("👑 Owner Panel", "o:menu"), ("🖥️ Hosting Panel", "hs:menu")],
            [("📊 Statistics", "u:stats"), ("📖 Help", "u:help")],
            [("🆘 Support", "u:support")],
        ]
    elif role_value == "approved":
        rows = [
            [("🎛️ Control Panel", "u:menu")],
            [("📊 My Statistics", "u:stats"), ("📖 Help", "u:help")],
            [("🆘 Support", "u:support")],
        ]
    elif role_value == "blocked":
        rows = [[("🚫 Blocked", "noop")]]
    else:
        rows = [[("⏳ Approval Pending", "noop")]]
    return kb(rows + [nav()])


@require(Role.OWNER, Role.APPROVED, Role.PENDING, Role.BLOCKED)
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    await ensure_user(u.id, u.username, u.first_name)
    role = await role_of(u.id)
    await show(update, context, WELCOME + ROLE_NOTE[role.value], main_menu(role.value), edit=False)


@require(Role.OWNER, Role.APPROVED)
async def on_home(update, context):
    role = await role_of(update.effective_user.id)
    await show(update, context, WELCOME + ROLE_NOTE[role.value], main_menu(role.value))


@require(Role.OWNER, Role.APPROVED)
async def on_refresh(update, context):
    last = context.user_data.get("last")
    q = update.callback_query
    if last:
        text, markup = last
        try:
            await q.edit_message_text(text, reply_markup=markup)
        except Exception:
            pass
    await q.answer("🔄 Refreshed")


async def on_noop(update, context):
    await update.callback_query.answer("—")


@require(Role.OWNER, Role.APPROVED)
async def cmd_id(update, context):
    c = update.effective_chat
    await update.effective_message.reply_text(f"chat_id: {c.id}\ntitle: {c.title or c.first_name}")

# ═══════════════════════════════════════════════════════
# APPROVAL SYSTEM — Owner only
# ═══════════════════════════════════════════════════════
@require(Role.OWNER)
async def ap_menu(update, context, view="pending"):
    users = await users_by_status(view)
    titles = {"pending": "⏳ Pending users", "approved": "👥 Approved users", "blocked": "🚫 Blocked users"}
    rows = []
    for u in users[:10]:
        uid = u["user_id"]
        name = (u["first_name"] or u["username"] or str(uid))[:14]
        if view == "pending":
            rows.append([(f"✅ {name}", f"ap:a:{uid}"), ("❌", f"ap:r:{uid}")])
        elif view == "approved":
            rows.append([(f"🚫 Block {name}", f"ap:b:{uid}"), ("↩️", f"ap:rev:{uid}")])
        else:
            rows.append([(f"♻️ Unblock {name}", f"ap:ub:{uid}")])
    rows.append([("⏳ Pending", "ap:menu"), ("👥 Approved", "ap:app"), ("🚫 Blocked", "ap:blk")])
    rows.append(nav("o:menu"))
    await show(update, context, f"{titles[view]} — {len(users)} (first 10)", kb(rows))


@require(Role.OWNER)
async def ap_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    d = q.data
    if d == "ap:menu":
        return await ap_menu(update, context, "pending")
    if d == "ap:app":
        return await ap_menu(update, context, "approved")
    if d == "ap:blk":
        return await ap_menu(update, context, "blocked")
    _, action, uid = d.split(":")
    uid = int(uid)
    if action == "a":
        await set_status(uid, "approved")
        await add_log("INFO", "security", uid, None, "user approved")
        try:
            await context.bot.send_message(uid, "✅ You have been approved! Send /start to begin.")
        except Exception:
            pass
        return await ap_menu(update, context, "pending")
    if action == "r":
        await delete_user(uid)
        await add_log("INFO", "security", uid, None, "user rejected")
        try:
            await context.bot.send_message(uid, "❌ Your request was rejected. You may /start again.")
        except Exception:
            pass
        return await ap_menu(update, context, "pending")
    if action == "b":
        await set_status(uid, "blocked")
        await add_log("WARN", "security", uid, None, "user blocked")
        return await ap_menu(update, context, "approved")
    if action == "rev":
        await set_status(uid, "pending")
        await add_log("WARN", "security", uid, None, "approval revoked")
        return await ap_menu(update, context, "approved")
    if action == "ub":
        await set_status(uid, "approved")
        await add_log("INFO", "security", uid, None, "user unblocked")
        return await ap_menu(update, context, "blocked")


@require(Role.OWNER)
async def cmd_pending(update, context):
    users = await users_by_status("pending")
    if not users:
        return await update.effective_message.reply_text("No pending users.")
    await update.effective_message.reply_text(
        "\n".join(f"{u['user_id']} — {u['first_name']}" for u in users))


@require(Role.OWNER)
async def cmd_approve(update, context):
    if not context.args or not context.args[0].lstrip("-").isdigit():
        return await update.effective_message.reply_text("Usage: /approve <user_id>")
    uid = int(context.args[0])
    await set_status(uid, "approved")
    await add_log("INFO", "security", uid, None, "approved via command")
    try:
        await context.bot.send_message(uid, "✅ You have been approved! Send /start.")
    except Exception:
        pass
    await update.effective_message.reply_text(f"✅ Approved {uid}")

# ═══════════════════════════════════════════════════════
# CHANNELS — add (auto-detect) / remove / per-channel settings
# ═══════════════════════════════════════════════════════
@require(Role.OWNER, Role.APPROVED)
async def ch_menu(update, context):
    uid = update.effective_user.id
    chs = await my_channels(uid)
    rows = [[(f"📢 {c['title'] or c['channel_id']}", f"ch:{c['channel_id']}")] for c in chs]
    rows.append([("➕ Add: promote me as admin in your channel", "noop")])
    rows.append(nav("u:menu"))
    await show(update, context, f"📢 My Channels — {len(chs)}", kb(rows))


async def ch_summary(cid):
    ch = await get_channel(cid)
    s = await channel_settings(cid)
    active = sum(1 for v in s["filters"].values() if v)
    ad, qh = s["auto_delete"], s["quiet_hours"]
    return (
        f"📢 {ch['title'] or cid}  ({cid})\n\n"
        f"🗑️ Auto Delete: {t(ad['enabled'])} ({ad['seconds']}s)\n"
        f"🚫 Filters active: {active}\n"
        f"📝 Auto Caption: {t(s['caption']['enabled'])} ({s['caption']['mode']})\n"
        f"🕐 Quiet Hours: {t(qh['enabled'])} {qh['start']}–{qh['end']}\n"
        f"✏️ Edit Detection: {t(s['edit_detect'])}\n"
        f"🧪 Dry Run: {t(s['dry_run'])}\n"
        f"🔔 Notifications: {t(s['notify'])}")


def ch_rows(cid):
    return [
        [("🗑️ Auto Delete", f"ad:{cid}"), ("🚫 Filters", f"flt:{cid}")],
        [("📝 Auto Caption", f"cap:{cid}"), ("🕐 Quiet Hours", f"qh:{cid}")],
        [("✏️ Edit Detect", f"ch:t:{cid}:edit_detect"), ("🧪 Dry Run", f"ch:t:{cid}:dry_run")],
        [("🔔 Notifications", f"ch:t:{cid}:notify"), ("🗑️ Remove", f"ch:rm:{cid}")],
        nav("u:ch"),
    ]


@require(Role.OWNER, Role.APPROVED)
async def ch_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    d = q.data
    uid = update.effective_user.id
    parts = d.split(":")

    if parts[0] == "ch":
        if len(parts) == 2:
            cid = int(parts[1])
            if not await owns_channel(uid, cid):
                await q.answer("⛔ Not your channel.", show_alert=True)
                return
            await show(update, context, await ch_summary(cid), kb(ch_rows(cid)))
        elif parts[1] == "t":
            cid, key = int(parts[2]), parts[3]
            if not await owns_channel(uid, cid):
                await q.answer("⛔ Not your channel.", show_alert=True)
                return
            s = await channel_settings(cid)
            s[key] = not s[key]
            await save_channel_settings(cid, s)
            await show(update, context, await ch_summary(cid), kb(ch_rows(cid)))
        elif parts[1] == "rm":
            cid = int(parts[2])
            await show(update, context, f"Remove channel {cid}?",
                       kb([[("✅ Yes, remove", f"ch:rm2:{cid}"), ("❌ No", f"ch:{cid}")], nav("u:ch")]))
        elif parts[1] == "rm2":
            cid = int(parts[2])
            if await owns_channel(uid, cid):
                await remove_channel(cid)
                await add_log("INFO", "security", uid, cid, "channel removed")
                try:
                    await context.bot.leave_chat(cid)   # 👋 bot channel chhod dega
                except Exception:
                    pass
            await ch_menu(update, context)

    elif parts[0] == "qh":
        if parts[1] in ("tg", "s", "e"):
            action, cid = parts[1], int(parts[2])
        else:
            action, cid = "menu", int(parts[1])
        if not await owns_channel(uid, cid):
            await q.answer("⛔ Not your channel.", show_alert=True)
            return
        s = await channel_settings(cid)
        qq = s["quiet_hours"]
        if action == "menu":
            rows = [
                [(f"🕐 Enabled {t(qq['enabled'])}", f"qh:tg:{cid}")],
                [("🌙 Set start", f"qh:s:{cid}"), ("🌅 Set end", f"qh:e:{cid}")],
                nav(f"ch:{cid}"),
            ]
            await show(update, context,
                       f"🕐 Quiet Hours — auto-delete paused between {qq['start']} and {qq['end']}.",
                       kb(rows))
        elif action == "tg":
            qq["enabled"] = not qq["enabled"]
            await save_channel_settings(cid, s)
            await show(update, context, f"🕐 Quiet Hours {'enabled' if qq['enabled'] else 'disabled'}.",
                       kb([[("⬅️ Back", f"qh:{cid}")], nav(f"ch:{cid}")]))
        else:
            context.user_data["await"] = ("qh_s" if action == "s" else "qh_e", uid, cid)
            await q.answer()
            await q.message.reply_text("Send time as HH:MM (24h).")


async def on_my_chat_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Auto-register a channel the moment an approved user promotes the bot."""
    m = update.my_chat_member
    chat = m.chat
    if chat.type != ChatType.CHANNEL:
        return
    promoter = m.from_user
    if not promoter:
        return
    new = m.new_chat_member.status
    if new == "administrator":
        role = await role_of(promoter.id)
        if role in (Role.OWNER, Role.APPROVED):
            await add_channel(chat.id, chat.title, promoter.id)
            await add_log("INFO", "security", promoter.id, chat.id, f"channel added: {chat.title}")
            try:
                await context.bot.send_message(
                    promoter.id, f"✅ Channel “{chat.title}” registered. Open 🎛️ Control Panel to configure it.")
            except Exception:
                pass
        else:
            await add_log("WARN", "security", promoter.id, chat.id, "denied channel add (not approved)")
    elif new in ("left", "kicked"):
        await add_log("INFO", "security", promoter.id, chat.id, "bot removed from channel")

# ═══════════════════════════════════════════════════════
# AUTO DELETE — timers, pause/resume, /settime
# ═══════════════════════════════════════════════════════
PRESETS = [("⚡5s", 5), ("⚡10s", 10), ("⚡30s", 30), ("1m", 60),
           ("5m", 300), ("15m", 900), ("1h", 3600), ("6h", 21600)]


@require(Role.OWNER, Role.APPROVED)
async def ad_menu(update, context, cid):
    s = await channel_settings(cid)
    ad = s["auto_delete"]
    chunks = [PRESETS[i:i + 4] for i in range(0, len(PRESETS), 4)]
    rows = [[(f"{lbl}", f"ad:s:{cid}:{sec}") for lbl, sec in chunk] for chunk in chunks]
    rows.append([("⏰ Custom", f"ad:c:{cid}"),
                 ("⏸ Pause" if ad["enabled"] else "▶️ Resume", f"ad:tg:{cid}")])
    rows.append(nav(f"ch:{cid}"))
    await show(update, context,
               f"🗑️ Auto Delete\nState: {t(ad['enabled'])} — posts are deleted after {ad['seconds']}s.\n\n"
               "Exemptions: pinned posts & protected-content chats. Quiet Hours pause the timer.",
               kb(rows))


@require(Role.OWNER, Role.APPROVED)
async def ad_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    uid = update.effective_user.id
    _, action, cid, *rest = q.data.split(":")
    cid = int(cid)
    if not await owns_channel(uid, cid):
        await q.answer("⛔ Not your channel.", show_alert=True)
        return
    s = await channel_settings(cid)
    if action == "s":
        s["auto_delete"] = {"enabled": True, "seconds": int(rest[0])}
        await save_channel_settings(cid, s)
        await ad_menu(update, context, cid)
    elif action == "tg":
        s["auto_delete"]["enabled"] = not s["auto_delete"]["enabled"]
        await save_channel_settings(cid, s)
        await ad_menu(update, context, cid)
    elif action == "c":
        context.user_data["await"] = ("ad_custom", uid, cid)
        await q.answer()
        await q.message.reply_text("Send the timer, e.g. 45, 90s, 5m, 2h")


@require(Role.OWNER, Role.APPROVED)
async def cmd_settime(update, context):
    if len(context.args) != 2 or not context.args[0].lstrip("-").isdigit() or not context.args[1].isdigit():
        return await update.effective_message.reply_text("Usage: /settime <channel_id> <seconds>")
    cid, sec = int(context.args[0]), int(context.args[1])
    if not await owns_channel(update.effective_user.id, cid):
        return await update.effective_message.reply_text("⛔ Not your channel.")
    s = await channel_settings(cid)
    s["auto_delete"] = {"enabled": True, "seconds": sec}
    await save_channel_settings(cid, s)
    await update.effective_message.reply_text(f"✅ Auto-delete for {cid} set to {sec}s.")

# ═══════════════════════════════════════════════════════
# FILTERS — 15 filters, har ek ka 🟢/🔴
# ═══════════════════════════════════════════════════════
LABELS = {
    "keyword": "🚫 Keyword", "links": "🔗 Links", "media": "🖼️ Media",
    "forward": "📢 Forward", "bot": "🤖 Bot", "duplicate": "🔁 Duplicate",
    "caps": "🔤 CAPS", "domain": "🌐 Domain", "document": "📄 Documents",
    "gif": "🎞️ GIF", "filesize": "📦 File Size", "length": "📏 Length",
    "flood": "🛡️ Flood", "smartspam": "🧠 Smart Spam", "hashtag": "📍 Hashtag",
}


@require(Role.OWNER, Role.APPROVED)
async def flt_menu(update, context, cid):
    s = await channel_settings(cid)
    items = [(LABELS[f], f"flt:t:{cid}:{f}", s["filters"][f]) for f in FILTERS]
    rows = []
    for i in range(0, len(items), 2):
        rows.append([(f"{lbl} {'🟢' if on else '🔴'}", data) for lbl, data, on in items[i:i + 2]])
    rows.append([("🔤 Keywords", f"flt:kw:{cid}"), ("🌐 Domains", f"flt:dm:{cid}")])
    rows.append(nav(f"ch:{cid}"))
    await show(update, context,
               "🚫 Filters — tap to toggle 🟢 ON / 🔴 OFF.\n"
               "Keywords & blocked domains are set via the buttons below.\n"
               "🛡️ Flood also needs Rate Limit enabled (per-minute limit).",
               kb(rows))


@require(Role.OWNER, Role.APPROVED)
async def flt_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    uid = update.effective_user.id
    parts = q.data.split(":")
    cid = int(parts[1])
    if not await owns_channel(uid, cid):
        await q.answer("⛔ Not your channel.", show_alert=True)
        return
    if parts[2] == "t":
        s = await channel_settings(cid)
        s["filters"][parts[3]] = not s["filters"][parts[3]]
        await save_channel_settings(cid, s)
        await flt_menu(update, context, cid)
    elif parts[2] == "kw":
        context.user_data["await"] = ("kw", uid, cid)
        await q.answer()
        cur = ", ".join((await channel_settings(cid))["keyword_blacklist"])
        await q.message.reply_text("Send keywords (comma/newline separated).\nCurrent: " + (cur or "(none)"))
    elif parts[2] == "dm":
        context.user_data["await"] = ("dm", uid, cid)
        await q.answer()
        await q.message.reply_text("Send blocked domains (e.g. example.com), comma separated.")

# ═══════════════════════════════════════════════════════
# AUTO CAPTION — replace / append
# ═══════════════════════════════════════════════════════
@require(Role.OWNER, Role.APPROVED)
async def cap_menu(update, context, cid):
    c = (await channel_settings(cid))["caption"]
    rows = [
        [(f"📝 Enabled {t(c['enabled'])}", f"cap:tg:{cid}")],
        [("✅ Replace" if c["mode"] == "replace" else "Replace", f"cap:m:{cid}:replace"),
         ("✅ Append" if c["mode"] == "append" else "Append", f"cap:m:{cid}:append")],
        [("✏️ Edit text", f"cap:txt:{cid}")],
        nav(f"ch:{cid}"),
    ]
    await show(update, context,
               f"📝 Auto Caption — {t(c['enabled'])} ({c['mode']})\nText: {clip(c['text'], 300) or '(empty)'}",
               kb(rows))


@require(Role.OWNER, Role.APPROVED)
async def cap_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    uid = update.effective_user.id
    _, action, cid, *rest = q.data.split(":")
    cid = int(cid)
    if not await owns_channel(uid, cid):
        await q.answer("⛔ Not your channel.", show_alert=True)
        return
    s = await channel_settings(cid)
    if action == "tg":
        s["caption"]["enabled"] = not s["caption"]["enabled"]
        await save_channel_settings(cid, s)
        await cap_menu(update, context, cid)
    elif action == "m":
        s["caption"]["mode"] = rest[0]
        await save_channel_settings(cid, s)
        await cap_menu(update, context, cid)
    elif action == "txt":
        context.user_data["await"] = ("cap_text", uid, cid)
        await q.answer()
        await q.message.reply_text("Send the caption text (max 1000 chars).")

# ═══════════════════════════════════════════════════════
# MESSAGE ENGINE — filter → caption → auto-delete 🔥
# ═══════════════════════════════════════════════════════
URL_RE = re.compile(r"(?:https?://|www\.)\S+", re.IGNORECASE)
DOM_RE = re.compile(r"https?://([^/\s:]+)", re.IGNORECASE)
TAG_RE = re.compile(r"#[A-Za-z0-9_]+")

_dups = defaultdict(OrderedDict)
_flood = defaultdict(lambda: defaultdict(deque))


def flush_caches():
    _dups.clear()
    _flood.clear()


def _msg_text(m):
    return m.text or m.caption or ""


def check_violation(m, s):
    """Violation ka naam return karo, ya None."""
    f = s["filters"]
    txt = _msg_text(m)
    sender = m.from_user
    if f["bot"] and sender and sender.is_bot:
        return "bot"
    if f["forward"] and (getattr(m, "forward_origin", None) or m.is_automatic_forward):
        return "forward"
    if f["media"] and (m.photo or m.video):
        return "media"
    if f["document"] and m.document:
        return "document"
    if f["gif"] and m.animation:
        return "gif"
    if f["links"] and URL_RE.search(txt):
        return "links"
    if f["hashtag"] and TAG_RE.search(txt):
        return "hashtag"
    if f["keyword"]:
        low = txt.lower()
        if any(k.lower() in low for k in s["keyword_blacklist"]):
            return "keyword"
    if f["length"] and len(txt) > s["max_length"]:
        return "length"
    if f["caps"]:
        letters = [c for c in txt if c.isalpha()]
        if len(letters) >= 10 and sum(c.isupper() for c in letters) * 100 / len(letters) >= s["caps_percent"]:
            return "caps"
    if f["filesize"]:
        cands = [x for x in (m.document, m.video, m.audio, m.animation, m.video_note) if x]
        size = max([x.file_size or 0 for x in cands] or [0])
        if size > s["max_file_mb"] * 1_000_000:
            return "filesize"
    if f["domain"] and s["blocked_domains"]:
        for host in DOM_RE.findall(txt):
            host = host.lower()
            for d in s["blocked_domains"]:
                d = d.lower().strip()
                if d and (host == d or host.endswith("." + d)):
                    return "domain"
    if f["duplicate"] and txt:
        h = hashlib.sha1(txt.encode()).hexdigest()
        cache = _dups[m.chat_id]
        if h in cache:
            return "duplicate"
        cache[h] = 1
        cache.move_to_end(h)
        while len(cache) > 500:
            cache.popitem(last=False)
    if f["flood"] and s["rate_limit"]["enabled"] and sender:
        dq = _flood[m.chat_id][sender.id]
        now = time.time()
        dq.append(now)
        while dq and now - dq[0] > 60:
            dq.popleft()
        if len(dq) > s["rate_limit"]["per_minute"]:
            return "flood"
    if f["smartspam"]:
        letters = [c for c in txt if c.isalpha()]
        emoji = sum(1 for c in txt if ord(c) > 0x1F000)
        ratio = (sum(c.isupper() for c in letters) / len(letters)) if letters else 0
        if (emoji >= 5 and ratio >= 0.4) or (txt and len(set(txt)) <= 3 and len(txt) > 12):
            return "smartspam"
    return None


def in_quiet(s):
    q = s["quiet_hours"]
    if not q["enabled"]:
        return False

    def mins(x):
        try:
            h, m = x.split(":")
            return int(h) * 60 + int(m)
        except Exception:
            return None

    a, b = mins(q["start"]), mins(q["end"])
    if a is None or b is None:
        return False
    now = datetime.now()
    cur = now.hour * 60 + now.minute
    if a <= b:
        return a <= cur < b
    return cur >= a or cur < b  # overnight window


async def _get_ctx(update, context):
    msg = update.channel_post or update.edited_channel_post
    if msg is None:
        return None
    ch = await get_channel(msg.chat_id)
    if not ch:
        return None
    return msg, ch, await channel_settings(msg.chat_id)


async def _delete(context, cid, mid, why):
    try:
        await context.bot.delete_message(cid, mid)
        await add_log("INFO", "delete", None, cid, f"deleted {mid} ({why})")
    except Exception as e:
        await add_log("ERROR", "delete", None, cid, f"{mid}: {e}")


async def on_post(update, context):
    if await get_kv("kill_switch") == "1" or await get_kv("lockdown") == "1":
        return
    got = await _get_ctx(update, context)
    if not got:
        return
    msg, ch, s = got

    violation = check_violation(msg, s)
    if violation:
        if s["dry_run"]:
            await add_log("INFO", "dryrun", None, msg.chat_id,
                          f"would delete ({violation}): {_msg_text(msg)[:80]}")
        else:
            await add_log("INFO", "filter", None, msg.chat_id, f"{violation}: {_msg_text(msg)[:80]}")
            await _delete(context, msg.chat_id, msg.message_id, violation)
        if s["notify"] and ch["added_by"]:
            try:
                await context.bot.send_message(
                    ch["added_by"],
                    f"{'🧪 Dry run: ' if s['dry_run'] else '🚫 '}{msg.chat.title}: {violation}")
            except Exception:
                pass
        return

    cap = s["caption"]
    if (cap["enabled"] and cap["text"] and not s["dry_run"]
            and (msg.photo or msg.video or msg.animation or msg.document)):
        new = cap["text"] if cap["mode"] == "replace" else ((_msg_text(msg) + "\n\n" + cap["text"]).strip())
        try:
            await context.bot.edit_message_caption(chat_id=msg.chat_id, message_id=msg.message_id,
                                                   caption=new[:1024])
        except Exception as e:
            await add_log("ERROR", "caption", None, msg.chat_id, str(e)[:150])

    ad = s["auto_delete"]
    if not ad["enabled"] or in_quiet(s):
        return
    if getattr(msg.chat, "has_protected_content", False):
        return  # 🧷 protected content exception
    try:
        info = await context.bot.get_chat(msg.chat_id)
        if getattr(info, "pinned_message", None) and info.pinned_message.message_id == msg.message_id:
            return  # 📌 pinned post exception
    except Exception:
        pass
    context.job_queue.run_once(del_job, ad["seconds"],
                               data={"cid": msg.chat_id, "mid": msg.message_id})


async def on_edited(update, context):
    got = await _get_ctx(update, context)
    if not got:
        return
    msg, ch, s = got
    if not s["edit_detect"]:
        return
    if s["dry_run"]:
        await add_log("INFO", "dryrun", None, msg.chat_id, "would delete edited post")
    else:
        await add_log("INFO", "filter", None, msg.chat_id, "edited post deleted")
        await _delete(context, msg.chat_id, msg.message_id, "edited")


async def del_job(context):
    d = context.job.data
    await _delete(context, d["cid"], d["mid"], "timer")

# ═══════════════════════════════════════════════════════
# SCHEDULED MESSAGES — restart recovery ke saath
# ═══════════════════════════════════════════════════════
@require(Role.OWNER, Role.APPROVED)
async def sch_menu(update, context):
    uid = update.effective_user.id
    rows_ = await my_scheduled(uid)
    rows = [[(f"⏰ #{r['id']} → {r['chat_id']} @ {r['run_at'][:16]}", f"sch:del:{r['id']}")]
            for r in rows_[:10]]
    rows.append([("➕ Add", "sch:add")])
    rows.append(nav("u:menu"))
    await show(update, context, "📅 Scheduled Messages — tap an entry to delete it.", kb(rows))


@require(Role.OWNER, Role.APPROVED)
async def sch_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    uid = update.effective_user.id
    if q.data == "sch:add":
        context.user_data["await"] = ("sch_add", uid)
        await q.answer()
        await q.message.reply_text("Send: channel_id | minutes | text")
    elif q.data.startswith("sch:del:"):
        await del_scheduled(uid, int(q.data.split(":")[2]))
        await sch_menu(update, context)


async def fire(context: ContextTypes.DEFAULT_TYPE):
    sid = context.job.data["sid"]
    row = await get_scheduled(sid)
    if not row or row["done"]:
        return
    try:
        await context.bot.send_message(row["chat_id"], row["text"])
        await add_log("INFO", "schedule", row["created_by"], row["chat_id"], "scheduled message sent")
    except Exception as e:
        await add_log("ERROR", "schedule", None, row["chat_id"], str(e)[:200])
    await finish_scheduled(sid)


async def rearm(app):
    """🔄 Restart recovery: pending scheduled messages dobara set karo."""
    now = datetime.now(timezone.utc)
    for r in await pending_scheduled():
        try:
            run_at = datetime.fromisoformat(r["run_at"])
        except Exception:
            continue
        delay = max((run_at - now).total_seconds(), 0)
        app.job_queue.run_once(fire, delay, data={"sid": r["id"]})

# ═══════════════════════════════════════════════════════
# CUSTOM COMMANDS — !name trigger
# ═══════════════════════════════════════════════════════
@require(Role.OWNER, Role.APPROVED)
async def cc_menu(update, context):
    uid = update.effective_user.id
    cmds = await my_commands(uid)
    rows = [[(f"🧩 !{c['name']}", f"cc:del:{c['id']}")] for c in cmds[:15]]
    rows.append([("➕ Add", "cc:add")])
    rows.append(nav("u:menu"))
    await show(update, context, "🧩 Custom Commands — tap to delete. Trigger in chat with !name", kb(rows))


@require(Role.OWNER, Role.APPROVED)
async def cc_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    uid = update.effective_user.id
    if q.data == "cc:add":
        context.user_data["await"] = ("cc_add", uid)
        await q.answer()
        await q.message.reply_text("Send: name = response")
    elif q.data.startswith("cc:del:"):
        await del_command(uid, int(q.data.split(":")[2]))
        await cc_menu(update, context)

# ═══════════════════════════════════════════════════════
# USER PANEL — stats, logs, help
# ═══════════════════════════════════════════════════════
@require(Role.OWNER, Role.APPROVED)
async def up_menu(update, context):
    rows = [
        [("📢 My Channels", "u:ch")],
        [("📊 My Statistics", "u:stats"), ("📜 My Logs", "u:logs")],
        [("📅 Scheduled Messages", "sch:menu"), ("🧩 Custom Commands", "cc:menu")],
        [("📖 Help", "u:help"), ("🆘 Support", "u:support")],
        nav("home"),
    ]
    await show(update, context, "🎛️ Control Panel", kb(rows))


async def up_stats_text(uid):
    chs = await my_channels(uid)
    lines = ["📊 Statistics"]
    td = tdel = tfil = 0
    for c in chs:
        cid = c["channel_id"]
        deleted = await count_logs(category="delete", chat_id=cid)
        filtered = await count_logs(category="filter", chat_id=cid)
        today = await count_logs(category="delete", chat_id=cid, today=True)
        td += today; tdel += deleted; tfil += filtered
        lines.append(f"• {c['title'] or cid}: 🗑️ {deleted} | 🚫 {filtered} | 📅 {today} today")
    lines.append("")
    lines.append(f"Total: 🗑️ {tdel} | 🚫 {tfil} | 📅 {td} today | ⏱️ {uptime()}")
    return "\n".join(lines)


@require(Role.OWNER, Role.APPROVED)
async def up_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    d = q.data
    uid = update.effective_user.id
    if d == "u:menu":
        await up_menu(update, context)
    elif d == "u:stats":
        await show(update, context, await up_stats_text(uid), kb([nav("u:menu")]))
    elif d == "u:logs":
        chs = await my_channels(uid)
        logs = []
        for c in chs:
            logs += await recent_logs(limit=8, chat_id=c["channel_id"])
        logs.sort(key=lambda r: r["id"], reverse=True)
        body = "\n".join(f"{r['ts']} [{r['category']}] {r['text']}" for r in logs[:15]) or "No logs yet."
        await show(update, context, "📜 Recent logs:\n" + clip(body, 3500),
                   kb([[("📤 Export", "u:logsx")], nav("u:menu")]))
    elif d == "u:logsx":
        chs = await my_channels(uid)
        logs = []
        for c in chs:
            logs += await recent_logs(limit=300, chat_id=c["channel_id"])
        body = "\n".join(f"{r['ts']} [{r['level']}/{r['category']}] {r['text']}" for r in logs) or "empty"
        await q.message.reply_document(document=io.BytesIO(body.encode()), filename="my_logs.txt")
        await q.answer("📤 Exported")
    elif d == "u:help":
        await show(update, context, HELP, kb([nav("u:menu")]))
    elif d == "u:support":
        await show(update, context, "🆘 Contact the bot owner for support.", kb([nav("u:menu")]))


@require(Role.OWNER, Role.APPROVED)
async def cmd_stats(update, context):
    await update.effective_message.reply_text(await up_stats_text(update.effective_user.id))


HELP = """📖 Help
• Add me to your channel as admin (Delete-messages permission) — the channel auto-registers.
• Control Panel → My Channels → pick a channel to configure.
• 🗑️ Auto Delete: posts are deleted after N seconds (5s…6h, or custom).
• 🚫 Filters: each filter is 🟢/🔴 per channel.
• 📝 Auto Caption: replace or append captions on media.
• 🧪 Dry Run: preview deletions without deleting.
• 🕐 Quiet Hours: auto-delete paused during the window.
• 🧩 Custom Commands: create "name = response", trigger with !name.

Commands:
/start — main menu | /id — chat id
/settime <channel_id> <seconds> | /stats
Owner: /pending, /approve <user_id>"""

# ═══════════════════════════════════════════════════════
# OWNER PANEL — dashboard, broadcast, backup, modes
# ═══════════════════════════════════════════════════════
@require(Role.OWNER)
async def own_menu(update, context):
    rows = [
        [("📊 Dashboard", "o:dash"), ("👥 Users", "ap:menu")],
        [("📢 Broadcast", "bc:menu"), ("📣 Announcement", "an:menu")],
        [("💾 Backup & Restore", "bk:menu"), ("🩺 System Health", "o:health")],
        [("📜 Logs", "o:logs"), ("🧹 Cleanup", "o:clean")],
        [("⚡ Modes", "o:modes"), ("⚙️ Config Preview", "o:cfg")],
        [("🖥️ Hosting Panel", "hs:menu")],
        nav("home"),
    ]
    await show(update, context, "👑 Owner Panel", kb(rows))


async def own_modes(update, context):
    kill = await get_kv("kill_switch", "0") == "1"
    lock = await get_kv("lockdown", "0") == "1"
    maint = await get_kv("maintenance", "0") == "1"
    rows = [
        [(f"🧠 Kill Switch {t(kill)}", "o:kill"), (f"🔒 Lockdown {t(lock)}", "o:lock")],
        [(f"🌙 Maintenance {t(maint)}", "o:maint")],
        [("🔴 Strict", "o:mode:strict"), ("🟡 Normal", "o:mode:normal"), ("🟢 Relaxed", "o:mode:relaxed")],
        nav("o:menu"),
    ]
    await show(update, context,
               "⚡ Modes — Kill Switch/Lockdown block all non-owner activity; "
               "presets apply filter sets to every channel.", kb(rows))


@require(Role.OWNER)
async def own_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    d = q.data
    uid = update.effective_user.id

    if d == "o:menu":
        return await own_menu(update, context)

    if d == "o:dash":
        txt = (
            "📊 Dashboard\n\n"
            f"👥 Users: {await count_users()} "
            f"(✅ {await count_users('approved')}, ⏳ {await count_users('pending')}, "
            f"🚫 {await count_users('blocked')})\n"
            f"📢 Channels: {len(await all_channels())}\n"
            f"🗑️ Deleted posts: {await count_logs(category='delete')}\n"
            f"🚫 Filtered posts: {await count_logs(category='filter')}\n"
            f"⚠️ Errors: {await count_logs(errors=True)}\n"
            f"⏱️ Uptime: {uptime()}"
        )
        return await show(update, context, txt, kb([nav("o:menu")]))

    if d == "o:health":
        proc = psutil.Process()
        txt = (
            "🩺 System Health\n\n"
            f"🖥️ CPU: {psutil.cpu_percent(interval=None)}%\n"
            f"💾 RAM: {psutil.virtual_memory().percent}% (bot: {proc.memory_info().rss // (1024 * 1024)} MB)\n"
            f"🗄️ Disk: {psutil.disk_usage('.').percent}%\n"
            f"⏱️ Uptime: {uptime()}\n"
            f"🔄 Process: running (pid {proc.pid})\n"
            f"⚠️ Errors logged: {await count_logs(errors=True)}"
        )
        return await show(update, context, txt, kb([nav("o:menu")]))

    if d == "o:logs":
        logs = await recent_logs(limit=25)
        body = "\n".join(f"{r['ts']} [{r['level']}/{r['category']}] {r['text']}" for r in logs) or "No logs."
        return await show(update, context, "📜 Recent logs:\n" + clip(body),
                          kb([[("📤 Export", "o:logsx"), ("🧹 Clear", "o:clrc")], nav("o:menu")]))

    if d == "o:logsx":
        logs = await recent_logs(limit=1000)
        body = "\n".join(f"{r['ts']} [{r['level']}/{r['category']}] chat={r['chat_id']} {r['text']}"
                         for r in logs) or "empty"
        await q.message.reply_document(document=io.BytesIO(body.encode()), filename="logs.txt")
        return await q.answer("📤 Exported")

    if d == "o:clrc":
        return await show(update, context, "Clear ALL logs?",
                          kb([[("✅ Yes", "o:clrc2"), ("❌ No", "o:logs")], nav("o:menu")]))
    if d == "o:clrc2":
        await clear_logs()
        return await show(update, context, "🧹 Logs cleared.", kb([nav("o:menu")]))

    if d == "o:clean":
        flush_caches()
        return await show(update, context,
                          "🧹 Cleanup\n\n✅ Duplicate-detection cache flushed.\n"
                          "ℹ️ The Bot API cannot fetch channel history, so historical purge is impossible — "
                          "Auto Delete covers everything posted after the bot joined.",
                          kb([[("🧹 Clear logs", "o:clrc")], nav("o:menu")]))

    if d == "o:modes":
        return await own_modes(update, context)
    if d in ("o:kill", "o:lock", "o:maint"):
        key = d.split(":")[1]
        await set_kv(key, "0" if await get_kv(key, "0") == "1" else "1")
        await add_log("WARN", "security", uid, None, f"{key} -> {await get_kv(key)}")
        return await own_modes(update, context)
    if d.startswith("o:mode:"):
        preset = d.split(":")[2]
        enabled = {"strict": set(FILTERS),
                   "normal": {"links", "forward", "caps", "flood", "keyword"},
                   "relaxed": set()}[preset]
        n = 0
        for c in await all_channels():
            s = await channel_settings(c["channel_id"])
            for f in FILTERS:
                s["filters"][f] = f in enabled
            await save_channel_settings(c["channel_id"], s)
            n += 1
        return await show(update, context, f"⚡ Preset “{preset}” applied to {n} channels.",
                          kb([nav("o:menu")]))

    if d == "o:cfg":
        parts = []
        for c in await all_channels():
            s = await channel_settings(c["channel_id"])
            parts.append(f"{c['channel_id']} ({c['title']}): " + json.dumps(s, ensure_ascii=False))
        return await show(update, context,
                          "⚙️ Configuration Preview\n\n" + clip("\n".join(parts) or "(no channels)"),
                          kb([nav("o:menu")]))

    if d == "bk:menu":
        return await show(update, context, "💾 Backup & Restore", kb([
            [("💾 Download DB backup", "bk:dl")],
            [("📤 Export configuration", "bk:cfg")],
            [("📥 Restore DB (send file)", "bk:res")],
            [("♻️ Reset configuration", "bk:reset")],
            nav("o:menu")]))
    if d == "bk:dl":
        await q.answer()
        with open(DB_PATH, "rb") as fh:
            await q.message.reply_document(document=fh, filename="autoguard_backup.db")
        return
    if d == "bk:cfg":
        data = {str(c["channel_id"]): await channel_settings(c["channel_id"])
                for c in await all_channels()}
        await q.message.reply_document(
            document=io.BytesIO(json.dumps(data, indent=2).encode()), filename="config.json")
        return await q.answer("📤 Exported")
    if d == "bk:res":
        context.user_data["await"] = ("restore", uid)
        await q.answer()
        return await q.message.reply_text("📥 Send the .db backup file as a document.")
    if d == "bk:reset":
        return await show(update, context, "♻️ Reset ALL channel configuration to defaults?",
                          kb([[("✅ Yes, reset", "bk:reset2"), ("❌ No", "bk:menu")], nav("o:menu")]))
    if d == "bk:reset2":
        for c in await all_channels():
            await save_channel_settings(c["channel_id"], {})
        for k in ("kill_switch", "lockdown", "maintenance"):
            await set_kv(k, "0")
        await add_log("WARN", "security", uid, None, "configuration reset")
        return await show(update, context, "♻️ Configuration reset to defaults.", kb([nav("o:menu")]))

    if d == "bc:menu":
        return await show(update, context,
                          "📢 Broadcast (OWNER ONLY)\nSend a message to every approved user.",
                          kb([[("📢 Compose", "bc:go")], nav("o:menu")]))
    if d == "bc:go":
        context.user_data["await"] = ("bc", uid)
        await q.answer()
        return await q.message.reply_text("📢 Send the broadcast text now.")

    if d == "an:menu":
        chs = await all_channels()
        rows = [[(f"📣 {c['title'] or c['channel_id']}", f"an:{c['channel_id']}")] for c in chs]
        rows.append(nav("o:menu"))
        return await show(update, context, "📣 Channel Announcement — pick a channel.", kb(rows))
    if d.startswith("an:"):
        cid = int(d.split(":")[1])
        context.user_data["await"] = ("an", uid, cid)
        await q.answer()
        return await q.message.reply_text("📣 Send the announcement text now.")


@require(Role.OWNER)
async def own_document(update, context):
    aw = context.user_data.get("await") or ("",)
    if aw[0] != "restore":
        return
    context.user_data["await"] = None
    doc = update.effective_message.document
    path = DB_PATH + ".restore"
    f = await doc.get_file()
    await f.download_to_drive(path)
    await update.effective_message.reply_text(
        f"📥 Backup saved to {path}.\nTo restore: stop the bot, replace the DB file with this backup, restart.")

# ═══════════════════════════════════════════════════════
# 🖥️ HOSTING PANEL — OWNER ONLY + 🧰 AUTO MODULES
# ═══════════════════════════════════════════════════════
os.makedirs(SANDBOX_DIR, exist_ok=True)
DEPS = os.path.join(SANDBOX_DIR, ".deps")
PROCS = {}  # name -> {"proc": ..., "restarts": int}

WARN = ("⚠️ Uploaded programs run with CPU/RAM/file-size limits in an isolated working directory. "
        "This is NOT a security sandbox — for untrusted code use Docker/nsjail.")

# import name → pip package name (baaki same maante hain)
MODULE_ALIASES = {
    "cv2": "opencv-python-headless",
    "PIL": "Pillow",
    "yaml": "PyYAML",
    "bs4": "beautifulsoup4",
    "sklearn": "scikit-learn",
    "Crypto": "pycryptodome",
    "dotenv": "python-dotenv",
    "dateutil": "python-dateutil",
    "serial": "pyserial",
    "docx": "python-docx",
    "pptx": "python-pptx",
    "fitz": "PyMuPDF",
}
STDLIB = set(getattr(sys, "stdlib_module_names", ()))  # Python 3.10+


def detect_imports(path):
    """AST parse karke top-level module names nikalo."""
    try:
        with open(path, encoding="utf-8", errors="ignore") as fh:
            tree = ast.parse(fh.read())
    except SyntaxError:
        return []
    mods = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                mods.add(a.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            mods.add(node.module.split(".")[0])
    return sorted(mods)


def is_local(mod):
    return (os.path.exists(os.path.join(SANDBOX_DIR, mod + ".py"))
            or os.path.isdir(os.path.join(SANDBOX_DIR, mod)))


async def installed_pkgs():
    return set((await get_kv("host_pkgs", "") or "").split(",")) - {""}


async def remember_pkg(pkg):
    cur = await installed_pkgs()
    base = pkg.split("==")[0].split(">=")[0].split("<")[0].strip()
    cur.add(base)
    await set_kv("host_pkgs", ",".join(sorted(cur)))


async def missing_packages(name):
    path = os.path.join(SANDBOX_DIR, name)
    if not name.endswith(".py"):
        return []
    done = await installed_pkgs()
    need = []
    for m in detect_imports(path):
        if m in STDLIB or is_local(m):
            continue
        try:
            found = importlib.util.find_spec(m) is not None
        except (ValueError, ModuleNotFoundError):
            found = False
        if not found and m not in done:
            need.append(MODULE_ALIASES.get(m, m))
    return sorted(set(need))


async def pip_install(pkgs):
    os.makedirs(DEPS, exist_ok=True)
    proc = await asyncio.create_subprocess_exec(
        sys.executable, "-m", "pip", "install", "--target", DEPS, *pkgs,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
    try:
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=180)
    except asyncio.TimeoutError:
        proc.kill()
        return 124, "timeout"
    return proc.returncode, out.decode(errors="replace")


async def pip_install_reqs(path):
    os.makedirs(DEPS, exist_ok=True)
    proc = await asyncio.create_subprocess_exec(
        sys.executable, "-m", "pip", "install", "--target", DEPS, "-r", path,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
    try:
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=300)
    except asyncio.TimeoutError:
        proc.kill()
        return 124, "timeout"
    return proc.returncode, out.decode(errors="replace")


async def scan_and_install(name, context):
    """🧰 Scan karo → missing modules install karo → report do."""
    pkgs = await missing_packages(name)
    if not pkgs:
        return True, "✅ Sab modules already available hain."
    ok, fails = [], []
    for pkg in pkgs:
        code, out = await pip_install([pkg])
        if code == 0:
            ok.append(pkg)
            await remember_pkg(pkg)
        else:
            fails.append(pkg)
        await add_log("INFO" if code == 0 else "ERROR", "hosting", None, None,
                      f"auto-install {pkg}: rc={code}")
    msg = f"🧰 Installed: {', '.join(ok) or '—'}"
    if fails:
        msg += f"\n❌ Failed: {', '.join(fails)}"
    return not fails, msg


def _rlimits():
    import resource
    resource.setrlimit(resource.RLIMIT_CPU, (HOST_CPU_SEC, HOST_CPU_SEC))
    resource.setrlimit(resource.RLIMIT_AS, (HOST_RAM_MB * 1024 * 1024,) * 2)
    resource.setrlimit(resource.RLIMIT_FSIZE, (64 * 1024 * 1024,) * 2)


def _cmd(path):
    if path.endswith(".py"):
        return [sys.executable, path]
    if path.endswith(".sh"):
        return ["bash", path]
    return None


def _files():
    try:
        return sorted(f for f in os.listdir(SANDBOX_DIR)
                      if not f.startswith(".") and not f.endswith(".log")
                      and os.path.isfile(os.path.join(SANDBOX_DIR, f)))
    except FileNotFoundError:
        return []


def _running(name):
    info = PROCS.get(name)
    return bool(info and info["proc"].returncode is None)


async def _env():
    env = dict(os.environ)
    env["PYTHONPATH"] = DEPS  # 🧰 .deps se modules load honge
    for line in (await get_kv("host_env") or "").splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip()
    return env


async def start_proc(name, context):
    path = os.path.join(SANDBOX_DIR, name)
    cmd = _cmd(path)
    if not cmd:
        return False, "Only .py and .sh files can be executed."
    if _running(name):
        return False, "Already running."
    logf = open(os.path.join(SANDBOX_DIR, name + ".log"), "ab")
    proc = await asyncio.create_subprocess_exec(
        *cmd, cwd=SANDBOX_DIR, stdout=logf, stderr=logf,
        preexec_fn=_rlimits, start_new_session=True, env=await _env())
    prev = PROCS.get(name)
    PROCS[name] = {"proc": proc, "restarts": (prev or {}).get("restarts", 0)}
    await add_log("INFO", "hosting", None, None, f"started {name} (pid {proc.pid})")
    context.application.create_task(_watch(name, context))
    return True, f"▶️ Started {name} (pid {proc.pid})"


async def _watch(name, context):
    """🔁 Auto-restart supervisor (max 3 tries, sirf tab jab enabled ho)."""
    info = PROCS.get(name)
    if not info:
        return
    rc = await info["proc"].wait()
    await add_log("WARN", "hosting", None, None, f"{name} exited (rc={rc})")
    if await get_kv("host_autorestart", "0") == "1" and rc != 0:
        info["restarts"] += 1
        if info["restarts"] <= 3:
            await asyncio.sleep(2)
            await start_proc(name, context)


async def stop_proc(name):
    info = PROCS.get(name)
    if not info or info["proc"].returncode is not None:
        return False, "Not running."
    info["proc"].terminate()
    try:
        await asyncio.wait_for(info["proc"].wait(), timeout=10)
    except asyncio.TimeoutError:
        info["proc"].kill()
    return True, f"⏹️ Stopped {name}"


@require(Role.OWNER)
async def host_menu(update, context):
    files = _files()
    has_reqs = os.path.exists(os.path.join(SANDBOX_DIR, "requirements.txt"))
    rows = [[(f"{'🟢' if _running(f) else '⚪'} {f}", f"hs:f:{f}")] for f in files[:12]]
    rows.append([("📤 Upload", "hs:up"), ("📊 Status", "hs:stat")])
    rows.append([("🧰 Auto-Install", "hs:ai"), ("♻️ Auto-restart", "hs:ar")])
    rows.append([("📦 requirements.txt", "hs:req"), ("🧰 pip install", "hs:pip"), ("🌿 Env vars", "hs:env")])
    rows.append(nav("o:menu"))
    ai = await get_kv("host_autoinst", "0") == "1"
    ar = await get_kv("host_autorestart", "0") == "1"
    txt = (f"🖥️ Hosting Panel — {len(files)} file(s)\n\n{WARN}\n\n"
           f"🧰 Auto-Install: {t(ai)}\n"
           f"♻️ Auto-restart: {t(ar)}\n"
           f"📦 requirements.txt: {'✅ uploaded' if has_reqs else '❌ not uploaded'}")
    await show(update, context, txt, kb(rows))


@require(Role.OWNER)
async def host_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    d = q.data
    uid = update.effective_user.id
    parts = d.split(":")

    if d == "hs:menu":
        return await host_menu(update, context)
    if d == "hs:up":
        context.user_data["await"] = ("host_up", uid)
        await q.answer()
        return await q.message.reply_text(
            f"📤 Send a .py, .sh file ya requirements.txt (max {MAX_UPLOAD_MB} MB).")
    if d == "hs:ai":
        await set_kv("host_autoinst", "0" if await get_kv("host_autoinst", "0") == "1" else "1")
        return await host_menu(update, context)
    if d == "hs:ar":
        await set_kv("host_autorestart", "0" if await get_kv("host_autorestart", "0") == "1" else "1")
        return await host_menu(update, context)
    if d == "hs:pip":
        context.user_data["await"] = ("host_pip", uid)
        await q.answer()
        return await q.message.reply_text("🧰 Send package names, space separated.")
    if d == "hs:env":
        context.user_data["await"] = ("host_env", uid)
        await q.answer()
        cur = await get_kv("host_env", "")
        return await q.message.reply_text(f"🌿 Send KEY=VALUE lines.\nCurrent:\n{cur or '(none)'}")
    if d == "hs:req":
        path = os.path.join(SANDBOX_DIR, "requirements.txt")
        if not os.path.exists(path):
            await q.answer("📤 Pehle requirements.txt upload karo (Upload → file bhejo).", show_alert=True)
            return await host_menu(update, context)
        with open(path, encoding="utf-8", errors="ignore") as fh:
            pkgs = [l.strip() for l in fh if l.strip() and not l.startswith("#")]
        if not pkgs:
            await q.answer("requirements.txt khali hai.", show_alert=True)
            return await host_menu(update, context)
        await q.answer(f"📦 {len(pkgs)} packages install ho rahe hain…")
        code, out = await pip_install_reqs(path)
        if code == 0:
            for line in pkgs:
                await remember_pkg(line)
        await add_log("INFO" if code == 0 else "ERROR", "hosting", uid, None,
                      f"requirements.txt install rc={code}")
        await q.message.reply_text(f"📦 requirements.txt → exit={code}\n{out[-1000:]}")
        return await host_menu(update, context)
    if d == "hs:stat":
        lines = []
        for name, info in PROCS.items():
            p = info["proc"]
            if p.returncode is None:
                try:
                    mem = psutil.Process(p.pid).memory_info().rss // (1024 * 1024)
                    lines.append(f"🟢 {name} pid={p.pid} ram={mem}MB")
                except Exception:
                    lines.append(f"🟢 {name} pid={p.pid}")
            else:
                lines.append(f"⚪ {name} exited rc={p.returncode}")
        return await show(update, context, "📊 Processes:\n" + ("\n".join(lines) or "(none)"),
                          kb([nav("hs:menu")]))

    name = parts[2]
    if not all(c.isalnum() or c in "._-" for c in name) or name.startswith("."):
        await q.answer("⛔ Bad filename", show_alert=True)
        return

    if parts[1] == "f":
        state = "🟢 running" if _running(name) else "⚪ stopped"
        return await show(update, context, f"📁 {name}\n{state}", kb([
            [("▶️ Start", f"hs:run:{name}"), ("⏹️ Stop", f"hs:stop:{name}")],
            [("🔄 Restart", f"hs:res:{name}"), ("📜 Logs", f"hs:log:{name}")],
            [("🧰 Scan & Install", f"hs:am:{name}"), ("🗑️ Delete", f"hs:del:{name}")],
            nav("hs:menu")]))
    if parts[1] == "am":
        await q.answer("🔍 Scanning…")
        oki, msgi = await scan_and_install(name, context)
        await q.message.reply_text(msgi)
        return await host_menu(update, context)
    if parts[1] == "run":
        if await get_kv("host_autoinst", "0") == "1":  # 🧰 auto-install ON?
            oki, msgi = await scan_and_install(name, context)
            if not oki:
                await q.answer(f"⛔ Install fail: {msgi}"[:190], show_alert=True)
                return await host_menu(update, context)
        ok, msgtxt = await start_proc(name, context)
        await q.answer(msgtxt[:190], show_alert=not ok)
        return await host_menu(update, context)
    if parts[1] == "stop":
        ok, msgtxt = await stop_proc(name)
        await q.answer(msgtxt[:190], show_alert=not ok)
        return await host_menu(update, context)
    if parts[1] == "res":
        await stop_proc(name)
        ok, msgtxt = await start_proc(name, context)
        await q.answer(msgtxt[:190], show_alert=not ok)
        return await host_menu(update, context)
    if parts[1] == "log":
        try:
            with open(os.path.join(SANDBOX_DIR, name + ".log"), "rb") as fh:
                fh.seek(0, os.SEEK_END)
                size = fh.tell()
                fh.seek(max(0, size - 1500))
                body = fh.read().decode(errors="replace")
        except FileNotFoundError:
            body = "(no output yet)"
        return await show(update, context, f"📜 {name} (tail):\n{body or '(empty)'}",
                          kb([[("🔄", f"hs:log:{name}")], nav(f"hs:f:{name}")]))
    if parts[1] == "del":
        return await show(update, context, f"🗑️ Delete {name}?",
                          kb([[("✅ Yes", f"hs:del2:{name}"), ("❌ No", f"hs:f:{name}")], nav("hs:menu")]))
    if parts[1] == "del2":
        if _running(name):
            await stop_proc(name)
        for suffix in ("", ".log"):
            try:
                os.remove(os.path.join(SANDBOX_DIR, name + suffix))
            except FileNotFoundError:
                pass
        PROCS.pop(name, None)
        await add_log("WARN", "hosting", uid, None, f"deleted {name}")
        return await host_menu(update, context)


@require(Role.OWNER)
async def host_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    aw = context.user_data.get("await") or ("",)
    if aw[0] != "host_up":
        return
    context.user_data["await"] = None
    doc = update.effective_message.document
    if (doc.file_size or 0) > MAX_UPLOAD_MB * 1_000_000:
        return await update.effective_message.reply_text(f"⛔ Too large (max {MAX_UPLOAD_MB} MB).")
    name = os.path.basename(doc.file_name or "program.py")
    if name != "requirements.txt" and not (name.endswith(".py") or name.endswith(".sh")):
        return await update.effective_message.reply_text("⛔ Sirf .py, .sh ya requirements.txt allowed.")
    if not all(c.isalnum() or c in "._-" for c in name):
        return await update.effective_message.reply_text("⛔ Unsafe filename.")
    f = await doc.get_file()
    await f.download_to_drive(os.path.join(SANDBOX_DIR, name))
    if name.endswith(".sh"):
        os.chmod(os.path.join(SANDBOX_DIR, name), 0o755)
    await add_log("INFO", "hosting", None, None, f"uploaded {name}")
    msg = f"📤 Saved {name}."
    if name == "requirements.txt":
        msg = "📤 requirements.txt saved! Menu se 📦 button dabao to install ho jayega."
    elif name.endswith(".py") and await get_kv("host_autoinst", "0") == "1":
        pkgs = await missing_packages(name)
        msg += f"\n🧰 Auto-Install ON hai — Start dabao to {len(pkgs) or 0} package(s) auto-install honge."
        if pkgs:
            msg += f"\nDetect: {', '.join(pkgs)}"
    await update.effective_message.reply_text(msg)

# ═══════════════════════════════════════════════════════
# INPUT DISPATCHER — text inputs + custom commands
# ═══════════════════════════════════════════════════════
@require(Role.OWNER, Role.APPROVED)
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await consume(update, context):
        return
    text = update.effective_message.text or ""
    if text.startswith("!"):  # custom command trigger
        name = text[1:].split()[0].lower()
        row = await get_command(update.effective_user.id, name)
        if row:
            await update.effective_message.reply_text(row["response"])


async def consume(update, context) -> bool:
    """Central 'awaiting input' dispatcher. Identity + ownership
    server-side re-verify hota hai apply karne se pehle."""
    aw = context.user_data.get("await")
    if not aw:
        return False
    context.user_data["await"] = None
    kind, uid = aw[0], aw[1]
    cid = aw[2] if len(aw) > 2 else None
    user = update.effective_user
    msg = update.effective_message
    text = (msg.text or "").strip()
    if user is None or user.id != uid:
        return True
    if cid is not None and not await owns_channel(uid, cid):
        await msg.reply_text("⛔ Not your channel.")
        return True

    s = await channel_settings(cid) if cid else None

    if kind == "ad_custom":
        m = re.fullmatch(r"(\d+)\s*([smh]?)", text.lower())
        if not m:
            await msg.reply_text("Format: 45, 90s, 5m, 2h")
            return True
        mult = {"": 1, "s": 1, "m": 60, "h": 3600}[m.group(2)]
        s["auto_delete"] = {"enabled": True, "seconds": int(m.group(1)) * mult}
        await save_channel_settings(cid, s)
        await msg.reply_text(f"✅ Timer set to {s['auto_delete']['seconds']}s.")
    elif kind == "cap_text":
        s["caption"]["text"] = text[:1000]
        s["caption"]["enabled"] = True
        await save_channel_settings(cid, s)
        await msg.reply_text("✅ Caption saved and enabled.")
    elif kind == "kw":
        s["keyword_blacklist"] = [w for w in (x.strip() for x in re.split(r"[,\n]", text)) if w]
        await save_channel_settings(cid, s)
        await msg.reply_text(f"✅ {len(s['keyword_blacklist'])} keywords saved.")
    elif kind == "dm":
        s["blocked_domains"] = [w.lower() for w in (x.strip() for x in re.split(r"[,\n]", text)) if w]
        await save_channel_settings(cid, s)
        await msg.reply_text("✅ Blocked domains saved.")
    elif kind in ("qh_s", "qh_e"):
        try:
            datetime.strptime(text, "%H:%M")
        except ValueError:
            await msg.reply_text("Format must be HH:MM.")
            return True
        s["quiet_hours"]["start" if kind == "qh_s" else "end"] = text
        await save_channel_settings(cid, s)
        await msg.reply_text("✅ Quiet hours updated.")
    elif kind == "bc":  # OWNER broadcast
        users = await users_by_status("approved")
        status = await msg.reply_text(f"📢 Broadcasting to {len(users)} users…")
        sent = fail = 0
        for u in users:
            try:
                await context.bot.send_message(u["user_id"], text)
                sent += 1
            except Exception:
                fail += 1
            await asyncio.sleep(0.05)  # rate limits respect karo
        await add_log("INFO", "broadcast", uid, None, f"sent={sent} failed={fail}")
        try:
            await status.edit_text(f"📢 Broadcast done. ✅ {sent} | ❌ {fail}")
        except Exception:
            pass
    elif kind == "an":
        try:
            await context.bot.send_message(cid, text)
            await add_log("INFO", "announce", uid, cid, text[:80])
            await msg.reply_text("📣 Announcement sent.")
        except Exception as e:
            await msg.reply_text(f"❌ Failed: {e}")
    elif kind == "sch_add":
        parts = [p.strip() for p in text.split("|")]
        if len(parts) != 3 or not parts[0].lstrip("-").isdigit() or not parts[1].isdigit():
            await msg.reply_text("Format: channel_id | minutes | text")
            return True
        tcid, minutes = int(parts[0]), int(parts[1])
        if not await owns_channel(uid, tcid):
            await msg.reply_text("⛔ Not your channel.")
            return True
        run_at = (datetime.now(timezone.utc) + timedelta(minutes=minutes)).isoformat()
        sid = await add_scheduled(tcid, parts[2], run_at, uid)
        context.application.job_queue.run_once(fire, minutes * 60, data={"sid": sid})
        await msg.reply_text(f"📅 Scheduled #{sid} in {minutes} min.")
    elif kind == "cc_add":
        if "=" not in text:
            await msg.reply_text("Format: name = response")
            return True
        name, resp = text.split("=", 1)
        name = name.strip().lower().split()[0] if name.strip() else ""
        if not name:
            await msg.reply_text("Format: name = response")
            return True
        await add_command(uid, name, resp.strip())
        await msg.reply_text(f"🧩 Command !{name} saved.")
    elif kind == "host_env":
        await set_kv("host_env", text)
        await msg.reply_text("✅ Environment variables saved.")
    elif kind == "host_pip":
        pkgs = text.split()
        if not pkgs:
            await msg.reply_text("Send one or more package names.")
            return True
        await msg.reply_text(f"🧰 Installing {', '.join(pkgs)}…")
        code, out = await pip_install(pkgs)
        if code == 0:
            for p in pkgs:
                await remember_pkg(p)
        await msg.reply_text(f"pip exit={code}\n{out[-1200:]}")
    elif kind == "restore":
        await msg.reply_text("Send the backup as a file/document (not text).")
    return True

# ═══════════════════════════════════════════════════════
# ERROR HANDLER
# ═══════════════════════════════════════════════════════
async def on_error(update, context):
    log.error("Unhandled error", exc_info=context.error)
    try:
        await add_log("ERROR", "error", None, None, repr(context.error)[:300])
    except Exception:
        pass

# ═══════════════════════════════════════════════════════
# MAIN — wiring
# ═══════════════════════════════════════════════════════
async def post_init(app):
    os.makedirs(SANDBOX_DIR, exist_ok=True)
    await db_init()
    await rearm(app)  # 🔄 restart recovery
    await app.bot.set_my_commands([
        BotCommand("start", "Main menu"),
        BotCommand("id", "Show chat id"),
        BotCommand("settime", "Set auto-delete timer"),
        BotCommand("stats", "Statistics"),
        BotCommand("pending", "Owner: pending users"),
        BotCommand("approve", "Owner: approve <user_id>"),
    ])
    log.info("AutoGuard Bot ready — single file edition ✅")


def main():
    app = Application.builder().token(BOT_TOKEN).post_init(post_init).build()

    # ── group -1: GLOBAL server-side authorization gate ──
    gate = ~filters.UpdateType.CHANNEL_POST & ~filters.UpdateType.EDITED_CHANNEL_POST
    app.add_handler(MessageHandler(gate, auth_gate), group=-1)
    app.add_handler(CallbackQueryHandler(auth_gate), group=-1)

    # core
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("id", cmd_id))
    app.add_handler(CallbackQueryHandler(on_home, pattern="^home$"))
    app.add_handler(CallbackQueryHandler(on_refresh, pattern="^refresh$"))
    app.add_handler(CallbackQueryHandler(on_noop, pattern="^noop$"))

    # approval (owner)
    app.add_handler(CallbackQueryHandler(ap_cb, pattern=r"^ap:"))
    app.add_handler(CommandHandler("pending", cmd_pending))
    app.add_handler(CommandHandler("approve", cmd_approve))

    # user panel
    app.add_handler(CallbackQueryHandler(up_cb, pattern=r"^u:"))
    app.add_handler(CommandHandler("stats", cmd_stats))
    app.add_handler(CallbackQueryHandler(ch_cb, pattern=r"^(ch|qh):"))
    app.add_handler(CallbackQueryHandler(ad_cb, pattern=r"^ad:"))
    app.add_handler(CommandHandler("settime", cmd_settime))
    app.add_handler(CallbackQueryHandler(flt_cb, pattern=r"^flt:"))
    app.add_handler(CallbackQueryHandler(cap_cb, pattern=r"^cap:"))
    app.add_handler(CallbackQueryHandler(sch_cb, pattern=r"^sch:"))
    app.add_handler(CallbackQueryHandler(cc_cb, pattern=r"^cc:"))

    # owner panel + hosting
    app.add_handler(CallbackQueryHandler(own_cb, pattern=r"^(o|bk|bc|an):"))
    app.add_handler(CallbackQueryHandler(host_cb, pattern=r"^hs:"))

    # channel registration + engine
    app.add_handler(ChatMemberHandler(on_my_chat_member, ChatMemberHandler.MY_CHAT_MEMBER))
    app.add_handler(MessageHandler(filters.UpdateType.CHANNEL_POST, on_post))
    app.add_handler(MessageHandler(filters.UpdateType.EDITED_CHANNEL_POST, on_edited))

    # documents (hosting upload / db restore) + text inputs
    app.add_handler(MessageHandler(filters.Document.ALL, host_document))
    app.add_handler(MessageHandler(filters.Document.ALL, own_document))
    app.add_handler(MessageHandler(filters.UpdateType.MESSAGE & filters.TEXT & ~filters.COMMAND,
                                   handle_text))

    app.add_error_handler(on_error)
    log.info("Starting polling…")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
