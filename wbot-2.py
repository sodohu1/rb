"""
Advanced Multi-Group Telegram Welcome Bot (All-in-One Single File)
Requirements: python-telegram-bot==20.7, Pillow, numpy, aiosqlite, python-dotenv
"""

import os
import io
import time
import logging
import sys
import asyncio
import random
from typing import Optional, List, Dict, Any, Tuple

import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageFilter
import aiosqlite

from telegram import (
    Update, 
    InlineKeyboardButton, 
    InlineKeyboardMarkup, 
    Chat, 
    ChatMemberUpdated, 
    User
)
from telegram.constants import ParseMode
from telegram.error import RetryAfter, Forbidden, BadRequest, TelegramError
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler,
    ChatMemberHandler, ContextTypes, filters
)

# ==========================================
# CONFIGURATION
# ==========================================
BOT_TOKEN: str = "8645260113:AAGObB5217U50TKX7IULY22m7l-39nFPcm8"
OWNER_ID: int = 8502412097
DATABASE_PATH: str = "bot_database.db"
LOG_LEVEL: str = "INFO"
DEFAULT_SUPPORT_URL: str = "https://t.me/telegram"
DEFAULT_COMMUNITY_URL: str = "https://t.me/telegram"

# ==========================================
# LOGGING SETUP
# ==========================================
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("bot.log", encoding="utf-8"),
    ],
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

# ==========================================
# HELPERS
# ==========================================
def is_owner(user_id: int) -> bool:
    return user_id == OWNER_ID

def extract_status_change(chat_member_update: ChatMemberUpdated) -> Tuple[Optional[str], Optional[str]]:
    old = chat_member_update.old_chat_member.status if chat_member_update.old_chat_member else None
    new = chat_member_update.new_chat_member.status if chat_member_update.new_chat_member else None
    return old, new

def user_display_name(user: User) -> str:
    return user.full_name or user.first_name or user.username or "User"

# ==========================================
# DATABASE LAYER
# ==========================================
SCHEMA = """
CREATE TABLE IF NOT EXISTS groups (
    group_id          INTEGER PRIMARY KEY,
    group_title       TEXT,
    group_username    TEXT,
    added_at          INTEGER,
    active            INTEGER DEFAULT 1,
    welcome_enabled   INTEGER DEFAULT 1,
    welcome_text      TEXT,
    random_theme      INTEGER DEFAULT 1,
    theme_name        TEXT DEFAULT 'random',
    goodbye_enabled   INTEGER DEFAULT 0,
    delete_timer      INTEGER DEFAULT 0,
    welcome_count     INTEGER DEFAULT 0,
    rules_text        TEXT
);
CREATE TABLE IF NOT EXISTS group_buttons (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    group_id        INTEGER,
    button_text     TEXT,
    button_url      TEXT,
    row_position    INTEGER DEFAULT 0,
    active          INTEGER DEFAULT 1,
    FOREIGN KEY(group_id) REFERENCES groups(group_id)
);
CREATE TABLE IF NOT EXISTS users (
    user_id       INTEGER PRIMARY KEY,
    username      TEXT,
    first_name    TEXT,
    last_seen     INTEGER
);
"""

