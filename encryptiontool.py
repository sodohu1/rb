import os
import re
import zlib
import base64
import marshal
import random
import string
from pathlib import Path

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

BOT_TOKEN = "8621707407:AAG0RQlyex8xS3XNMA8YpuUbKcEGFdj27Fo"

OUTPUT_DIR = Path("output")
OUTPUT_DIR.mkdir(exist_ok=True)


# =========================================================
# RANDOM UNICODE VARIABLE GENERATOR
# =========================================================

CHARS = (
    "嬜槌풀충仪웘睷闢涾污翊틵혽얭쉇耜蜭孎혬"
    "蟪儇캚딉久盒鯵徛溧鶞貽敃殺礀靉誑껒耭쀻"
    "镘캫晀軱傝邾嘋욶잶霃섁湬랿뎥뗔邌명惻"
    "軠鍦浲퓆작鸜倇裧箇魏큪瑈佴岻顶瑱轛"
)

def unicode_name(length=None):
    if length is None:
        length = random.randint(10, 30)

    return "".join(random.choice(CHARS) for _ in range(length))


def junk_line():
    name = unicode_name()
    value = random.randint(100, 9999)
    operation = random.choice([
        f"[{value} for _ in range({random.randint(5, 120)})]",
        f"{{{value} ^ i for i in range({random.randint(5, 120)})}}",
        f"(lambda x: x * {random.randint(10, 9000)} + {random.randint(1, 999)})(89)",
        f"[(lambda x: x ^ {random.randint(1, 255)})(i) for i in range({random.randint(5, 100)})]",
    ])
    return f"{name} = {operation}"


# =========================================================
# OBFUSCATOR
# =========================================================

def make_obfuscated(source: str, layers: int = 1, junk_amount: int = 50):
    code = compile(source, "<obfuscated>", "exec")
    payload = marshal.dumps(code)

    for _ in range(layers):
        payload = zlib.compress(payload, 9)

    encoded = base64.b85encode(payload).decode()

    var_a = unicode_name()
    var_b = unicode_name()
    var_c = unicode_name()
    var_d = unicode_name()

    junk_before = "\n".join(junk_line() for _ in range(junk_amount))
    junk_after = "\n".join(junk_line() for _ in range(junk_amount))

    decode_layers = ""

    for _ in range(layers):
        decode_layers += f"{var_b}=__import__('zlib').decompress({var_b})\n"

    output = f'''#!/usr/bin/env python3
# -*- coding: utf-8 -*-

__OWN__ = "SODO",
__OBF__ = "SODO-PY",
__VER__ = "1.0",

{junk_before}

{var_a} = "{encoded}"
{var_b} = __import__("base64").b85decode({var_a}.encode())
{decode_layers}
{var_c} = __import__("marshal").loads({var_b})
{junk_after}
exec({var_c})
'''

    return output


# =========================================================
# USER SETTINGS
# =========================================================

def get_settings(context):
    if "layers" not in context.user_data:
        context.user_data["layers"] = 1

    if "junk" not in context.user_data:
        context.user_data["junk"] = 50

    return (
        context.user_data["layers"],
        context.user_data["junk"],
    )


def keyboard(context):
    layers, junk = get_settings(context)

    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                f"🔐 Layers: {layers}",
                callback_data="layers"
            ),
            InlineKeyboardButton(
                f"🧩 Junk: {junk}",
                callback_data="junk"
            ),
        ],
        [
            InlineKeyboardButton(
                "🚀 Reset Settings",
                callback_data="reset"
            )
        ],
    ])


# =========================================================
# COMMANDS
# =========================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "🔐 PYTHON OBFUSCATOR BOT\n\n"
        "📁 Send me a .py file\n"
        "⚙️ Choose obfuscation settings\n"
        "🔒 Get obfuscated Python file\n\n"
        "Current options are shown below."
    )

    await update.message.reply_text(
        text,
        reply_markup=keyboard(context)
    )


async def settings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "⚙️ Current obfuscation settings:",
        reply_markup=keyboard(context)
    )


# =========================================================
# BUTTONS
# =========================================================

async def buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    action = query.data

    layers, junk = get_settings(context)

    if action == "layers":
        layers += 1

        if layers > 5:
            layers = 1

        context.user_data["layers"] = layers

    elif action == "junk":
        junk += 50

        if junk > 300:
            junk = 50

        context.user_data["junk"] = junk

    elif action == "reset":
        context.user_data["layers"] = 1
        context.user_data["junk"] = 50

    await query.edit_message_reply_markup(
        reply_markup=keyboard(context)
    )


# =========================================================
# FILE HANDLER
# =========================================================

async def handle_file(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    document = update.message.document

    if not document:
        return

    filename = document.file_name or "input.py"

    if not filename.lower().endswith(".py"):
        await update.message.reply_text(
            "❌ Only .py files are supported."
        )
        return

    status = await update.message.reply_text(
        "⏳ Downloading and obfuscating..."
    )

    try:
        file = await context.bot.get_file(document.file_id)

        user_id = update.effective_user.id

        input_path = OUTPUT_DIR / f"{user_id}_input.py"

        await file.download_to_drive(
            custom_path=str(input_path)
        )

        source = input_path.read_text(
            encoding="utf-8",
            errors="ignore"
        )

        layers, junk = get_settings(context)

        obfuscated = make_obfuscated(
            source=source,
            layers=layers,
            junk_amount=junk,
        )

        clean_name = Path(filename).stem

        output_path = OUTPUT_DIR / (
            f"{clean_name}_OBFUSCATED.py"
        )

        output_path.write_text(
            obfuscated,
            encoding="utf-8"
        )

        await status.edit_text(
            "✅ Obfuscation complete!"
        )

        with open(output_path, "rb") as result:
            await update.message.reply_document(
                document=result,
                filename=output_path.name,
                caption=(
                    "🔐 OBFUSCATED SUCCESSFULLY\n\n"
                    f"🔒 Layers: {layers}\n"
                    f"🧩 Junk Lines: {junk}"
                )
            )

        if input_path.exists():
            input_path.unlink()

        if output_path.exists():
            output_path.unlink()

    except Exception as error:
        await status.edit_text(
            f"❌ Error:\n{error}"
        )


# =========================================================
# MAIN
# =========================================================

def main():
    if BOT_TOKEN == "PUT_YOUR_BOT_TOKEN_HERE":
        print("ERROR: Add your bot token first!")
        return

    app = (
        ApplicationBuilder()
        .token(BOT_TOKEN)
        .build()
    )

    app.add_handler(
        CommandHandler("start", start)
    )

    app.add_handler(
        CommandHandler("settings", settings)
    )

    app.add_handler(
        CallbackQueryHandler(buttons)
    )

    app.add_handler(
        MessageHandler(
            filters.Document.ALL,
            handle_file
        )
    )

    print("Bot started...")
    app.run_polling(
        allowed_updates=Update.ALL_TYPES
    )


if __name__ == "__main__":
    main()