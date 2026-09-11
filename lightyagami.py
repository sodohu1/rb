import asyncio
import time
import random
import re
import os
import shutil
import gc
from datetime import datetime
from collections import defaultdict
from telegram import Update
from telegram import ChatPermissions
from telegram.error import TelegramError
from telegram.ext import Application, MessageHandler, filters, ContextTypes
from telegram.error import RetryAfter

try:
    import psutil
except ImportError:
    psutil = None

try:
    import yt_dlp
except ImportError:
    yt_dlp = None

# ========================= MULTI BOT CONFIG =========================
BOT_TOKENS = [
"8964272303:AAGO-hQp-myUvHR02nLP1R5ooa0BmXCLXmM",
]

OWNER_ID = 8773707255

# ====================== SUPER FAST CONFIG ======================
DELAYS = {
    'nc': 0,
    'spam': 0,
    'swipe': 0,
    'reply': 0,
}

# ====================== TEXT LISTS ======================
NC_TEXTS = {
    'snc': [
        r"{target} 𝘔𝘈𝘋𝘈𝘙𝘊𝘏𝘖𝘋 𝘖𝘠𝘌𝘌𝘌𝘌𝘌𝘌.....,🥶🤍💢᳄᳄᳄᳄᳄᳄᳄᳄᳄᳄᳄᳄᳄᳄᳄᳄᳄᳄᳄᳄᳄᳄༺═──────────────═༻☟☜♻𓂃𓂃𓂃♻᳄᳄᳄᳄᳄᳄᳄༺═────(🌀)",
        r"{target} 𝘔𝘈𝘋𝘈𝘙𝘊𝘏𝘖𝘋 𝘖𝘠𝘌𝘌𝘌𝘌𝘌𝘌.....,🥶🤍💢᳄᳄᳄᳄᳄᳄᳄᳄᳄᳄᳄᳄᳄᳄᳄᳄᳄᳄᳄᳄᳄᳄༺═──────────────═༻☟☜♻𓂃𓂃𓂃♻᳄᳄᳄᳄᳄᳄᳄༺═────(🔥)",
        r"{target} 𝘔𝘈𝘋𝘈𝘙𝘊𝘏𝘖𝘋 𝘖𝘠𝘌𝘌𝘌𝘌𝘌𝘌.....,🥶🤍💢᳄᳄᳄᳄᳄᳄᳄᳄᳄᳄᳄᳄᳄᳄᳄᳄᳄᳄᳄᳄᳄᳄༺═──────────────═༻☟☜♻𓂃𓂃𓂃♻᳄᳄᳄᳄᳄᳄᳄༺═────(💀)",
        r"{target} 𝘔𝘈𝘋𝘈𝘙𝘊𝘏𝘖𝘋 𝘖𝘠𝘌𝘌𝘌𝘌𝘌𝘌.....,🥶🤍💢᳄᳄᳄᳄᳄᳄᳄᳄᳄᳄᳄᳄᳄᳄᳄᳄᳄᳄᳄᳄᳄᳄༺═──────────────═༻☟☜♻𓂃𓂃𓂃♻᳄᳄᳄᳄᳄᳄᳄༺═────(⚡)",
        r"{target} 𝘔𝘈𝘋𝘈𝘙𝘊𝘏𝘖𝘋 𝘖𝘠𝘌𝘌𝘌𝘌𝘌𝘌.....,🥶🤍💢᳄᳄᳄᳄᳄᳄᳄᳄᳄᳄᳄᳄᳄᳄᳄᳄᳄᳄᳄᳄᳄᳄༺═──────────────═༻☟☜♻𓂃𓂃𓂃♻᳄᳄᳄᳄᳄᳄᳄༺═────(😈)",
        r"{target} 𝘔𝘈𝘋𝘈𝘙𝘊𝘏𝘖𝘋 𝘖𝘠𝘌𝘌𝘌𝘌𝘌𝘌.....,🥶🤍💢᳄᳄᳄᳄᳄᳄᳄᳄᳄᳄᳄᳄᳄᳄᳄᳄᳄᳄᳄᳄᳄᳄༺═──────────────═༻☟☜♻𓂃𓂃𓂃♻᳄᳄᳄᳄᳄᳄᳄༺═────(☠️)",
        r"{target} 𝘔𝘈𝘋𝘈𝘙𝘊𝘏𝘖𝘋 𝘖𝘠𝘌𝘌𝘌𝘌𝘌𝘌.....,🥶🤍💢᳄᳄᳄᳄᳄᳄᳄᳄᳄᳄᳄᳄᳄᳄᳄᳄᳄᳄᳄᳄᳄᳄༺═──────────────═༻☟☜♻𓂃𓂃𓂃♻᳄᳄᳄᳄᳄᳄᳄༺═────(🌪️)",
        r"{target} 𝘔𝘈𝘋𝘈𝘙𝘊𝘏𝘖𝘋 𝘖𝘠𝘌𝘌𝘌𝘌𝘌𝘌.....,🥶🤍💢᳄᳄᳄᳄᳄᳄᳄᳄᳄᳄᳄᳄᳄᳄᳄᳄᳄᳄᳄᳄᳄᳄༺═──────────────═༻☟☜♻𓂃𓂃𓂃♻᳄᳄᳄᳄᳄᳄᳄༺═────(👑)",
        r"{target} 𝘔𝘈𝘋𝘈𝘙𝘊𝘏𝘖𝘋 𝘖𝘠𝘌𝘌𝘌𝘌𝘌𝘌.....,🥶🤍💢᳄᳄᳄᳄᳄᳄᳄᳄᳄᳄᳄᳄᳄᳄᳄᳄᳄᳄᳄᳄᳄᳄༺═──────────────═༻☟☜♻𓂃𓂃𓂃♻᳄᳄᳄᳄᳄᳄᳄༺═────(💥)",
        r"{target} 𝘔𝘈𝘋𝘈𝘙𝘊𝘏𝘖𝘋 𝘖𝘠𝘌𝘌𝘌𝘌𝘌𝘌.....,🥶🤍💢᳄᳄᳄᳄᳄᳄᳄᳄᳄᳄᳄᳄᳄᳄᳄᳄᳄᳄᳄᳄᳄᳄༺═──────────────═༻☟☜♻𓂃𓂃𓂃♻᳄᳄᳄᳄᳄᳄᳄༺═────(🚨)"
    ],
    'ssnc': [
        r"{target}﷽🩷﷽﷽🩷﷽﷽🩷﷽﷽🩷﷽﷽🩷﷽﷽🩷﷽﷽🩷﷽﷽🩷﷽﷽🩷﷽﷽🩷﷽﷽🩷﷽﷽🩷﷽﷽🩷﷽﷽🩷﷽﷽🩷﷽﷽🩷﷽﷽﷽﷽🩷﷽﷽🩷﷽﷽🩷﷽﷽🩷﷽﷽🩷﷽﷽🩷﷽﷽🩷﷽﷽🩷〘𝐂ʜʜᴀᴋᴀ ᴄᴜᴅᴀɪ ᴋʜᴀ〙(🌀)",
        r"{target}﷽🩷﷽﷽🩷﷽﷽🩷﷽﷽🩷﷽﷽🩷﷽﷽🩷﷽﷽🩷﷽﷽🩷﷽﷽🩷﷽﷽🩷﷽﷽🩷﷽﷽🩷﷽﷽🩷﷽﷽🩷﷽﷽🩷﷽﷽🩷﷽﷽﷽﷽🩷﷽﷽🩷﷽﷽🩷﷽﷽🩷﷽﷽🩷﷽﷽🩷﷽﷽🩷﷽﷽🩷〘𝐂ʜʜᴀᴋᴀ ᴄᴜᴅᴀɪ ᴋʜᴀ〙(🔥)",
        r"{target}﷽🩷﷽﷽🩷﷽﷽🩷﷽﷽🩷﷽﷽🩷﷽﷽🩷﷽﷽🩷﷽﷽🩷﷽﷽🩷﷽﷽🩷﷽﷽🩷﷽﷽🩷﷽﷽🩷﷽﷽🩷﷽﷽🩷﷽﷽🩷﷽﷽﷽﷽🩷﷽﷽🩷﷽﷽🩷﷽﷽🩷﷽﷽🩷﷽﷽🩷﷽﷽🩷﷽﷽🩷〘𝐂ʜʜᴀᴋᴀ ᴄᴜᴅᴀɪ ᴋʜᴀ〙(💀)",
        r"{target}﷽🩷﷽﷽🩷﷽﷽🩷﷽﷽🩷﷽﷽🩷﷽﷽🩷﷽﷽🩷﷽﷽🩷﷽﷽🩷﷽﷽🩷﷽﷽🩷﷽﷽🩷﷽﷽🩷﷽﷽🩷﷽﷽🩷﷽﷽🩷﷽﷽﷽﷽🩷﷽﷽🩷﷽﷽🩷﷽﷽🩷﷽﷽🩷﷽﷽🩷﷽﷽🩷﷽﷽🩷〘𝐂ʜʜᴀᴋᴀ ᴄᴜᴅᴀɪ ᴋʜᴀ〙(⚡)",
        r"{target}﷽🩷﷽﷽🩷﷽﷽🩷﷽﷽🩷﷽﷽🩷﷽﷽🩷﷽﷽🩷﷽﷽🩷﷽﷽🩷﷽﷽🩷﷽﷽🩷﷽﷽🩷﷽﷽🩷﷽﷽🩷﷽﷽🩷﷽﷽🩷﷽﷽﷽﷽🩷﷽﷽🩷﷽﷽🩷﷽﷽🩷﷽﷽🩷﷽﷽🩷﷽﷽🩷﷽﷽🩷〘𝐂ʜʜᴀᴋᴀ ᴄᴜᴅᴀɪ ᴋʜᴀ〙(😈)",
        r"{target}﷽🩷﷽﷽🩷﷽﷽🩷﷽﷽🩷﷽﷽🩷﷽﷽🩷﷽﷽🩷﷽﷽🩷﷽﷽🩷﷽﷽🩷﷽﷽🩷﷽﷽🩷﷽﷽🩷﷽﷽🩷﷽﷽🩷﷽﷽🩷﷽﷽﷽﷽🩷﷽﷽🩷﷽﷽🩷﷽﷽🩷﷽﷽🩷﷽﷽🩷﷽﷽🩷﷽﷽🩷〘𝐂ʜʜᴀᴋᴀ ᴄᴜᴅᴀɪ ᴋʜᴀ〙(☠️)",
        r"{target}﷽🩷﷽﷽🩷﷽﷽🩷﷽﷽🩷﷽﷽🩷﷽﷽🩷﷽﷽🩷﷽﷽🩷﷽﷽🩷﷽﷽🩷﷽﷽🩷﷽﷽🩷﷽﷽🩷﷽﷽🩷﷽﷽🩷﷽﷽🩷﷽﷽﷽﷽🩷﷽﷽🩷﷽﷽🩷﷽﷽🩷﷽﷽🩷﷽﷽🩷﷽﷽🩷﷽﷽🩷〘𝐂ʜʜᴀᴋᴀ ᴄᴜᴅᴀɪ ᴋʜᴀ〙(🌪️)",
        r"{target}﷽🩷﷽﷽🩷﷽﷽🩷﷽﷽🩷﷽﷽🩷﷽﷽🩷﷽﷽🩷﷽﷽🩷﷽﷽🩷﷽﷽🩷﷽﷽🩷﷽﷽🩷﷽﷽🩷﷽﷽🩷﷽﷽🩷﷽﷽🩷﷽﷽﷽﷽🩷﷽﷽🩷﷽﷽🩷﷽﷽🩷﷽﷽🩷﷽﷽🩷﷽﷽🩷﷽﷽🩷〘𝐂ʜʜᴀᴋᴀ ᴄᴜᴅᴀɪ ᴋʜᴀ〙(👑)",
        r"{target}﷽🩷﷽﷽🩷﷽﷽🩷﷽﷽🩷﷽﷽🩷﷽﷽🩷﷽﷽🩷﷽﷽🩷﷽﷽🩷﷽﷽🩷﷽﷽🩷﷽﷽🩷﷽﷽🩷﷽﷽🩷﷽﷽🩷﷽﷽🩷﷽﷽﷽﷽🩷﷽﷽🩷﷽﷽🩷﷽﷽🩷﷽﷽🩷﷽﷽🩷﷽﷽🩷﷽﷽🩷〘𝐂ʜʜᴀᴋᴀ ᴄᴜᴅᴀɪ ᴋʜᴀ〙(💥)",
        r"{target}﷽🩷﷽﷽🩷﷽﷽🩷﷽﷽🩷﷽﷽🩷﷽﷽🩷﷽﷽🩷﷽﷽🩷﷽﷽🩷﷽﷽🩷﷽﷽🩷﷽﷽🩷﷽﷽🩷﷽﷽🩷﷽﷽🩷﷽﷽🩷﷽﷽﷽﷽🩷﷽﷽🩷﷽﷽🩷﷽﷽🩷﷽﷽🩷﷽﷽🩷﷽﷽🩷﷽﷽🩷〘𝐂ʜʜᴀᴋᴀ ᴄᴜᴅᴀɪ ᴋʜᴀ〙(🚨)"
    ],
    'fnc': [
        r"˚⊱━━🍁━━⊰˚{target} Cʜᴜᴘ Cʜᴀᴘ Cʜᴜᴅ Rɴᴅʏᴋ\n꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅",
        r"˚⊱━━🔥━━⊰˚{target} Cʜᴜᴘ Cʜᴀᴘ Cʜᴜᴅ Rɴᴅʏᴋ\n꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅",
        r"˚⊱━━💀━━⊰˚{target} Cʜᴜᴘ Cʜᴀᴘ Cʜᴜᴅ Rɴᴅʏᴋ\n꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅",
        r"˚⊱━━⚡━━⊰˚{target} Cʜᴜᴘ Cʜᴀᴘ Cʜᴜᴅ Rɴᴅʏᴋ\n꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅",
        r"˚⊱━━😈━━⊰˚{target} Cʜᴜᴘ Cʜᴀᴘ Cʜᴜᴅ Rɴᴅʏᴋ\n꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅",
        r"˚⊱━━☠️━━⊰˚{target} Cʜᴜᴘ Cʜᴀᴘ Cʜᴜᴅ Rɴᴅʏᴋ\n꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅",
        r"˚⊱━━🌪️━━⊰˚{target} Cʜᴜᴘ Cʜᴀᴘ Cʜᴜᴅ Rɴᴅʏᴋ\n꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅",
        r"˚⊱━━👑━━⊰˚{target} Cʜᴜᴘ Cʜᴀᴘ Cʜᴜᴅ Rɴᴅʏᴋ\n꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅",
        r"˚⊱━━💥━━⊰˚{target} Cʜᴜᴘ Cʜᴀᴘ Cʜᴜᴅ Rɴᴅʏᴋ\n꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅",
        r"˚⊱━━🚨━━⊰˚{target} Cʜᴜᴘ Cʜᴀᴘ Cʜᴜᴅ Rɴᴅʏᴋ\n꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅꧅"
    ],
    'cnc': [
        r"˚⊱━━😛━━⊰˚{target} chote bhag rndice 𒐫𒐫𒐫𒐫𒐫𒐫𒐫✨✨✨𒐫✨✨✨𒐫✨✨✨𒐫𒐫✨✨𒐫✨✨✨𒐫✨✨𒐫𒐫✨✨✨𒐫𒐫𒐫𒐫𒐫𒐫𒐫✨✨𒐫𒐫𒐫✨𒐫✨✨𒐫𒐫✨✨𒐫✨✨𒐫𒐫𒐫✨🎀✨",
        r"˚⊱━━🔥━━⊰˚{target} chote bhag rndice 𒐫𒐫𒐫𒐫𒐫𒐫𒐫✨✨✨𒐫✨✨✨𒐫✨✨✨𒐫𒐫✨✨𒐫✨✨✨𒐫✨✨𒐫𒐫✨✨✨𒐫𒐫𒐫𒐫𒐫𒐫𒐫✨✨𒐫𒐫𒐫✨𒐫✨✨𒐫𒐫✨✨𒐫✨✨𒐫𒐫𒐫✨🎀✨",
        r"˚⊱━━💀━━⊰˚{target} chote bhag rndice 𒐫𒐫𒐫𒐫𒐫𒐫𒐫✨✨✨𒐫✨✨✨𒐫✨✨✨𒐫𒐫✨✨𒐫✨✨✨𒐫✨✨𒐫𒐫✨✨✨𒐫𒐫𒐫𒐫𒐫𒐫𒐫✨✨𒐫𒐫𒐫✨𒐫✨✨𒐫𒐫✨✨𒐫✨✨𒐫𒐫𒐫✨🎀✨",
        r"˚⊱━━⚡━━⊰˚{target} chote bhag rndice 𒐫𒐫𒐫𒐫𒐫𒐫𒐫✨✨✨𒐫✨✨✨𒐫✨✨✨𒐫𒐫✨✨𒐫✨✨✨𒐫✨✨𒐫𒐫✨✨✨𒐫𒐫𒐫𒐫𒐫𒐫𒐫✨✨𒐫𒐫𒐫✨𒐫✨✨𒐫𒐫✨✨𒐫✨✨𒐫𒐫𒐫✨🎀✨",
        r"˚⊱━━😈━━⊰˚{target} chote bhag rndice 𒐫𒐫𒐫𒐫𒐫𒐫𒐫✨✨✨𒐫✨✨✨𒐫✨✨✨𒐫𒐫✨✨𒐫✨✨✨𒐫✨✨𒐫𒐫✨✨✨𒐫𒐫𒐫𒐫𒐫𒐫𒐫✨✨𒐫𒐫𒐫✨𒐫✨✨𒐫𒐫✨✨𒐫✨✨𒐫𒐫𒐫✨🎀✨",
        r"˚⊱━━☠️━━⊰˚{target} chote bhag rndice 𒐫𒐫𒐫𒐫𒐫𒐫𒐫✨✨✨𒐫✨✨✨𒐫✨✨✨𒐫𒐫✨✨𒐫✨✨✨𒐫✨✨𒐫𒐫✨✨✨𒐫𒐫𒐫𒐫𒐫𒐫𒐫✨✨𒐫𒐫𒐫✨𒐫✨✨𒐫𒐫✨✨𒐫✨✨𒐫𒐫𒐫✨🎀✨",
        r"˚⊱━━🌪️━━⊰˚{target} chote bhag rndice 𒐫𒐫𒐫𒐫𒐫𒐫𒐫✨✨✨𒐫✨✨✨𒐫✨✨✨𒐫𒐫✨✨𒐫✨✨✨𒐫✨✨𒐫𒐫✨✨✨𒐫𒐫𒐫𒐫𒐫𒐫𒐫✨✨𒐫𒐫𒐫✨𒐫✨✨𒐫𒐫✨✨𒐫✨✨𒐫𒐫𒐫✨🎀✨",
        r"˚⊱━━👑━━⊰˚{target} chote bhag rndice 𒐫𒐫𒐫𒐫𒐫𒐫𒐫✨✨✨𒐫✨✨✨𒐫✨✨✨𒐫𒐫✨✨𒐫✨✨✨𒐫✨✨𒐫𒐫✨✨✨𒐫𒐫𒐫𒐫𒐫𒐫𒐫✨✨𒐫𒐫𒐫✨𒐫✨✨𒐫𒐫✨✨𒐫✨✨𒐫𒐫𒐫✨🎀✨",
        r"˚⊱━━💥━━⊰˚{target} chote bhag rndice 𒐫𒐫𒐫𒐫𒐫𒐫𒐫✨✨✨𒐫✨✨✨𒐫✨✨✨𒐫𒐫✨✨𒐫✨✨✨𒐫✨✨𒐫𒐫✨✨✨𒐫𒐫𒐫𒐫𒐫𒐫𒐫✨✨𒐫𒐫𒐫✨𒐫✨✨𒐫𒐫✨✨𒐫✨✨𒐫𒐫𒐫✨🎀✨",
        r"˚⊱━━🚨━━⊰˚{target} chote bhag rndice 𒐫𒐫𒐫𒐫𒐫𒐫𒐫✨✨✨𒐫✨✨✨𒐫✨✨✨𒐫𒐫✨✨𒐫✨✨✨𒐫✨✨𒐫𒐫✨✨✨𒐫𒐫𒐫𒐫𒐫𒐫𒐫✨✨𒐫𒐫𒐫✨𒐫✨✨𒐫𒐫✨✨𒐫✨✨𒐫𒐫𒐫✨🎀✨"
    ],
    'bnc': [
        r"✨ {target} ke maa ke periods 🩸🩸 💧🩸💧🩸💧🩸💧🩸🩸💧🩸🩸💧🩸🩸💧🩸🩸💧🩸🩸💧🩸🩸💧🩸🩸💧🩸🩸💧🩸🩸💧🩸🩸💧🩸🩸💧🩸🩸💧🩸🩸💧🩸🩸💧🩸🩸💧🩸🩸💧🩸🩸💧💫",
        r"🌟 {target} ke maa ke periods 🩸🩸 💧🩸💧🩸💧🩸💧🩸🩸💧🩸🩸💧🩸🩸💧🩸🩸💧🩸🩸💧🩸🩸💧🩸🩸💧🩸🩸💧🩸🩸💧🩸🩸💧🩸🩸💧🩸🩸💧🩸🩸💧🩸🩸💧🩸🩸💧🩸🩸💧🩸🩸💧✨",
        r"🌀 {target} ke maa ke periods 🩸🩸 💧🩸💧🩸💧🩸💧🩸🩸💧🩸🩸💧🩸🩸💧🩸🩸💧🩸🩸💧🩸🩸💧🩸🩸💧🩸🩸💧🩸🩸💧🩸🩸💧🩸🩸💧🩸🩸💧🩸🩸💧🩸🩸💧🩸🩸💧🩸🩸💧🩸🩸💧💫",
        r"🔱 {target} ke maa ke periods 🩸🩸 💧🩸💧🩸💧🩸💧🩸🩸💧🩸🩸💧🩸🩸💧🩸🩸💧🩸🩸💧🩸🩸💧🩸🩸💧🩸🩸💧🩸🩸💧🩸🩸💧🩸🩸💧🩸🩸💧🩸🩸💧🩸🩸💧🩸🩸💧🩸🩸💧🩸🩸💧✨",
        r"🌈 {target} ke maa ke periods 🩸🩸 💧🩸💧🩸💧🩸💧🩸🩸💧🩸🩸💧🩸🩸💧🩸🩸💧🩸🩸💧🩸🩸💧🩸🩸💧🩸🩸💧🩸🩸💧🩸🩸💧🩸🩸💧🩸🩸💧🩸🩸💧🩸🩸💧🩸🩸💧🩸🩸💧🩸🩸💧💫",
        r"⭐ {target} ke maa ke periods 🩸🩸 💧🩸💧🩸💧🩸💧🩸🩸💧🩸🩸💧🩸🩸💧🩸🩸💧🩸🩸💧🩸🩸💧🩸🩸💧🩸🩸💧🩸🩸💧🩸🩸💧🩸🩸💧🩸🩸💧🩸🩸💧🩸🩸💧🩸🩸💧🩸🩸💧🩸🩸💧✨",
        r"🫧 {target} ke maa ke periods 🩸🩸 💧🩸💧🩸💧🩸💧🩸🩸💧🩸🩸💧🩸🩸💧🩸🩸💧🩸🩸💧🩸🩸💧🩸🩸💧🩸🩸💧🩸🩸💧🩸🩸💧🩸🩸💧🩸🩸💧🩸🩸💧🩸🩸💧🩸🩸💧🩸🩸💧🩸🩸💧💫",
        r"🪩 {target} ke maa ke periods 🩸🩸 💧🩸💧🩸💧🩸💧🩸🩸💧🩸🩸💧🩸🩸💧🩸🩸💧🩸🩸💧🩸🩸💧🩸🩸💧🩸🩸💧🩸🩸💧🩸🩸💧🩸🩸💧🩸🩸💧🩸🩸💧🩸🩸💧🩸🩸💧🩸🩸💧🩸🩸💧✨",
        r"🪷 {target} ke maa ke periods 🩸🩸 💧🩸💧🩸💧🩸💧🩸🩸💧🩸🩸💧🩸🩸💧🩸🩸💧🩸🩸💧🩸🩸💧🩸🩸💧🩸🩸💧🩸🩸💧🩸🩸💧🩸🩸💧🩸🩸💧🩸🩸💧🩸🩸💧🩸🩸💧🩸🩸💧🩸🩸💧💫",
        r"🌙 {target} ke maa ke periods 🩸🩸 💧🩸💧🩸💧🩸💧🩸🩸💧🩸🩸💧🩸🩸💧🩸🩸💧🩸🩸💧🩸🩸💧🩸🩸💧🩸🩸💧🩸🩸💧🩸🩸💧🩸🩸💧🩸🩸💧🩸🩸💧🩸🩸💧🩸🩸💧🩸🩸💧🩸🩸💧✨"
    ],
    'sgcnc': [
        r"{target} tmkc INOSUKE💋 mare 💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤-----(💔)",
        r"{target} tmkc INOSUKE💋 mare 💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤-----(❤️)",
        r"{target} tmkc INOSUKE💋 mare 💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤-----(🧡)",
        r"{target} tmkc INOSUKE💋 mare 💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤-----(💛)",
        r"{target} tmkc INOSUKE💋 mare 💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤-----(💚)",
        r"{target} tmkc INOSUKE💋 mare 💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤-----(🩶)",
        r"{target} tmkc INOSUKE💋 mare 💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤-----(🤎)",
        r"{target} tmkc INOSUKE💋 mare 💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤-----(💜)",
        r"{target} tmkc INOSUKE💋 mare 💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤-----(💙)",
        r"{target} tmkc INOSUKE💋 mare 💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤💤-----(🩵)"
    ]
}