class Database:
    def __init__(self, db_path: str = DATABASE_PATH):
        self.db_path = db_path
        self._conn: Optional[aiosqlite.Connection] = None

    async def init(self) -> None:
        self._conn = await aiosqlite.connect(self.db_path)
        self._conn.row_factory = aiosqlite.Row
        await self._conn.executescript(SCHEMA)
        await self._conn.commit()

    async def close(self) -> None:
        if self._conn:
            await self._conn.close()

    async def add_group(self, group_id: int, group_title: str, group_username: Optional[str]) -> None:
        await self._conn.execute(
            """INSERT INTO groups (group_id, group_title, group_username, added_at, active)
            VALUES (?, ?, ?, ?, 1)
            ON CONFLICT(group_id) DO UPDATE SET
                group_title=excluded.group_title, group_username=excluded.group_username, active=1""",
            (group_id, group_title, group_username, int(time.time())),
        )
        await self._conn.commit()

    async def set_group_inactive(self, group_id: int) -> None:
        await self._conn.execute("UPDATE groups SET active=0 WHERE group_id=?", (group_id,))
        await self._conn.commit()

    async def get_group(self, group_id: int) -> Optional[Dict[str, Any]]:
        async with self._conn.execute("SELECT * FROM groups WHERE group_id=?", (group_id,)) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None

    async def get_active_groups(self) -> List[Dict[str, Any]]:
        async with self._conn.execute("SELECT * FROM groups WHERE active=1 ORDER BY added_at DESC") as cur:
            rows = await cur.fetchall()
            return [dict(r) for r in rows]

    async def get_all_groups(self) -> List[Dict[str, Any]]:
        async with self._conn.execute("SELECT * FROM groups ORDER BY active DESC, added_at DESC") as cur:
            rows = await cur.fetchall()
            return [dict(r) for r in rows]

    async def count_active_groups(self) -> int:
        async with self._conn.execute("SELECT COUNT(*) FROM groups WHERE active=1") as cur:
            row = await cur.fetchone()
            return row[0] if row else 0

    async def count_all_groups(self) -> int:
        async with self._conn.execute("SELECT COUNT(*) FROM groups") as cur:
            row = await cur.fetchone()
            return row[0] if row else 0

    async def increment_welcome_count(self, group_id: int) -> None:
        await self._conn.execute("UPDATE groups SET welcome_count = welcome_count + 1 WHERE group_id=?", (group_id,))
        await self._conn.commit()

    async def total_welcomes(self) -> int:
        async with self._conn.execute("SELECT COALESCE(SUM(welcome_count),0) FROM groups") as cur:
            row = await cur.fetchone()
            return row[0] if row else 0

    async def get_group_buttons(self, group_id: int) -> List[Dict[str, Any]]:
        async with self._conn.execute(
            "SELECT * FROM group_buttons WHERE group_id=? AND active=1 ORDER BY row_position ASC", (group_id,)
        ) as cur:
            rows = await cur.fetchall()
            return [dict(r) for r in rows]

    async def add_user(self, user_id: int, username: Optional[str], first_name: Optional[str]) -> None:
        await self._conn.execute(
            """INSERT INTO users (user_id, username, first_name, last_seen)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                username=excluded.username, first_name=excluded.first_name, last_seen=excluded.last_seen""",
            (user_id, username, first_name, int(time.time())),
        )
        await self._conn.commit()

    async def count_users(self) -> int:
        async with self._conn.execute("SELECT COUNT(*) FROM users") as cur:
            row = await cur.fetchone()
            return row[0] if row else 0

    async def get_recent_users(self, limit: int = 10) -> List[Dict[str, Any]]:
        async with self._conn.execute("SELECT * FROM users ORDER BY last_seen DESC LIMIT ?", (limit,)) as cur:
            rows = await cur.fetchall()
            return [dict(r) for r in rows]

    async def cleanup_inactive(self) -> int:
        cur = await self._conn.execute("DELETE FROM groups WHERE active=0")
        await self._conn.commit()
        return cur.rowcount

db = Database()

# ==========================================
# WELCOME CARD GENERATOR
# ==========================================
THEMES = {
    "blue_cyan": {"bg_top": (15, 23, 42), "bg_bottom": (6, 78, 109), "accent": (56, 189, 248), "glow": (34, 211, 238), "border": (125, 211, 252), "panel": (8, 15, 30)},
    "purple_pink": {"bg_top": (30, 12, 50), "bg_bottom": (131, 24, 67), "accent": (236, 72, 153), "glow": (217, 70, 239), "border": (244, 114, 182), "panel": (20, 8, 35)},
    "red_orange": {"bg_top": (40, 10, 10), "bg_bottom": (194, 65, 12), "accent": (251, 146, 60), "glow": (248, 113, 113), "border": (252, 165, 165), "panel": (25, 8, 8)},
    "green_emerald": {"bg_top": (6, 30, 22), "bg_bottom": (4, 120, 87), "accent": (52, 211, 153), "glow": (16, 185, 129), "border": (110, 231, 183), "panel": (4, 20, 14)},
    "gold_black": {"bg_top": (10, 10, 10), "bg_bottom": (76, 60, 8), "accent": (250, 204, 21), "glow": (234, 179, 8), "border": (253, 224, 71), "panel": (5, 5, 5)},
    "dark_neon": {"bg_top": (5, 5, 15), "bg_bottom": (40, 5, 70), "accent": (168, 85, 247), "glow": (217, 70, 239), "border": (232, 121, 249), "panel": (4, 4, 12)},
}

