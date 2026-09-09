#!/usr/bin/env python3
# language: Python 3, file: osint_bot.py
# requires: pip install pyTelegramBotAPI requests beautifulsoup4

import requests
import telebot
from io import BytesIO
from bs4 import BeautifulSoup

# ══════════════════════════════════════════════
#  TOKEN YAHAN DAALO
#  1. Telegram pe @BotFather kholo
#  2. /newbot likho
#  3. Jo token milega wo yahan paste karo
# ══════════════════════════════════════════════
BOT_TOKEN = "8253791330:AAGFs7Cf_a3AaGiWQcQHhX0dquzMid2r6V8"
# ══════════════════════════════════════════════

bot = telebot.TeleBot(BOT_TOKEN)

ANISH_URL   = "https://exploitsindia.site/osint/api.php"
ANISH_KEY   = "anish-exploits"
TG2NUM_URL  = "https://astha-9vd8.onrender.com/tapi-e79c7312cf5329b07b0ad3ee2aeaea19?Astha="
TITAN_URL   = "https://titan-num-info-api.onrender.com/search"
ECI_SEARCH  = "https://voterportal.eci.gov.in/Home/SearchByEPIC"
ECI_CAPTCHA = "https://voterportal.eci.gov.in/Home/GetCaptchaImage"

eci_session = requests.Session()
eci_session.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer": "https://voterportal.eci.gov.in/",
})

user_state = {}

# ─────────────────────────────────────────────
#  SAFE JSON PARSER — empty/bad response handle
# ─────────────────────────────────────────────
def safe_json(response) -> dict | None:
    text = response.text.strip()
    if not text:
        return None
    try:
        return response.json()
    except Exception:
        return None

# ─────────────────────────────────────────────
#  /start
# ─────────────────────────────────────────────
@bot.message_handler(commands=["start", "help"])
def handle_start(msg):
    text = (
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "     🔍 OSINT TOOLKIT BOT\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "📌 Commands:\n\n"
        "/phone `<number>` — Phone OSINT \\(Anish\\)\n"
        "   _Name, Aadhaar, Address, Email_\n\n"
        "/titan `<number>` — Phone Info \\(Titan API\\)\n"
        "   _Alternate number info source_\n\n"
        "/tg `<telegram\\_id>` — TG ID → Phone\n"
        "   _Telegram numeric ID se number_\n\n"
        "/voter — Voter ID \\(EPIC\\) Lookup\n"
        "   _ECI se poori voter info_\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━"
    )
    bot.send_message(msg.chat.id, text, parse_mode="MarkdownV2")

# ─────────────────────────────────────────────
#  /phone <number>  — Anish OSINT
#  Fix: safe_json + fallback APIs
# ─────────────────────────────────────────────
@bot.message_handler(commands=["phone"])
def handle_phone(msg):
    parts = msg.text.strip().split(maxsplit=1)
    if len(parts) < 2:
        bot.send_message(msg.chat.id, "❌ Usage: `/phone 9876543210`", parse_mode="Markdown")
        return

    number = parts[1].strip()
    bot.send_message(msg.chat.id, f"🔍 Searching `{number}`...", parse_mode="Markdown")

    try:
        r = requests.get(
            ANISH_URL,
            params={"key": ANISH_KEY, "type": "number", "num": number},
            timeout=30,
            headers={"User-Agent": "Mozilla/5.0"}
        )

        data = safe_json(r)

        if data is None:
            bot.send_message(
                msg.chat.id,
                f"⚠️ API ne khaali response diya\\.\nRaw: `{r.text[:200] or 'empty'}`",
                parse_mode="MarkdownV2"
            )
            return

        if data.get("status") == "error" or not data.get("result"):
            bot.send_message(msg.chat.id, "❌ No data found for this number.")
            return

        i = data["result"][0]

        def esc(val):
            # escape MarkdownV2 special chars
            val = str(val or "N/A")
            for c in r"\_*[]()~`>#+-=|{}.!":
                val = val.replace(c, f"\\{c}")
            return val

        text = (
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            "     📱 PHONE OSINT RESULT\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"📞 Phone:      `{esc(i.get('num'))}`\n"
            f"👤 Name:       `{esc(i.get('name'))}`\n"
            f"👨 Father:     `{esc(i.get('fname'))}`\n"
            f"🪪 Aadhaar:    `{esc(i.get('aadhar'))}`\n"
            f"🏠 Address:    `{esc(i.get('address'))}`\n"
            f"📶 Circle:     `{esc(i.get('circle'))}`\n"
            f"📱 Alternate:  `{esc(i.get('alt'))}`\n"
            f"📧 Email:      `{esc(i.get('email'))}`\n\n"
            "━━━━━━━━━━━━━━━━━━━━━━"
        )
        bot.send_message(msg.chat.id, text, parse_mode="MarkdownV2")

    except requests.exceptions.Timeout:
        bot.send_message(msg.chat.id, "⏱️ API timeout ho gaya. Dobara try karo.")
    except requests.exceptions.ConnectionError:
        bot.send_message(msg.chat.id, "🔌 API server se connect nahi hua.")
    except Exception as e:
        bot.send_message(msg.chat.id, f"⚠️ Error: `{e}`", parse_mode="Markdown")

