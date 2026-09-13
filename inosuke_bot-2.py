#!/usr/bin/env python3
"""
╔══════════════════════════════════════╗
║       INOSUKE ATTACK BOT v2.0        ║
║   Single file — auto-installs deps   ║
║   Run: python3 inosuke_bot.py        ║
╚══════════════════════════════════════╝
"""

# ═══════════════════════════════════════════════════════════════
#  AUTO INSTALLER — runs before any import
# ═══════════════════════════════════════════════════════════════
import subprocess, sys, os

def auto_install():
    # No version pin — latest PTB (21.5+) has Python 3.13 __slots__ fix
    pkgs = [
        "python-telegram-bot",
        "playwright",
    ]
    for pkg in pkgs:
        print(f"[INSTALL] installing {pkg} ...")
        subprocess.check_call(
            [sys.executable, "-m", "pip", "install", pkg, "-q", "--upgrade"],
            stderr=subprocess.DEVNULL
        )
    print("[INSTALL] setting up chromium ...")
    subprocess.run(
        [sys.executable, "-m", "playwright", "install", "chromium"],
        capture_output=True
    )
    print("[INSTALL] done.\n")

auto_install()

# ═══════════════════════════════════════════════════════════════
#  IMPORTS
# ═══════════════════════════════════════════════════════════════
import asyncio
import json
import random
import shutil
import sqlite3
from datetime import datetime

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)
from playwright.async_api import async_playwright

# ═══════════════════════════════════════════════════════════════
#  CONFIG — EDIT THESE BEFORE RUNNING
# ═══════════════════════════════════════════════════════════════
BOT_TOKEN        = "YOUR_BOT_TOKEN"   # @BotFather token
ADMIN_IDS        = [123456789]        # your Telegram user ID(s)
REQUIRE_APPROVAL = False              # True = admin must approve each user

# ═══════════════════════════════════════════════════════════════
#  DEFAULT ATTACK MESSAGES
# ═══════════════════════════════════════════════════════════════
DEFAULT_MSGS = [
    "[{target}] 𝐒𝐘𝐒𝐓𝐄𝐌 𝐎𝐕𝐄𝐑𝐋𝐎𝐀𝐃 teri aukat nahi hamse ladne ki 😂🦅",
    "[{target}] 𝐈𝐍𝐎𝐒𝐔𝐊𝐄 𝐒𝐈𝐃𝐄 𝐀𝐂𝐓𝐈𝐕𝐄 ab rone ka alawa koi rasta nahi 🤣🔥",
    "[{target}] 𝐓𝐄𝐑𝐈 𝐆𝐀𝐋𝐓𝐈 𝐓𝐇𝐈 𝐇𝐀𝐌𝐒𝐄 𝐏𝐀𝐍𝐆𝐀 𝐋𝐄𝐍𝐀 👑🔱",
    "[{target}] 𝐋𝐎𝐒𝐄𝐑 𝐀𝐋𝐄𝐑𝐓 bhag ja yahan se 😈💀",
    "[{target}] 𝐅𝐋𝐎𝐎𝐃𝐄𝐃 𝐁𝐘 𝐈𝐍𝐎𝐒𝐔𝐊𝐄 koi nahi bachayega tujhe 🔱⚡",
]

# ═══════════════════════════════════════════════════════════════
#  DATABASE
# ═══════════════════════════════════════════════════════════════
DB_FILE = "inosuke_bot.db"

def db_exec(query, params=(), fetch=None):
    con = sqlite3.connect(DB_FILE)
    c   = con.cursor()
    c.execute(query, params)
    r   = None
    if   fetch == "one": r = c.fetchone()
    elif fetch == "all": r = c.fetchall()
    con.commit()
    con.close()
    return r