def _load_font(size: int, bold: bool = True) -> ImageFont.FreeTypeFont:
    paths = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
        "C:\\Windows\\Fonts\\arialbd.ttf",
    ] if bold else [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        "C:\\Windows\\Fonts\\arial.ttf",
    ]
    for p in paths:
        try: return ImageFont.truetype(p, size)
        except: continue
    return ImageFont.load_default()

def _make_gradient(width: int, height: int, c1: tuple, c2: tuple) -> Image.Image:
    c1, c2 = np.array(c1, dtype=np.float32), np.array(c2, dtype=np.float32)
    x, y = np.linspace(0, 1, width, dtype=np.float32), np.linspace(0, 1, height, dtype=np.float32)
    xv, yv = np.meshgrid(x, y)
    t = np.clip((xv + yv) / 2.0, 0.0, 1.0)
    arr = (c1[None, None, :] + (c2[None, None, :] - c1[None, None, :]) * t[:, :, None]).astype(np.uint8)
    return Image.fromarray(arr, "RGB").convert("RGBA")

def _circular_image(img: Image.Image, size: int) -> Image.Image:
    img = img.convert("RGBA").resize((size, size), Image.LANCZOS)
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, size-1, size-1), fill=255)
    out = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    out.paste(img, (0, 0), mask)
    return out

def _placeholder_avatar(name: str, size: int, theme: dict) -> Image.Image:
    img = Image.new("RGBA", (size, size), theme["accent"] + (255,))
    draw = ImageDraw.Draw(img)
    initial = (name or "?").strip()[:1].upper() or "?"
    font = _load_font(int(size * 0.55))
    bbox = draw.textbbox((0, 0), initial, font=font)
    tw, th = bbox[2]-bbox[0], bbox[3]-bbox[1]
    draw.text(((size-tw)/2 - bbox[0], (size-th)/2 - bbox[1] - 5), initial, fill=(255, 255, 255), font=font)
    return img