# ─────────────────────────────────────────────
#  TITAN API HELPER — tries common param names
#  422 = wrong param key, tries fallbacks
# ─────────────────────────────────────────────
def titan_query(number: str) -> dict | None:
    """
    Titan API param name unknown — try in order:
    number → num → phone → mobile → q
    Returns parsed JSON dict or None on all failures.
    """
    param_keys = ["number", "num", "phone", "mobile", "q"]
    headers = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}

    for key in param_keys:
        try:
            r = requests.get(
                TITAN_URL,
                params={key: number},
                headers=headers,
                timeout=30
            )
            if r.status_code == 422:
                continue                    # wrong param, try next
            if r.status_code != 200:
                return {"_error": f"HTTP {r.status_code}", "_raw": r.text[:300]}
            data = safe_json(r)
            if data is not None:
                data["_param_used"] = key   # debug info, stripped before display
                return data
        except requests.exceptions.Timeout:
            return {"_error": "timeout"}
        except requests.exceptions.ConnectionError:
            return {"_error": "connection_failed"}
        except Exception as e:
            return {"_error": str(e)}

    return {"_error": "all_params_failed_422"}


# ─────────────────────────────────────────────
#  /titan <number>  — Titan number info API
# ─────────────────────────────────────────────
@bot.message_handler(commands=["titan"])
def handle_titan(msg):
    parts = msg.text.strip().split(maxsplit=1)
    if len(parts) < 2:
        bot.send_message(msg.chat.id, "❌ Usage: `/titan 9876543210`", parse_mode="Markdown")
        return

    number = parts[1].strip()
    bot.send_message(msg.chat.id, f"🔍 Titan API se `{number}` search ho raha hai...", parse_mode="Markdown")

    data = titan_query(number)

    if data is None:
        bot.send_message(msg.chat.id, "⚠️ Titan API ne khaali response diya.")
        return

    if "_error" in data:
        err = data["_error"]
        raw = data.get("_raw", "")
        if err == "timeout":
            bot.send_message(msg.chat.id, "⏱️ Titan API timeout. Dobara try karo.")
        elif err == "connection_failed":
            bot.send_message(msg.chat.id, "🔌 Titan API server se connect nahi hua.")
        elif err == "all_params_failed_422":
            bot.send_message(msg.chat.id, "⚠️ Titan API: parameter name match nahi hua. API update ho sakti hai.")
        else:
            bot.send_message(
                msg.chat.id,
                f"⚠️ Error: `{err}`\n\nRaw: `{raw[:200]}`" if raw else f"⚠️ Error: `{err}`",
                parse_mode="Markdown"
            )
        return

    # ── strip internal debug key before display ──
    data.pop("_param_used", None)

    # ── check common error/empty patterns ──
    status = data.get("status") or data.get("success") or data.get("error")
    if status in ("error", False, "false", 0):
        msg_text = data.get("message") or data.get("msg") or "No data found."
        bot.send_message(msg.chat.id, f"❌ {msg_text}")
        return

    # ── extract result object (handles nested or flat response) ──
    result = (
        data.get("result")
        or data.get("data")
        or data.get("info")
        or data
    )
    if isinstance(result, list):
        result = result[0] if result else {}

    def esc(val):
        val = str(val or "N/A")
        for c in r"\_*[]()~`>#+-=|{}.!":
            val = val.replace(c, f"\\{c}")
        return val

    # ── build readable output from whatever keys exist ──
    field_map = {
        "name":      ("👤 Name",       ["name", "full_name", "fullname", "subscriber_name"]),
        "number":    ("📞 Number",     ["number", "num", "phone", "mobile", "msisdn"]),
        "operator":  ("📶 Operator",   ["operator", "carrier", "telecom", "circle_name"]),
        "circle":    ("🗺️ Circle",     ["circle", "state", "location", "region"]),
        "address":   ("🏠 Address",    ["address", "addr", "full_address"]),
        "email":     ("📧 Email",      ["email", "mail"]),
        "aadhaar":   ("🪪 Aadhaar",    ["aadhar", "aadhaar", "uid"]),
        "alt":       ("📱 Alternate",  ["alt", "alternate", "alt_number"]),
        "dob":       ("🎂 DOB",        ["dob", "date_of_birth", "birth_date"]),
        "gender":    ("⚧ Gender",     ["gender", "sex"]),
        "father":    ("👨 Father",     ["fname", "father", "father_name"]),
    }

    lines = [
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "   📡 TITAN API RESULT\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
    ]

    found_any = False
    for _field, (label, keys) in field_map.items():
        for k in keys:
            val = result.get(k)
            if val and str(val).strip() not in ("", "N/A", "null", "None"):
                lines.append(f"{label}:  `{esc(val)}`")
                found_any = True
                break

    # ── dump unknown keys if nothing matched standard map ──
    if not found_any:
        for k, v in result.items():
            if v and str(v).strip() not in ("", "null", "None"):
                lines.append(f"`{esc(k)}`:  `{esc(v)}`")

    lines.append("\n━━━━━━━━━━━━━━━━━━━━━━")
    bot.send_message(msg.chat.id, "\n".join(lines), parse_mode="MarkdownV2")