def db_init():
    db_exec("""CREATE TABLE IF NOT EXISTS users (
        uid        INTEGER PRIMARY KEY,
        username   TEXT    DEFAULT '',
        approved   INTEGER DEFAULT 0,
        banned     INTEGER DEFAULT 0,
        daily_cnt  INTEGER DEFAULT 0,
        last_date  TEXT    DEFAULT '',
        joined     TEXT    DEFAULT ''
    )""")
    db_exec("""CREATE TABLE IF NOT EXISTS user_settings (
        uid          INTEGER PRIMARY KEY,
        sid          TEXT    DEFAULT '',
        multi_ids    TEXT    DEFAULT '[]',
        url          TEXT    DEFAULT '',
        opponent     TEXT    DEFAULT '',
        engine_count INTEGER DEFAULT 4,
        delay        REAL    DEFAULT 0.3,
        name_locker  INTEGER DEFAULT 1,
        custom_msgs  TEXT    DEFAULT '[]'
    )""")
    db_exec("""CREATE TABLE IF NOT EXISTS global_config (
        key TEXT PRIMARY KEY,
        val TEXT
    )""")
    db_exec("""CREATE TABLE IF NOT EXISTS logs (
        id     INTEGER PRIMARY KEY AUTOINCREMENT,
        uid    INTEGER,
        action TEXT,
        detail TEXT,
        ts     TEXT
    )""")
    for k, v in [
        ("bot_active",   "1"),
        ("max_engines",  "6"),
        ("daily_limit",  "999"),
        ("global_delay", "0.0"),
    ]:
        db_exec("INSERT OR IGNORE INTO global_config VALUES (?,?)", (k, v))

# ── helpers ──────────────────────────────────────────────────
def gcfg(key):
    r = db_exec("SELECT val FROM global_config WHERE key=?", (key,), fetch="one")
    return r[0] if r else None

def scfg(key, val):
    db_exec("INSERT OR REPLACE INTO global_config VALUES (?,?)", (key, str(val)))

def get_user(uid):
    return db_exec("SELECT * FROM users WHERE uid=?", (uid,), fetch="one")

def ensure_user(uid, username):
    approved = 0 if REQUIRE_APPROVAL else 1
    db_exec(
        "INSERT OR IGNORE INTO users VALUES (?,?,?,0,0,'',?)",
        (uid, username or "", approved,
         datetime.now().strftime("%Y-%m-%d %H:%M")),
    )

def get_us(uid):
    r = db_exec("SELECT * FROM user_settings WHERE uid=?", (uid,), fetch="one")
    if not r:
        db_exec(
            "INSERT OR IGNORE INTO user_settings VALUES (?,?,?,?,?,4,0.3,1,'[]')",
            (uid, "", "[]", "", ""),
        )
        r = db_exec("SELECT * FROM user_settings WHERE uid=?", (uid,), fetch="one")
    return r
# columns: uid,sid,multi_ids,url,opponent,engine_count,delay,name_locker,custom_msgs
#          0   1   2         3   4        5            6     7           8

def upd_us(uid, field, value):
    db_exec(f"UPDATE user_settings SET {field}=? WHERE uid=?", (value, uid))

