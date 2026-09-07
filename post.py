import logging
import asyncio
import os
from datetime import datetime, timedelta

import aiosqlite

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler, 
    MessageHandler, filters, ContextTypes
)
from telegram.error import TelegramError

# ==========================================
# CONFIGURATION - Aapki Values
# ==========================================
BOT_TOKEN = "8982922702:AAEuSWzlp_de_WymFxja_HSNwph9AXLNT5Y"
OWNER_ID = "8609127164"
DELETE_AFTER_SECONDS = 0  # 0 = Keep latest post only

# Setup logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

DB_NAME = "bot.db"
RUNTIME_DELETE_SECONDS = 0
CHANNEL_ID = None # Will be loaded dynamically from DB

# ==========================================
# DATABASE OPERATIONS
# ==========================================

async def init_db():
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute('''CREATE TABLE IF NOT EXISTS usage (
                        date TEXT PRIMARY KEY,
                        count INTEGER DEFAULT 0
                    )''')
        await db.execute('''CREATE TABLE IF NOT EXISTS posts (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        channel_message_id INTEGER,
                        created_at TEXT
                    )''')
        await db.execute('''CREATE TABLE IF NOT EXISTS settings (
                        key TEXT PRIMARY KEY,
                        value TEXT
                    )''')
        await db.commit()

async def get_setting(key, default):
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT value FROM settings WHERE key = ?", (key,)) as cursor:
            row = await cursor.fetchone()
            return row[0] if row else str(default)

async def set_setting(key, value):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, str(value)))
        await db.commit()

# ==========================================
# AUTO-REMOVE LOGIC
# ==========================================

async def delete_after_delay(bot, message_id, delay):
    await asyncio.sleep(delay)
    try:
        if CHANNEL_ID:
            await bot.delete_message(chat_id=CHANNEL_ID, message_id=message_id)
    except TelegramError as e:
        logger.warning(f"Failed to delete message {message_id} after delay: {e}")
    
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("DELETE FROM posts WHERE channel_message_id = ?", (message_id,))
        await db.commit()

async def delete_old_posts(bot):
    if not CHANNEL_ID: return
    
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT channel_message_id FROM posts ORDER BY created_at DESC LIMIT -1 OFFSET 1") as cursor:
            old_posts = await cursor.fetchall()
        
        for (msg_id,) in old_posts:
            try:
                await bot.delete_message(chat_id=CHANNEL_ID, message_id=msg_id)
            except TelegramError as e:
                logger.warning(f"Failed to delete old message {msg_id}: {e}")
        
        await db.execute("DELETE FROM posts WHERE id NOT IN (SELECT id FROM posts ORDER BY created_at DESC LIMIT 1)")
        await db.commit()

# ==========================================
# HELPERS & UI GENERATION
# ==========================================

def is_owner(update: Update) -> bool:
    user = update.effective_user
    return user is not None and str(user.id) == str(OWNER_ID)

async def get_start_content(context: ContextTypes.DEFAULT_TYPE):
    channel_status = "Not Set"
    if CHANNEL_ID:
        try:
            chat = await context.bot.get_chat(CHANNEL_ID)
            channel_status = chat.title
        except TelegramError:
            channel_status = "Disconnected"

    auto_remove_status = "Enabled" if RUNTIME_DELETE_SECONDS > 0 else "Latest Post Only"

    text = (
        "👑 <b>POST CONTROL CENTER</b>\n\n"
        "⚡ Welcome, Owner!\n\n"
        f"📢 <b>Channel:</b> {channel_status}\n"
        "📊 <b>Daily Limit:</b> 2 Posts\n"
        f"🗑️ <b>Auto Remove:</b> {auto_remove_status}\n\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        "📤 Send a post and the bot will publish it directly to your configured channel.\n\n"
        "🔥 <b>Owner-only access</b>\n"
        "⚡ <b>2 posts per day</b>\n"
        "🗑️ <b>Automatic post removal</b>\n"
        "💾 <b>Persistent database</b>\n\n"
        "Use the inline buttons below to manage everything."
    )

    keyboard = [
        [InlineKeyboardButton("📊 Today's Limit", callback_data="limit")],
        [InlineKeyboardButton("⚙️ Settings", callback_data="settings")],
        [InlineKeyboardButton("🔄 Reset Daily Limit", callback_data="reset_limit")],
        [InlineKeyboardButton("📢 Channel Status", callback_data="channel_status")]
    ]
    return text, InlineKeyboardMarkup(keyboard)