def generate_welcome_card(profile_photo_bytes: Optional[bytes], group_name: str, user_name: str, user_id: int, username: Optional[str], member_count: int, theme_name: str = "random") -> Tuple[io.BytesIO, str]:
    actual_theme_name = random.choice(list(THEMES.keys())) if (not theme_name or theme_name == "random") else theme_name
    theme = THEMES[actual_theme_name]
    W, H = 1000, 600
    base = _make_gradient(W, H, theme["bg_top"], theme["bg_bottom"])

    glow_layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow_layer)
    def glow_blob(cx, cy, max_r, color):
        for r in range(max_r, 0, -8):
            gd.ellipse([cx-r, cy-r, cx+r, cy+r], fill=color+(int(80*(1-r/max_r)),))
    glow_blob(W-100, 60, 260, theme["glow"])
    glow_blob(60, H-60, 220, theme["accent"])
    glow_blob(W//2, H+80, 200, theme["glow"])
    base = Image.alpha_composite(base, glow_layer.filter(ImageFilter.GaussianBlur(radius=30)))
    draw = ImageDraw.Draw(base)

    f_label, f_group = _load_font(26), _load_font(42)
    f_name, f_info_label, f_info_value, f_members = _load_font(52), _load_font(20), _load_font(26), _load_font(24)

    def draw_centered(text, y, font, fill):
        bbox = draw.textbbox((0, 0), text, font=font)
        draw.text(((W-(bbox[2]-bbox[0]))/2, y), text, fill=fill, font=font)

    draw_centered("WELCOME TO", 35, f_label, theme["border"])
    gname = group_name if len(group_name) <= 32 else group_name[:29]+"..."
    draw_centered(gname, 70, f_group, (255, 255, 255))

    PHOTO = 200
    px, py = (W-PHOTO)//2, 160
    if profile_photo_bytes:
        try: pimg = _circular_image(Image.open(io.BytesIO(profile_photo_bytes)), PHOTO)
        except: pimg = _placeholder_avatar(user_name, PHOTO, theme)
    else: pimg = _placeholder_avatar(user_name, PHOTO, theme)

    halo = Image.new("RGBA", (PHOTO+70, PHOTO+70), (0, 0, 0, 0))
    ImageDraw.Draw(halo).ellipse((0, 0, PHOTO+69, PHOTO+69), fill=theme["glow"]+(110,))
    base.paste(halo.filter(ImageFilter.GaussianBlur(radius=18)), (px-35, py-35), halo)

    ring = Image.new("RGBA", (PHOTO+16, PHOTO+16), (0, 0, 0, 0))
    rd = ImageDraw.Draw(ring)
    rd.ellipse((0, 0, PHOTO+15, PHOTO+15), fill=theme["border"])
    rd.ellipse((4, 4, PHOTO+11, PHOTO+11), fill=theme["panel"]+(255,))
    base.paste(ring, (px-8, py-8), ring)
    base.paste(pimg, (px, py), pimg)

    uname = user_name if len(user_name) <= 26 else user_name[:23]+"..."
    draw_centered(uname, py+PHOTO+18, f_name, (255, 255, 255))

    panel_x, panel_y, panel_w, panel_h = 40, H-110, W-80, 90
    panel = Image.new("RGBA", (panel_w, panel_h), (0, 0, 0, 0))
    pd = ImageDraw.Draw(panel)
    pd.rounded_rectangle((0, 0, panel_w-1, panel_h-1), radius=18, fill=theme["panel"]+(220,))
    base.paste(panel, (panel_x, panel_y), panel)
    info = ImageDraw.Draw(base)

    info.text((panel_x+25, panel_y+18), "ID", fill=theme["border"], font=f_info_label)
    info.text((panel_x+25, panel_y+42), f"#{user_id}", fill=(255, 255, 255), font=f_info_value)

    uname_str = f"@{username}" if username else "None"
    if len(uname_str) > 22: uname_str = uname_str[:19]+"..."
    info.text((panel_x+panel_w//2-30, panel_y+18), "USERNAME", fill=theme["border"], font=f_info_label)
    info.text((panel_x+panel_w//2-30, panel_y+42), uname_str, fill=(255, 255, 255), font=f_info_value)

    members_text = f"👥  {member_count}"
    bbox = info.textbbox((0, 0), members_text, font=f_members)
    info.text((panel_x+panel_w-(bbox[2]-bbox[0])-25, panel_y+18), "MEMBERS", fill=theme["border"], font=f_info_label)
    info.text((panel_x+panel_w-(bbox[2]-bbox[0])-25, panel_y+42), members_text, fill=theme["accent"], font=f_members)

    output = base.convert("RGB")
    bytes_io = io.BytesIO()
    output.save(bytes_io, format="JPEG", quality=95)
    bytes_io.seek(0)
    return bytes_io, actual_theme_name

# ==========================================
# KEYBOARDS
# ==========================================
def owner_panel_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📢  BROADCAST", callback_data="owner_broadcast")],
        [InlineKeyboardButton("🏘️  ALL GROUPS", callback_data="owner_groups"), InlineKeyboardButton("👥  TOTAL USERS", callback_data="owner_users")],
        [InlineKeyboardButton("📊  GLOBAL STATS", callback_data="owner_stats")],
        [InlineKeyboardButton("⚙️  BOT SETTINGS", callback_data="owner_settings"), InlineKeyboardButton("🛠️  MAINTENANCE", callback_data="owner_maintenance")],
    ])

def back_owner_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("🔙  Back to Admin Panel", callback_data="owner_panel")]])

def broadcast_cancel_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("❌  Cancel", callback_data="broadcast_cancel")]])

def broadcast_preview_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🚀  SEND TO ALL GROUPS", callback_data="broadcast_send")],
        [InlineKeyboardButton("❌  Cancel", callback_data="broadcast_cancel")],
    ])

def broadcast_confirm_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅  OK, SEND NOW", callback_data="broadcast_send_now")],
        [InlineKeyboardButton("❌  CANCEL", callback_data="broadcast_cancel")],
    ])

def welcome_buttons(user_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🌟  VIEW NEW MEMBER  🌟", url=f"tg://user?id={user_id}")],
        [InlineKeyboardButton("💬  SUPPORT", url=DEFAULT_SUPPORT_URL)],
        [InlineKeyboardButton("🌐  COMMUNITY", url=DEFAULT_COMMUNITY_URL)],
    ])