SPAM_TEXTS = {
    'bspam': [
        r"✫: ̗̀➛「{target}」────────Tᴇʀɪ Mᴀ Kᴀʟᴡɪ 「🎀」\n✫: ̗̀➛「{target}」────────Tᴇʀɪ Mᴀ Kᴀʟᴡɪ 「🤍」\n✫: ̗̀➛「{target}」────────Tᴇʀɪ Mᴀ Kᴀʟᴡɪ 「🎀」\n✫: ̗̀➛「{target}」────────Tᴇʀɪ Mᴀ Kᴀʟᴡɪ 「🤍」\n✫: ̗̀➛「{target}」────────Tᴇʀɪ Mᴀ Kᴀʟᴡɪ 「🎀」\n✫: ̗̀➛「{target}」────────Tᴇʀɪ Mᴀ Kᴀʟᴡɪ 「🤍」",
        r"✫: ̗̀➛「{target}」────────Tᴇʀɪ Mᴀ Bᴀᴜɴɪ 「✨」\n✫: ̗̀➛「{target}」────────Tᴇʀɪ Mᴀ Bᴀᴜɴɪ 「🩷」\n✫: ̗̀➛「{target}」────────Tᴇʀɪ Mᴀ Bᴀᴜɴɪ 「✨」\n✫: ̗̀➛「{target}」────────Tᴇʀɪ Mᴀ Bᴀᴜɴɪ 「🩷」\n✫: ̗̀➛「{target}」────────Tᴇʀɪ Mᴀ Bᴀᴜɴɪ 「✨」\n✫: ̗̀➛「{target}」────────Tᴇʀɪ Mᴀ Bᴀᴜɴɪ 「🩷」",
        r"✫: ̗̀➛「{target}」────────Tᴇʀɪ Mᴀ Hᴀᴋʟɪ 「💫」\n✫: ̗̀➛「{target}」────────Tᴇʀɪ Mᴀ Hᴀᴋʟɪ 「🩵」\n✫: ̗̀➛「{target}」────────Tᴇʀɪ Mᴀ Hᴀᴋʟɪ 「💫」\n✫: ̗̀➛「{target}」────────Tᴇʀɪ Mᴀ Hᴀᴋʟɪ 「🩵」\n✫: ̗̀➛「{target}」────────Tᴇʀɪ Mᴀ Hᴀᴋʟɪ 「💫」\n✫: ̗̀➛「{target}」────────Tᴇʀɪ Mᴀ Hᴀᴋʟɪ 「🩵」",
        r"✫: ̗̀➛「{target}」────────Tᴇʀɪ Mᴀ Lᴀɴɢᴅɪ 「🌙」\n✫: ̗̀➛「{target}」────────Tᴇʀɪ Mᴀ Lᴀɴɢᴅɪ 「🖤」\n✫: ̗̀➛「{target}」────────Tᴇʀɪ Mᴀ Lᴀɴɢᴅɪ 「🌙」\n✫: ̗̀➛「{target}」────────Tᴇʀɪ Mᴀ Lᴀɴɢᴅɪ 「🖤」\n✫: ̗̀➛「{target}」────────Tᴇʀɪ Mᴀ Lᴀɴɢᴅɪ 「🌙」\n✫: ̗̀➛「{target}」────────Tᴇʀɪ Mᴀ Lᴀɴɢᴅɪ 「🖤」"
    ],
    'aspam': [
        r"🤍{target}  Ki Kɪ Mᴀ Kɪ Sᴀᴛʀᴀɴɢɪ Cʜᴜᴛ 🤍",
        r" 🖤{target}  Kɪ Mᴀ Kɪ Sᴀᴛʀᴀɴɢɪ Cʜᴜᴛ  🖤",
        r" 🤎{target}  Kɪ Mᴀ Kɪ Sᴀᴛʀᴀɴɢɪ Cʜᴜᴛ  🤎",
        r" 💜{target}  Ki Kɪ Mᴀ Kɪ Sᴀᴛʀᴀɴɢɪ Cʜᴜᴛ  💜",
        r" 💙{target}  Kɪ Mᴀ Kɪ Sᴀᴛʀᴀɴɢɪ Cʜᴜᴛ  💙",
        r" 🩵{target}  Kɪ Mᴀ Kɪ Sᴀᴛʀᴀɴɢɪ Cʜᴜᴛ  🩵",
        r" 💚{target}  Kɪ Mᴀ Kɪ Sᴀᴛʀ4ɴɢɪ Cʜᴜᴛ  💚",
        r" 💛{target}  Kɪ Mᴀ Kɪ Sᴀᴛʀᴀɴɢɪ Cʜᴜᴛ  💛",
        r" 🧡{target}  Kɪ Mᴀ Kɪ Sᴀᴛʀᴀɴɢɪ Cʜᴜᴛ  🧡",
        r" ❤️{target}  Kɪ Mᴀ Kɪ Sᴀᴛʀᴀɴɢɪ Cʜᴜᴛ  ❤️"
    ],
    'sspam': [
        r"{target}  CVR KR MC GAREEB 👞👞👞👞👞👞👞👞👞👞👞👞👞👞👞👞👞👞👞👞👞👞👞👞👞👞👞👞👞👞👞👞👞👞👞👞👞👞👞👞👞👞👞👞👞👞👞👞👞👞👞👞👞👞👞👞👞👞👞👞👞👞👞👞👞👞👞👞👞👞👞👞👞👞👞👞👞👞👞👞👞👞👞👞👞👞👞👞👞👞👞👞👞👞👞👞👞👞👞👞👞👞👞👞👞👞👞👞👞👞👞👞👞👞👞👞👞👞👞👞👞👞👞👞👞👞👞👞👞👞👞👞👞👞👞👞👞👞👞👞👞👞👞👞👞👞👞👞👞👞👞👞👞👞👞👞👞👞👞👞👞👞👞👞👞 {target}  CVR KR MC GAREEB {target}  CVR KR MC GAREEB"
    ],
    'fspam': [
        r"💛 𓂃𓈒 {target} ㅤㅤㅤㅤㅤㅤㅤㅤㅤㅤ 𝙎𝘼𝙍𝙀 𝙆𝙃𝙀𝙏 𝙀𝙆 𝙎𝘼𝙏𝙃 𝙆𝙃𝙊𝘿 𝘿𝙐𝙉𝙂𝘼 𝙃𝘼𝙏𝙀𝙍 𝙏𝙀𝙍𝙄 𝙈𝘼𝘼 𝘿𝙄𝙆𝙃𝙏𝙀 𝙃𝙄 𝘾𝙃𝙊𝘿 𝘿𝙐𝙉𝙂𝘼___/>🤣𓂃𓈒"
    ],
    'gspam': [
        r"TERYYYYYYYYYYYY AMMMMIIII KIIIII BURRRR FADUUGAAAA MADHARXHODDDDD👀👀👀 INOSUKE💋 KEEEEE PILLEEEE  RANDDDD TERYYYY BHENNNN KIIII SEALLLL TODUGAAAAA SAREYAMMMMM CHAURAHEEEEE PEEEEE🤣🤣🤣🤣🤣BHENNNN KEEEE TAKEEEE MADHARXHODDDDDDD🖕🖕 {target}"
    ],
    'rspam': [
        r"{target}𝐑ᴀɴᴅʏ 𝐊ᴀ 𝐁ᴀᴄʜᴀ ˏˋ°•*⁀➷ 𝑳𝑼𝑵𝑫 𝑪𝑯𝑶𝑶𝑺 𝐓𝐨𝐧𝐲 𝑲𝑨 कुतिया के 🥂🌙 {target}𝐑ᴀɴᴅʏ 𝐊ᴀ 𝐁ᴀᴄʜᴀ ˏˋ°•*⁀➷ 𝑳𝑼𝑵𝑫 𝑪𝑯𝑶𝑶𝑺 𝐓𝐨𝐧𝐲 𝑲𝑨 कुतिया के 🥂🌙"
    ]
}