def log_it(uid, action, detail=""):
    db_exec(
        "INSERT INTO logs VALUES (NULL,?,?,?,?)",
        (uid, action, detail, datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
    )

# ═══════════════════════════════════════════════════════════════
#  RUNTIME STATE
# ═══════════════════════════════════════════════════════════════
active_attacks: dict[int, list]  = {}   # uid → [asyncio.Task]
attack_stats:   dict[int, dict]  = {}   # uid → {strikes, start, engines, opponent}
user_state:     dict[int, str]   = {}   # uid → waiting_for

# ═══════════════════════════════════════════════════════════════
#  KEYBOARD BUILDERS
# ═══════════════════════════════════════════════════════════════
def IB(text, cb):
    return InlineKeyboardButton(text, callback_data=cb)

def kb_main():
    return InlineKeyboardMarkup([
        [IB("▶️ Start Attack",   "start_atk"),  IB("⏹ Stop Attack",    "stop_atk")],
        [IB("📊 Status",          "status"),      IB("⚙️ Settings",       "settings")],
        [IB("📝 Custom Msgs",     "custom_msgs"), IB("❓ Help",           "help")],
    ])

def kb_settings():
    return InlineKeyboardMarkup([
        [IB("🎯 Set URL",         "set_url"),    IB("🪪 Set Session ID", "set_sid")],
        [IB("👤 Set Opponent",    "set_opp"),    IB("⚡ Engine Count",   "set_eng")],
        [IB("💬 Set Delay",       "set_delay"),  IB("🔒 Toggle Locker", "tog_lock")],
        [IB("🆔 Multi-ID Mode",   "multi_id"),   IB("🔙 Back",          "main_menu")],
    ])

def kb_admin():
    active  = gcfg("bot_active") == "1"
    tog_lbl = "🔴 Bot OFF" if active else "🟢 Bot ON"
    tog_cb  = "bot_off"   if active else "bot_on"
    return InlineKeyboardMarkup([
        [IB("👥 All Users",       "adm_users"),     IB("✅ Approve User",  "adm_approve")],
        [IB("🚫 Ban User",        "adm_ban"),        IB("🔓 Unban User",   "adm_unban")],
        [IB("💀 Remove User",     "adm_remove"),     IB("📈 Stats",        "adm_stats")],
        [IB("📋 Logs",            "adm_logs"),       IB("🕐 Live Monitor", "adm_live")],
        [IB(tog_lbl,              tog_cb),           IB("⚡ Global Delay", "adm_gdelay")],
        [IB("🔢 Max Engines",     "adm_maxeng"),     IB("📨 Daily Limit",  "adm_dlimit")],
        [IB("📣 Broadcast",       "adm_broadcast"),  IB("👑 View Admins",  "adm_admins")],
    ])

def kb_custom():
    return InlineKeyboardMarkup([
        [IB("➕ Add Message",  "add_msg"),     IB("🗑 Clear All", "clear_msgs")],
        [IB("🔙 Back",         "main_menu")],
    ])

def kb_back():
    return InlineKeyboardMarkup([[IB("🔙 Back", "main_menu")]])

# ═══════════════════════════════════════════════════════════════
#  GUARDS
# ═══════════════════════════════════════════════════════════════
async def guard(update: Update) -> bool:
    uid = update.effective_user.id
    u   = get_user(uid)
    if not u:
        return False
    if u[3]:
        await update.effective_message.reply_text("🚫 You are banned.")
        return False
    if gcfg("bot_active") == "0" and uid not in ADMIN_IDS:
        await update.effective_message.reply_text("🔴 Bot is currently offline.")
        return False
    if not u[2] and uid not in ADMIN_IDS:
        await update.effective_message.reply_text("⏳ Awaiting admin approval.")
        return False
    return True

def is_admin(uid: int) -> bool:
    return uid in ADMIN_IDS

# ═══════════════════════════════════════════════════════════════
#  ATTACK ENGINE
# ═══════════════════════════════════════════════════════════════
def build_payload(opponent: str, custom_msgs: list) -> str:
    pool    = custom_msgs if custom_msgs else DEFAULT_MSGS
    gap     = "\n" * 160
    rand_id = random.randint(1000, 9999)
    core    = random.choice(pool).replace("{target}", opponent)
    return f"{core}{gap}{core}{gap}{core}\n🔱 INOSUKE GOD [{rand_id}] 🔱"

async def block_media(route):
    if route.request.resource_type in ("image", "media", "font"):
        await route.abort()
    else:
        await route.continue_()

async def force_name_lock(page, gc_name: str):
    try:
        gear = page.locator('svg[aria-label="Conversation information"]')
        await gear.click(timeout=5000)
        change_btn  = page.locator('div[aria-label="Change group name"][role="button"]')
        group_input = page.locator('input[aria-label="Group name"][name="change-group-name"]')
        save_btn    = page.locator('div[role="button"]:has-text("Save")')
        await change_btn.click(timeout=5000)
        await group_input.fill(gc_name)
        if await save_btn.is_enabled():
            await save_btn.click()
        await gear.click(timeout=3000)
    except Exception:
        await page.reload(wait_until="domcontentloaded")

async def run_engine(
    engine_id:   int,
    sid:         str,
    url:         str,
    opponent:    str,
    gc_name:     str,
    is_locker:   bool,
    delay:       float,
    custom_msgs: list,
    uid:         int,
    strike_counter: dict,
):
    udir = f"./sess_{uid}_{engine_id}"
    while True:
        try:
            async with async_playwright() as pw:
                ctx = await pw.chromium.launch_persistent_context(
                    udir,
                    headless=True,
                    args=["--no-sandbox", "--disable-gpu", "--disable-dev-shm-usage"],
                )
                await ctx.add_cookies([{
                    "name":     "sessionid",
                    "value":    sid,
                    "domain":   ".instagram.com",
                    "path":     "/",
                    "secure":   True,
                    "httpOnly": True,
                }])
                page = await ctx.new_page()
                await page.route("**/*", block_media)
                await page.goto(url, wait_until="domcontentloaded", timeout=60000)
                mbox = page.locator(
                    'div[role="textbox"], div[aria-label="Message"]'
                ).first

                for i in range(150):
                    # reload every 30 strikes to stay fresh
                    if i > 0 and i % 30 == 0:
                        await page.reload(wait_until="domcontentloaded")
                        mbox = page.locator(
                            'div[role="textbox"], div[aria-label="Message"]'
                        ).first
                        await mbox.focus()
                    # name lock every 19 strikes on engine 1
                    if is_locker and i > 0 and i % 19 == 0:
                        await force_name_lock(page, gc_name)
                        await mbox.focus()

                    await mbox.focus()
                    await mbox.fill(build_payload(opponent, custom_msgs))
                    await page.keyboard.press("Enter")
                    strike_counter[engine_id] = strike_counter.get(engine_id, 0) + 1
                    await asyncio.sleep(random.uniform(delay, delay + 0.1))

                await ctx.close()

        except asyncio.CancelledError:
            if os.path.exists(udir):
                shutil.rmtree(udir, ignore_errors=True)
            return
        except Exception:
            pass
        finally:
            if os.path.exists(udir):
                shutil.rmtree(udir, ignore_errors=True)
        await asyncio.sleep(1)

# ═══════════════════════════════════════════════════════════════
#  COMMAND HANDLERS
# ═══════════════════════════════════════════════════════════════
async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid   = update.effective_user.id
    uname = update.effective_user.username or update.effective_user.first_name or "user"
    ensure_user(uid, uname)
    if not await guard(update):
        return
    await update.message.reply_text(
        f"🔱 *INOSUKE ATTACK BOT*\n"
        f"━━━━━━━━━━━━━━━━\n"
        f"👑 *DEVELOPER:* InosukexGOD\n"
        f"⚡ *STATUS:* ACTIVE\n"
        f"━━━━━━━━━━━━━━━━\n"
        f"Aagaye `{uname}` — bench ready hai.",
        parse_mode="Markdown",
        reply_markup=kb_main(),
    )

async def cmd_admin(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not is_admin(uid):
        await update.message.reply_text("🚫 Admin only.")
        return
    await update.message.reply_text(
        "👑 *Admin Panel*",
        parse_mode="Markdown",
        reply_markup=kb_admin(),
    )

# ═══════════════════════════════════════════════════════════════
#  CALLBACK ROUTER
# ═══════════════════════════════════════════════════════════════
async def cb_router(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q     = update.callback_query
    await q.answer()
    uid   = q.from_user.id
    uname = q.from_user.username or q.from_user.first_name or "user"
    data  = q.data
    ensure_user(uid, uname)

    # admin path
    admin_cbs = {
        "adm_users", "adm_approve", "adm_ban", "adm_unban", "adm_remove",
        "adm_stats", "adm_logs", "adm_live", "adm_gdelay", "adm_maxeng",
        "adm_dlimit", "adm_broadcast", "adm_admins", "bot_on", "bot_off",
    }
    if data in admin_cbs:
        if not is_admin(uid):
            await q.edit_message_text("🚫 Admin only.")
            return
        await handle_admin_cb(q, uid, data, ctx)
        return

    if not await guard(update):
        return

    # user path
    routes = {
        "main_menu":   lambda: q.edit_message_text("🔱 Main Menu", reply_markup=kb_main()),
        "settings":    lambda: show_settings(q, uid),
        "status":      lambda: show_status(q, uid),
        "help":        lambda: show_help(q),
        "custom_msgs": lambda: show_custom_msgs(q, uid),
        "start_atk":   lambda: start_attack(q, uid, ctx),
        "stop_atk":    lambda: stop_attack(q, uid),
        "tog_lock":    lambda: toggle_locker(q, uid),
        "clear_msgs":  lambda: clear_custom_msgs(q, uid),
        "multi_id":  lambda: prompt_input(q, uid, "multi_id",
                               "🆔 Multi-ID — session ids comma-separated bhej:"),
        "set_url":   lambda: prompt_input(q, uid, "url",
                               "🎯 Group URL bhej:"),
        "set_sid":   lambda: prompt_input(q, uid, "sid",
                               "🪪 Session ID bhej:"),
        "set_opp":   lambda: prompt_input(q, uid, "opp",
                               "👤 Opponent naam bhej:"),
        "set_eng":   lambda: prompt_input(q, uid, "eng",
                               f"⚡ Engine count bhej (1–{gcfg('max_engines')}):"),
        "set_delay": lambda: prompt_input(q, uid, "delay",
                               "💬 Delay bhej (0.0 = fastest, 1.0 = slow):"),
        "add_msg":   lambda: prompt_input(q, uid, "add_msg",
                               "📝 Custom message bhej.\n`{target}` = opponent naam:"),
    }
    fn = routes.get(data)
    if fn:
        await fn()

async def prompt_input(q, uid: int, state: str, text: str):
    user_state[uid] = state
    await q.edit_message_text(text, parse_mode="Markdown", reply_markup=kb_back())

# ═══════════════════════════════════════════════════════════════
#  MESSAGE HANDLER — input state machine
# ═══════════════════════════════════════════════════════════════
async def msg_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid   = update.effective_user.id
    uname = update.effective_user.username or update.effective_user.first_name or "user"
    ensure_user(uid, uname)
    if not await guard(update):
        return

    state = user_state.pop(uid, None)
    if not state:
        return

    raw = update.message.text.strip()
    us  = get_us(uid)

    # ── user inputs ─────────────────────────────────────────
    if state == "url":
        upd_us(uid, "url", raw)
        await update.message.reply_text("✅ URL saved.", reply_markup=kb_settings())

    elif state == "sid":
        upd_us(uid, "sid",       raw)
        upd_us(uid, "multi_ids", "[]")
        await update.message.reply_text("✅ Session ID saved.", reply_markup=kb_settings())

    elif state == "multi_id":
        ids = [s.strip() for s in raw.split(",") if s.strip()]
        upd_us(uid, "multi_ids", json.dumps(ids))
        upd_us(uid, "sid",       ids[0] if ids else "")
        await update.message.reply_text(
            f"✅ {len(ids)} session id(s) saved.", reply_markup=kb_settings()
        )

    elif state == "opp":
        upd_us(uid, "opponent", raw)
        await update.message.reply_text("✅ Opponent set.", reply_markup=kb_settings())

    elif state == "eng":
        try:
            n = max(1, min(int(raw), int(gcfg("max_engines"))))
            upd_us(uid, "engine_count", n)
            await update.message.reply_text(f"✅ Engines: {n}", reply_markup=kb_settings())
        except ValueError:
            await update.message.reply_text("❌ Number bhej.", reply_markup=kb_settings())

    elif state == "delay":
        try:
            d = max(0.0, float(raw))
            upd_us(uid, "delay", d)
            await update.message.reply_text(f"✅ Delay: {d}s", reply_markup=kb_settings())
        except ValueError:
            await update.message.reply_text("❌ Number bhej (e.g. 0.3).", reply_markup=kb_settings())

    elif state == "add_msg":
        msgs = json.loads(us[8] or "[]")
        msgs.append(raw)
        upd_us(uid, "custom_msgs", json.dumps(msgs))
        await update.message.reply_text(
            f"✅ Message added. Total: {len(msgs)}", reply_markup=kb_back()
        )

    # ── admin inputs ─────────────────────────────────────────
    elif state == "adm_approve":
        try:
            tid = int(raw)
            db_exec("UPDATE users SET approved=1 WHERE uid=?", (tid,))
            await update.message.reply_text(f"✅ User {tid} approved.")
        except ValueError:
            await update.message.reply_text("❌ Valid user ID bhej.")
        await update.message.reply_text("👑 Admin", reply_markup=kb_admin())

    elif state == "adm_ban":
        try:
            tid = int(raw)
            db_exec("UPDATE users SET banned=1 WHERE uid=?", (tid,))
            await update.message.reply_text(f"🚫 User {tid} banned.")
        except ValueError:
            await update.message.reply_text("❌ Valid user ID bhej.")
        await update.message.reply_text("👑 Admin", reply_markup=kb_admin())

    elif state == "adm_unban":
        try:
            tid = int(raw)
            db_exec("UPDATE users SET banned=0 WHERE uid=?", (tid,))
            await update.message.reply_text(f"✅ User {tid} unbanned.")
        except ValueError:
            await update.message.reply_text("❌ Valid user ID bhej.")
        await update.message.reply_text("👑 Admin", reply_markup=kb_admin())

    elif state == "adm_remove":
        try:
            tid = int(raw)
            db_exec("DELETE FROM users WHERE uid=?", (tid,))
            db_exec("DELETE FROM user_settings WHERE uid=?", (tid,))
            await update.message.reply_text(f"💀 User {tid} removed from DB.")
        except ValueError:
            await update.message.reply_text("❌ Valid user ID bhej.")
        await update.message.reply_text("👑 Admin", reply_markup=kb_admin())

    elif state == "adm_broadcast":
        users = db_exec("SELECT uid FROM users WHERE banned=0", fetch="all")
        sent  = 0
        for (tuid,) in (users or []):
            try:
                await ctx.bot.send_message(
                    tuid, f"📣 *BROADCAST*\n\n{raw}", parse_mode="Markdown"
                )
                sent += 1
            except Exception:
                pass
        await update.message.reply_text(f"✅ Sent to {sent} users.", reply_markup=kb_admin())

    elif state == "adm_gdelay":
        try:
            scfg("global_delay", float(raw))
            await update.message.reply_text(f"✅ Global delay: {raw}s", reply_markup=kb_admin())
        except ValueError:
            await update.message.reply_text("❌ Number bhej.", reply_markup=kb_admin())

    elif state == "adm_maxeng":
        try:
            scfg("max_engines", int(raw))
            await update.message.reply_text(f"✅ Max engines: {raw}", reply_markup=kb_admin())
        except ValueError:
            await update.message.reply_text("❌ Number bhej.", reply_markup=kb_admin())

    elif state == "adm_dlimit":
        try:
            scfg("daily_limit", int(raw))
            await update.message.reply_text(f"✅ Daily limit: {raw}", reply_markup=kb_admin())
        except ValueError:
            await update.message.reply_text("❌ Number bhej.", reply_markup=kb_admin())

# ═══════════════════════════════════════════════════════════════
#  ATTACK CONTROL
# ═══════════════════════════════════════════════════════════════
async def start_attack(q, uid: int, ctx: ContextTypes.DEFAULT_TYPE):
    us = get_us(uid)
    sid       = us[1]
    multi_ids = json.loads(us[2] or "[]")
    url       = us[3]
    opponent  = us[4]
    eng_n     = us[5]
    delay     = us[6] + float(gcfg("global_delay") or 0)
    locker    = bool(us[7])
    custom    = json.loads(us[8] or "[]")

    if not url or (not sid and not multi_ids):
        await q.edit_message_text(
            "❌ Pehle Settings mein URL aur Session ID set kar.",
            reply_markup=kb_main(),
        )
        return
    if not opponent:
        await q.edit_message_text(
            "❌ Settings mein Opponent naam set kar.",
            reply_markup=kb_main(),
        )
        return
    if uid in active_attacks and active_attacks[uid]:
        await q.edit_message_text(
            "⚠️ Attack already running hai. Pehle stop kar.",
            reply_markup=kb_main(),
        )
        return

    sids            = multi_ids if multi_ids else [sid]
    gc_name         = f"[{opponent}] ki maa chudke pagal"
    strike_counter  = {}
    attack_stats[uid] = {
        "strikes":  strike_counter,
        "start":    datetime.now().strftime("%H:%M:%S"),
        "engines":  eng_n,
        "opponent": opponent,
    }

    tasks = []
    for i in range(eng_n):
        s = sids[i % len(sids)]
        t = asyncio.create_task(
            run_engine(
                i + 1, s, url, opponent, gc_name,
                (i == 0 and locker), delay, custom,
                uid, strike_counter,
            )
        )
        tasks.append(t)

    active_attacks[uid] = tasks
    log_it(uid, "ATTACK_START", f"target={opponent} engines={eng_n}")

    await q.edit_message_text(
        f"🔱 *ATTACK LAUNCHED*\n"
        f"━━━━━━━━━━━━━━━━\n"
        f"🎯 Target:  `{opponent}`\n"
        f"⚡ Engines: `{eng_n}`\n"
        f"🔒 Locker:  `{'ON' if locker else 'OFF'}`\n"
        f"💬 Delay:   `{delay}s`\n"
        f"━━━━━━━━━━━━━━━━\n"
        f"Use ⏹ Stop Attack to halt.",
        parse_mode="Markdown",
        reply_markup=kb_main(),
    )

async def stop_attack(q, uid: int):
    tasks = active_attacks.pop(uid, [])
    if not tasks:
        await q.edit_message_text("⚠️ Koi attack running nahi.", reply_markup=kb_main())
        return
    for t in tasks:
        t.cancel()
    log_it(uid, "ATTACK_STOP")
    stats  = attack_stats.pop(uid, {})
    total  = sum(stats.get("strikes", {}).values()) if stats else 0
    await q.edit_message_text(
        f"⏹ *ATTACK STOPPED*\n\nTotal strikes fired: `{total}`",
        parse_mode="Markdown",
        reply_markup=kb_main(),
    )

# ═══════════════════════════════════════════════════════════════
#  USER UI
# ═══════════════════════════════════════════════════════════════
async def show_settings(q, uid: int):
    us       = get_us(uid)
    sid_disp = f"...{us[1][-8:]}" if us[1] else "❌ Not set"
    multi    = json.loads(us[2] or "[]")
    await q.edit_message_text(
        f"⚙️ *Settings*\n"
        f"━━━━━━━━━━━━━━━━\n"
        f"🪪 Session ID:   `{sid_disp}`\n"
        f"🆔 Multi IDs:    `{len(multi)}`\n"
        f"🎯 URL:          `{'Set ✅' if us[3] else 'Not set ❌'}`\n"
        f"👤 Opponent:     `{us[4] or 'Not set ❌'}`\n"
        f"⚡ Engines:      `{us[5]}`\n"
        f"💬 Delay:        `{us[6]}s`\n"
        f"🔒 Name Locker:  `{'ON ✅' if us[7] else 'OFF ❌'}`\n"
        f"📝 Custom Msgs:  `{len(json.loads(us[8] or '[]'))}`",
        parse_mode="Markdown",
        reply_markup=kb_settings(),
    )

async def show_status(q, uid: int):
    tasks = active_attacks.get(uid, [])
    stats = attack_stats.get(uid, {})
    if tasks:
        total   = sum(stats.get("strikes", {}).values())
        per_eng = "\n".join(
            f"  E-{k}: {v} strikes"
            for k, v in stats.get("strikes", {}).items()
        )
        await q.edit_message_text(
            f"📊 *Attack Status*\n"
            f"━━━━━━━━━━━━━━━━\n"
            f"🎯 Target:   `{stats.get('opponent','?')}`\n"
            f"⏱ Started:  `{stats.get('start','?')}`\n"
            f"🔥 Total:    `{total}` strikes\n"
            f"━━━━━━━━━━━━━━━━\n"
            f"{per_eng}",
            parse_mode="Markdown",
            reply_markup=kb_main(),
        )
    else:
        await q.edit_message_text("📊 Koi attack active nahi.", reply_markup=kb_main())

async def show_help(q):
    await q.edit_message_text(
        "❓ *Help*\n"
        "━━━━━━━━━━━━━━━━\n"
        "1️⃣  Settings mein URL, Session ID, Opponent set kar\n"
        "2️⃣  ▶️ Start Attack dabao\n"
        "3️⃣  📊 Status se live strikes dekho\n"
        "4️⃣  ⏹ Stop Attack se band karo\n"
        "━━━━━━━━━━━━━━━━\n"
        "👑 Admin panel: /admin\n"
        "🪪 Session ID: Instagram browser cookies → `sessionid` field",
        parse_mode="Markdown",
        reply_markup=kb_back(),
    )

async def show_custom_msgs(q, uid: int):
    us   = get_us(uid)
    msgs = json.loads(us[8] or "[]")
    text = "📝 *Custom Messages*\n━━━━━━━━━━━━━━━━\n"
    if msgs:
        for i, m in enumerate(msgs, 1):
            preview = m[:50] + "..." if len(m) > 50 else m
            text += f"{i}. {preview}\n"
    else:
        text += "_Default messages use ho rahe hain_\n"
    await q.edit_message_text(text, parse_mode="Markdown", reply_markup=kb_custom())

async def clear_custom_msgs(q, uid: int):
    upd_us(uid, "custom_msgs", "[]")
    await q.edit_message_text(
        "✅ Custom messages cleared. Defaults active.",
        reply_markup=kb_main(),
    )

async def toggle_locker(q, uid: int):
    us  = get_us(uid)
    new = 0 if us[7] else 1
    upd_us(uid, "name_locker", new)
    await q.edit_message_text(
        f"🔒 Name Locker: `{'ON ✅' if new else 'OFF ❌'}`",
        parse_mode="Markdown",
        reply_markup=kb_settings(),
    )

# ═══════════════════════════════════════════════════════════════
#  ADMIN CALLBACKS
# ═══════════════════════════════════════════════════════════════
async def handle_admin_cb(q, uid: int, data: str, ctx: ContextTypes.DEFAULT_TYPE):
    input_prompts = {
        "adm_approve":   "✅ Approve karne ka User ID bhej:",
        "adm_ban":       "🚫 Ban karne ka User ID bhej:",
        "adm_unban":     "🔓 Unban karne ka User ID bhej:",
        "adm_remove":    "💀 Remove karne ka User ID bhej:",
        "adm_broadcast": "📣 Broadcast message bhej:",
        "adm_gdelay":    "⚡ Global delay bhej (seconds, e.g. 0.5):",
        "adm_maxeng":    "🔢 Max engines per user bhej:",
        "adm_dlimit":    "📨 Daily attack limit bhej:",
    }

    if data == "bot_on":
        scfg("bot_active", "1")
        await q.edit_message_text("🟢 Bot ON", reply_markup=kb_admin())

    elif data == "bot_off":
        scfg("bot_active", "0")
        await q.edit_message_text("🔴 Bot OFF", reply_markup=kb_admin())

    elif data == "adm_stats":
        total    = db_exec("SELECT COUNT(*) FROM users",                      fetch="one")[0]
        approved = db_exec("SELECT COUNT(*) FROM users WHERE approved=1",     fetch="one")[0]
        banned   = db_exec("SELECT COUNT(*) FROM users WHERE banned=1",       fetch="one")[0]
        live     = len(active_attacks)
        await q.edit_message_text(
            f"📈 *Bot Stats*\n"
            f"━━━━━━━━━━━━━━━━\n"
            f"👥 Total Users:   `{total}`\n"
            f"✅ Approved:      `{approved}`\n"
            f"🚫 Banned:        `{banned}`\n"
            f"⚡ Live Attacks:  `{live}`\n"
            f"🤖 Bot:           `{'ON' if gcfg('bot_active') == '1' else 'OFF'}`\n"
            f"🔢 Max Engines:   `{gcfg('max_engines')}`\n"
            f"📨 Daily Limit:   `{gcfg('daily_limit')}`",
            parse_mode="Markdown",
            reply_markup=kb_admin(),
        )

    elif data == "adm_users":
        users = db_exec(
            "SELECT uid, username, approved, banned FROM users LIMIT 20", fetch="all"
        ) or []
        text = "👥 *Users (latest 20)*\n━━━━━━━━━━━━━━━━\n"
        for u in users:
            st    = "🚫" if u[3] else ("✅" if u[2] else "⏳")
            uname = f"@{u[1]}" if u[1] else "noname"
            text += f"{st} `{u[0]}` — {uname}\n"
        await q.edit_message_text(
            text or "No users.", parse_mode="Markdown", reply_markup=kb_admin()
        )

    elif data == "adm_logs":
        logs = db_exec(
            "SELECT uid, action, detail, ts FROM logs ORDER BY id DESC LIMIT 15",
            fetch="all",
        ) or []
        text = "📋 *Recent Logs*\n━━━━━━━━━━━━━━━━\n"
        for l in logs:
            text += f"`{l[3]}` | `{l[0]}` | {l[1]} {l[2]}\n"
        await q.edit_message_text(
            text or "No logs.", parse_mode="Markdown", reply_markup=kb_admin()
        )

    elif data == "adm_live":
        if not active_attacks:
            await q.edit_message_text("🕐 Koi active attack nahi.", reply_markup=kb_admin())
            return
        text = "🕐 *Live Attacks*\n━━━━━━━━━━━━━━━━\n"
        for auid, tasks in active_attacks.items():
            st    = attack_stats.get(auid, {})
            total = sum(st.get("strikes", {}).values())
            text += (
                f"👤 `{auid}` | 🎯 {st.get('opponent','?')} "
                f"| ⚡ {len(tasks)} engines | 🔥 {total} strikes\n"
            )
        await q.edit_message_text(text, parse_mode="Markdown", reply_markup=kb_admin())

    elif data == "adm_admins":
        text = "👑 *Admins*\n━━━━━━━━━━━━━━━━\n"
        for aid in ADMIN_IDS:
            text += f"`{aid}`\n"
        await q.edit_message_text(text, parse_mode="Markdown", reply_markup=kb_admin())

    elif data in input_prompts:
        user_state[uid] = data
        await q.edit_message_text(input_prompts[data], reply_markup=kb_back())

# ═══════════════════════════════════════════════════════════════
#  MAIN
# ═══════════════════════════════════════════════════════════════
def main():
    db_init()
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("admin", cmd_admin))
    app.add_handler(CallbackQueryHandler(cb_router))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, msg_handler))
    print("🔱 INOSUKE BOT RUNNING — Ctrl+C to stop")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