# ==========================================
# HANDLERS: START & BASIC
# ==========================================
async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    chat = update.effective_chat
    if user: await db.add_user(user.id, user.username, user.first_name)

    if chat.type == "private":
        if is_owner(user.id):
            text = "👑 <b>OWNER CONTROL PANEL</b>\n\nWelcome back, Owner. Select an action below:"
            await update.message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=owner_panel_kb())
        else:
            me = await context.bot.get_me()
            add_link = f"https://t.me/{me.username}?startgroup=true"
            text = f"👋 <b>Hello {user.first_name}!</b>\nI am a Premium Multi-Group Welcome Bot.\n\n➕ <b>Add me to your group</b> and make me admin to get started.\n<a href=\"{add_link}\">👉 Click here to add me</a>"
            kb = InlineKeyboardMarkup([[InlineKeyboardButton("➕  Add me to your group", url=add_link)]])
            await update.message.reply_text(text, parse_mode=ParseMode.HTML, disable_web_page_preview=True, reply_markup=kb)
    else:
        await db.add_group(chat.id, chat.title, chat.username)
        await update.message.reply_text("👋 I'm now active in this group. New members will receive a premium welcome card!", parse_mode=ParseMode.HTML)

async def help_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = "📚 <b>Commands</b>\n• /start - Start bot\n• /id - Show ID\n• /info - Group info"
    if is_owner(update.effective_user.id):
        text += "\n\n👑 <b>Owner Commands</b>\n• /admin - Admin Panel\n• /broadcast - Start Broadcast"
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)

async def id_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(f"🆔 Your ID: <code>{update.effective_user.id}</code>\n💬 Chat ID: <code>{update.effective_chat.id}</code>", parse_mode=ParseMode.HTML)

# ==========================================
# HANDLERS: GROUP EVENTS & WELCOME
# ==========================================
async def my_chat_member_update(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_member = update.my_chat_member
    chat = chat_member.chat
    old_status, new_status = extract_status_change(chat_member)

    if new_status in ["member", "administrator", "restricted"]:
        await db.add_group(chat.id, chat.title or "Unknown Group", chat.username)
        extra = "✅ I'm now an admin." if new_status == "administrator" else "⚠️ Please promote me to admin with send message permissions."
        text = f"👋 <b>HELLO!</b>\n\nThank you for adding me to:\n<b>{chat.title}</b>\n\n✨ Welcome system is now active.\n\n━━━━━━━━━━━━━━\n{extra}\n\nOnly the BOT OWNER controls the global Admin Panel."
        try: await context.bot.send_message(chat_id=chat.id, text=text, parse_mode=ParseMode.HTML)
        except: pass
    elif new_status in ["left", "kicked"]:
        await db.set_group_inactive(chat.id)

async def new_member_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat = update.effective_chat
    new_members = update.message.new_chat_members
    if not new_members: return
    
    me = await context.bot.get_me()
    if any(m.id == me.id for m in new_members): return

    group = await db.get_group(chat.id)
    if not group:
        await db.add_group(chat.id, chat.title, chat.username)
        group = await db.get_group(chat.id)
    if not group["welcome_enabled"]: return

    try: member_count = await context.bot.get_chat_member_count(chat.id)
    except: member_count = 0

    for member in new_members:
        photo_bytes = None
        try:
            photos = await context.bot.get_user_profile_photos(user_id=member.id, limit=1)
            if photos and photos.photos:
                file = await photos.photos[0][-1].get_file()
                buf = await file.download_to_memory()
                buf.seek(0)
                photo_bytes = buf.read()
        except: pass

        display_name = user_display_name(member)
        theme_name = "random" if group["random_theme"] else (group["theme_name"] or "random")

        try:
            img_io, _ = generate_welcome_card(photo_bytes, chat.title or "this group", display_name, member.id, member.username, member_count, theme_name)
            welcome_text = group["welcome_text"] or f"👋 Welcome <b>{display_name}</b> to <b>{chat.title}</b>!\nYou are our <b>{member_count}th</b> member 🎉"
            await context.bot.send_photo(chat_id=chat.id, photo=img_io, caption=welcome_text, parse_mode=ParseMode.HTML, reply_markup=welcome_buttons(member.id))
        except Exception as e:
            logger.error("Failed to gen welcome card: %s", e)
            await context.bot.send_message(chat_id=chat.id, text=f"👋 Welcome {display_name}!", parse_mode=ParseMode.HTML)
        
        await db.increment_welcome_count(chat.id)



# ==========================================
# HANDLERS: OWNER PANEL & BROADCAST
# ==========================================
BROADCAST_STATE_KEY = "broadcast_state"
BROADCAST_CONTENT_KEY = "broadcast_content"

async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_owner(update.effective_user.id):
        await update.message.reply_text("⛔ Access denied. Owner only.")
        return
    await update.message.reply_text("👑 <b>OWNER ADMIN PANEL</b>", parse_mode=ParseMode.HTML, reply_markup=owner_panel_kb())

async def show_all_groups(update: Update, context: ContextTypes.DEFAULT_TYPE, page: int = 0) -> None:
    groups = await db.get_all_groups()
    per_page, total = 10, len(groups)
    start, end = page * per_page, page * per_page + per_page
    page_groups = groups[start:end]
    
    lines = [f"🏘️ <b>ALL GROUPS</b> ({total} total)\n", "━━━━━━━━━━━━━━"]
    for i, g in enumerate(page_groups, start=start+1):
        status = "✅" if g["active"] else "🚫"
        title = g["group_title"][:32]+"..." if len(g["group_title"] or "") > 35 else g["group_title"]
        lines.append(f"{status} <b>{i}. {title}</b>\n   <code>{g['group_id']}</code>")
    
    nav_row = []
    if page > 0:
        nav_row.append(InlineKeyboardButton("⬅️ Prev", callback_data=f"owner_groups_{page-1}"))
    nav_row.append(InlineKeyboardButton(f"Page {page+1}/{max(1,(total+per_page-1)//per_page)}", callback_data="noop"))
    if end < total:
        nav_row.append(InlineKeyboardButton("Next ➡️", callback_data=f"owner_groups_{page+1}"))
    kb = InlineKeyboardMarkup([
        nav_row,
        [InlineKeyboardButton("🔙 Back", callback_data="owner_panel")]
    ])
    if update.callback_query:
        await update.callback_query.edit_message_text("\n".join(lines), parse_mode=ParseMode.HTML, reply_markup=kb)
    else:
        await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML, reply_markup=kb)