SWIPE_TEXTS = {
    'aswipe': [
        r"𝐊ʏᴀ 𝐑ᴇ 𝐑ᴀɴᴅɪᴋᴇ 𝐂ᴏᴏʟ 𝐁ᴀɴᴇɢᴀ 𝐓ᴜ 𝐂ʜᴀʟ 𝐀ʙ 𝐂ʜᴜᴅ 𝐀ᴘɴᴇ 𝐁ᴀᴀᴘ 𝗧𝗼𝗻𝘆 𝐒ᴇ - 🦢💘",
        r"𝐊ɪ 𝐌ᴀᴀ 𝐌ᴀʀʀ 𝐆ᴀʏɪ 𝐘ᴀᴀʀ - 𝐉ᴀɪ 𝗧𝗼𝗻𝘆 ! 🌙",
        r"acha beta 😂🔥👊🏻 ? coi na me toh HATER codunga 😹💔🔥😆👊🏻💥",
        r"chudke bhaga kaise 😂💥🤣🤘🏻",
        r"ne toh 𝗧𝗼𝗻𝘆 ka lun muh me lelia 😂🙏🏻😂🙏🏻",
        r"try maa सूर्य☀ nikalte hi pel du 😹🔥💔",
        r"mkl lun te vaj 😂✊🏻💦",
        r"𝗧ᴍᴋ𝗕 pe 𝗧𝗼𝗻𝘆 ka hamla 😂⚔🔥💥",
        r"𝐂ʜʟ 𝐇ᴀʀᴍᴢᴀᴅ𝐈 𝐊ᴇ लड़के 💛🤍🩵",
        r"oi 𝐓ᴇʀɪ 𝐌‌ᴀᴀ गुलाम ₰🖤",
    ],
    'fswipe': [
        r"chudke bhaga kaise 😂💥🤣🤘🏻",
        r"ne toh 𝗧𝗼𝗻𝘆 ka lun muh me lelia 😂🙏🏻😂🙏🏻",
        r"try maa सूर्य☀ nikalte hi pel du 😹🔥💔",
        r"mkl lun te vaj 😂✊🏻💦",
        r"𝗧ᴍᴋ𝗕 pe 𝗧𝗼𝗻𝘆 ka hamla 😂⚔🔥💥",
        r"𝐂ʜʟ 𝐇ᴀʀᴍᴢᴀᴅ𝐈 𝐊ᴇ लड़के 💛🤍🩵",
        r"oi 𝐓ᴇʀɪ 𝐌‌ᴀᴀ गुलाम ₰🖤",
        r"chl rndyce chud ke dikha 😂💥🤣🔥",
        r"𝐊ɪ 𝐌ᴀᴀ 𝐌ᴀʀʀ 𝐆ᴀʏɪ naacho 💃🏻💃🏻🕺🏻🎶😂😆💞🔥 !",
        r"tera baap bass 𝗧𝗼𝗻𝘆 hai 😂🎀",
        r"try maa hagte hue paad mari 😹🔥🥀",
        r"𝐓ᴇʀɪ 𝐌ᴜᴍᴍʏ 𝐂ʜᴏᴅ 𝐃ɪ 𝗧𝗼𝗻𝘆 𝐍ᴇ 𝐁ᴡᴀʜᴀʜᴀʜᴀ ⚜"
    ],
    'rrswipe': [
        r"𓂃˖˳·˖ ִֶָ ⋆❤️͙⋆ ִֶָ˖·˳˖𓂃 ִֶָ⁀➴༯ sꪶꪖꪜꫀ ִֶָ. ..𓂃 ࣪ ִֶָ🌈་༘࿐ 𝗟𝗡𝗗 𝗖𝗛𝗢𝗢𝗦 -/- ⋆˚❤️ ݁˖⭑.ᐟ",
        r"𓂃˖˳·˖ ִֶָ ⋆🧡͙⋆ ִֶָ˖·˳˖𓂃 ִֶָ⁀➴༯ sꪶꪖꪜꫀ ִֶָ. ..𓂃 ࣪ ִֶָ🌈་༘࿐ 𝗟𝗡𝗗 𝗖𝗛𝗢𝗢𝗦 -/- ⋆˚🧡 ݁˖⭑.ᐟ",
        r"𓂃˖˳·˖ ִֶָ ⋆💛͙⋆ ִֶָ˖·˳˖𓂃 ִֶָ⁀➴༯ sꪶꪖꪜꫀ ִֶָ. ..𓂃 ࣪ ִֶָ🌈་༘࿐ 𝗟𝗡𝗗 𝗖𝗛𝗢𝗢𝗦 -/- ⋆˚💛 ݁˖⭑.ᐟ",
        r"𓂃˖˳·˖ ִֶָ ⋆💚͙⋆ ִֶָ˖·˳˖𓂃 ִֶָ⁀➴༯ sꪶꪖꪜꫀ ִֶָ. ..𓂃 ࣪ ִֶָ🌈་༘࿐ 𝗟𝗡𝗗 𝗖𝗛𝗢𝗢𝗦 -/- ⋆˚💚 ݁˖⭑.ᐟ",
        r"𓂃˖˳·˖ ִֶָ ⋆💙͙⋆ ִֶָ˖·˳˖𓂃 ִֶָ⁀➴༯ sꪶꪖꪜꫀ ִֶָ. ..𓂃 ࣪ ִֶָ🌈་༘࿐ 𝗟𝗡𝗗 𝗖𝗛𝗢𝗢𝗦 -/- ⋆˚💙 ݁˖⭑.ᐟ",
        r"𓂃˖˳·˖ ִֶָ ⋆💜͙⋆ ִֶָ˖·˳˖𓂃 ִֶָ⁀➴༯ sꪶꪖꪜꫀ ִֶָ. ..𓂃 ࣪ ִֶָ🌈་༘࿐ 𝗟𝗡𝗗 𝗖𝗛𝗢𝗢𝗦 -/- ⋆˚💜 ݁˖⭑.ᐟ",
        r"𓂃˖˳·˖ ִֶָ ⋆🖤͙⋆ ִֶָ˖·˳˖𓂃 ִֶָ⁀➴༯ sꪶꪖꪜꫀ ִֶָ. ..𓂃 ࣪ ִֶָ🌈་༘࿐ 𝗟𝗡𝗗 𝗖𝗛𝗢𝗢𝗦 -/- ⋆˚🖤 ݁˖⭑.ᐟ",
        r"𓂃˖˳·˖ ִֶָ ⋆🤍͙⋆ ִֶָ˖·˳˖𓂃 ִֶָ⁀➴༯ sꪶꪖꪜꫀ ִֶָ. ..𓂃 ࣪ ִֶָ🌈་༘࿐ 𝗟𝗡𝗗 𝗖𝗛𝗢𝗢𝗦 -/- ⋆˚🤍 ݁˖⭑.ᐟ",
        r"𓂃˖˳·˖ ִֶָ ⋆🤎͙⋆ ִֶָ˖·˳˖𓂃 ִֶָ⁀➴༯ sꪶꪖꪜꫀ ִֶָ. ..𓂃 ࣪ ִֶָ🌈་༘࿐ 𝗟𝗡𝗗 𝗖𝗛𝗢𝗢𝗦 -/- ⋆˚🤎 ݁˖⭑.ᐟ",
        r"𓂃˖˳·˖ ִֶָ ⋆💖͙⋆ ִֶָ˖·˳˖𓂃 ִֶָ⁀➴༯ sꪶꪖꪜꫀ ִֶָ. ..𓂃 ࣪ ִֶָ🌈་༘࿐ 𝗟𝗡𝗗 𝗖𝗛𝗢𝗢𝗦 -/- ⋆˚💖 ݁˖⭑.ᐟ",
        r"𓂃˖˳·˖ ִֶָ ⋆💗͙⋆ ִֶָ˖·˳˖𓂃 ִֶָ⁀➴༯ sꪶꪖꪜꫀ ִֶָ. ..𓂃 ࣪ ִֶָ🌈་༘࿐ 𝗟𝗡𝗗 𝗖𝗛𝗢𝗢𝗦 -/- ⋆˚💗 ݁˖⭑.ᐟ",
        r"𓂃˖˳·˖ ִֶָ ⋆💓͙⋆ ִֶָ˖·˳˖𓂃 ִֶָ⁀➴༯ sꪶꪖꪜꫀ ִֶָ. ..𓂃 ࣪ ִֶָ🌈་༘࿐ 𝗟𝗡𝗗 𝗖𝗛𝗢𝗢𝗦 -/- ⋆˚💓 ݁˖⭑.ᐟ",
        r"𓂃˖˳·˖ ִֶָ ⋆💞͙⋆ ִֶָ˖·˳˖𓂃 ִֶָ⁀➴༯ sꪶꪖꪜꫀ ִֶָ. ..𓂃 ࣪ ִֶָ🌈་༘࿐ 𝗟𝗡𝗗 𝗖𝗛𝗢𝗢𝗦 -/- ⋆˚💞 ݁˖⭑.ᐟ",
        r"𓂃˖˳·˖ ִֶָ ⋆💕͙⋆ ִֶָ˖·˳˖𓂃 ִֶָ⁀➴༯ sꪶꪖꪜꫀ ִֶָ. ..𓂃 ࣪ ִֶָ🌈་༘࿐ 𝗟𝗡𝗗 𝗖𝗛𝗢𝗢𝗦 -/- ⋆˚💕 ݁˖⭑.ᐟ",
        r"𓂃˖˳·˖ ִֶָ ⋆💘͙⋆ ִֶָ˖·˳˖𓂃 ִֶָ⁀➴༯ sꪶꪖꪜꫀ ִֶָ. ..𓂃 ࣪ ִֶָ🌈་༘࿐ 𝗟𝗡𝗗 𝗖𝗛𝗢𝗢𝗦 -/- ⋆˚💘 ݁˖⭑.ᐟ",
        r"𓂃˖˳·˖ ִֶָ ⋆💝͙⋆ ִֶָ˖·˳˖𓂃 ִֶָ⁀➴༯ sꪶꪖꪜꫀ ִֶָ. ..𓂃 ࣪ ִֶָ🌈་༘࿐ 𝗟𝗡𝗗 𝗖𝗛𝗢𝗢𝗦 -/- ⋆˚💝 ݁˖⭑.ᐟ",
        r"𓂃˖˳·˖ ִֶָ ⋆💟͙⋆ ִֶָ˖·˳˖𓂃 ִֶָ⁀➴༯ sꪶꪖꪜꫀ ִֶָ. ..𓂃 ࣪ ִֶָ🌈་༘࿐ 𝗟𝗡𝗗 𝗖𝗛𝗢𝗢𝗦 -/- ⋆˚💟 ݁˖⭑.ᐟ"
    ],
    'cswipe': [
        r" 𝐾𝐵𝐴𝐷𝐼 𝑊𝐴𝐿𝐸 ⇝ ༼ 🍓༽ ",
        r"𝐾𝐵𝐴𝐷𝐼 𝑊𝐴𝐿𝐸  ⇝ ༼ 🍈༽",
        r"𝐾𝐵𝐴𝐷𝐼 𝑊𝐴𝐿𝐸  ⇝ ༼ 🫜༽",
        r"𝐾𝐵𝐴𝐷𝐼 𝑊𝐴𝐿𝐸  ⇝ ༼ 🍒༽",
        r"𝐾𝐵𝐴𝐷𝐼 𝑊𝐴𝐿𝐸  ⇝ ༼ 🍐༽",
        r"𝐾𝐵𝐴𝐷𝐼 𝑊𝐴𝐿𝐸  ⇝ ༼ 🥥༽",
        r"𝐾𝐵𝐴𝐷𝐼 𝑊𝐴𝐿𝐸  ⇝ ༼ 🍎༽",
        r"𝐾𝐵𝐴𝐷𝐼 𝑊𝐴𝐿𝐸  ⇝ ༼ 🫛༽",
        r"𝐾𝐵𝐴𝐷𝐼 𝑊𝐴𝐿𝐸  ⇝ ༼ 🥔༽",
        r"𝐾𝐵𝐴𝐷𝐼 𝑊𝐴𝐿𝐸  ⇝ ༼ 🍅༽",
        r"𝐾𝐵𝐴𝐷𝐼 𝑊𝐴𝐿𝐸  ⇝ ༼ 🥬༽",
        r"𝐾𝐵𝐴𝐷𝐼 𝑊𝐴𝐿𝐸  ⇝ ༼ 🧅༽",
        r"𝐾𝐵𝐴𝐷𝐼 𝑊𝐴𝐿𝐸  ⇝ ༼ 🌶️༽",
        r"𝐾𝐵𝐴𝐷𝐼 𝑊𝐴𝐿𝐸  ⇝ ༼ 🫑༽",
        r"𝐾𝐵𝐴𝐷𝐼 𝑊𝐴𝐿𝐸  ⇝ ༼ 🫚༽",
        r"𝐾𝐵𝐴𝐷𝐼 𝑊𝐴𝐿𝐸  ⇝ ༼ 🍉༽",
        r"𝐾𝐵𝐴𝐷𝐼 𝑊𝐴𝐿𝐸  ⇝ ༼ 🍏༽",
        r"𝐾𝐵𝐴𝐷𝐼 𝑊𝐴𝐿𝐸  ⇝ ༼ 🫘༽",
        r"𝐾𝐵𝐴𝐷𝐼 𝑊𝐴𝐿𝐸  ⇝ ༼ 🍑༽",
        r"𝐾𝐵𝐴𝐷𝐼 𝑊𝐴𝐿𝐸  ⇝ ༼ 🥝༽",
    ]
}

