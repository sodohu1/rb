import json
import os
from datetime import datetime

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

BOT_TOKEN = "8976765441:AAEyxw8_BAJLByeqIULouGalOC5Pf5022jM"  # 👈 apna naya (rotated) token yahan daalo
ADMIN_ID = 8609127164  # APNA TELEGRAM USER ID

BRAND = "🛟 <b>SODO Support</b>"
DIVIDER = "▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬"
USERS_FILE = "known_users.json"


def load_known_users() -> set:
    if os.path.exists(USERS_FILE):
        try:
            with open(USERS_FILE, "r") as f:
                return set(json.load(f))
        except (json.JSONDecodeError, IOError):
            return set()
    return set()


def save_known_users(users: set):
    with open(USERS_FILE, "w") as f:
        json.dump(list(users), f)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Regular user /start."""
    user = update.effective_user

    await update.message.reply_text(
        f"{BRAND}\n\n"
        f"👋 Hi <b>{user.first_name}</b>!\n\n"
        "Apna sawal ya message yahan likh kar bhej do — "
        "humari team jald se jald reply karegi. 📝\n\n"
        f"{DIVIDER}\n"
        "💬 Bas type karo aur send karo!",
        parse_mode="HTML",
    )


async def user_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Relay a normal user's message to the admin, then confirm to the user."""
    message = update.message
    user = update.effective_user
    chat_id = update.effective_chat.id

    if user.id == ADMIN_ID:
        return

    # User ko "known_users" list mein add karo (broadcast ke liye)
    known_users = context.application.bot_data["known_users"]
    if chat_id not in known_users:
        known_users.add(chat_id)
        save_known_users(known_users)

    username = f"@{user.username}" if user.username else "No Username"
    timestamp = datetime.now().strftime("%d %b, %I:%M %p")

    await context.bot.send_chat_action(chat_id=ADMIN_ID, action="typing")

    info = await context.bot.send_message(
        chat_id=ADMIN_ID,
        text=(
            "📩 <b>NEW MESSAGE</b>\n"
            f"{DIVIDER}\n"
            f"👤 <b>Name:</b> {user.full_name}\n"
            f"🆔 <b>User ID:</b> <code>{user.id}</code>\n"
            f"🔗 <b>Username:</b> {username}\n"
            f"🕐 <b>Time:</b> {timestamp}\n"
            f"{DIVIDER}\n"
            "💬 Message niche hai ⬇️"
        ),
        parse_mode="HTML",
    )

    copied = await context.bot.copy_message(
        chat_id=ADMIN_ID,
        from_chat_id=chat_id,
        message_id=message.message_id,
    )

    context.application.bot_data[copied.message_id] = chat_id
    context.application.bot_data[info.message_id] = chat_id


async def admin_reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin replies to a forwarded message; bot relays it to the right user."""
    message = update.message

    if update.effective_user.id != ADMIN_ID:
        return

    if not message.reply_to_message:
        return

    reply_to_id = message.reply_to_message.message_id
    target_user_id = context.application.bot_data.get(reply_to_id)

    if not target_user_id:
        await message.reply_text(
            "❌ <b>User ke message par reply karo.</b>\n"
            "Bot ko seedha message bhejne se relay nahi hoga.",
            parse_mode="HTML",
        )
        return

    try:
        await context.bot.send_chat_action(chat_id=target_user_id, action="typing")

        await context.bot.copy_message(
            chat_id=target_user_id,
            from_chat_id=ADMIN_ID,
            message_id=message.message_id,
        )

        await message.reply_text("✅ Reply user ko send ho gaya. 🚀")

    except Exception as e:
        await message.reply_text(
            f"❌ <b>User ko reply nahi bhej saka:</b>\n<code>{e}</code>",
            parse_mode="HTML",
        )


async def broadcast_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin ke liye /broadcast — agla message sabhi users ko chala jayega."""
    if update.effective_user.id != ADMIN_ID:
        return

    context.application.bot_data["awaiting_broadcast"] = True
    count = len(context.application.bot_data["known_users"])

    await update.message.reply_text(
        "📢 <b>Broadcast Mode ON</b>\n"
        f"{DIVIDER}\n"
        f"Ab jo bhi bhejoge, wo <b>{count} users</b> ko chala jayega.\n\n"
        "Cancel karne ke liye /cancel bhejo.",
        parse_mode="HTML",
    )


