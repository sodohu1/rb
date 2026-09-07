#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AutoGuard Bot - single-file Telegram channel moderation bot.

Install:
    pip install -U python-telegram-bot

Environment:
    BOT_TOKEN=123456:ABC...
    OWNER_ID=123456789

Run:
    python bot.py

Notes:
- Add the bot as an administrator in every channel it manages.
- The bot needs permission to delete messages and post/edit messages where those
  features are enabled.
- Hosting is OWNER ONLY. It is intentionally limited to Python projects started
  as child processes; keep this bot on a trusted VPS and do not expose it publicly.
"""

import asyncio
import html
import io
import json
import logging
import os
import re
import shutil
import signal
import sqlite3
import subprocess
import sys
import time
import traceback
import zipfile
from datetime import datetime, timezone, timedelta
from pathlib import Path

from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup, InputFile
)
from telegram.constants import ChatMemberStatus, ParseMode
from telegram.error import TelegramError, Forbidden, BadRequest
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler, MessageHandler,
    ContextTypes, filters
)

# ----------------------------- CONFIG ---------------------------------

TOKEN = os.getenv("BOT_TOKEN", "8982922702:AAHkZNt37tr5zCWdbZWBz66D_W4k1RCr94Y").strip()
OWNER_ID = int(os.getenv("OWNER_ID", "8609127164") or 0)

DATA_DIR = Path(os.getenv("AUTOGUARD_DATA", "autoguard_data"))
HOST_DIR = DATA_DIR / "hosting"
DB_PATH = DATA_DIR / "autoguard.sqlite3"
LOG_DIR = DATA_DIR / "logs"
DATA_DIR.mkdir(parents=True, exist_ok=True)
HOST_DIR.mkdir(parents=True, exist_ok=True)
LOG_DIR.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(LOG_DIR / "bot.log", encoding="utf-8")
    ],
)
log = logging.getLogger("autoguard")

# ----------------------------- DATABASE --------------------------------

DEFAULTS = {
    "auto_delete": 0,
    "delete_timer": 10,
    "auto_caption": 0,
    "caption": "",
    "keyword_filter": 0,
    "keywords": "",
    "link_filter": 0,
    "media_filter": 0,
    "gif_filter": 0,
    "document_filter": 0,
    "forward_filter": 0,
    "bot_filter": 0,
    "duplicate_filter": 0,
    "spam_filter": 0,
    "hashtag_filter": 0,
    "caps_filter": 0,
    "domain_filter": 0,
    "allowed_domains": "",
    "filetype_filter": 0,
    "blocked_extensions": "apk,zip,exe,bat,sh",
    "filesize_filter": 0,
    "max_file_mb": 50,
    "length_filter": 0,
    "max_chars": 4000,
    "flood_control": 0,
    "flood_limit": 5,
    "flood_window": 60,
    "smart_spam": 0,
    "edit_detection": 0,
    "quiet_hours": 0,
    "quiet_start": "00:00",
    "quiet_end": "00:00",
    "link_preview": 1,
    "album_detection": 1,
    "rate_limit": 0,
    "category_rules": 0,
    "scheduled_cleanup": 0,
    "cleanup_hours": 24,
    "dry_run": 0,
    "delete_logs": 1,
    "error_alerts": 1,
    "stats": 1,
    "silent_logs": 0,
    "maintenance": 0,
    "auto_retry": 1,
    "global_kill": 0,
    "emergency_lockdown": 0,
    "preset": "normal",
    "max_posts_per_min": 20,
}

def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with db() as c:
        c.execute("""CREATE TABLE IF NOT EXISTS users(
            user_id INTEGER PRIMARY KEY,
            status TEXT NOT NULL DEFAULT 'pending',
            label TEXT DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )""")
        c.execute("""CREATE TABLE IF NOT EXISTS channels(
            chat_id INTEGER PRIMARY KEY,
            title TEXT DEFAULT '',
            label TEXT DEFAULT '',
            owner_user_id INTEGER,
            added_at TEXT NOT NULL
        )""")
        c.execute("""CREATE TABLE IF NOT EXISTS settings(
            chat_id INTEGER PRIMARY KEY,
            data TEXT NOT NULL
        )""")
        c.execute("""CREATE TABLE IF NOT EXISTS logs(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT NOT NULL,
            user_id INTEGER,
            chat_id INTEGER,
            action TEXT,
            detail TEXT
        )""")
        c.execute("""CREATE TABLE IF NOT EXISTS stats(
            chat_id INTEGER PRIMARY KEY,
            detected INTEGER DEFAULT 0,
            deleted INTEGER DEFAULT 0,
            errors INTEGER DEFAULT 0
        )""")
        c.execute("""CREATE TABLE IF NOT EXISTS schedules(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            owner_id INTEGER,
            chat_id INTEGER,
            send_at TEXT,
            text TEXT,
            sent INTEGER DEFAULT 0
        )""")
        c.execute("""CREATE TABLE IF NOT EXISTS custom_commands(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            owner_id INTEGER,
            chat_id INTEGER,
            name TEXT,
            text TEXT,
            UNIQUE(owner_id, chat_id, name)
        )""")
        now = now_iso()
        c.execute("INSERT OR IGNORE INTO users(user_id,status,created_at,updated_at) VALUES(?,?,?,?,?)",
                  (OWNER_ID, "owner", now, now))
    if OWNER_ID:
        set_user_status(OWNER_ID, "owner")

def now_iso():
    return datetime.now(timezone.utc).isoformat()

def user_status(uid):
    with db() as c:
        r = c.execute("SELECT status FROM users WHERE user_id=?", (uid,)).fetchone()
        return r["status"] if r else None

def set_user_status(uid, status):
    now = now_iso()
    with db() as c:
        c.execute("""INSERT INTO users(user_id,status,created_at,updated_at)
                     VALUES(?,?,?,?)
                     ON CONFLICT(user_id) DO UPDATE SET status=excluded.status, updated_at=excluded.updated_at""",
                  (uid, status, now, now))

def set_user_label(uid, label):
    with db() as c:
        c.execute("UPDATE users SET label=?,updated_at=? WHERE user_id=?", (label, now_iso(), uid))

def add_log(action, detail="", user_id=None, chat_id=None):
    with db() as c:
        c.execute("INSERT INTO logs(ts,user_id,chat_id,action,detail) VALUES(?,?,?,?,?)",
                  (now_iso(), user_id, chat_id, action, detail))

def get_settings(chat_id):
    with db() as c:
        r = c.execute("SELECT data FROM settings WHERE chat_id=?", (chat_id,)).fetchone()
    if r:
        try:
            d = DEFAULTS.copy()
            d.update(json.loads(r["data"]))
            return d
        except Exception:
            pass
    return DEFAULTS.copy()

def save_settings(chat_id, s):
    with db() as c:
        c.execute("""INSERT INTO settings(chat_id,data) VALUES(?,?)
                     ON CONFLICT(chat_id) DO UPDATE SET data=excluded.data""",
                  (chat_id, json.dumps(s)))

def setting(chat_id, key):
    return get_settings(chat_id).get(key, DEFAULTS.get(key))

def toggle_setting(chat_id, key):
    s = get_settings(chat_id)
    s[key] = 0 if s.get(key) else 1
    save_settings(chat_id, s)
    return s[key]

def add_channel(chat_id, title, owner_uid):
    with db() as c:
        c.execute("""INSERT INTO channels(chat_id,title,owner_user_id,added_at)
                     VALUES(?,?,?,?)
                     ON CONFLICT(chat_id) DO UPDATE SET title=excluded.title""",
                  (chat_id, title, owner_uid, now_iso()))
        c.execute("INSERT OR IGNORE INTO stats(chat_id) VALUES(?)", (chat_id,))
    add_log("channel_add", title, owner_uid, chat_id)

def remove_channel(chat_id):
    with db() as c:
        c.execute("DELETE FROM channels WHERE chat_id=?", (chat_id,))
        c.execute("DELETE FROM settings WHERE chat_id=?", (chat_id,))
        c.execute("DELETE FROM stats WHERE chat_id=?", (chat_id,))
    add_log("channel_remove", str(chat_id), OWNER_ID, chat_id)

def channel_ids():
    with db() as c:
        return [r["chat_id"] for r in c.execute("SELECT chat_id FROM channels").fetchall()]

def channel_rows():
    with db() as c:
        return c.execute("SELECT * FROM channels ORDER BY title").fetchall()

def inc_stat(chat_id, field):
    if field not in ("detected", "deleted", "errors"):
        return
    with db() as c:
        c.execute(f"UPDATE stats SET {field}={field}+1 WHERE chat_id=?", (chat_id,))

def is_owner(uid):
    return uid == OWNER_ID and OWNER_ID != 0

def is_approved(uid):
    return is_owner(uid) or user_status(uid) in ("approved", "admin", "owner")

def is_admin(uid):
    return is_owner(uid) or user_status(uid) in ("admin", "owner")

def ensure_user(uid):
    if not user_status(uid):
        now = now_iso()
        with db() as c:
            c.execute("INSERT INTO users(user_id,status,created_at,updated_at) VALUES(?,?,?,?,?)",
                      (uid, "pending", now, now))

# ----------------------------- UI --------------------------------------

def btn(text, data):
    return InlineKeyboardButton(text, callback_data=data)

def main_menu(uid):
    rows = [
        [btn("🎛️ Control Panel", "panel"), btn("📊 Statistics", "stats")],
        [btn("📢 My Channels", "channels"), btn("📖 Help", "help")],
    ]
    if is_owner(uid):
        rows += [
            [btn("👑 Owner Panel", "owner"), btn("🖥️ Hosting Panel", "host")],
        ]
    return InlineKeyboardMarkup(rows)

def owner_menu():
    return InlineKeyboardMarkup([
        [btn("📊 Dashboard", "dashboard"), btn("👥 Users", "users")],
        [btn("📢 Channels", "channels"), btn("🎛️ Global Settings", "global")],
        [btn("📈 Statistics", "stats"), btn("📜 Logs & Audit", "logs")],
        [btn("📢 Broadcast", "broadcast"), btn("📣 Channel Announcement", "announce")],
        [btn("📅 Scheduled Messages", "schedule"), btn("💾 Backup", "backup")],
        [btn("🩺 System Health", "health"), btn("📊 Resource Monitor", "resources")],
        [btn("🛠️ Bot Control", "botcontrol"), btn("🧩 Custom Commands", "customcmd")],
        [btn("🧹 Cleanup", "cleanup"), btn("🧪 Dry Run", "dryrun")],
        [btn("🔔 Notifications", "notify"), btn("🏷️ Labels", "labels")],
        [btn("🖥️ Hosting Panel", "host")],
        [btn("🔒 Emergency Lockdown", "lockdown"), btn("🧠 Kill Switch", "killswitch")],
        [btn("⚙️ Config Preview", "preview")],
        [btn("⬅️ Back", "home")]
    ])

FILTERS = [
    ("keyword_filter","🚫 Keyword Filter"),
    ("link_filter","🔗 Link Filter"),
    ("media_filter","🖼️ Media Filter"),
    ("gif_filter","🎞️ GIF Filter"),
    ("document_filter","📄 Document Filter"),
    ("forward_filter","📢 Forward Filter"),
    ("bot_filter","🤖 Bot Message Filter"),
    ("duplicate_filter","🔁 Duplicate Filter"),
    ("spam_filter","🤖 Spam Filter"),
    ("hashtag_filter","📍 Hashtag Filter"),
    ("caps_filter","🔤 Caps Filter"),
    ("domain_filter","🌐 Domain Filter"),
    ("filetype_filter","📦 File-Type Filter"),
    ("filesize_filter","📦 File Size Filter"),
    ("length_filter","📏 Message Length Filter"),
    ("flood_control","🛡️ Flood Control"),
    ("smart_spam","🧠 Smart Spam Detection"),
]

def channel_picker(prefix="cp"):
    rows = []
    for r in channel_rows():
        title = r["label"] or r["title"] or str(r["chat_id"])
        rows.append([btn(f"📢 {title[:35]}", f"{prefix}:{r['chat_id']}")])
    rows.append([btn("⬅️ Back", "panel")])
    return InlineKeyboardMarkup(rows)

def panel_menu(chat_id):
    s = get_settings(chat_id)
    rows = [
        [btn(f"🗑️ Auto Delete {'🟢' if s['auto_delete'] else '🔴'}", f"tg:{chat_id}:auto_delete"),
         btn(f"⏱️ Timer {s['delete_timer']}s", f"timer:{chat_id}")],
        [btn(f"📝 Caption {'🟢' if s['auto_caption'] else '🔴'}", f"tg:{chat_id}:auto_caption"),
         btn(f"🧪 Dry Run {'🟢' if s['dry_run'] else '🔴'}", f"tg:{chat_id}:dry_run")],
        [btn("🚫 Filters", f"filters:{chat_id}"), btn("⚙️ Advanced", f"advanced:{chat_id}")],
        [btn("📊 Statistics", f"cstats:{chat_id}"), btn("📜 Logs", f"clogs:{chat_id}")],
        [btn("🔔 Notifications", f"notifyc:{chat_id}"), btn("🧹 Cleanup", f"cleanupc:{chat_id}")],
        [btn("🧩 Custom Commands", f"cc:{chat_id}"), btn("🧪 Config Preview", f"previewc:{chat_id}")],
        [btn("⬅️ Channels", "channels")]
    ]
    return InlineKeyboardMarkup(rows)

def filter_menu(chat_id):
    s = get_settings(chat_id)
    rows=[]
    for i in range(0, len(FILTERS), 2):
        pair=[]
        for key,label in FILTERS[i:i+2]:
            pair.append(btn(f"{label} {'🟢' if s[key] else '🔴'}", f"tg:{chat_id}:{key}"))
        rows.append(pair)
    rows += [
        [btn("⚙️ Filter Values", f"fvalues:{chat_id}")],
        [btn("⬅️ Control Panel", f"panelc:{chat_id}")]
    ]
    return InlineKeyboardMarkup(rows)

# ----------------------------- AUTH ------------------------------------

async def require_access(update, owner_only=False):
    uid = update.effective_user.id
    ensure_user(uid)
    if owner_only:
        if not is_owner(uid):
            if update.callback_query:
                await update.callback_query.answer("Owner only.", show_alert=True)
            else:
                await update.effective_message.reply_text("🔒 Owner only.")
            return False
        return True
    if not is_approved(uid):
        text = "⏳ Your approval is pending.\n\nPlease wait for the Owner to approve you."
        if update.callback_query:
            await update.callback_query.answer("Approval pending.", show_alert=True)
            try: await update.callback_query.edit_message_text(text)
            except TelegramError: pass
        else:
            await update.effective_message.reply_text(text)
        if is_owner(OWNER_ID):
            await notify_owner_new_user(uid, update.effective_user)
        return False
    return True

async def notify_owner_new_user(uid, user):
    # Avoid spam: only notify if currently pending and log it.
    if is_owner(uid):
        return
    try:
        name = html.escape(user.full_name or str(uid))
        username = f"@{html.escape(user.username)}" if user.username else "no username"
        kb = InlineKeyboardMarkup([
            [btn("✅ Approve", f"approve:{uid}"), btn("❌ Reject", f"reject:{uid}")],
            [btn("🚫 Block", f"block:{uid}")]
        ])
        await app.bot.send_message(
            OWNER_ID,
            f"🔔 <b>Approval Request</b>\n\n👤 {name}\n🆔 <code>{uid}</code>\n🔗 {username}",
            parse_mode=ParseMode.HTML,
            reply_markup=kb
        )
        add_log("approval_request", str(uid), uid)
    except Exception:
        pass

# ----------------------------- START / HELP ----------------------------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    ensure_user(uid)
    if is_owner(uid):
        await update.message.reply_text(
            "👑 <b>Welcome, Owner!</b>\n\n🤖 AutoGuard is ready.",
            parse_mode=ParseMode.HTML, reply_markup=main_menu(uid)
        )
    elif is_approved(uid):
        await update.message.reply_text(
            "🤖 <b>Welcome to AutoGuard Bot</b>\n🛡️ Smart Channel Management System",
            parse_mode=ParseMode.HTML, reply_markup=main_menu(uid)
        )
    else:
        await update.message.reply_text(
            "⏳ <b>Approval Pending</b>\n\nOwner approval is required before commands and panels become available.",
            parse_mode=ParseMode.HTML
        )
        await notify_owner_new_user(uid, update.effective_user)

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await require_access(update): return
    await update.message.reply_text(
        "📖 <b>Help</b>\n\n"
        "1. Add me as channel admin with Delete Messages permission.\n"
        "2. Owner adds the channel from Channel Management.\n"
        "3. Choose a channel in Control Panel.\n"
        "4. Turn features ON/OFF with buttons.\n\n"
        "Useful commands:\n"
        "/start — open menu\n"
        "/help — help\n"
        "/settime 10 — set delete timer for selected channel\n"
        "/approve ID — owner approve\n"
        "/reject ID — owner reject\n"
        "/block ID — owner block\n"
        "/addchannel — owner: use in a channel where the bot is admin\n"
        "/setcaption TEXT — set caption for current channel\n",
        parse_mode=ParseMode.HTML
    )

# ----------------------------- COMMANDS --------------------------------

async def settime_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await require_access(update): return
    if not context.args:
        await update.message.reply_text("Usage: /settime 10")
        return
    try:
        sec = max(1, min(86400, int(context.args[0])))
    except ValueError:
        await update.message.reply_text("Timer must be a number of seconds.")
        return
    ch = await get_current_channel(update.effective_user.id)
    if not ch:
        await update.message.reply_text("First open 📢 My Channels and select a channel.")
        return
    s=get_settings(ch); s["delete_timer"]=sec; save_settings(ch,s)
    await update.message.reply_text(f"⏱️ Delete timer set to <b>{sec}s</b>.", parse_mode=ParseMode.HTML)

async def setcaption_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await require_access(update): return
    ch=await get_current_channel(update.effective_user.id)
    if not ch:
        await update.message.reply_text("Select a channel first.")
        return
    text=" ".join(context.args)
    s=get_settings(ch); s["caption"]=text; s["auto_caption"]=1; save_settings(ch,s)
    await update.message.reply_text("📝 Caption saved and enabled.")

async def approve_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await require_access(update, True): return
    if not context.args: return await update.message.reply_text("Usage: /approve USER_ID")
    try: uid=int(context.args[0])
    except: return await update.message.reply_text("Invalid user ID.")
    ensure_user(uid); set_user_status(uid,"approved"); add_log("approve",str(uid),OWNER_ID)
    await update.message.reply_text(f"✅ Approved <code>{uid}</code>.",parse_mode=ParseMode.HTML)

async def reject_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await require_access(update, True): return
    if not context.args: return await update.message.reply_text("Usage: /reject USER_ID")
    uid=int(context.args[0]); ensure_user(uid); set_user_status(uid,"rejected"); add_log("reject",str(uid),OWNER_ID)
    await update.message.reply_text(f"❌ Rejected <code>{uid}</code>.",parse_mode=ParseMode.HTML)

async def block_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await require_access(update, True): return
    if not context.args: return await update.message.reply_text("Usage: /block USER_ID")
    uid=int(context.args[0]); ensure_user(uid); set_user_status(uid,"blocked"); add_log("block",str(uid),OWNER_ID)
    await update.message.reply_text(f"🚫 Blocked <code>{uid}</code>.",parse_mode=ParseMode.HTML)

async def addchannel_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await require_access(update, True): return
    chat=update.effective_chat
    # Intended to be run inside a channel.
    if chat.type != "channel":
        await update.message.reply_text("Run /addchannel inside the target channel.")
        return
    try:
        me=await context.bot.get_chat_member(chat.id, context.bot.id)
        if me.status not in (ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER):
            await update.message.reply_text("Make the bot an administrator first.")
            return
    except TelegramError as e:
        await update.message.reply_text(f"Could not verify channel admin status: {e}")
        return
    add_channel(chat.id, chat.title or str(chat.id), OWNER_ID)
    await update.message.reply_text("✅ Channel added to AutoGuard.")

async def get_current_channel(uid):
    # Per-user ephemeral selection is held in memory.
    return selections.get(uid)

selections = {}

# ----------------------------- CALLBACKS -------------------------------

async def callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q=update.callback_query
    await q.answer()
    uid=q.from_user.id
    data=q.data

    if data=="home":
        if not await require_access(update): return
        await q.edit_message_text("🏠 <b>Home</b>", parse_mode=ParseMode.HTML, reply_markup=main_menu(uid)); return
    if data=="help":
        if not await require_access(update): return
        await q.edit_message_text(
            "📖 <b>Help</b>\n\nUse the menus to manage approved channels. "
            "Owner-only actions are protected server-side.",
            parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup([[btn("⬅️ Back","home")]])
        ); return
    if data.startswith(("approve:","reject:","block:")):
        if not is_owner(uid):
            await q.answer("Owner only.",show_alert=True); return
        action,target=data.split(":"); target=int(target); ensure_user(target)
        new={"approve":"approved","reject":"rejected","block":"blocked"}[action]
        set_user_status(target,new); add_log(action,str(target),uid)
        await q.edit_message_reply_markup(reply_markup=None)
        await q.message.reply_text(f"{'✅' if action=='approve' else '❌' if action=='reject' else '🚫'} {action.title()}d <code>{target}</code>.",parse_mode=ParseMode.HTML)
        return
    if data=="owner":
        if not await require_access(update, True): return
        await q.edit_message_text("👑 <b>Owner Panel</b>",parse_mode=ParseMode.HTML,reply_markup=owner_menu()); return
    if data=="panel":
        if not await require_access(update): return
        await q.edit_message_text("📢 Select a channel:",reply_markup=channel_picker("cp")); return
    if data.startswith("cp:"):
        if not await require_access(update): return
        ch=int(data.split(":")[1]); selections[uid]=ch
        await q.edit_message_text(f"🎛️ <b>Control Panel</b>\nChannel: <code>{ch}</code>",parse_mode=ParseMode.HTML,reply_markup=panel_menu(ch)); return
    if data.startswith("panelc:"):
        ch=int(data.split(":")[1]); await q.edit_message_text("🎛️ Control Panel",reply_markup=panel_menu(ch)); return
    if data.startswith("filters:"):
        ch=int(data.split(":")[1]); await q.edit_message_text("🚫 <b>Filters</b>",parse_mode=ParseMode.HTML,reply_markup=filter_menu(ch)); return
    if data.startswith("tg:"):
        _,ch,key=data.split(":",2); ch=int(ch)
        if not await require_access(update): return
        val=toggle_setting(ch,key)
        add_log("toggle",f"{key}={val}",uid,ch)
        await q.edit_message_text("🚫 <b>Filters</b>" if key.endswith("filter") or key in DEFAULTS else "⚙️ Setting",
                                    parse_mode=ParseMode.HTML,reply_markup=filter_menu(ch) if key in dict(FILTERS) else panel_menu(ch)); return
    if data.startswith("timer:"):
        ch=int(data.split(":")[1])
        await q.edit_message_text("⏱️ Use /settime SECONDS in chat after selecting this channel.\n\nExample: /settime 10",
                                   reply_markup=InlineKeyboardMarkup([[btn("⬅️ Back",f"panelc:{ch}")]])); return
    if data.startswith("fvalues:"):
        ch=int(data.split(":")[1])
        await q.edit_message_text(
            "⚙️ <b>Filter values</b>\n\n"
            "Use commands or environment/database customization in this single-file version.\n"
            "Keyword list and allowed domains can be edited with the owner/admin value handlers.",
            parse_mode=ParseMode.HTML,reply_markup=InlineKeyboardMarkup([[btn("⬅️ Filters",f"filters:{ch}")]])
        ); return
    if data.startswith("advanced:"):
        ch=int(data.split(":")[1]); s=get_settings(ch)
        kb=InlineKeyboardMarkup([
            [btn(f"✏️ Edit Detection {'🟢' if s['edit_detection'] else '🔴'}",f"tg:{ch}:edit_detection"),
             btn(f"🕐 Quiet Hours {'🟢' if s['quiet_hours'] else '🔴'}",f"tg:{ch}:quiet_hours")],
            [btn(f"🔗 Link Preview {'🟢' if s['link_preview'] else '🔴'}",f"tg:{ch}:link_preview"),
             btn(f"🖼️ Album {'🟢' if s['album_detection'] else '🔴'}",f"tg:{ch}:album_detection")],
            [btn(f"🔁 Rate Limit {'🟢' if s['rate_limit'] else '🔴'}",f"tg:{ch}:rate_limit"),
             btn(f"🗂️ Category Rules {'🟢' if s['category_rules'] else '🔴'}",f"tg:{ch}:category_rules")],
            [btn(f"🧹 Scheduled Cleanup {'🟢' if s['scheduled_cleanup'] else '🔴'}",f"tg:{ch}:scheduled_cleanup")],
            [btn("⬅️ Control Panel",f"panelc:{ch}")]
        ])
        await q.edit_message_text("⚙️ <b>Advanced Settings</b>",parse_mode=ParseMode.HTML,reply_markup=kb); return
    if data.startswith("cstats:"):
        ch=int(data.split(":")[1])
        with db() as c: r=c.execute("SELECT * FROM stats WHERE chat_id=?",(ch,)).fetchone()
        txt=f"📊 <b>Statistics</b>\n\nDetected: {r['detected'] if r else 0}\nDeleted: {r['deleted'] if r else 0}\nErrors: {r['errors'] if r else 0}"
        await q.edit_message_text(txt,parse_mode=ParseMode.HTML,reply_markup=InlineKeyboardMarkup([[btn("⬅️ Back",f"panelc:{ch}")]])); return
    if data=="stats":
        if not await require_access(update): return
        await show_stats(q); return
    if data.startswith("clogs:"):
        ch=int(data.split(":")[1]); await show_channel_logs(q,ch); return
    if data=="channels":
        if not await require_access(update): return
        await q.edit_message_text("📢 <b>Channels</b>",parse_mode=ParseMode.HTML,reply_markup=channel_picker("cp")); return
    if data.startswith("cleanupc:"):
        ch=int(data.split(":")[1]); await q.edit_message_text("🧹 Use Cleanup from Owner Panel for global cleanup, or set scheduled cleanup for this channel.",reply_markup=InlineKeyboardMarkup([[btn("⬅️ Back",f"panelc:{ch}")]])); return
    if data.startswith("notifyc:"):
        ch=int(data.split(":")[1]); await q.edit_message_text("🔔 Delete/error notifications are controlled by channel settings.",reply_markup=InlineKeyboardMarkup([[btn("⬅️ Back",f"panelc:{ch}")]])); return
    if data.startswith("cc:"):
        ch=int(data.split(":")[1]); await q.edit_message_text("🧩 Custom Commands\n\nOwner/admin can create commands using the command manager.",reply_markup=InlineKeyboardMarkup([[btn("⬅️ Back",f"panelc:{ch}")]])); return
    if data.startswith("previewc:"):
        ch=int(data.split(":")[1]); await show_config(q,ch); return

    # Owner-only callbacks
    if data in ("dashboard","users","global","logs","broadcast","announce","schedule","backup","health","resources","botcontrol","customcmd","cleanup","dryrun","notify","labels","lockdown","killswitch","preview","host"):
        if not await require_access(update, True): return

    if data=="dashboard":
        with db() as c:
            users=c.execute("SELECT COUNT(*) n FROM users").fetchone()["n"]
            approved=c.execute("SELECT COUNT(*) n FROM users WHERE status IN ('approved','admin','owner')").fetchone()["n"]
            chans=c.execute("SELECT COUNT(*) n FROM channels").fetchone()["n"]
            deleted=c.execute("SELECT COALESCE(SUM(deleted),0) n FROM stats").fetchone()["n"]
        await q.edit_message_text(f"📊 <b>Dashboard</b>\n\nUsers: {users}\nApproved: {approved}\nChannels: {chans}\nDeleted: {deleted}",parse_mode=ParseMode.HTML,reply_markup=owner_back()); return
    if data=="users":
        await owner_users(q); return
    if data=="global":
        await q.edit_message_text("🎛️ <b>Global Settings</b>\n\nUse per-channel settings from Channel Management.",parse_mode=ParseMode.HTML,reply_markup=owner_back()); return
    if data=="logs":
        await owner_logs(q); return
    if data=="broadcast":
        await q.edit_message_text("📢 Send a broadcast by replying to this message with /broadcast TEXT.",reply_markup=owner_back()); return
    if data=="announce":
        await q.edit_message_text("📣 Channel Announcement\n\nUse /announce CHANNEL_ID TEXT",reply_markup=owner_back()); return
    if data=="schedule":
        await q.edit_message_text("📅 Scheduling\n\nUse /schedule CHANNEL_ID YYYY-MM-DDTHH:MM:SS TEXT (UTC).",reply_markup=owner_back()); return
    if data=="backup":
        path=make_backup()
        await q.message.reply_document(InputFile(path.open("rb"),filename=path.name),caption="💾 Database backup")
        return
    if data=="health":
        await q.edit_message_text(health_text(),reply_markup=owner_back()); return
    if data=="resources":
        total,free=shutil.disk_usage(DATA_DIR)
        await q.edit_message_text(f"📊 <b>Resource Monitor</b>\n\nDisk: {total//(1024**3)} GB\nFree: {free//(1024**3)} GB\nPython: {sys.version.split()[0]}",parse_mode=ParseMode.HTML,reply_markup=owner_back()); return
    if data=="botcontrol":
        await q.edit_message_text("🛠️ <b>Bot Control</b>",parse_mode=ParseMode.HTML,reply_markup=InlineKeyboardMarkup([
            [btn(f"🌙 Maintenance {'🟢' if global_flag('maintenance') else '🔴'}","g:maintenance"),
             btn(f"🧠 Kill Switch {'🟢' if global_flag('global_kill') else '🔴'}","g:global_kill")],
            [btn(f"🔒 Lockdown {'🟢' if global_flag('emergency_lockdown') else '🔴'}","g:emergency_lockdown")],
            [btn("⬅️ Owner Panel","owner")]
        ])); return
    if data.startswith("g:"):
        key=data.split(":")[1]
        if key not in ("maintenance","global_kill","emergency_lockdown"): return
        # Global state stored in synthetic chat_id 0.
        s=get_settings(0); s[key]=0 if s.get(key) else 1; save_settings(0,s)
        add_log("global_toggle",f"{key}={s[key]}",uid)
        await q.edit_message_text("🛠️ <b>Bot Control</b>",parse_mode=ParseMode.HTML,reply_markup=InlineKeyboardMarkup([
            [btn(f"🌙 Maintenance {'🟢' if s['maintenance'] else '🔴'}","g:maintenance"),
             btn(f"🧠 Kill Switch {'🟢' if s['global_kill'] else '🔴'}","g:global_kill")],
            [btn(f"🔒 Lockdown {'🟢' if s['emergency_lockdown'] else '🔴'}","g:emergency_lockdown")],
            [btn("⬅️ Owner Panel","owner")]
        ])); return
    if data=="customcmd":
        await q.edit_message_text("🧩 Custom Commands\n\nUse /addcmd CHANNEL_ID NAME TEXT and /delcmd CHANNEL_ID NAME",reply_markup=owner_back()); return
    if data=="cleanup":
        await q.edit_message_text("🧹 Cleanup\n\nUse /cleanup CHANNEL_ID COUNT to remove recent posts. Bot must have delete permission.",reply_markup=owner_back()); return
    if data=="dryrun":
        await q.edit_message_text("🧪 Dry Run is available per channel in Control Panel → Dry Run.",reply_markup=owner_back()); return
    if data=="notify":
        await q.edit_message_text("🔔 Notification toggles are available in each channel's Control Panel.",reply_markup=owner_back()); return
    if data=="labels":
        await q.edit_message_text("🏷️ Labels\n\nUse /labeluser USER_ID LABEL or /labelchannel CHANNEL_ID LABEL.",reply_markup=owner_back()); return
    if data=="lockdown":
        s=get_settings(0); s["emergency_lockdown"]=0 if s.get("emergency_lockdown") else 1; save_settings(0,s)
        await q.answer(f"Lockdown {'ON' if s['emergency_lockdown'] else 'OFF'}",show_alert=True)
        return
    if data=="killswitch":
        s=get_settings(0); s["global_kill"]=0 if s.get("global_kill") else 1; save_settings(0,s)
        await q.answer(f"Kill switch {'ON' if s['global_kill'] else 'OFF'}",show_alert=True)
        return
    if data=="preview":
        await show_global_config(q); return
    if data=="host":
        await host_panel(q); return

def owner_back():
    return InlineKeyboardMarkup([[btn("⬅️ Owner Panel","owner")]])

def global_flag(k): return bool(get_settings(0).get(k,0))

async def owner_users(q):
    with db() as c:
        rows=c.execute("SELECT * FROM users ORDER BY status,created_at DESC LIMIT 30").fetchall()
    text="👥 <b>Users</b>\n\n"
    for r in rows:
        text += f"{r['user_id']} — {html.escape(r['status'])} {html.escape(r['label'] or '')}\n"
    await q.edit_message_text(text[:4000],parse_mode=ParseMode.HTML,reply_markup=owner_back())

async def owner_logs(q):
    with db() as c:
        rows=c.execute("SELECT * FROM logs ORDER BY id DESC LIMIT 25").fetchall()
    text="📜 <b>Recent Logs</b>\n\n"
    for r in rows:
        text += f"{r['ts'][:19]} | {r['action']} | {r['detail'][:80]}\n"
    await q.edit_message_text(text[:4000],parse_mode=ParseMode.HTML,reply_markup=owner_back())

async def show_stats(q):
    with db() as c:
        rows=c.execute("SELECT * FROM stats ORDER BY chat_id").fetchall()
    text="📊 <b>Statistics</b>\n\n"
    if not rows: text += "No channels yet."
    for r in rows:
        text += f"Channel <code>{r['chat_id']}</code>: detected {r['detected']}, deleted {r['deleted']}, errors {r['errors']}\n"
    await q.edit_message_text(text,parse_mode=ParseMode.HTML,reply_markup=InlineKeyboardMarkup([[btn("⬅️ Back","home")]]))

async def show_channel_logs(q,ch):
    with db() as c:
        rows=c.execute("SELECT * FROM logs WHERE chat_id=? ORDER BY id DESC LIMIT 20",(ch,)).fetchall()
    text="📜 <b>Channel Logs</b>\n\n"
    for r in rows: text += f"{r['ts'][:19]} | {r['action']} | {r['detail'][:90]}\n"
    await q.edit_message_text(text[:4000],parse_mode=ParseMode.HTML,reply_markup=InlineKeyboardMarkup([[btn("⬅️ Back",f"panelc:{ch}")]]))

async def show_config(q,ch):
    s=get_settings(ch)
    text="⚙️ <b>Configuration</b>\n\n"
    for k,v in s.items():
        text += f"{k}: {v}\n"
    await q.edit_message_text(text[:4000],parse_mode=ParseMode.HTML,reply_markup=InlineKeyboardMarkup([[btn("⬅️ Back",f"panelc:{ch}")]]))

async def show_global_config(q):
    s=get_settings(0)
    text="⚙️ <b>Global Configuration</b>\n\n" + "\n".join(f"{k}: {v}" for k,v in s.items())
    await q.edit_message_text(text[:4000],parse_mode=ParseMode.HTML,reply_markup=owner_back())

def health_text():
    return f"🩺 <b>System Health</b>\n\n🤖 Bot process: OK\n💾 Database: {'OK' if DB_PATH.exists() else 'MISSING'}\n🗂️ Data directory: {'OK' if DATA_DIR.exists() else 'MISSING'}\n🐍 Python: {sys.version.split()[0]}"

def make_backup():
    path=DATA_DIR / f"backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.sqlite3"
    shutil.copy2(DB_PATH,path)
    return path

# ----------------------------- HOSTING ---------------------------------

processes = {}

def safe_project(name):
    name=re.sub(r"[^A-Za-z0-9_.-]","_",name)
    name=name.strip(".") or "project"
    return (HOST_DIR/name).resolve()

async def host_panel(q):
    if not is_owner(q.from_user.id):
        await q.answer("Owner only.",show_alert=True); return
    await q.edit_message_text(
        "🖥️ <b>Hosting Panel — OWNER ONLY</b>\n\n"
        "Upload a Python file to the bot, then start/stop it.\n"
        "Projects run as child processes under the hosting directory.",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup([
            [btn("📁 Projects","h:list"),btn("📋 Processes","h:proc")],
            [btn("🆘 Hosting Help","h:help")],
            [btn("⬅️ Owner Panel","owner")]
        ])
    )

async def host_callback(q,data):
    if not is_owner(q.from_user.id):
        await q.answer("Owner only.",show_alert=True); return
    action=data.split(":",1)[1]
    if action=="list":
        projects=[p.name for p in HOST_DIR.iterdir() if p.is_dir()]
        text="📁 <b>Projects</b>\n\n"+("\n".join(projects) if projects else "No projects yet.")
        kb=[[btn(f"▶️ {p[:25]}",f"hstart:{p}"),btn(f"🗑️ {p[:20]}",f"hdel:{p}")] for p in projects]
        kb.append([btn("⬅️ Hosting","host")])
        await q.edit_message_text(text[:4000],parse_mode=ParseMode.HTML,reply_markup=InlineKeyboardMarkup(kb)); return
    if action=="proc":
        text="📋 <b>Processes</b>\n\n"
        if not processes: text+="No running processes."
        for name,p in list(processes.items()):
            text+=f"{name} — PID {p.pid} — {'running' if p.poll() is None else 'stopped'}\n"
        await q.edit_message_text(text,parse_mode=ParseMode.HTML,reply_markup=owner_back_host()); return
    if action=="help":
        await q.edit_message_text("📤 Send a .py file to the bot with a caption containing the project name.\nExample caption: mybot\nThen use Hosting → Projects → Start.\n\nFor security, projects run with their own working directory.",reply_markup=owner_back_host()); return

def owner_back_host():
    return InlineKeyboardMarkup([[btn("⬅️ Hosting","host")]])

async def host_start(q,name):
    if not is_owner(q.from_user.id): return
    proj=safe_project(name)
    main=proj/"main.py"
    if not proj.exists() or not main.exists():
        await q.answer("main.py not found.",show_alert=True); return
    if name in processes and processes[name].poll() is None:
        await q.answer("Already running.",show_alert=True); return
    try:
        p=subprocess.Popen(
            [sys.executable, str(main)],
            cwd=str(proj),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            start_new_session=True,
        )
        processes[name]=p
        add_log("hosting_start",name,q.from_user.id)
        await q.answer(f"Started {name}",show_alert=True)
    except Exception as e:
        await q.answer(f"Start failed: {e}",show_alert=True)

async def host_delete(q,name):
    if not is_owner(q.from_user.id): return
    proj=safe_project(name)
    if name in processes and processes[name].poll() is None:
        await q.answer("Stop the process first.",show_alert=True); return
    if proj.exists():
        shutil.rmtree(proj)
    add_log("hosting_delete",name,q.from_user.id)
    await q.answer("Deleted.",show_alert=True)
    await host_panel(q)

# ----------------------------- MODERATION ------------------------------

URL_RE=re.compile(r"(https?://|www\.)\S+",re.I)
WORD_RE=re.compile(r"[A-Za-z0-9_]+")

def message_text(msg):
    return (msg.text or msg.caption or "").strip()

def has_link(text): return bool(URL_RE.search(text))

def domains_in(text):
    out=[]
    for m in URL_RE.finditer(text):
        u=m.group(0).lower()
        u=re.sub(r"^https?://","",u)
        u=u.split("/")[0].split(":")[0]
        out.append(u)
    return out

def quiet_now(s):
    if not s["quiet_hours"]: return False
    try:
        sh,sm=map(int,s["quiet_start"].split(":"))
        eh,em=map(int,s["quiet_end"].split(":"))
        cur=datetime.now().time()
        start=cur.replace(hour=sh,minute=sm,second=0,microsecond=0)
        end=cur.replace(hour=eh,minute=em,second=0,microsecond=0)
        return (start<=cur<end) if start<=end else (cur>=start or cur<end)
    except Exception:
        return False

def filter_reason(msg,s,history=None):
    text=message_text(msg)
    reasons=[]
    if s["keyword_filter"] and s["keywords"]:
        words=[x.strip().lower() for x in s["keywords"].split(",") if x.strip()]
        if any(w in text.lower() for w in words): reasons.append("keyword")
    if s["link_filter"] and has_link(text): reasons.append("link")
    if s["domain_filter"] and has_link(text):
        allowed=[x.strip().lower() for x in s["allowed_domains"].split(",") if x.strip()]
        if allowed and any(d not in allowed for d in domains_in(text)): reasons.append("domain")
    if s["caps_filter"] and len(text)>=20:
        letters=[x for x in text if x.isalpha()]
        if letters and sum(x.isupper() for x in letters)/len(letters) >= .8: reasons.append("caps")
    if s["hashtag_filter"] and "#" in text: reasons.append("hashtag")
    if s["length_filter"] and len(text)>int(s["max_chars"]): reasons.append("length")
    if s["forward_filter"] and getattr(msg,"forward_origin",None): reasons.append("forward")
    if s["bot_filter"] and getattr(getattr(msg,"from_user",None),"is_bot",False): reasons.append("bot")
    if s["media_filter"] and (msg.photo or msg.video or msg.audio or msg.voice or msg.sticker): reasons.append("media")
    if s["gif_filter"] and msg.animation: reasons.append("gif")
    if s["document_filter"] and msg.document: reasons.append("document")
    if s["filetype_filter"] and msg.document:
        ext=Path(msg.document.file_name or "").suffix.lower().lstrip(".")
        blocked=[x.strip().lower().lstrip(".") for x in s["blocked_extensions"].split(",") if x.strip()]
        if ext in blocked: reasons.append("filetype")
    if s["filesize_filter"]:
        size=0
        for obj in (msg.document,msg.video,msg.audio):
            if obj: size=obj.file_size or 0; break
        if size > int(s["max_file_mb"])*1024*1024: reasons.append("filesize")
    if s["spam_filter"] and len(text)>0 and re.search(r"(.)\1{8,}",text): reasons.append("spam")
    if s["smart_spam"] and len(text)>2000: reasons.append("smart_spam")
    return reasons

async def schedule_delete(context, chat_id, message_id, delay, dry_run=False):
    await asyncio.sleep(delay)
    if dry_run: return
    try:
        await context.bot.delete_message(chat_id, message_id)
        inc_stat(chat_id,"deleted")
        add_log("delete","message deleted",None,chat_id)
    except TelegramError as e:
        inc_stat(chat_id,"errors")
        add_log("delete_error",str(e)[:200],None,chat_id)

async def channel_message(update:Update,context:ContextTypes.DEFAULT_TYPE):
    msg=update.channel_post or update.edited_channel_post
    if not msg: return
    chat_id=msg.chat.id
    if chat_id not in channel_ids(): return
    s=get_settings(chat_id)
    if global_flag("maintenance") or global_flag("global_kill") or global_flag("emergency_lockdown"): return
    if update.edited_channel_post and not s["edit_detection"]: return
    inc_stat(chat_id,"detected")
    reasons=filter_reason(msg,s)
    if quiet_now(s):
        reasons.append("quiet_hours")
    if s["auto_delete"]:
        reasons.append("auto_delete")
    if not reasons: return
    if s["dry_run"]:
        add_log("dry_run",",".join(reasons),None,chat_id)
        return
    delay=max(0,int(s["delete_timer"]))
    context.application.create_task(schedule_delete(context,chat_id,msg.message_id,delay,False))

# ----------------------------- BROADCAST / SCHEDULE --------------------

async def broadcast_cmd(update:Update, context:ContextTypes.DEFAULT_TYPE):
    if not await require_access(update,True): return
    text=" ".join(context.args).strip()
    if not text: return await update.message.reply_text("Usage: /broadcast TEXT")
    with db() as c: rows=c.execute("SELECT user_id FROM users WHERE status IN ('approved','admin','owner')").fetchall()
    ok=0
    for r in rows:
        try:
            await context.bot.send_message(r["user_id"],text)
            ok+=1
            await asyncio.sleep(.04)
        except TelegramError: pass
    await update.message.reply_text(f"📢 Broadcast complete: {ok}/{len(rows)} delivered.")

async def announce_cmd(update:Update, context:ContextTypes.DEFAULT_TYPE):
    if not await require_access(update,True): return
    if len(context.args)<2: return await update.message.reply_text("Usage: /announce CHANNEL_ID TEXT")
    ch=int(context.args[0]); text=" ".join(context.args[1:])
    await context.bot.send_message(ch,text,disable_web_page_preview=not bool(setting(ch,"link_preview")))
    await update.message.reply_text("📣 Announcement sent.")

async def schedule_cmd(update:Update, context:ContextTypes.DEFAULT_TYPE):
    if not await require_access(update,True): return
    if len(context.args)<3: return await update.message.reply_text("Usage: /schedule CHANNEL_ID YYYY-MM-DDTHH:MM:SS TEXT")
    ch=int(context.args[0]); when=context.args[1]; text=" ".join(context.args[2:])
    try: datetime.fromisoformat(when).replace(tzinfo=timezone.utc)
    except: return await update.message.reply_text("Invalid UTC datetime.")
    with db() as c: c.execute("INSERT INTO schedules(owner_id,chat_id,send_at,text) VALUES(?,?,?,?)",(OWNER_ID,ch,when,text))
    await update.message.reply_text("📅 Scheduled.")

async def scheduler_job(context:ContextTypes.DEFAULT_TYPE):
    now=datetime.now(timezone.utc)
    with db() as c:
        rows=c.execute("SELECT * FROM schedules WHERE sent=0").fetchall()
    for r in rows:
        try: due=datetime.fromisoformat(r["send_at"]).replace(tzinfo=timezone.utc)
        except: continue
        if due<=now:
            try:
                await context.bot.send_message(r["chat_id"],r["text"])
                with db() as c: c.execute("UPDATE schedules SET sent=1 WHERE id=?",(r["id"],))
                add_log("scheduled_sent",str(r["id"]),OWNER_ID,r["chat_id"])
            except TelegramError as e:
                add_log("scheduled_error",str(e)[:200],OWNER_ID,r["chat_id"])

# ----------------------------- CUSTOM COMMANDS -------------------------

async def addcmd_cmd(update:Update,context:ContextTypes.DEFAULT_TYPE):
    if not await require_access(update): return
    if len(context.args)<3: return await update.message.reply_text("Usage: /addcmd CHANNEL_ID NAME TEXT")
    ch=int(context.args[0]); name=re.sub(r"[^a-zA-Z0-9_]","",context.args[1]).lower(); text=" ".join(context.args[2:])
    with db() as c:
        c.execute("""INSERT INTO custom_commands(owner_id,chat_id,name,text) VALUES(?,?,?,?)
                     ON CONFLICT(owner_id,chat_id,name) DO UPDATE SET text=excluded.text""",(update.effective_user.id,ch,name,text))
    await update.message.reply_text(f"🧩 Custom command /{name} saved.")

async def delcmd_cmd(update:Update,context:ContextTypes.DEFAULT_TYPE):
    if not await require_access(update): return
    if len(context.args)<2: return await update.message.reply_text("Usage: /delcmd CHANNEL_ID NAME")
    ch=int(context.args[0]); name=context.args[1].lower()
    with db() as c: c.execute("DELETE FROM custom_commands WHERE owner_id=? AND chat_id=? AND name=?",(update.effective_user.id,ch,name))
    await update.message.reply_text("🗑️ Custom command removed.")

async def custom_command_handler(update:Update,context:ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text or not update.message.text.startswith("/"): return
    cmd=update.message.text.split()[0][1:].split("@")[0].lower()
    with db() as c:
        r=c.execute("SELECT text FROM custom_commands WHERE name=? ORDER BY id DESC LIMIT 1",(cmd,)).fetchone()
    if r and is_approved(update.effective_user.id):
        await update.message.reply_text(r["text"])

# ----------------------------- LABELS / CLEANUP ------------------------

async def labeluser_cmd(update:Update,context:ContextTypes.DEFAULT_TYPE):
    if not await require_access(update,True): return
    if len(context.args)<2: return await update.message.reply_text("Usage: /labeluser USER_ID LABEL")
    uid=int(context.args[0]); ensure_user(uid); set_user_label(uid," ".join(context.args[1:]))
    await update.message.reply_text("🏷️ User label saved.")

async def labelchannel_cmd(update:Update,context:ContextTypes.DEFAULT_TYPE):
    if not await require_access(update,True): return
    if len(context.args)<2: return await update.message.reply_text("Usage: /labelchannel CHANNEL_ID LABEL")
    ch=int(context.args[0]); label=" ".join(context.args[1:])
    with db() as c: c.execute("UPDATE channels SET label=? WHERE chat_id=?",(label,ch))
    await update.message.reply_text("🏷️ Channel label saved.")

async def cleanup_cmd(update:Update,context:ContextTypes.DEFAULT_TYPE):
    if not await require_access(update,True): return
    if len(context.args)<2: return await update.message.reply_text("Usage: /cleanup CHANNEL_ID COUNT")
    ch=int(context.args[0]); count=max(1,min(100,int(context.args[1])))
    # Telegram does not expose a general history listing API to bots. Cleanup is
    # therefore performed on message IDs tracked in memory during this run.
    ids=recent_ids.get(ch,[])[-count:]
    if not ids: return await update.message.reply_text("No recent tracked posts available.")
    done=0
    for mid in ids:
        try:
            await context.bot.delete_message(ch,mid); done+=1
        except TelegramError: pass
    await update.message.reply_text(f"🧹 Cleanup complete: {done} deleted.")

recent_ids={}

# ----------------------------- FILE UPLOAD -----------------------------

async def document_upload(update:Update,context:ContextTypes.DEFAULT_TYPE):
    if not is_owner(update.effective_user.id): return
    doc=update.message.document
    if not doc: return
    name=doc.file_name or "upload.bin"
    # Only allow safe file names and common project archives/python files.
    if not (name.lower().endswith(".py") or name.lower().endswith(".zip")):
        await update.message.reply_text("Only .py or .zip hosting uploads are accepted.")
        return
    project=(update.message.caption or Path(name).stem).strip()
    project=re.sub(r"[^A-Za-z0-9_.-]","_",project)[:40] or Path(name).stem
    proj=safe_project(project); proj.mkdir(parents=True,exist_ok=True)
    tgfile=await doc.get_file()
    target=proj/name
    await tgfile.download_to_drive(str(target))
    if name.lower().endswith(".py"):
        main=proj/"main.py"
        if target != main:
            shutil.copy2(target,main)
    else:
        with zipfile.ZipFile(target) as z:
            # prevent zip-slip
            for member in z.infolist():
                dest=(proj/member.filename).resolve()
                if not str(dest).startswith(str(proj)+os.sep): raise ValueError("Unsafe archive path")
            z.extractall(proj)
        if not (proj/"main.py").exists():
            py=next(proj.glob("*.py"),None)
            if py: shutil.copy2(py,proj/"main.py")
    await update.message.reply_text(f"📁 Project <b>{html.escape(project)}</b> uploaded.",parse_mode=ParseMode.HTML)

# ----------------------------- BACKGROUND ------------------------------

async def process_watcher(context:ContextTypes.DEFAULT_TYPE):
    for name,p in list(processes.items()):
        if p.poll() is not None:
            add_log("hosting_exit",f"{name} exit={p.returncode}",OWNER_ID)
            processes.pop(name,None)

# ----------------------------- CALLBACK DISPATCH EXTENSION --------------

async def callback_router(update:Update,context:ContextTypes.DEFAULT_TYPE):
    q=update.callback_query
    if q.data.startswith("hstart:"):
        await q.answer(); await host_start(q,q.data.split(":",1)[1]); return
    if q.data.startswith("hdel:"):
        await q.answer(); await host_delete(q,q.data.split(":",1)[1]); return
    if q.data.startswith("h:"):
        await q.answer(); await host_callback(q,q.data); return
    await callback(update,context)

# ----------------------------- MAIN ------------------------------------

app = None

def build_app():
    global app
    if not TOKEN: raise SystemExit("BOT_TOKEN environment variable is required.")
    if not OWNER_ID: raise SystemExit("OWNER_ID environment variable is required.")
    init_db()
    app=Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start",start))
    app.add_handler(CommandHandler("help",help_cmd))
    app.add_handler(CommandHandler("settime",settime_cmd))
    app.add_handler(CommandHandler("setcaption",setcaption_cmd))
    app.add_handler(CommandHandler("approve",approve_cmd))
    app.add_handler(CommandHandler("reject",reject_cmd))
    app.add_handler(CommandHandler("block",block_cmd))
    app.add_handler(CommandHandler("addchannel",addchannel_cmd))
    app.add_handler(CommandHandler("broadcast",broadcast_cmd))
    app.add_handler(CommandHandler("announce",announce_cmd))
    app.add_handler(CommandHandler("schedule",schedule_cmd))
    app.add_handler(CommandHandler("addcmd",addcmd_cmd))
    app.add_handler(CommandHandler("delcmd",delcmd_cmd))
    app.add_handler(CommandHandler("labeluser",labeluser_cmd))
    app.add_handler(CommandHandler("labelchannel",labelchannel_cmd))
    app.add_handler(CommandHandler("cleanup",cleanup_cmd))
    app.add_handler(CallbackQueryHandler(callback_router))
    app.add_handler(MessageHandler(filters.Document.ALL,document_upload))
    app.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND,custom_command_handler))
    app.add_handler(MessageHandler(filters.UpdateType.CHANNEL_POSTS,channel_message))
    app.job_queue.run_repeating(scheduler_job, interval=10, first=5)
    app.job_queue.run_repeating(process_watcher, interval=5, first=5)
    return app

if __name__=="__main__":
    build_app()
    log.info("AutoGuard starting...")
    app.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)