REPLY_TEXTS = {
    'rreply': [
        r"⋆｡ﾟ☁︎｡𝐂ʏᴜ 𝐑ᴇ मदरचोद 𝗧𝗼𝗻𝘆 बाप के सामने 𝐅ʏᴛᴇʀ 𝐁ᴀɴᴇɢᴀ ⋆𓂃 ོ☼𓂃 😂🔥",
        r"नहीं नहीं तेरी मां को 𝐒ɪʀғ 𝗧𝗼𝗻𝘆 बाप चोद सकता है ִֶָ𓂃 ࣪ ִֶָ👑་༘࿐ sᴀᴍᴊʜᴀ ʀᴀɴᴅɪᴋᴇ ???",
        r"तेरी मां का 𝐒ᴛʏʟɪsʜ भोसड़ा 😱",
        r"𝑻𝒆𝒓𝒚 𝒎𝒂𝒂 𝒓𝒂𝒏𝒅𝒂𝒍 𝒉 𝒃𝒂𝒔 𝒃𝒂𝒂𝒕 𝒌𝒉𝒂𝒕𝒂𝒎 😡🔥",
        r"सोच तेरी बहन को 𝗧𝗼𝗻𝘆 बाप का गुलाम चोद रहा 😎🔥",
        r"Hello hello?? Oxygen aarahi है? रण्डी पुत्र 🧘🏻",
        r"Shut up रंडीके वरना दुनिया यही बोलेगी तेरी बहन 𝗧𝗼𝗻𝘆 👑 बाप से सही chudi 🥵🔥"
    ],
    'breply': [
        r"ᴛᴜ ᴏʀ ᴛᴇʀɪ ᴍᴀᴀ ᴅᴏɴᴏ 𝗧𝗼𝗻𝘆 बाप के ʟɴᴅ sᴇ ᴋᴀʙʜɪ ᴜᴛʜ ɴʜɪ ᴘᴀʏᴇ 😂🔥",
        r"🇮🇳𝐵𝐻𝐴𝑅𝐴𝑇 𝐻𝐴𝑀𝐴𝑅𝐴 𝐷𝐸𝑆𝐻 𝐻 𝐴𝑈𝑅 𝑈𝑆 𝐷𝐸𝑆𝐻 𝑀𝐸 तेरी मां घर घर जाके MOAN करती है ! 🛐",
        r"⋆｡ﾟ☁︎｡𝐂ʏᴜ 𝐑ᴇ मदरचोद 𝗧𝗼𝗻𝘆 बाप के सामने 𝐅ʏᴛᴇʀ 𝐁ᴀɴᴇɢᴀ ⋆𓂃 ོ☼𓂃 😂🔥",
        r"नहीं नहीं तेरी मां को 𝐒ɪʀғ 𝗧𝗼𝗻𝘆 बाप चोद सकता है ִֶָ𓂃 ࣪ ִֶָ👑་༘࿐ sᴀᴍᴊʜᴀ ʀᴀɴᴅɪᴋᴇ ???",
        r"तेरी मां का 𝐒ᴛʏʟɪsʜ भोसड़ा 😱",
        r"𝑻𝒆𝒓𝒚 𝒎𝒂𝒂 𝒓𝒂𝒏𝒅𝒂𝒍 𝒉 𝒃𝒂𝒔 𝒃𝒂𝒂𝒕 𝒌𝒉𝒂𝒕𝒂𝒎 😡🔥",
        r"सोच तेरी बहन को 𝗧𝗼𝗻𝘆 बाप का गुलाम चोद रहा 😎🔥",
        r"Hello hello?? Oxygen aarahi है? रण्डी पुत्र 🧘🏻",
        r"Shut up रंडीके वरना दुनिया यही बोलेगी तेरी बहन 𝗧𝗼𝗻𝘆 👑 बाप से सही chudi 🥵🔥",
        r"ᴛᴜ ᴏʀ ᴛᴇʀɪ ᴍᴀᴀ ᴅᴏɴᴏ 𝗧𝗼𝗻𝘆 बाप के ʟɴᴅ sᴇ ᴋᴀʙʜɪ ᴜᴛʜ ɴʜɪ ᴘᴀʏᴇ 😂🔥",
        r"⋆｡ﾟ☁︎｡𝐂ʏᴜ 𝐑ᴇ मदरचोद 𝗧𝗼𝗻𝘆 बाप के सामने 𝐅ʏᴛᴇʀ 𝐁ᴀɴᴇɢᴀ ⋆𓂃 ོ☼𓂃 😂🔥"
    ],
    'creply': [
        r"नहीं नहीं तेरी मां को 𝐒ɪʀғ 𝗧𝗼𝗻𝘆 बाप चोद सकता है ִֶָ𓂃 ࣪ ִֶָ👑་༘࿐ sᴀᴍᴊʜᴀ ʀᴀɴᴅɪᴋᴇ ???",
        r"तेरी मां का 𝐒ᴛʏʟɪsʜ भोसड़ा 😱",
        r"𝑻𝒆𝒓𝒚 𝒎𝒂𝒂 𝒓𝒂𝒏𝒅𝒂𝒍 𝒉 𝒃𝒂𝒔 𝒃𝒂𝒂𝒕 𝒌𝒉𝒂𝒕𝒂𝒎 😡🔥",
        r"सोच तेरी बहन को 𝗧𝗼𝗻𝘆 बाप का गुलाम चोद रहा 😎🔥",
        r"Hello hello?? Oxygen aarahi है? रण्डी पुत्र 🧘🏻",
        r"Shut up रंडीके वरना दुनिया यही बोलेगी तेरी बहन 𝗧𝗼𝗻𝘆 👑 बाप से सही chudi 🥵🔥",
        r"ᴛᴜ ᴏʀ ᴛᴇʀɪ ᴍᴀᴀ ᴅᴏɴᴏ 𝗧𝗼𝗻𝘆 बाप के ʟɴᴅ sᴇ ᴋᴀʙʜɪ ᴜᴛʜ ɴʜɪ ᴘᴀʏᴇ 😂🔥",
        r"🇮🇳𝐵𝐻𝐴𝑅𝐴𝑇 𝐻𝐴𝑀𝐴𝑅𝐴 𝐷𝐸𝑆𝐻 𝐻 𝐴𝑈𝑅 𝑈𝑆 𝐷𝐸𝑆𝐻 𝑀𝐸 तेरी मां घर घर जाके MOAN करती है ! 🛐",
        r"⋆｡ﾟ☁︎｡𝐂ʏᴜ 𝐑ᴇ मदरचोद 𝗧𝗼𝗻𝘆 बाप के सामने 𝐅ʏᴛᴇʀ 𝐁ᴀɴᴇɢᴀ ⋆𓂃 ོ☼𓂃 😂🔥",
        r"नहीं नहीं तेरी मां को 𝐒ɪʀғ 𝗧𝗼𝗻𝘆 बाप चोद सकता है ִֶָ𓂃 ࣪ ִֶָ👑་༘࿐ sᴀᴍᴊʜᴀ ʀᴀɴᴅɪᴋᴇ ???",
        r"तेरी मां का 𝐒ᴛʏʟɪsʜ भोसड़ा 😱",
        r"𝑻𝒆𝒓𝒚 𝒎𝒂𝒂 𝒓𝒂𝒏𝒅𝒂𝒍 𝒉 𝒃𝒂𝒔 𝒃𝒂𝒂𝒕 𝒌𝒉𝒂𝒕𝒂𝒎 😡🔥"
    ]
}