# ─────────────────────────────────────────────
#  /tg <telegram_id>  — tg2num
# ─────────────────────────────────────────────
@bot.message_handler(commands=["tg"])
def handle_tg(msg):
    parts = msg.text.strip().split(maxsplit=1)
    if len(parts) < 2 or not parts[1].strip().isdigit():
        bot.send_message(msg.chat.id, "❌ Usage: `/tg 123456789`\n_Numeric ID only_", parse_mode="Markdown")
        return

    tg_id = parts[1].strip()
    bot.send_message(msg.chat.id, f"🔍 Looking up Telegram ID `{tg_id}`...", parse_mode="Markdown")

    try:
        r = requests.get(f"{TG2NUM_URL}{tg_id}", timeout=30)
        r.raise_for_status()

        data = safe_json(r)
        if data is None:
            bot.send_message(msg.chat.id, "⚠️ API khaali response de raha hai.")
            return

        if data.get("status") == "error":
            bot.send_message(msg.chat.id, "❌ No data found for this Telegram ID.")
            return

        res   = data.get("result", {})
        phone = res.get("number")
        if not phone:
            bot.send_message(msg.chat.id, "❌ No phone number found.")
            return

        text = (
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            "    📲 TELEGRAM → PHONE\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"🆔 Telegram ID:   `{res.get('tg_id', tg_id)}`\n"
            f"📞 Phone Number:  `{phone}`\n"
            f"🌍 Country:       `{res.get('country', 'N/A')}`\n"
            f"🔢 Country Code:  `{res.get('country_code', 'N/A')}`\n\n"
            "━━━━━━━━━━━━━━━━━━━━━━"
        )
        bot.send_message(msg.chat.id, text, parse_mode="Markdown")

    except requests.exceptions.Timeout:
        bot.send_message(msg.chat.id, "⏱️ Timeout. Dobara try karo.")
    except Exception as e:
        bot.send_message(msg.chat.id, f"⚠️ Error: `{e}`", parse_mode="Markdown")

# ─────────────────────────────────────────────
#  /voter  — ECI EPIC lookup (2-step: epic → captcha)
# ─────────────────────────────────────────────
@bot.message_handler(commands=["voter"])
def handle_voter_start(msg):
    chat_id = msg.chat.id
    user_state[chat_id] = {"step": "await_epic"}
    bot.send_message(
        chat_id,
        "🗳️ *Voter ID Lookup*\n\nApna EPIC / Voter ID bhejo:\n_Example: `ZNO1150077`_",
        parse_mode="Markdown"
    )