async def show_total_users(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    total = await db.count_users()
    recent = await db.get_recent_users(15)
    lines = [f"👥 <b>TOTAL USERS</b>: <b>{total}</b>\n", "━━━━━━━━━━━━━━", "<i>Recent:</i>"]
    for u in recent:
        lines.append(f"• {u['first_name']} · <code>{u['user_id']}</code>")
    await update.callback_query.edit_message_text("\n".join(lines), parse_mode=ParseMode.HTML, reply_markup=back_owner_kb())

async def show_global_stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    tg = await db.count_all_groups()
    ag = await db.count_active_groups()
    tu = await db.count_users()
    tw = await db.total_welcomes()
    text = f"📊 <b>GLOBAL STATS</b>\n\n🏘️ Total: <b>{tg}</b>\n✅ Active: <b>{ag}</b>\n👥 Users: <b>{tu}</b>\n👋 Welcomes: <b>{tw}</b>"
    await update.callback_query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=back_owner_kb())

async def show_bot_settings(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = f"⚙️ <b>BOT SETTINGS</b>\n\n👑 Owner ID: <code>{OWNER_ID}</code>\n📊 Active Groups: <b>{await db.count_active_groups()}</b>"
    await update.callback_query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=back_owner_kb())

async def show_maintenance(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🧹 Clean inactive", callback_data="maint_cleanup")],
        [InlineKeyboardButton("🔙 Back", callback_data="owner_panel")]
    ])
    await update.callback_query.edit_message_text("🛠️ <b>MAINTENANCE</b>", parse_mode=ParseMode.HTML, reply_markup=kb)