# ====================== STATE ======================
active_tasks = {}
sudo_users = {OWNER_ID}
sudo_list = [OWNER_ID]
start_time = time.time()
menu_video_id = None
menu_image_id = None
# FIX: per-bot active state instead of single global
is_bot_active = {}  # {bot_id: True/False}

def is_sudo(user_id: int) -> bool:
    return user_id in sudo_users or user_id == OWNER_ID

# FIX: sync function, no reason to be async
def replace_target(text: str, target: str = "") -> str:
    if target:
        text = text.replace("{target}", target).replace("<target>", target).replace("<TARGET>", target.upper())
    return text

# ====================== THEMED ACTION PANELS ======================
def make_start_panel(category: str, command: str, target: str) -> str:
    now = datetime.now()
    return f"""
📓━━━━━━━━━━━━━━━━━━━━📓
   ⚖️ 𝐊𝐈𝐑𝐀 : 𝐄𝐗𝐄𝐂𝐔𝐓𝐈𝐎𝐍 𝐒𝐓𝐀𝐑𝐓𝐄𝐃 ⚖️
📓━━━━━━━━━━━━━━━━━━━━📓
  
  📂 Protocol : {category}
  ✒️ Command  : ~{command.lower()}
  🎯 Target   : {target}
  ⏳ Time     : {now.strftime("%H:%M:%S")}
  🍎 Status   : Active & Bound to Death Note
  
📓━━━━━━━━━━━━━━━━━━━━📓
  "Just as planned... keikaku doori." ♟️
📓━━━━━━━━━━━━━━━━━━━━📓
""".strip()

def make_stop_panel(stopped_name: str, count: int) -> str:
    now = datetime.now()
    return f"""
📓━━━━━━━━━━━━━━━━━━━━📓
   🛑 𝐊𝐈𝐑𝐀 : 𝐄𝐗𝐄𝐂𝐔𝐓𝐈𝐎𝐍 𝐓𝐄𝐑𝐌𝐈𝐍𝐀𝐓𝐄𝐃 🛑
📓━━━━━━━━━━━━━━━━━━━━📓
  
  ⚖️ Verdict  : Execution Halted
  📂 Scope    : {stopped_name.upper()}
  💀 Stopped  : {count} Active Loop(s)
  ⏳ Time     : {now.strftime("%H:%M:%S")}
  
📓━━━━━━━━━━━━━━━━━━━━📓
  "The judgment has ceased... for now." ♟️
📓━━━━━━━━━━━━━━━━━━━━📓
""".strip()

def make_auth_panel(action: str, user_id: int, user_name: str = "") -> str:
    now = datetime.now()
    title = "🍎 𝐒𝐇𝐈𝐍𝐈𝐆𝐀𝐌𝐈 𝐄𝐘𝐄𝐒 𝐆𝐑𝐀𝐍𝐓𝐄𝐃 🍎" if action == "ADD" else "💀 𝐀𝐔𝐓𝐇𝐎𝐑𝐈𝐓𝐘 𝐑𝐄𝐕𝐎𝐊𝐄𝐃 💀"
    status_str = "Granted Apostles Authority" if action == "ADD" else "Purged from Apostles"
    user_str = f"{user_name} (`{user_id}`)" if user_name else f"`{user_id}`"
    return f"""
📓━━━━━━━━━━━━━━━━━━━━📓
   {title}
📓━━━━━━━━━━━━━━━━━━━━📓
  
  👁️ Apostle : {user_str}
  ⚖️ Status  : {status_str}
  ⏳ Time    : {now.strftime("%H:%M:%S")}
  
📓━━━━━━━━━━━━━━━━━━━━📓
  "Those who stand with Kira rule the New World." ♟️
📓━━━━━━━━━━━━━━━━━━━━📓
""".strip()

def make_admin_panel(action: str, user_name: str, target_id: int) -> str:
    now = datetime.now()
    return f"""
📓━━━━━━━━━━━━━━━━━━━━📓
   ⚖️ 𝐊𝐈𝐑𝐀'𝐒 𝐉𝐔𝐃𝐆𝐄𝐌𝐄𝐍𝐓 ⚖️
📓━━━━━━━━━━━━━━━━━━━━📓
  
  💀 Action   : {action}
  👁️ Subject  : {user_name} (`{target_id}`)
  ⏳ Time     : {now.strftime("%H:%M:%S")}
  🍎 Verdict  : Absolute Enforcement
  
📓━━━━━━━━━━━━━━━━━━━━📓
  "No one can escape divine justice." ♟️
📓━━━━━━━━━━━━━━━━━━━━📓
""".strip()

# ====================== STEALTH / HEALTH SYSTEM ======================
async def stealth_health_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    start = time.time()
    temp_msg = await msg.reply_text("🍎 Scanning Host Intel...")
    end = time.time()
    latency = round((end - start) * 1000)

    if psutil:
        cpu_pct = psutil.cpu_percent(interval=0.1)
        mem = psutil.virtual_memory()
        mem_used = round(mem.used / (1024 ** 2), 1)
        mem_total = round(mem.total / (1024 ** 2), 1)
        mem_pct = mem.percent
        disk = psutil.disk_usage('/')
        disk_used = round(disk.used / (1024 ** 3), 1)
        disk_total = round(disk.total / (1024 ** 3), 1)
        disk_pct = disk.percent
        proc_count = len(psutil.pids())
    else:
        cpu_pct = "N/A"
        mem_used, mem_total, mem_pct = "N/A", "N/A", "N/A"
        disk_used, disk_total, disk_pct = "N/A", "N/A", "N/A"
        proc_count = "N/A (psutil missing)"

    up = int(time.time() - start_time)
    hours = up // 3600
    minutes = (up % 3600) // 60
    seconds = up % 60

    panel = f"""
📓━━━━━━━━━━━━━━━━━━━━📓
   ⚖️ 𝐊𝐈𝐑𝐀 : 𝐒𝐓𝐄𝐀𝐋𝐓𝐇 𝐇𝐄𝐀𝐋𝐓𝐇 ⚖️
      "System Diagnostics Under Kira"
📓━━━━━━━━━━━━━━━━━━━━📓

  ⚡ Synapse Latency  : {latency}ms
  ⏳ Uptime           : {hours}h {minutes}m {seconds}s
  
  🍎 CPU Consumption  : {cpu_pct}%
  🧠 Memory (RAM)     : {mem_used}MB / {mem_total}MB ({mem_pct}%)
  💾 Storage (Disk)   : {disk_used}GB / {disk_total}GB ({disk_pct}%)
  ♟️ Active Processes : {proc_count}
  👁️ Active Bot Loops : {len(active_tasks)}
  
📓━━━━━━━━━━━━━━━━━━━━📓
  "All vitals within optimal parameters." ♟️
📓━━━━━━━━━━━━━━━━━━━━📓
""".strip()
    await temp_msg.edit_text(panel)

# ====================== CACHE SYSTEM ======================
def calculate_cache_size():
    total_size = 0
    file_count = 0
    for root, dirs, files in os.walk('.'):
        if '__pycache__' in root:
            for f in files:
                fp = os.path.join(root, f)
                total_size += os.path.getsize(fp)
                file_count += 1
    return file_count, round(total_size / 1024, 2)

async def cache_inspect_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    file_count, size_kb = calculate_cache_size()
    unreachable = gc.collect()
    panel = f"""
📓━━━━━━━━━━━━━━━━━━━━📓
   👁️ 𝐊𝐈𝐑𝐀 : 𝐂𝐀𝐂𝐇𝐄 𝐀𝐔𝐃𝐈𝐓 👁️
      "Tracing Residual Memory"
📓━━━━━━━━━━━━━━━━━━━━📓

  📂 Bytecode Files   : {file_count} __pycache__ items
  💾 Cached Footprint : {size_kb} KB
  🗑️ Garbage Traces   : {unreachable} uncollected objects
  🍎 Host Condition   : Stable
  
📓━━━━━━━━━━━━━━━━━━━━📓
  "Use `~clean` to incinerate all residue." ✒️
📓━━━━━━━━━━━━━━━━━━━━📓
""".strip()
    await update.message.reply_text(panel, parse_mode="Markdown")

async def clean_cache_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cleared_dirs = 0
    for root, dirs, files in os.walk('.'):
        for d in dirs:
            if d == '__pycache__':
                shutil.rmtree(os.path.join(root, d), ignore_errors=True)
                cleared_dirs += 1
    collected = gc.collect()
    panel = f"""
📓━━━━━━━━━━━━━━━━━━━━📓
   🧹 𝐊𝐈𝐑𝐀 : 𝐂𝐀𝐂𝐇𝐄 𝐄𝐑𝐀𝐃𝐈𝐂𝐀𝐓𝐄𝐃 🧹
      "Evidence Incinerated"
📓━━━━━━━━━━━━━━━━━━━━📓

  🗑️ PyCache Purged   : {cleared_dirs} directory blocks
  🧠 RAM Objects Freed: {collected} unreferenced variables
  ⚖️ Status           : Clean Memory State Restored
  
📓━━━━━━━━━━━━━━━━━━━━📓
  "Not a single trace left behind for L." ♟️
📓━━━━━━━━━━━━━━━━━━━━📓
""".strip()
    await update.message.reply_text(panel)

# ====================== MUSIC / PLAY SYSTEM (MP3) ======================
async def play_music(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    # FIX: context.args is None for custom prefix; parse from message text directly
    text = msg.text or ""
    raw_args = text.split()[1:]

    if not raw_args:
        return await msg.reply_text("⚠️ Usage: `~play <song name>`", parse_mode="Markdown")

    if not yt_dlp:
        return await msg.reply_text("❌ `yt-dlp` is not installed! Run `pip install yt-dlp`.")

    query = " ".join(raw_args)
    status_msg = await msg.reply_text(f"🍎 Shinigami hunting track: `{query}`...", parse_mode="Markdown")

    os.makedirs("downloads", exist_ok=True)
    out_template = f"downloads/{int(time.time())}_%(id)s.%(ext)s"

    ydl_opts = {
        'format': 'bestaudio/best',
        'default_search': 'ytsearch1:',
        'noplaylist': True,
        'outtmpl': out_template,
        'postprocessors': [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '192',
        }],
        'quiet': True,
        'no_warnings': True,
    }

    try:
        # FIX: asyncio.to_thread replaces deprecated get_event_loop().run_in_executor
        def download():
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(query, download=True)
                if 'entries' in info:
                    info = info['entries'][0]
                base = ydl.prepare_filename(info)
                mp3_file = os.path.splitext(base)[0] + ".mp3"
                return mp3_file, info.get('title', query), int(info.get('duration', 0)), info.get('uploader', 'Unknown Artist')

        file_path, title, duration, performer = await asyncio.to_thread(download)

        if not os.path.exists(file_path):
            return await status_msg.edit_text("❌ Failed to encode audio to MP3.")

        mins = duration // 60
        secs = duration % 60

        caption = f"""
📓━━━━━━━━━━━━━━━━━━━━📓
   🎵 𝐊𝐈𝐑𝐀 : 𝐒𝐎𝐔𝐍𝐃 𝐎𝐅 𝐉𝐔𝐃𝐆𝐌𝐄𝐍𝐓 🎵
📓━━━━━━━━━━━━━━━━━━━━📓
  
  🎧 Title    : {title}
  🎙️ Artist   : {performer}
  ⏳ Duration : {mins}:{secs:02d}
  🍎 Status   : Extracted & Rendered (192kbps)
  
📓━━━━━━━━━━━━━━━━━━━━📓
  "Hear the melodies of the New World." ♟️
📓━━━━━━━━━━━━━━━━━━━━📓
""".strip()

        with open(file_path, 'rb') as audio_file:
            await msg.reply_audio(
                audio=audio_file,
                title=title,
                performer=performer,
                duration=duration,
                caption=caption
            )

        await status_msg.delete()
        if os.path.exists(file_path):
            os.remove(file_path)

    except Exception as e:
        await status_msg.edit_text(f"❌ Kira Audio Extraction Failed: {str(e)}")

