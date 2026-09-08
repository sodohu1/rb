"""
Python 3.10+ | Telegram Bot | python-telegram-bot==20.x
pip install python-telegram-bot httpx
"""

import os
import logging
import httpx
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.getenv("BOT_TOKEN", "8981191823:AAHP6LThAgfhceiKbc6aF82eKfGb3BEl2ZU")
API_BASE  = "https://titan-num-info-api.onrender.com/search"


# ─── helpers ────────────────────────────────────────────────────────────────

def is_valid_mobile(num: str) -> bool:
    return num.isdigit() and 7 <= len(num) <= 15


async def fetch_info(mobile: str) -> dict | None:
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.get(API_BASE, params={"mobile": mobile})
            r.raise_for_status()
            return r.json()
    except Exception as e:
        logger.error(f"API error: {e}")
        return None


def format_result(entry: dict, idx: int, total: int) -> str:
    lines = [f"📋 *Result {idx}/{total}*\n"]

    if entry.get("name"):
        lines.append(f"👤 *Name:* `{entry['name']}`")
    if entry.get("fathersName"):
        lines.append(f"👨 *Father:* `{entry['fathersName']}`")
    if entry.get("phoneNumber"):
        lines.append(f"📞 *Phone:* `{entry['phoneNumber']}`")
    if entry.get("aadharNumber"):
        lines.append(f"🪪 *Aadhar:* `{entry['aadharNumber']}`")
    if entry.get("otherNumber"):
        lines.append(f"📱 *Alt Number:* `{entry['otherNumber']}`")

    addr_parts = filter(None, [
        entry.get("address"),
        entry.get("town"),
        entry.get("district"),
        entry.get("state"),
        entry.get("pincode"),
    ])
    addr = ", ".join(addr_parts)
    if addr:
        lines.append(f"📍 *Address:* `{addr}`")

    if entry.get("source"):
        lines.append(f"🗂 *Source:* `{entry['source'].upper()}`")

    connected = entry.get("connected_numbers", [])
    if len(connected) > 1:
        c_vals = ", ".join(f"`{c['value']}`" for c in connected)
        lines.append(f"🔗 *Connected:* {c_vals}")

    return "\n".join(lines)


# ─── handlers ───────────────────────────────────────────────────────────────

async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👾 *Titan Number Lookup Bot*\n\n"
        "बस mobile number भेजो — मैं बाकी करता हूँ।\n\n"
        "Example: `9876543210`\n\n"
        "Commands:\n"
        "/start — यह message\n"
        "/help  — usage guide",
        parse_mode="Markdown",
    )


async def help_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📖 *How to use:*\n\n"
        "1️⃣ कोई भी 10-digit mobile number भेजो\n"
        "2️⃣ Bot API से info fetch करेगा\n"
        "3️⃣ सारे results एक-एक करके आएंगे\n\n"
        "⚠️ Sirf digits, no spaces/dashes.",
        parse_mode="Markdown",
    )


async def lookup(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    raw = update.message.text.strip().replace(" ", "").replace("-", "")

    if not is_valid_mobile(raw):
        await update.message.reply_text(
            "❌ Valid mobile number bhejo bhai (7-15 digits only)."
        )
        return

    msg = await update.message.reply_text(f"🔍 Searching `{raw}`...", parse_mode="Markdown")

    data = await fetch_info(raw)

    if data is None:
        await msg.edit_text("⚠️ API se response nahi aaya. Thodi der baad try karo.")
        return

    if not data.get("success") or data.get("count", 0) == 0:
        await msg.edit_text(f"😶 `{raw}` ke liye koi result nahi mila.", parse_mode="Markdown")
        return

    results = data["results"]
    total   = len(results)

    await msg.edit_text(f"✅ *{total} result(s) mila!*\n\n`{raw}` ke liye:", parse_mode="Markdown")

    for i, entry in enumerate(results, start=1):
        text = format_result(entry, i, total)
        await update.message.reply_text(text, parse_mode="Markdown")


async def non_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Bhai, sirf number bhejo text mein 😄")


# ─── main ───────────────────────────────────────────────────────────────────

def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help",  help_cmd))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, lookup))
    app.add_handler(MessageHandler(~filters.TEXT, non_text))

    logger.info("Bot chal pada 👾")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