async def maintenance_cleanup(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    removed = await db.cleanup_inactive()
    await update.callback_query.edit_message_text(f"🧹 Removed <b>{removed}</b> inactive groups.", parse_mode=ParseMode.HTML, reply_markup=back_owner_kb())

async def start_broadcast_flow(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    context.user_data[BROADCAST_STATE_KEY] = "awaiting_content"
    context.user_data.pop(BROADCAST_CONTENT_KEY, None)
    text = "📢 <b>BROADCAST</b>\n\nSend me Text, Photo, Video, GIF, Document or Forwarded message."
    await update.callback_query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=broadcast_cancel_kb())

async def receive_broadcast_content(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    if not is_owner(update.effective_user.id): return False
    if context.user_data.get(BROADCAST_STATE_KEY) != "awaiting_content": return False
    
    msg = update.message
    content = {"type": None, "text": "", "entities": [], "file_id": None}
    
    if msg.text:
        content["type"] = "text"
        content["text"] = msg.text
        content["entities"] = msg.entities or []
    elif msg.photo:
        content["type"] = "photo"
        content["file_id"] = msg.photo[-1].file_id
        content["text"] = msg.caption or ""
        content["entities"] = msg.caption_entities or []
    elif msg.video:
        content["type"] = "video"
        content["file_id"] = msg.video.file_id
        content["text"] = msg.caption or ""
        content["entities"] = msg.caption_entities or []
    elif msg.animation:
        content["type"] = "animation"
        content["file_id"] = msg.animation.file_id
        content["text"] = msg.caption or ""
        content["entities"] = msg.caption_entities or []
    elif msg.document:
        content["type"] = "document"
        content["file_id"] = msg.document.file_id
        content["text"] = msg.caption or ""
        content["entities"] = msg.caption_entities or []
    else:
        await msg.reply_text("⚠️ Unsupported type.", reply_markup=broadcast_cancel_kb())
        return True

    context.user_data[BROADCAST_CONTENT_KEY] = content
    context.user_data[BROADCAST_STATE_KEY] = "previewing"
    
    # Echo Preview
    t, fid, txt, ents = content["type"], content["file_id"], content["text"], content["entities"]
    if t == "text": await msg.reply_text(txt, entities=ents)
    elif t == "photo": await msg.reply_photo(photo=fid, caption=txt, caption_entities=ents)
    elif t == "video": await msg.reply_video(video=fid, caption=txt, caption_entities=ents)
    elif t == "animation": await msg.reply_animation(animation=fid, caption=txt, caption_entities=ents)
    elif t == "document": await msg.reply_document(document=fid, caption=txt, caption_entities=ents)
        
    await msg.reply_text("📋 <b>PREVIEW</b>\nReady to send?", parse_mode=ParseMode.HTML, reply_markup=broadcast_preview_kb())
    return True

async def confirm_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    context.user_data[BROADCAST_STATE_KEY] = "confirming"
    total = await db.count_active_groups()
    text = f"⚠️ <b>CONFIRM</b>\n\nSend to <b>ALL {total} ACTIVE GROUPS</b>?"
    await update.callback_query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=broadcast_confirm_kb())

async def execute_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    content = context.user_data.get(BROADCAST_CONTENT_KEY)
    if not content:
        await update.callback_query.edit_message_text("⚠️ Error. Start over.")
        return
        
    groups = await db.get_active_groups()
    total, success, failed, inactive = len(groups), 0, 0, 0
    
    await update.callback_query.edit_message_text(f"🚀 Sending to {total} groups...", parse_mode=ParseMode.HTML)
    
    for idx, group in enumerate(groups, 1):
        cid = group["group_id"]
        try:
            t, fid, txt, ents = content["type"], content["file_id"], content["text"], content["entities"]
            if t == "text": await context.bot.send_message(chat_id=cid, text=txt, entities=ents)
            elif t == "photo": await context.bot.send_photo(chat_id=cid, photo=fid, caption=txt, caption_entities=ents)
            elif t == "video": await context.bot.send_video(chat_id=cid, video=fid, caption=txt, caption_entities=ents)
            elif t == "animation": await context.bot.send_animation(chat_id=cid, animation=fid, caption=txt, caption_entities=ents)
            elif t == "document": await context.bot.send_document(chat_id=cid, document=fid, caption=txt, caption_entities=ents)
            success += 1
        except RetryAfter as e:
            await asyncio.sleep(e.retry_after + 1)
            try:
                t, fid, txt, ents = content["type"], content["file_id"], content["text"], content["entities"]
                if t == "text": await context.bot.send_message(chat_id=cid, text=txt, entities=ents)
                elif t == "photo": await context.bot.send_photo(chat_id=cid, photo=fid, caption=txt, caption_entities=ents)
                elif t == "video": await context.bot.send_video(chat_id=cid, video=fid, caption=txt, caption_entities=ents)
                elif t == "animation": await context.bot.send_animation(chat_id=cid, animation=fid, caption=txt, caption_entities=ents)
                elif t == "document": await context.bot.send_document(chat_id=cid, document=fid, caption=txt, caption_entities=ents)
                success += 1
            except: failed += 1
        except (Forbidden, BadRequest) as e:
            if "kicked" in str(e).lower() or "not a member" in str(e).lower() or "chat not found" in str(e).lower():
                await db.set_group_inactive(cid)
                inactive += 1
            else: failed += 1
        except: failed += 1
        
        if idx % 10 == 0:
            await context.bot.send_message(chat_id=OWNER_ID, text=f"⏳ {idx}/{total} done...")
        await asyncio.sleep(0.6)
        
    res = f"📢 <b>BROADCAST COMPLETED</b>\n\n📤 Total: <b>{total}</b>\n✅ Success: <b>{success}</b>\n❌ Failed: <b>{failed}</b>\n🚫 Inactive: <b>{inactive}</b>"
    await context.bot.send_message(chat_id=OWNER_ID, text=res, parse_mode=ParseMode.HTML, reply_markup=owner_panel_kb())
    context.user_data.pop(BROADCAST_STATE_KEY, None)
    context.user_data.pop(BROADCAST_CONTENT_KEY, None)

async def cancel_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    context.user_data.pop(BROADCAST_STATE_KEY, None)
    context.user_data.pop(BROADCAST_CONTENT_KEY, None)
    await update.callback_query.edit_message_text("❌ Cancelled.", parse_mode=ParseMode.HTML, reply_markup=owner_panel_kb())

# ==========================================
# CALLBACK ROUTER
# ==========================================
async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    data = query.data or ""
    uid = query.from_user.id

    if data.startswith(("owner_", "broadcast_", "maint_")) and not is_owner(uid):
        await query.answer("⛔ Access denied. Owner only.", show_alert=True)
        return

    if data == "owner_panel":
        await query.edit_message_text("👑 <b>OWNER ADMIN PANEL</b>", parse_mode=ParseMode.HTML, reply_markup=owner_panel_kb())
    elif data == "owner_groups":
        await show_all_groups(update, context, 0)
    elif data.startswith("owner_groups_"):
        page = int(data.split("_")[-1]) if data.split("_")[-1].isdigit() else 0
        await show_all_groups(update, context, page)
    elif data == "owner_users":
        await show_total_users(update, context)
    elif data == "owner_stats":
        await show_global_stats(update, context)
    elif data == "owner_settings":
        await show_bot_settings(update, context)
    elif data == "owner_maintenance":
        await show_maintenance(update, context)
    elif data == "maint_cleanup":
        await maintenance_cleanup(update, context)
    elif data == "owner_broadcast":
        await start_broadcast_flow(update, context)
    elif data == "broadcast_send":
        await confirm_broadcast(update, context)
    elif data == "broadcast_send_now":
        await execute_broadcast(update, context)
    elif data == "broadcast_cancel":
        await cancel_broadcast(update, context)
    elif data == "noop":
        await query.answer()
    else:
        await query.answer()

async def private_message_router(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_chat.type != "private" or not is_owner(update.effective_user.id): return
    if context.user_data.get(BROADCAST_STATE_KEY) == "awaiting_content":
        await receive_broadcast_content(update, context)

# ==========================================
# MAIN APP
# ==========================================
async def post_init(app: Application) -> None:
    await db.init()
    me = await app.bot.get_me()
    logger.info(f"Bot @{me.username} online. Owner: {OWNER_ID}")

async def post_shutdown(app: Application) -> None:
    await db.close()

def main() -> None:
    app = Application.builder().token(BOT_TOKEN).post_init(post_init).post_shutdown(post_shutdown).build()

    app.add_handler(CommandHandler("start", start_handler))
    app.add_handler(CommandHandler("help", help_handler))
    app.add_handler(CommandHandler("id", id_handler))
    app.add_handler(CommandHandler("admin", admin_command))
    
    app.add_handler(MessageHandler(filters.ChatType.PRIVATE & ~filters.COMMAND, private_message_router), group=1)
    app.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, new_member_handler), group=2)
    app.add_handler(ChatMemberHandler(my_chat_member_update, ChatMemberHandler.MY_CHAT_MEMBER), group=3)
    app.add_handler(CallbackQueryHandler(callback_handler), group=4)

    app.run_polling(allowed_updates=["message", "callback_query", "chat_member", "my_chat_member"], drop_pending_updates=True)

if __name__ == "__main__":
    main()