# ====================== GAME OVER ======================
async def gameover(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text or ""
    parts = text.split(" ", 1)
    target = parts[1].strip() if len(parts) > 1 else "Criminal"
    now = datetime.now()
    game_msg = f"""
📓━━━━━━━━━━━━━━━━━━━━📓
  💀 𝐃𝐄𝐀𝐓𝐇 𝐍𝐎𝐓𝐄 : 𝐄𝐗𝐄𝐂𝐔𝐓𝐈𝐎𝐍 💀
📓━━━━━━━━━━━━━━━━━━━━📓
👁️ Subject: {target}
⚖️ Cause: Heart Failure (Kira's Verdict)
⏳ Date: {now.strftime("%d %b %Y")}
⌛ Time: {now.strftime("%H:%M:%S")}
🍎 "I am the God of the New World!"
📓━━━━━━━━━━━━━━━━━━━━📓
"""
    await update.message.reply_text(game_msg.strip())

# ====================== MEDIA CONFIG COMMANDS ======================
async def set_menu_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    reply = update.message.reply_to_message
    if not reply or not (reply.video or reply.animation):
        await update.message.reply_text("⚠️ Reply to a video/GIF with `~setmenuvideo`!")
        return
    global menu_video_id
    if reply.video:
        menu_video_id = reply.video.file_id
    elif reply.animation:
        menu_video_id = reply.animation.file_id
    await update.message.reply_text("📓 Kira Domain Video Set Successfully! 🍎")

async def rm_menu_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global menu_video_id
    if menu_video_id is None:
        await update.message.reply_text("⚠️ No video set!")
        return
    menu_video_id = None
    await update.message.reply_text("🗑️ Main menu video removed.")

async def set_menu_img(update: Update, context: ContextTypes.DEFAULT_TYPE):
    reply = update.message.reply_to_message
    if not reply or not reply.photo:
        await update.message.reply_text("⚠️ Reply to a photo with `~setmenuimg`!")
        return
    global menu_image_id
    menu_image_id = reply.photo[-1].file_id
    await update.message.reply_text("📓 Sub-Menu Death Note Photo Set Successfully! ✒️")

async def rm_menu_img(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global menu_image_id
    if menu_image_id is None:
        await update.message.reply_text("⚠️ No menu image set!")
        return
    menu_image_id = None
    await update.message.reply_text("🗑️ Sub-menus image removed.")

# ====================== PIN / UNPIN ======================
async def pin_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.reply_to_message:
        return await update.message.reply_text("⚠️ Reply to a message to pin it!")
    try:
        await update.message.reply_to_message.pin()
        await update.message.reply_text("""
📓━━━━━━━━━━━━━━━━━━━━📓
  📌 𝐏𝐈𝐍𝐍𝐄𝐃 𝐁𝐘 𝐊𝐈𝐑𝐀'𝐒 𝐃𝐄𝐂𝐑𝐄𝐄
📓━━━━━━━━━━━━━━━━━━━━📓
  ⚖️ Message permanently fixed to chat memory.
""".strip())
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}")

async def unpin_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.reply_to_message:
        return await update.message.reply_text("⚠️ Reply to a message to unpin it!")
    try:
        await update.message.reply_to_message.unpin()
        await update.message.reply_text("""
📓━━━━━━━━━━━━━━━━━━━━📓
  📌 𝐔𝐍𝐏𝐈𝐍𝐍𝐄𝐃
📓━━━━━━━━━━━━━━━━━━━━📓
  ⚖️ Message released from pin hierarchy.
""".strip())
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}")

async def unpin_all_messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        await update.effective_chat.unpin_all_messages()
        await update.message.reply_text("""
📓━━━━━━━━━━━━━━━━━━━━📓
  📌 𝐀𝐋𝐋 𝐏𝐈𝐍𝐒 𝐄𝐑𝐀𝐃𝐈𝐂𝐀𝐓𝐄𝐃
📓━━━━━━━━━━━━━━━━━━━━📓
  ⚖️ Chat cleared of all pinned decrees.
""".strip())
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}")