# ==========================================
# HANDLERS
# ==========================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update):
        await update.message.reply_text("⛔ Access Denied")
        return

    text, keyboard = await get_start_content(context)
    await update.message.reply_text(text, parse_mode='HTML', reply_markup=keyboard)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global CHANNEL_ID 
    
    if not is_owner(update):
        await update.message.reply_text("⛔ Access Denied")
        return

    # 1. Check if waiting for channel ID (Dynamic Channel Setup)
    if context.user_data.get('awaiting_channel'):
        if not update.message.text:
            context.user_data['awaiting_channel'] = False
            await update.message.reply_text("❌ Cancelled. Please send a text message with the Channel ID or Username.")
            return
            
        context.user_data['awaiting_channel'] = False
        channel_input = update.message.text.strip()
        
        status_msg = await update.message.reply_text("🔄 Verifying channel...")
        
        try:
            chat = await context.bot.get_chat(channel_input)
            
            # Check bot permissions
            bot_member = await context.bot.get_chat_member(chat.id, context.bot.id)
            can_post = bot_member.can_post_messages if bot_member.status in ['administrator', 'creator'] else False
            can_delete = bot_member.can_delete_messages if bot_member.status in ['administrator', 'creator'] else False
            
            if not (can_post and can_delete):
                await status_msg.edit_text(
                    "❌ <b>Permission Error</b>\n\n"
                    "I can see the channel, but I lack required permissions.\n"
                    "Please promote me to Admin with:\n"
                    "✅ Post Messages\n"
                    "✅ Delete Messages"
                )
                return

            # Save to DB and global variable
            CHANNEL_ID = chat.id
            await set_setting("CHANNEL_ID", str(chat.id))
            
            await status_msg.edit_text(
                f"✅ <b>Channel Set Successfully!</b>\n\n"
                f"<b>Title:</b> {chat.title}\n"
                f"<b>ID:</b> <code>{chat.id}</code>\n\n"
                "You can now start posting!"
            )
            
        except TelegramError as e:
            await status_msg.edit_text(
                f"❌ <b>Invalid Channel</b>\n\n"
                "Could not find the channel or I am not added to it.\n"
                f"<i>Error: {str(e)}</i>\n\n"
                "Make sure to:\n"
                "1. Add me to the channel as Admin.\n"
                "2. Send the correct Username (e.g., @mychannel) or ID."
            )
        return

    # 2. Normal post handling
    if not CHANNEL_ID:
        await update.message.reply_text("⚠️ <b>No Channel Configured</b>\n\nPlease set a channel in ⚙️ Settings first.", parse_mode='HTML')
        return

    today = datetime.utcnow().strftime("%Y-%m-%d")
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT count FROM usage WHERE date = ?", (today,)) as cursor:
            row = await cursor.fetchone()
            current_count = row[0] if row else 0

        if current_count >= 2:
            await update.message.reply_text("⛔ Daily limit reached (2/2). Try again tomorrow.")
            return

    # Block photos — delete the message, don't post
    if update.message.photo:
        try:
            await update.message.delete()
        except TelegramError:
            pass
        await update.message.reply_text("🚫 <b>Photos not allowed.</b>\n\nSend text, video, or document instead.", parse_mode='HTML')
        return

    try:
        result = await update.effective_message.copy_to(chat_id=CHANNEL_ID)
        channel_msg_id = result.message_id
    except TelegramError as e:
        logger.error(f"Failed to copy message: {e}")
        await update.message.reply_text(
            "❌ Failed to post to channel. Ensure I am an admin with <b>Post Messages</b> permission.\n"
            f"<i>Error: {str(e)}</i>", 
            parse_mode='HTML'
        )
        return

    now = datetime.utcnow().isoformat()
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("INSERT INTO posts (channel_message_id, created_at) VALUES (?, ?)", (channel_msg_id, now))
        await db.execute("INSERT OR REPLACE INTO usage (date, count) VALUES (?, ?)", (today, current_count + 1))
        await db.commit()

    await update.message.reply_text(f"✅ Post published successfully!\n📊 Usage: {current_count + 1}/2")

    if RUNTIME_DELETE_SECONDS > 0:
        asyncio.create_task(delete_after_delay(context.bot, channel_msg_id, RUNTIME_DELETE_SECONDS))
    else:
        await delete_old_posts(context.bot)

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global RUNTIME_DELETE_SECONDS 
    
    query = update.callback_query
    await query.answer()

    if not is_owner(update):
        await query.edit_message_text("⛔ Access Denied")
        return

    data = query.data

    if data == "back_to_start":
        text, keyboard = await get_start_content(context)
        await query.edit_message_text(text, parse_mode='HTML', reply_markup=keyboard)
        
    elif data == "limit":
        today = datetime.utcnow().strftime("%Y-%m-%d")
        async with aiosqlite.connect(DB_NAME) as db:
            async with db.execute("SELECT count FROM usage WHERE date = ?", (today,)) as cursor:
                row = await cursor.fetchone()
                count = row[0] if row else 0
                
        text = (
            "📊 <b>TODAY'S LIMIT</b>\n\n"
            f"📅 <b>Date:</b> {today}\n"
            f"📤 <b>Posts Used:</b> {count}\n"
            f"📥 <b>Posts Remaining:</b> {2 - count}\n"
            f"🎯 <b>Daily Limit:</b> 2"
        )
        keyboard = [[InlineKeyboardButton("🔙 Back", callback_data="back_to_start")]]
        await query.edit_message_text(text, parse_mode='HTML', reply_markup=InlineKeyboardMarkup(keyboard))

    elif data == "reset_limit":
        today = datetime.utcnow().strftime("%Y-%m-%d")
        async with aiosqlite.connect(DB_NAME) as db:
            await db.execute("INSERT OR REPLACE INTO usage (date, count) VALUES (?, 0)", (today,))
            await db.commit()
        await query.edit_message_text("✅ Daily limit has been reset to 0/2.")

    elif data == "settings":
        channel_info = "Not Configured"
        if CHANNEL_ID:
            try:
                chat = await context.bot.get_chat(CHANNEL_ID)
                channel_info = f"Title: {chat.title}\nID: <code>{chat.id}</code>"
            except TelegramError:
                channel_info = "Disconnected / Invalid"

        text = (
            "⚙️ <b>SETTINGS</b>\n\n"
            f"📢 <b>Channel:</b>\n{channel_info}\n\n"
            f"🗑️ <b>Auto-Delete Duration:</b> {RUNTIME_DELETE_SECONDS} seconds\n"
            "<i>(0 means keep only the latest post)</i>\n\n"
            "Manage your configuration:"
        )
        
        keyboard = [
            [InlineKeyboardButton("📢 Set / Change Channel", callback_data="set_channel")],
            [InlineKeyboardButton("0 (Latest Only)", callback_data="set_delete_0")],
            [InlineKeyboardButton("60 seconds", callback_data="set_delete_60")],
            [InlineKeyboardButton("300 seconds (5m)", callback_data="set_delete_300")],
            [InlineKeyboardButton("3600 seconds (1h)", callback_data="set_delete_3600")],
            [InlineKeyboardButton("🔙 Back", callback_data="back_to_start")]
        ]
        await query.edit_message_text(text, parse_mode='HTML', reply_markup=InlineKeyboardMarkup(keyboard))

    elif data == "set_channel":
        context.user_data['awaiting_channel'] = True
        text = (
            "📢 <b>SET CHANNEL</b>\n\n"
            "Send the Channel Username (e.g., <code>@mychannel</code>) or Channel ID (e.g., <code>-100123456789</code>).\n\n"
            "<i>Note: Ensure the bot is added as an Admin in the channel before sending.</i>"
        )
        keyboard = [[InlineKeyboardButton("❌ Cancel", callback_data="cancel_set_channel")]]
        await query.edit_message_text(text, parse_mode='HTML', reply_markup=InlineKeyboardMarkup(keyboard))

    elif data == "cancel_set_channel":
        context.user_data['awaiting_channel'] = False
        text, keyboard = await get_start_content(context)
        await query.edit_message_text(text, parse_mode='HTML', reply_markup=keyboard)

    elif data.startswith("set_delete_"):
        seconds = int(data.split("_")[2])
        RUNTIME_DELETE_SECONDS = seconds
        await set_setting("DELETE_AFTER_SECONDS", seconds)
        await query.edit_message_text(f"✅ Auto-delete duration set to {seconds} seconds.")

    elif data == "channel_status":
        if not CHANNEL_ID:
            text = "⚠️ <b>CHANNEL STATUS</b>\n\nNo channel is configured yet.\nPlease set a channel in ⚙️ Settings."
        else:
            try:
                chat = await context.bot.get_chat(CHANNEL_ID)
                bot_member = await context.bot.get_chat_member(CHANNEL_ID, context.bot.id)
                status = bot_member.status
                
                can_post = bot_member.can_post_messages if status in ['administrator', 'creator'] else False
                can_delete = bot_member.can_delete_messages if status in ['administrator', 'creator'] else False
                
                perms = []
                perms.append("✅ Post Messages" if can_post else "❌ Post Messages")
                perms.append("✅ Delete Messages" if can_delete else "❌ Delete Messages")
                
                text = (
                    "📢 <b>CHANNEL STATUS</b>\n\n"
                    f"<b>Title:</b> {chat.title}\n"
                    f"<b>ID:</b> <code>{chat.id}</code>\n"
                    f"<b>Bot Status:</b> {status.capitalize()}\n\n"
                    f"<b>Permissions:</b>\n" + "\n".join(perms)
                )
            except TelegramError as e:
                text = (
                    "❌ <b>CHANNEL STATUS</b>\n\n"
                    "Could not connect to channel.\n"
                    f"<i>Error: {str(e)}</i>\n\n"
                    "Ensure the bot is added as an admin."
                )
                
        keyboard = [[InlineKeyboardButton("🔙 Back", callback_data="back_to_start")]]
        await query.edit_message_text(text, parse_mode='HTML', reply_markup=InlineKeyboardMarkup(keyboard))