async def broadcast_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin ke liye /cancel — broadcast mode band karo."""
    if update.effective_user.id != ADMIN_ID:
        return

    context.application.bot_data["awaiting_broadcast"] = False
    await update.message.reply_text("❌ Broadcast cancel ho gaya.")


async def admin_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin ka plain (non-reply) message — ya to broadcast content, ya hint."""
    message = update.message

    if update.effective_user.id != ADMIN_ID:
        return

    if context.application.bot_data.get("awaiting_broadcast"):
        context.application.bot_data["awaiting_broadcast"] = False
        known_users = context.application.bot_data["known_users"]

        sent, failed = 0, 0
        for uid in known_users:
            try:
                await context.bot.copy_message(
                    chat_id=uid,
                    from_chat_id=ADMIN_ID,
                    message_id=message.message_id,
                )
                sent += 1
            except Exception:
                failed += 1

        await message.reply_text(
            "📢 <b>Broadcast Bhej Diya!</b>\n"
            f"{DIVIDER}\n"
            f"✅ Sent: {sent}\n"
            f"❌ Failed: {failed}",
            parse_mode="HTML",
        )
        return

    await message.reply_text(
        "ℹ️ Kisi <b>user ke message</b> par reply karo usko respond karne ke liye, "
        "ya /broadcast se sabko ek saath message bhejo.",
        parse_mode="HTML",
    )


async def admin_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin sees a dedicated panel instead of the regular welcome message."""
    await update.message.reply_text(
        "👑 <b>SODO ADMIN PANEL</b>\n"
        f"{DIVIDER}\n\n"
        "📩 Naya message aayega → notification milegi\n"
        "↩️ Us message par <b>Reply</b> karo → seedha user tak chala jayega\n"
        "📢 <b>/broadcast</b> → sabhi users ko ek saath message bhejo\n\n"
        "Bas itna hi — simple aur fast. ⚡",
        parse_mode="HTML",
    )


def main():
    print("🤖 SODO Support Bot is running...")

    app = Application.builder().token(BOT_TOKEN).build()
    app.bot_data["known_users"] = load_known_users()
    app.bot_data["awaiting_broadcast"] = False

    # /broadcast aur /cancel — generic command handler se PEHLE add karna zaroori hai
    app.add_handler(CommandHandler("broadcast", broadcast_start, filters=filters.User(ADMIN_ID)))
    app.add_handler(CommandHandler("cancel", broadcast_cancel, filters=filters.User(ADMIN_ID)))

    # Start - regular users
    app.add_handler(
        MessageHandler(
            filters.COMMAND & filters.ChatType.PRIVATE & ~filters.User(ADMIN_ID),
            start
        )
    )

    # Start (aur baaki commands) - admin panel
    app.add_handler(
        MessageHandler(
            filters.COMMAND & filters.ChatType.PRIVATE & filters.User(ADMIN_ID),
            admin_start
        )
    )

    # Admin kisi user ke message par reply kare
    app.add_handler(
        MessageHandler(
            filters.Chat(ADMIN_ID) & ~filters.COMMAND & filters.REPLY,
            admin_reply
        )
    )

    # Admin ka plain message - broadcast content ya hint
    app.add_handler(
        MessageHandler(
            filters.Chat(ADMIN_ID) & ~filters.COMMAND & ~filters.REPLY,
            admin_message
        )
    )

    # Normal users
    app.add_handler(
        MessageHandler(
            filters.ChatType.PRIVATE
            & ~filters.COMMAND
            & ~filters.User(ADMIN_ID),
            user_message
        )
    )

    app.run_polling(
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=False,
    )


if __name__ == "__main__":
    main()