# ====================== MUTE / UNMUTE ======================
async def mute(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.reply_to_message:
        return
    user = update.message.reply_to_message.from_user
    try:
        await context.bot.restrict_chat_member(
            chat_id=update.effective_chat.id,
            user_id=user.id,
            permissions=ChatPermissions(can_send_messages=False)
        )
        await update.message.reply_text(make_admin_panel("SILENCED / MUTED 🔇", user.first_name, user.id), parse_mode="Markdown")
    except Exception as e:
        await update.message.reply_text(f"❌ {e}")

async def unmute(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.reply_to_message:
        return
    user = update.message.reply_to_message.from_user
    try:
        await context.bot.restrict_chat_member(
            chat_id=update.effective_chat.id,
            user_id=user.id,
            permissions=ChatPermissions(can_send_messages=True, can_send_media_messages=True, can_send_other_messages=True)
        )
        await update.message.reply_text(make_admin_panel("VOICE RESTORED / UNMUTED 🔊", user.first_name, user.id), parse_mode="Markdown")
    except Exception as e:
        await update.message.reply_text(f"❌ {e}")

async def gcmute(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        await context.bot.set_chat_permissions(
            chat_id=update.effective_chat.id,
            permissions=ChatPermissions(can_send_messages=False)
        )
        await update.message.reply_text("""
📓━━━━━━━━━━━━━━━━━━━━📓
  🔇 𝐆𝐑𝐎𝐔𝐏 𝐃𝐎𝐌𝐀𝐈𝐍 𝐌𝐔𝐓𝐄𝐃
📓━━━━━━━━━━━━━━━━━━━━📓
  ⚖️ Absolute silence ordered by Kira.
""".strip())
    except Exception as e:
        await update.message.reply_text(f"❌ {e}")

async def gcunmute(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        await context.bot.set_chat_permissions(
            chat_id=update.effective_chat.id,
            permissions=ChatPermissions(can_send_messages=True, can_send_media_messages=True, can_send_other_messages=True)
        )
        await update.message.reply_text("""
📓━━━━━━━━━━━━━━━━━━━━📓
  🔊 𝐆𝐑𝐎𝐔𝐏 𝐃𝐎𝐌𝐀𝐈𝐍 𝐔𝐍𝐌𝐔𝐓𝐄𝐃
📓━━━━━━━━━━━━━━━━━━━━📓
  ⚖️ Freedom of speech restored by Kira.
""".strip())
    except Exception as e:
        await update.message.reply_text(f"❌ {e}")

# ====================== OTHER UTILS ======================
async def stopall(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    removed = 0
    for key in list(active_tasks.keys()):
        if str(chat_id) in key:
            task = active_tasks.pop(key, None)
            if task and not task.done():
                task.cancel()
                removed += 1
    await update.message.reply_text(make_stop_panel("ALL ACTIVE VERDICTS", removed))

async def add_sudo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID:
        return
    user_name = ""
    if update.message.reply_to_message:
        user_id = update.message.reply_to_message.from_user.id
        user_name = update.message.reply_to_message.from_user.first_name
    elif context.args:
        try:
            user_id = int(context.args[0])
        except ValueError:
            return await update.message.reply_text("❌ Invalid ID!")
    else:
        # parse from message text for custom prefix
        parts = (update.message.text or "").split()
        if len(parts) > 1:
            try:
                user_id = int(parts[1])
            except ValueError:
                return await update.message.reply_text("❌ Invalid ID!")
        else:
            return await update.message.reply_text("Usage: ~sudo <user_id> ya reply karein.")

    sudo_users.add(user_id)
    if user_id not in sudo_list:
        sudo_list.append(user_id)
    await update.message.reply_text(make_auth_panel("ADD", user_id, user_name), parse_mode="Markdown")

async def remove_sudo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID:
        return
    user_name = ""
    if update.message.reply_to_message:
        user_id = update.message.reply_to_message.from_user.id
        user_name = update.message.reply_to_message.from_user.first_name
    elif context.args:
        try:
            user_id = int(context.args[0])
        except ValueError:
            return await update.message.reply_text("❌ Invalid ID!")
    else:
        parts = (update.message.text or "").split()
        if len(parts) > 1:
            try:
                user_id = int(parts[1])
            except ValueError:
                return await update.message.reply_text("❌ Invalid ID!")
        else:
            return await update.message.reply_text("Usage: ~dsudo <user_id> ya reply karein.")

    sudo_users.discard(user_id)
    if user_id in sudo_list:
        sudo_list.remove(user_id)
    await update.message.reply_text(make_auth_panel("REMOVE", user_id, user_name), parse_mode="Markdown")

async def ban_unban(update: Update, context: ContextTypes.DEFAULT_TYPE, ban_action: bool = True):
    if not update.message.reply_to_message:
        return
    user = update.message.reply_to_message.from_user
    chat = update.effective_chat
    try:
        if ban_action:
            await chat.ban_member(user.id)
            await update.message.reply_text(make_admin_panel("SENTENCED TO DEATH / BANNED 💀", user.first_name, user.id), parse_mode="Markdown")
        else:
            await chat.unban_member(user.id)
            await update.message.reply_text(make_admin_panel("SPARED BY MERCY / UNBANNED ⚖️", user.first_name, user.id), parse_mode="Markdown")
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}")

async def delmsg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.reply_to_message:
        return
    try:
        await update.message.reply_to_message.delete()
        await update.message.reply_text("✒️ Evidence eradicated from history.")
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}")

async def sudolist_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    apostles = "\n".join([f"  • `{uid}`" for uid in sudo_users])
    panel = f"""
📓━━━━━━━━━━━━━━━━━━━━📓
   👁️ 𝐊𝐈𝐑𝐀'𝐒 𝐀𝐏𝐎𝐒𝐓𝐋𝐄𝐒 (𝐒𝐔𝐃𝐎 𝐋𝐈𝐒𝐓) 👁️
📓━━━━━━━━━━━━━━━━━━━━📓
  
  Total Apostles : {len(sudo_users)}
{apostles}

📓━━━━━━━━━━━━━━━━━━━━📓
  "Those who enforce the divine will." ♟️
📓━━━━━━━━━━━━━━━━━━━━📓
""".strip()
    await update.message.reply_text(panel, parse_mode="Markdown")

async def adminlist_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        admins = await update.effective_chat.get_administrators()
        admin_names = [f"  • ♟️ {admin.user.first_name} (`{admin.user.id}`)" for admin in admins]
        panel = f"""
📓━━━━━━━━━━━━━━━━━━━━📓
   ⚖️ 𝐒𝐏𝐊 / 𝐓𝐀𝐒𝐊 𝐅𝐎𝐑𝐂𝐄 (𝐀𝐃𝐌𝐈𝐍𝐒) ⚖️
📓━━━━━━━━━━━━━━━━━━━━📓
  
{chr(10).join(admin_names)}

📓━━━━━━━━━━━━━━━━━━━━📓
  "Watching every move from the shadows." 👁️
📓━━━━━━━━━━━━━━━━━━━━📓
""".strip()
        await update.message.reply_text(panel, parse_mode="Markdown")
    except Exception as e:
        await update.message.reply_text(f"Cannot fetch: {e}")

async def refresh_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global active_tasks, sudo_users, sudo_list, start_time, menu_video_id, menu_image_id, is_bot_active
    for key, task in list(active_tasks.items()):
        if not task.done():
            task.cancel()
    active_tasks.clear()
    sudo_users = {OWNER_ID}
    sudo_list = [OWNER_ID]
    start_time = time.time()
    menu_video_id = None
    menu_image_id = None
    is_bot_active = {}
    panel = """
📓━━━━━━━━━━━━━━━━━━━━📓
   🔄 𝐊𝐄𝐈𝐊𝐀𝐊𝐔 𝐅𝐔𝐋𝐋 𝐑𝐄𝐒𝐄𝐓 🔄
📓━━━━━━━━━━━━━━━━━━━━📓
  
  🍎 Verdict : All traces incinerated
  ⚖️ Status  : Fresh canvas prepared
  💀 State   : Everything according to keikaku
  
📓━━━━━━━━━━━━━━━━━━━━📓
""".strip()
    await update.message.reply_text(panel)

async def status_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    nc = sum(1 for k in active_tasks if "_nc" in k or any(f"_{x}" in k for x in NC_TEXTS))
    spam = sum(1 for k in active_tasks if any(f"_{x}" in k for x in SPAM_TEXTS))
    swipe = sum(1 for k in active_tasks if any(f"_{x}" in k for x in SWIPE_TEXTS))
    reply = sum(1 for k in active_tasks if any(f"_{x}" in k for x in REPLY_TEXTS))
    video_set = "Active 🍎" if menu_video_id else "None 💀"
    img_set = "Active 📓" if menu_image_id else "None 💀"

    await update.message.reply_text(
        f"**⚖️ KIRA PROTOCOL STATUS**\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"📓 Title Rewrite (NC): {nc}\n"
        f"✒️ Script Execution (Spam): {spam}\n"
        f"⚡ Targeted Strikes (Swipe): {swipe}\n"
        f"👁️ Eye Protocol (Reply): {reply}\n"
        f"🎬 Death Note Clip: {video_set}\n"
        f"🖼️ Shinigami Portrait: {img_set}\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"♟️ Total Moves: {len(active_tasks)}"
    )

# ====================== CORE LOOP FUNCTIONS (PREVIOUSLY MISSING) ======================

async def nc_loop(context, bot_id: str, chat_id: int, cmd: str, target: str):
    """Send NC (name changer) texts in a continuous loop."""
    texts = NC_TEXTS.get(cmd, [])
    if not texts:
        return
    idx = 0
    key = f"{bot_id}_{chat_id}_{cmd}"
    while key in active_tasks:
        text = replace_target(texts[idx % len(texts)], target)
        try:
            await context.bot.send_message(chat_id=chat_id, text=text)
        except RetryAfter as e:
            await asyncio.sleep(e.retry_after)
            continue
        except Exception:
            pass
        idx += 1
        delay = DELAYS.get('nc', 0)
        if delay > 0:
            await asyncio.sleep(delay)
        else:
            await asyncio.sleep(0)

async def spam_loop(context, bot_id: str, chat_id: int, cmd: str, target: str):
    """Send SPAM texts in a continuous loop."""
    texts = SPAM_TEXTS.get(cmd, [])
    if not texts:
        return
    idx = 0
    key = f"{bot_id}_{chat_id}_{cmd}"
    while key in active_tasks:
        text = replace_target(texts[idx % len(texts)], target)
        try:
            await context.bot.send_message(chat_id=chat_id, text=text)
        except RetryAfter as e:
            await asyncio.sleep(e.retry_after)
            continue
        except Exception:
            pass
        idx += 1
        delay = DELAYS.get('spam', 0)
        if delay > 0:
            await asyncio.sleep(delay)
        else:
            await asyncio.sleep(0)

async def swipe_loop(context, bot_id: str, chat_id: int, reply_to: int, cmd: str, target: str, is_reply: bool):
    """Reply to a specific message repeatedly with swipe or reply texts."""
    if is_reply:
        texts = REPLY_TEXTS.get(cmd, [])
        delay_key = 'reply'
    else:
        texts = SWIPE_TEXTS.get(cmd, [])
        delay_key = 'swipe'

    if not texts:
        return
    idx = 0
    key = f"{bot_id}_{chat_id}_{reply_to}_{cmd}"
    while key in active_tasks:
        text = replace_target(texts[idx % len(texts)], target)
        try:
            await context.bot.send_message(
                chat_id=chat_id,
                text=text,
                reply_to_message_id=reply_to
            )
        except RetryAfter as e:
            await asyncio.sleep(e.retry_after)
            continue
        except Exception:
            pass
        idx += 1
        delay = DELAYS.get(delay_key, 0)
        if delay > 0:
            await asyncio.sleep(delay)
        else:
            await asyncio.sleep(0)

# ====================== LIGHT YAGAMI THEMED MENUS ======================
MAIN_INDEX_MENU = """
📓━━━━━━━━━━━━━━━━━━━━📓
   ⚖️ 𝐋𝐈𝐆𝐇𝐓 𝐘𝐀𝐆𝐀𝐌𝐈 ╳ 𝐊𝐈𝐑𝐀 ⚖️
      "𝐈 𝐖𝐢𝐥𝐥 𝐁𝐞𝐜𝐨𝐦𝐞 𝐓𝐡𝐞 𝐆𝐨𝐝 
        𝐎𝐟 𝐓𝐡𝐞 𝐍𝐞𝐰 𝐖𝐨𝐫𝐥𝐝"
📓━━━━━━━━━━━━━━━━━━━━📓

   ♟️ ~menu 1 : 𝐊𝐄𝐈𝐊𝐀𝐊𝐔 (Core & Audio)
   📓 ~menu 2 : 𝐃𝐄𝐀𝐓𝐇 𝐍𝐎𝐓𝐄 (NC)
   ✒️ ~menu 3 : 𝐉𝐔𝐃𝐆𝐄𝐌𝐄𝐍𝐓 (Spam)
   👁️ ~menu 4 : 𝐒𝐇𝐈𝐍𝐈𝐆𝐀𝐌𝐈 𝐄𝐘𝐄𝐒
   ⚖️ ~menu 5 : 𝐓𝐀𝐒𝐊 𝐅𝐎𝐑𝐂𝐄 (Auth)
   🍎 ~menu 6 : 𝐋 𝐈𝐍𝐕𝐄𝐒𝐓𝐈𝐆𝐀𝐓𝐈𝐎𝐍
   📜 ~fmenu  : 𝐅𝐔𝐋𝐋 𝐑𝐄𝐆𝐈𝐒𝐓𝐑𝐘

📓━━━━━━━━━━━━━━━━━━━━📓
  "All according to keikaku." ♟️
   • Powered By 𝗧𝐨𝐧𝘆 Syndicate •
📓━━━━━━━━━━━━━━━━━━━━📓
"""

MENU_1_CORE = """
╭━━〔 ♟️ 𝐌𝐄𝐍𝐔 𝟏 : 𝐊𝐄𝐈𝐊𝐀𝐊𝐔 〕━━╮
│
│ ⚡ ~light          - Awaken Kira (Bot ON)
│ 🌙 ~dak            - Dormant Mode (Bot OFF)
│ 🎵 ~play <song>    - Stream MP3 Audio Track
│ 🩺 ~stealth        - Host Hardware Diagnostics
│ 👁️ ~cache          - Audit Residual Memory
│ 🧹 ~clean          - Purge Buffer & PyCache
│ 🍎 ~ping           - Synapse Latency
│ ⚖️ ~status         - Active Kira Loops
│ ⏳ ~uptime         - Domain Runtime
│ 🔄 ~refresh        - Wipe All Keikaku
│
│ ── ✒️ DELAY CALIBRATION ──
│ ⏳ ~setdelaync <sec>
│ ⏳ ~setdelayspam <sec>
│ ⏳ ~setdelayswipe <sec>
│ ⏳ ~setdelayreply <sec>
│
│ ── 🎬 ARTIFACT CONFIG ──
│ 📓 ~setmenuvideo   - Bind Kira Clip
│ 🗑️ ~rmvid          - Discard Video
│ 🖼️ ~setmenuimg     - Bind Ryuk Portrait
│ 🗑️ ~rmimg          - Discard Image
│
╰━━━━━━━━━━━━━━━━━━━━━━━╯
"""

MENU_2_NC = """
╭━━〔 📓 𝐌𝐄𝐍𝐔 𝟐 : 𝐃𝐄𝐀𝐓𝐇 𝐍𝐎𝐓𝐄 〕━━╮
│   "The name written in this note
│           shall die."
│
│ ✒️ ~snc <target>    / ~dsnc
│ ✒️ ~ssnc <target>   / ~dssnc
│ ✒️ ~fnc <target>    / ~dfnc
│ ✒️ ~cnc <target>    / ~dcnc
│ ✒️ ~bnc <target>    / ~dbnc
│ ✒️ ~sgcnc <target>  / ~dsgcnc
│
│ 💀 ~dallnc         - Cease All NC
│
╰━━━━━━━━━━━━━━━━━━━━━━━╯
"""

MENU_3_SPAM = """
╭━━〔 ✒️ 𝐌𝐄𝐍𝐔 𝟑 : 𝐉𝐔𝐃𝐆𝐄𝐌𝐄𝐍𝐓 〕━━╮
│  "Eliminating the rotten vermin."
│
│ 🩸 ~bspam <target>  / ~dbspam
│ 🩸 ~aspam <target>  / ~daspam
│ 🩸 ~sspam <target>  / ~dsspam
│ 🩸 ~fspam <target>  / ~dfspam
│ 🩸 ~gspam <target>  / ~dgspam
│ 🩸 ~rspam <target>  / ~drspam
│
│ ⚖️ ~dallspam       - Stop Purge
│
╰━━━━━━━━━━━━━━━━━━━━━━━╯
"""

MENU_4_TARGET = """
╭━━〔 👁️ 𝐌𝐄𝐍𝐔 𝟒 : 𝐒𝐇𝐈𝐍𝐈𝐆𝐀𝐌𝐈 𝐄𝐘𝐄𝐒 〕━━╮
│  "I can see your name and lifespan."
│
│ 🎯 ~aswipe         / ~daswipe
│ 🎯 ~fswipe         / ~dfswipe
│ 🎯 ~rrswipe        / ~drrswipe
│ 🎯 ~cswipe         / ~dcswipe
│ 💀 ~dallswipe
│
│ ── 🍎 RETALIATION PROTOCOL ──
│ ⚡ ~rreply         / ~drreply
│ ⚡ ~breply         / ~dbreply
│ ⚡ ~creply         / ~dcreply
│ ⚖️ ~dallreply
│
╰━━━━━━━━━━━━━━━━━━━━━━━╯
"""

MENU_5_AUTH = """
╭━━〔 ⚖️ 𝐌𝐄𝐍𝐔 𝟓 : 𝐓𝐀𝐒𝐊 𝐅𝐎𝐑𝐂𝐄 〕━━╮
│    "Justice will prevail, no matter
│               what!"
│
│ 👑 ~sudo <id/reply> - Grant Eyes
│ 💀 ~dsudo <id>      - Revoke Eyes
│ 📜 ~sudolist        - View Apostles
│ 🚫 ~ban / ~unban    - Exile Criminal
│ 🔇 ~mute / ~unmute  - Cut Off Tongue
│ 🛑 ~gcmute / ~gcunmute
│ 🗑️ ~delmsg          - Incinerate Evidence
│ 📌 ~pin / ~unpin / ~revpin
│ 💀 ~gameover <tgt>  - Heart Failure
│ 🛑 ~stopall         - Absolute Zero
│
╰━━━━━━━━━━━━━━━━━━━━━━━╯
"""

MENU_6_GHOST = """
╭━━〔 🍎 𝐌𝐄𝐍𝐔 𝟔 : 𝐋 𝐈𝐍𝐕𝐄𝐒𝐓𝐈𝐆𝐀𝐓𝐈𝐎𝐍 〕━━╮
│   "L, do you know Gods of Death 
│          love apples?"
│
│ 👁️ ~adminlist      - Scan SPK Admins
│ 📓 ~banlist        - Death Registry
│ 🛑 ~stopall        - Abort All Operations
│ 🔄 ~refresh        - Erase All Traces
│
╰━━━━━━━━━━━━━━━━━━━━━━━╯
"""

FMENU_ALL = """
╭━━〔 📜 𝐓𝐇𝐄 𝐂𝐎𝐌𝐏𝐋𝐄𝐓𝐄 𝐃𝐄𝐀𝐓𝐇 𝐑𝐄𝐆𝐈𝐒𝐓𝐑𝐘 〕━━╮
│
│ ⚡ SYSTEM: ~light, ~dak, ~stealth, ~cache, ~clean, ~play
│ 📓 NC: ~snc, ~ssnc, ~fnc, ~cnc, ~bnc, ~sgcnc, ~dallnc
│ ✒️ SPAM: ~bspam, ~aspam, ~sspam, ~fspam, ~gspam, ~rspam, ~dallspam
│ 🎯 SWIPE: ~aswipe, ~fswipe, ~rrswipe, ~cswipe, ~dallswipe
│ ⚡ REPLY: ~rreply, ~breply, ~creply, ~dallreply
│ 👁️ APOSTLES: ~sudo, ~dsudo, ~sudolist
│ ⚖️ ENFORCEMENT: ~ban, ~unban, ~mute, ~unmute, ~gcmute, ~gcunmute, ~delmsg
│ 📌 PINS: ~pin, ~unpin, ~revpin
│ ♟️ ARTIFACTS: ~ping, ~status, ~uptime, ~refresh, ~setmenuvideo, ~rmvid, ~setmenuimg, ~rmimg, ~stopall
│
╰━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╯
"""

async def send_main_menu_response(msg, text: str):
    global menu_video_id
    if menu_video_id:
        try:
            return await msg.reply_video(video=menu_video_id, caption=text)
        except Exception:
            return await msg.reply_text(text)
    else:
        return await msg.reply_text(text)

async def send_submenu_response(msg, text: str):
    global menu_image_id
    if menu_image_id:
        try:
            return await msg.reply_photo(photo=menu_image_id, caption=text)
        except Exception:
            return await msg.reply_text(text)
    else:
        return await msg.reply_text(text)

# ====================== MAIN HANDLER ======================
async def make_handler(bot_id: str):
    async def handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not update.message or not update.message.text:
            return

        text = update.message.text
        if not text.startswith('~'):
            return

        msg = update.message
        cmd_parts = text.lower().strip().split()
        cmd = cmd_parts[0][1:] if cmd_parts else ""
        args = cmd_parts[1:] if len(cmd_parts) > 1 else []

        # ================= POWER CONTROLS (~light / ~dak) =================
        if cmd == "light":
            if not is_sudo(update.effective_user.id):
                return await msg.reply_text("⚖️ Only Kira has the authority to awaken the Death Note.")
            is_bot_active[bot_id] = True
            panel = """
📓━━━━━━━━━━━━━━━━━━━━📓
   ⚡ 𝐊𝐈𝐑𝐀 𝐇𝐀𝐒 𝐀𝐖𝐀𝐊𝐄𝐍𝐄𝐃 (𝐁𝐎𝐓 𝐎𝐍) ⚡
📓━━━━━━━━━━━━━━━━━━━━📓
  
  👁️ Divine Will : Active
  🍎 Domain Status: Full Execution Mode
  ⚖️ Verdict      : The New World is in Motion
  
📓━━━━━━━━━━━━━━━━━━━━📓
  "I will show them the justice of God!" ♟️
📓━━━━━━━━━━━━━━━━━━━━📓
""".strip()
            return await msg.reply_text(panel)

        if cmd == "dak":
            if not is_sudo(update.effective_user.id):
                return await msg.reply_text("⚖️ Only Kira has the authority to silence the domain.")
            is_bot_active[bot_id] = False

            chat_id = msg.chat.id
            removed = 0
            for key in list(active_tasks.keys()):
                if str(chat_id) in key and key.startswith(bot_id):
                    task = active_tasks.pop(key, None)
                    if task and not task.done():
                        task.cancel()
                        removed += 1

            panel = f"""
📓━━━━━━━━━━━━━━━━━━━━📓
   🌙 𝐊𝐈𝐑𝐀 𝐇𝐀𝐒 𝐆𝐎𝐍𝐄 𝐃𝐎𝐑𝐌𝐀𝐍𝐓 (𝐁𝐎𝐓 𝐎𝐅𝐅) 🌙
📓━━━━━━━━━━━━━━━━━━━━📓
  
  👁️ Domain State : Inactive / Sleeping
  🛑 Action       : All {removed} Active Loops Terminated
  ⏳ Reactivation : Send `~light` to re-awaken
  
📓━━━━━━━━━━━━━━━━━━━━📓
  "Hiding in the shadows until the next move." ♟️
📓━━━━━━━━━━━━━━━━━━━━📓
""".strip()
            return await msg.reply_text(panel)

        # BOT INACTIVE CHECK (per-bot)
        if not is_bot_active.get(bot_id, True):
            return

        # PUBLIC MENU COMMANDS
        if cmd == "menu":
            if args:
                sub = args[0]
                if sub == "1":
                    return await send_submenu_response(msg, MENU_1_CORE)
                elif sub == "2":
                    return await send_submenu_response(msg, MENU_2_NC)
                elif sub == "3":
                    return await send_submenu_response(msg, MENU_3_SPAM)
                elif sub == "4":
                    return await send_submenu_response(msg, MENU_4_TARGET)
                elif sub == "5":
                    return await send_submenu_response(msg, MENU_5_AUTH)
                elif sub == "6":
                    return await send_submenu_response(msg, MENU_6_GHOST)
            return await send_main_menu_response(msg, MAIN_INDEX_MENU)

        if cmd == "menu1":
            return await send_submenu_response(msg, MENU_1_CORE)
        elif cmd == "menu2":
            return await send_submenu_response(msg, MENU_2_NC)
        elif cmd == "menu3":
            return await send_submenu_response(msg, MENU_3_SPAM)
        elif cmd == "menu4":
            return await send_submenu_response(msg, MENU_4_TARGET)
        elif cmd == "menu5":
            return await send_submenu_response(msg, MENU_5_AUTH)
        elif cmd == "menu6":
            return await send_submenu_response(msg, MENU_6_GHOST)
        elif cmd == "fmenu":
            return await send_submenu_response(msg, FMENU_ALL)

        # PUBLIC AUDIO STREAM COMMAND
        if cmd == "play":
            return await play_music(update, context)

        # PUBLIC UTILS
        if cmd == "ping":
            start = time.time()
            temp_msg = await msg.reply_text("🍎 Measuring Reflex...")
            end = time.time()
            latency = round((end - start) * 1000)
            ping_panel = f"""
📓━━━━━━━━━━━━━━━━━━━━📓
   ⚖️ 𝐊𝐈𝐑𝐀 : 𝐒𝐘𝐍𝐀𝐏𝐒𝐄 𝐒𝐏𝐄𝐄𝐃 ⚖️
📓━━━━━━━━━━━━━━━━━━━━📓
  
  🍎 Keikaku Latency : {latency}ms
  ⚡ Shinigami Reflex : Ultra Fast
  ⏳ Status           : Divine Synchronization
  
📓━━━━━━━━━━━━━━━━━━━━📓
  "I'll take a potato chip... 
         AND EAT IT!" ♟️
📓━━━━━━━━━━━━━━━━━━━━📓
""".strip()
            return await temp_msg.edit_text(ping_panel)

        if cmd == "uptime":
            up = int(time.time() - start_time)
            hours = up // 3600
            minutes = (up % 3600) // 60
            seconds = up % 60
            return await msg.reply_text(f"⏳ Reign of Kira: {hours}h {minutes}m {seconds}s")

        # SUDO ONLY COMMANDS
        if not is_sudo(update.effective_user.id):
            return await msg.reply_text("⚖️ Only Kira has the authority.")

        chat_id = msg.chat.id

        # STEALTH & CACHE COMMANDS
        if cmd == "stealth":
            return await stealth_health_panel(update, context)
        if cmd == "cache":
            return await cache_inspect_panel(update, context)
        if cmd == "clean":
            return await clean_cache_panel(update, context)

        # MENU MEDIA COMMANDS
        if cmd == "setmenuvideo":
            return await set_menu_video(update, context)
        if cmd == "rmvid":
            return await rm_menu_video(update, context)
        if cmd == "setmenuimg":
            return await set_menu_img(update, context)
        if cmd == "rmimg":
            return await rm_menu_img(update, context)

        # GAME OVER & STOP
        if cmd == "gameover":
            return await gameover(update, context)
        if cmd == "stopall":
            return await stopall(update, context)

        # PIN
        if cmd == "pin":
            return await pin_message(update, context)
        if cmd == "unpin":
            return await unpin_message(update, context)
        if cmd == "revpin":
            return await unpin_all_messages(update, context)

        # START LOOPS
        if cmd in NC_TEXTS or cmd in SPAM_TEXTS or cmd in SWIPE_TEXTS or cmd in REPLY_TEXTS:
            target = " ".join(args) if args else msg.from_user.first_name
            is_swipe = cmd in SWIPE_TEXTS
            is_reply = cmd in REPLY_TEXTS

            if is_swipe or is_reply:
                if not msg.reply_to_message:
                    return await msg.reply_text("Reply to a message!")
                reply_to = msg.reply_to_message.message_id
                target_name = msg.reply_to_message.from_user.first_name if msg.reply_to_message.from_user else target
                key = f"{bot_id}_{chat_id}_{reply_to}_{cmd}"
                if key in active_tasks:
                    return await msg.reply_text("⚠️ Already Running!")
                task = asyncio.create_task(swipe_loop(context, bot_id, chat_id, reply_to, cmd, target_name, is_reply))
                category_name = "TARGET REPLY" if is_reply else "SWIPE RAID"
            elif cmd in SPAM_TEXTS:
                key = f"{bot_id}_{chat_id}_{cmd}"
                if key in active_tasks:
                    return await msg.reply_text("⚠️ Already Running!")
                task = asyncio.create_task(spam_loop(context, bot_id, chat_id, cmd, target))
                category_name = "SPAM PURGE"
            else:
                key = f"{bot_id}_{chat_id}_{cmd}"
                if key in active_tasks:
                    return await msg.reply_text("⚠️ Already Running!")
                task = asyncio.create_task(nc_loop(context, bot_id, chat_id, cmd, target))
                category_name = "NAME CHANGER (NC)"

            active_tasks[key] = task
            await msg.reply_text(make_start_panel(category_name, cmd, target))

        # STOP LOOPS
        elif cmd.startswith('d'):
            removed = 0
            base_cmd = cmd.replace('d', '', 1)

            if cmd in ['dallnc', 'dallspam', 'dallswipe', 'dallreply']:
                category = cmd.replace('dall', '')
                for key in list(active_tasks.keys()):
                    # FIX: use _{category} to avoid false partial matches (e.g. "nc" matching "bnc")
                    if f"_{category}" in key and str(chat_id) in key:
                        task = active_tasks.pop(key, None)
                        if task and not task.done():
                            task.cancel()
                            removed += 1
                await msg.reply_text(make_stop_panel(f"ALL {category.upper()}", removed))
            else:
                for key in list(active_tasks.keys()):
                    if key.endswith(f"_{base_cmd}") and str(chat_id) in key:
                        task = active_tasks.pop(key, None)
                        if task and not task.done():
                            task.cancel()
                            removed += 1
                await msg.reply_text(make_stop_panel(f"COMMAND ~{base_cmd.upper()}", removed))

        # DELAYS
        elif cmd.startswith("setdelay"):
            try:
                if not args:
                    return await msg.reply_text("Usage: ~setdelaync 0.001")
                sec = float(args[0])
                if sec < 0:
                    sec = 0
                dtype = cmd.replace("setdelay", "")
                if dtype in DELAYS:
                    DELAYS[dtype] = sec
                    await msg.reply_text(f"""
📓━━━━━━━━━━━━━━━━━━━━📓
  ⏳ 𝐓𝐈𝐌𝐈𝐍𝐆 𝐂𝐀𝐋𝐈𝐁𝐑𝐀𝐓𝐄𝐃
📓━━━━━━━━━━━━━━━━━━━━📓
  ⚖️ Module : {dtype.upper()}
  ⚡ Delay  : {sec}s
""".strip())
                else:
                    await msg.reply_text(f"❌ Invalid! Use: nc, spam, swipe, reply")
            except Exception:
                await msg.reply_text("❌ Invalid number!")

        # SUDO
        elif cmd == "sudo":
            await add_sudo(update, context)
        elif cmd == "dsudo":
            await remove_sudo(update, context)
        elif cmd == "sudolist":
            await sudolist_cmd(update, context)

        # ADMIN
        elif cmd == "ban":
            await ban_unban(update, context, True)
        elif cmd == "unban":
            await ban_unban(update, context, False)
        elif cmd == "mute":
            await mute(update, context)
        elif cmd == "unmute":
            await unmute(update, context)
        elif cmd == "gcmute":
            await gcmute(update, context)
        elif cmd == "gcunmute":
            await gcunmute(update, context)
        elif cmd == "delmsg":
            await delmsg(update, context)

        # STATUS / LISTS
        elif cmd == "adminlist":
            await adminlist_cmd(update, context)
        elif cmd == "banlist":
            await update.message.reply_text("📓 Check Death Note manually.")
        elif cmd == "status":
            await status_cmd(update, context)
        elif cmd == "refresh":
            await refresh_cmd(update, context)

    return handler

# ====================== RUN MULTI BOT ======================
async def run_multibot():
    applications = []

    for i, token in enumerate(BOT_TOKENS):
        if not token or "YOUR_BOT_TOKEN" in token:
            continue

        try:
            app = Application.builder().token(token).build()
            handler = await make_handler(str(i))
            app.add_handler(MessageHandler(
                (filters.TEXT & filters.ChatType.GROUPS & (filters.Regex(r'^~'))),
                handler
            ))

            await app.initialize()
            await app.start()
            await app.updater.start_polling()

            applications.append(app)
            print(f"📓 Shinigami {i+1} Awakened - {token[-8:]}")

        except Exception as e:
            print(f"❌ Shinigami {i+1} failed: {e}")

    if applications:
        print("\n🍎 Kira's New World Order is Live! Press Ctrl+C to terminate.\n")
        try:
            while True:
                await asyncio.sleep(1)
        except KeyboardInterrupt:
            print("\n👋 Erasing domain...")
            for app in applications:
                await app.updater.stop()
                await app.stop()
                await app.shutdown()
            print("⚖️ Shut down complete.")
    else:
        print("❌ No bots started!")

if __name__ == '__main__':
    print("📓 DEATH NOTE PROTOCOL INITIATED")
    print("⚖️ THEME: LIGHT YAGAMI / KIRA")
    print("⚡ PREFIX: ~")
    print("=" * 50)
    try:
        asyncio.run(run_multibot())
    except KeyboardInterrupt:
        print("\n👋 Terminated.")
    except Exception as e:
        print(f"❌ Error: {e}")