@bot.message_handler(func=lambda msg: user_state.get(msg.chat.id, {}).get("step") == "await_epic")
def handle_voter_epic(msg):
    chat_id = msg.chat.id
    epic    = msg.text.strip().upper()

    if len(epic) < 6:
        bot.send_message(chat_id, "❌ Invalid EPIC. Dobara bhejo.")
        return

    user_state[chat_id]["epic"] = epic
    bot.send_message(chat_id, "⏳ CAPTCHA fetch ho raha hai...")

    try:
        resp = eci_session.get(ECI_SEARCH, timeout=10)
        soup = BeautifulSoup(resp.text, "html.parser")

        def h(name):
            t = soup.find("input", {"name": name})
            return t["value"] if t else ""

        user_state[chat_id]["hidden"] = {
            "__RequestVerificationToken": h("__RequestVerificationToken"),
            "__VIEWSTATE":                h("__VIEWSTATE"),
            "__EVENTVALIDATION":          h("__EVENTVALIDATION"),
        }

        cap = eci_session.get(ECI_CAPTCHA, timeout=10, stream=True)
        cap.raise_for_status()
        image_bytes = cap.content

        if len(image_bytes) < 200:
            bot.send_message(chat_id, "⚠️ CAPTCHA invalid. /voter se dobara karo.")
            user_state.pop(chat_id, None)
            return

        bot.send_photo(chat_id, BytesIO(image_bytes), caption="👆 Is CAPTCHA ka text bhejo:")
        user_state[chat_id]["step"] = "await_captcha"

    except Exception as e:
        bot.send_message(chat_id, f"⚠️ CAPTCHA fetch failed: `{e}`", parse_mode="Markdown")
        user_state.pop(chat_id, None)

@bot.message_handler(func=lambda msg: user_state.get(msg.chat.id, {}).get("step") == "await_captcha")
def handle_voter_captcha(msg):
    chat_id = msg.chat.id
    captcha = msg.text.strip()
    epic    = user_state[chat_id].get("epic")
    hidden  = user_state[chat_id].get("hidden", {})

    bot.send_message(chat_id, "⏳ Searching...")

    try:
        payload = {"EpicNo": epic, "CaptchaText": captcha, **hidden}
        resp    = eci_session.post(ECI_SEARCH, data=payload, timeout=15)
        soup    = BeautifulSoup(resp.text, "html.parser")

        if soup.find("div", {"class": "alert-danger"}):
            bot.send_message(chat_id, "❌ Not found ya CAPTCHA galat. /voter se dobara karo.")
            user_state.pop(chat_id, None)
            return

        def gt(sel):
            e = soup.select_one(sel)
            return e.text.strip() if e else "N/A"

        name = gt("#lblName")
        if name == "N/A":
            bot.send_message(chat_id, "❌ Voter nahi mila. /voter se dobara karo.")
            user_state.pop(chat_id, None)
            return

        text = (
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            "      🗳️ VOTER DETAILS\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"🆔 EPIC:            `{epic}`\n"
            f"👤 Name:            `{name}`\n"
            f"📛 Name (Hindi):    `{gt('#lblNameHindi')}`\n"
            f"👨 Relative:        `{gt('#lblRelative')}`\n"
            f"⚧ Gender:          `{gt('#lblGender')}`\n"
            f"🎂 Age:             `{gt('#lblAge')}`\n"
            f"📅 Birth Year:      `{gt('#lblBirthYear')}`\n\n"
            f"🏛️ Assembly:        `{gt('#lblAssembly')}`\n"
            f"🗳️ Parliament:      `{gt('#lblParliament')}`\n"
            f"📍 District:        `{gt('#lblDistrict')}`\n"
            f"🗺️ State:           `{gt('#lblState')}`\n\n"
            f"🏫 Polling Station: `{gt('#lblPollingStation')}`\n"
            f"📌 Lat-Long:        `{gt('#lblLatLong')}`\n"
            f"✅ Active:          `{gt('#lblActive')}`\n\n"
            "━━━━━━━━━━━━━━━━━━━━━━"
        )
        bot.send_message(chat_id, text, parse_mode="Markdown")

    except Exception as e:
        bot.send_message(chat_id, f"⚠️ Error: `{e}`", parse_mode="Markdown")
    finally:
        user_state.pop(chat_id, None)

# ─────────────────────────────────────────────
#  START
# ─────────────────────────────────────────────
if __name__ == "__main__":
    if BOT_TOKEN == "APNA_TOKEN_YAHAN_DAALO":
        print("[!] BOT_TOKEN set karo pehle — line 20 pe")
    else:
        print("[*] Bot chal raha hai...")
        bot.infinity_polling()