# Command shortcuts
async def limit_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update): return await update.message.reply_text("⛔ Access Denied")
    today = datetime.utcnow().strftime("%Y-%m-%d")
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT count FROM usage WHERE date = ?", (today,)) as cursor:
            count = (await cursor.fetchone())[0] or 0
    await update.message.reply_text(f"📊 <b>Today's Limit:</b> {count}/2", parse_mode='HTML')

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error("Exception while handling an update:", exc_info=context.error)

# ==========================================
# MAIN EXECUTION
# ==========================================

async def post_init(application: Application):
    global CHANNEL_ID, RUNTIME_DELETE_SECONDS
    await init_db()
    
    # Load Channel ID from DB
    db_channel = await get_setting("CHANNEL_ID", None)
    if db_channel:
        CHANNEL_ID = db_channel
    else:
        CHANNEL_ID = None

    RUNTIME_DELETE_SECONDS = int(await get_setting("DELETE_AFTER_SECONDS", DELETE_AFTER_SECONDS))
    await set_setting("DELETE_AFTER_SECONDS", RUNTIME_DELETE_SECONDS)

    # Startup cleanup for persistent auto-deletion
    if CHANNEL_ID:
        if RUNTIME_DELETE_SECONDS > 0:
            async with aiosqlite.connect(DB_NAME) as db:
                async with db.execute("SELECT channel_message_id, created_at FROM posts") as cursor:
                    posts = await cursor.fetchall()
            
            now = datetime.utcnow()
            for msg_id, created_at_str in posts:
                created_at = datetime.fromisoformat(created_at_str)
                delete_time = created_at + timedelta(seconds=RUNTIME_DELETE_SECONDS)
                if delete_time <= now:
                    try:
                        await application.bot.delete_message(chat_id=CHANNEL_ID, message_id=msg_id)
                    except TelegramError as e:
                        logger.warning(f"Startup cleanup: failed to delete {msg_id}: {e}")
                    async with aiosqlite.connect(DB_NAME) as db:
                        await db.execute("DELETE FROM posts WHERE channel_message_id = ?", (msg_id,))
                        await db.commit()
                else:
                    delay = (delete_time - now).total_seconds()
                    asyncio.create_task(delete_after_delay(application.bot, msg_id, delay))
        else:
            await delete_old_posts(application.bot)

def main():
    application = Application.builder().token(BOT_TOKEN).post_init(post_init).build()
    
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("limit", limit_cmd))
    
    application.add_handler(CallbackQueryHandler(button_handler))
    
    # Handles both normal posts AND dynamic channel input
    post_filter = (filters.TEXT | filters.PHOTO | filters.VIDEO | filters.DOCUMENT | 
                   filters.AUDIO | filters.ANIMATION | filters.Sticker) & ~filters.COMMAND
    application.add_handler(MessageHandler(post_filter, handle_message))
    
    application.add_error_handler(error_handler)
    
    logger.info("Bot is starting...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()