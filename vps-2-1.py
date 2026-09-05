"""Telegram VPS Manager Bot.

This program converts the original Discord VPS bot to Telegram while retaining
Docker-backed VPS creation, web-terminal SSH access, user limits, administration,
SQLite storage, logging, and periodic container-status synchronization.

Run this only on the Docker host. The process needs permission to control the
local Docker daemon. Telegram bot commands that expose VPS data are restricted
to private chats because Telegram group replies are normally visible to others.
"""

from __future__ import annotations

# =============================================================================
# EDIT ONLY THESE SETTINGS BEFORE RUNNING: python3 bot.py
# =============================================================================
BOT_TOKEN = "8647351719:AAH_LlmO7iovvJzOzH2O4ezT2FTHzGqRDcU"
ADMIN_ID = 8502412097 # Replace 0 with your numeric Telegram user ID from @userinfobot.

BOT_STATUS_NAME = "UnixNodes"
WATERMARK = "Powered by UnixNodes VPS Bot"
DEFAULT_RAM = "2g"
DEFAULT_CPU = "1"
DEFAULT_DISK = "10G"
VPS_HOSTNAME = "unix-free"
SERVER_LIMIT = 1
TOTAL_SERVER_LIMIT = 50
DATABASE_FILE = "vps_bot.db"
STATUS_SYNC_SECONDS = 300

# =============================================================================
# FORCE-JOIN + REFERRAL SETTINGS
# Channels are managed live via bot commands — no file edit or restart needed.
#   /admin_channel_add  <@username or chat_id> <Name> <url>
#   /admin_channel_list
#   /admin_channel_remove <@username or chat_id>
# =============================================================================

# How many accepted referrals = 1 extra VPS slot
REFERRALS_PER_CREDIT = 5

# This block installs the two required Python packages automatically when absent.
import importlib.util
import os
import subprocess
import sys


def ensure_python_dependencies() -> None:
    required = {
        "telegram": "python-telegram-bot[job-queue]>=22.0,<23.0",
        "docker": "docker>=7.0,<8.0",
    }
    missing = [package for module, package in required.items() if importlib.util.find_spec(module) is None]
    if not missing:
        return
    print("Installing required Python packages. Please wait...")
    try:
        subprocess.check_call([sys.executable, "-m", "pip", "install", "--upgrade", *missing])
    except subprocess.CalledProcessError as exc:
        print(f"Could not install packages automatically: {exc}")
        print("Run: python3 -m pip install python-telegram-bot[job-queue] docker")
        raise SystemExit(1) from exc
    os.execv(sys.executable, [sys.executable, *sys.argv])


ensure_python_dependencies()

import asyncio
import html
import logging
import random
import re
import sqlite3
import time
from contextlib import suppress
from datetime import datetime, timezone
from typing import Iterable, Optional

import docker
from telegram import BotCommand, BotCommandScopeChat, InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ChatType, ParseMode
from telegram.error import BadRequest, Forbidden, TelegramError
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    Defaults,
)


# ---------------------------------------------------------------------------
# Configuration aliases
# ---------------------------------------------------------------------------
TOKEN = BOT_TOKEN.strip()

LOG_FORMAT = "%(asctime)s - %(levelname)s - %(name)s - %(message)s"
logging.basicConfig(
    level=logging.INFO,
    format=LOG_FORMAT,
    handlers=[logging.FileHandler("vps_bot.log"), logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("telegram_vps_bot")

# Creation may take a few minutes. The lock prevents concurrent requests from
# bypassing per-user/global limits in a single bot process.
creation_lock = asyncio.Lock()
_docker_client: Optional[docker.DockerClient] = None


# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------
def init_db() -> None:
    """Create the database and preserve compatibility with the source schema."""
    with sqlite3.connect(DATABASE_FILE, timeout=30) as conn:
        cursor = conn.cursor()
        cursor.execute("PRAGMA foreign_keys = ON")
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS vps (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                container_id TEXT UNIQUE NOT NULL,
                container_name TEXT NOT NULL,
                os_type TEXT NOT NULL,
                hostname TEXT NOT NULL,
                status TEXT DEFAULT 'stopped',
                ssh_command TEXT,
                ram TEXT DEFAULT '2g',
                cpu TEXT DEFAULT '1',
                disk TEXT DEFAULT '10G',
                suspended INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users (user_id)
            )
            """
        )
        columns = {column[1] for column in cursor.execute("PRAGMA table_info(vps)")}
        if "suspended" not in columns:
            cursor.execute("ALTER TABLE vps ADD COLUMN suspended INTEGER DEFAULT 0")
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS bans (
                user_id INTEGER PRIMARY KEY
            )
            """
        )
        # referral tracking
        # referred_user_id  — the person who used the referral link
        # referrer_id       — the person whose link was shared
        # channel_joined    — 1 once we confirm the referred user joined the channel
        # credit_given      — 1 once this referral was counted toward a credit
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS referrals (
                referred_user_id INTEGER PRIMARY KEY,
                referrer_id      INTEGER NOT NULL,
                channel_joined   INTEGER DEFAULT 0,
                credit_given     INTEGER DEFAULT 0,
                created_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        # extra VPS slots earned through referrals
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS user_credits (
                user_id     INTEGER PRIMARY KEY,
                extra_slots INTEGER DEFAULT 0
            )
            """
        )
        # force-join channels (managed via bot commands, no file edit needed)
        # channel_id  — @username or numeric chat id string
        # name        — display name shown in join prompt
        # url         — invite link shown as button
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS force_channels (
                channel_id  TEXT PRIMARY KEY,
                name        TEXT NOT NULL,
                url         TEXT NOT NULL,
                added_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )


def get_db_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DATABASE_FILE, timeout=30)
    conn.row_factory = sqlite3.Row
    return conn


def add_user(user_id: int, username: str) -> None:
    with get_db_connection() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO users (user_id, username) VALUES (?, ?)",
            (user_id, username),
        )
        conn.execute("UPDATE users SET username = ? WHERE user_id = ?", (username, user_id))


def add_ban(user_id: int) -> None:
    with get_db_connection() as conn:
        conn.execute("INSERT OR IGNORE INTO bans (user_id) VALUES (?)", (user_id,))


def remove_ban(user_id: int) -> None:
    with get_db_connection() as conn:
        conn.execute("DELETE FROM bans WHERE user_id = ?", (user_id,))


def is_banned(user_id: int) -> bool:
    with get_db_connection() as conn:
        return conn.execute("SELECT 1 FROM bans WHERE user_id = ?", (user_id,)).fetchone() is not None


# ---------------------------------------------------------------------------
# Referral helpers
# ---------------------------------------------------------------------------

def save_referral_pending(referred_user_id: int, referrer_id: int) -> None:
    """Record that referred_user_id arrived via referrer_id's link (not yet joined channel)."""
    with get_db_connection() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO referrals (referred_user_id, referrer_id) VALUES (?, ?)",
            (referred_user_id, referrer_id),
        )


def mark_referral_joined(referred_user_id: int) -> Optional[int]:
    """
    Mark the referred user as having joined the channel.
    Returns the referrer_id if this referral hadn't been marked yet, else None.
    """
    with get_db_connection() as conn:
        row = conn.execute(
            "SELECT referrer_id, channel_joined FROM referrals WHERE referred_user_id = ?",
            (referred_user_id,),
        ).fetchone()
        if row is None or row["channel_joined"] == 1:
            return None
        conn.execute(
            "UPDATE referrals SET channel_joined = 1 WHERE referred_user_id = ?",
            (referred_user_id,),
        )
        return row["referrer_id"]


def count_credited_referrals(referrer_id: int) -> int:
    """Pending-but-credited referrals already applied for this referrer."""
    with get_db_connection() as conn:
        return conn.execute(
            "SELECT COUNT(*) FROM referrals WHERE referrer_id = ? AND channel_joined = 1",
            (referrer_id,),
        ).fetchone()[0]


def get_uncredited_joined_referrals(referrer_id: int) -> list:
    """Joined referrals for this referrer that have not yet been counted toward a credit."""
    with get_db_connection() as conn:
        return conn.execute(
            "SELECT referred_user_id FROM referrals "
            "WHERE referrer_id = ? AND channel_joined = 1 AND credit_given = 0",
            (referrer_id,),
        ).fetchall()


def mark_referrals_credited(referred_ids: list[int]) -> None:
    with get_db_connection() as conn:
        conn.executemany(
            "UPDATE referrals SET credit_given = 1 WHERE referred_user_id = ?",
            [(rid,) for rid in referred_ids],
        )


def get_extra_slots(user_id: int) -> int:
    with get_db_connection() as conn:
        row = conn.execute(
            "SELECT extra_slots FROM user_credits WHERE user_id = ?", (user_id,)
        ).fetchone()
        return row["extra_slots"] if row else 0


def add_extra_slot(user_id: int) -> int:
    """Add one extra VPS slot. Returns the new total extra slots."""
    with get_db_connection() as conn:
        conn.execute(
            "INSERT INTO user_credits (user_id, extra_slots) VALUES (?, 1) "
            "ON CONFLICT(user_id) DO UPDATE SET extra_slots = extra_slots + 1",
            (user_id,),
        )
        return conn.execute(
            "SELECT extra_slots FROM user_credits WHERE user_id = ?", (user_id,)
        ).fetchone()[0]


def get_referral_stats(user_id: int) -> dict:
    with get_db_connection() as conn:
        total = conn.execute(
            "SELECT COUNT(*) FROM referrals WHERE referrer_id = ?", (user_id,)
        ).fetchone()[0]
        joined = conn.execute(
            "SELECT COUNT(*) FROM referrals WHERE referrer_id = ? AND channel_joined = 1",
            (user_id,),
        ).fetchone()[0]
        pending = total - joined
    extra = get_extra_slots(user_id)
    uncredited = get_uncredited_joined_referrals(user_id)
    progress_toward_next = len(uncredited) % REFERRALS_PER_CREDIT
    return {
        "total": total,
        "joined": joined,
        "pending": pending,
        "extra_slots": extra,
        "progress": progress_toward_next,
        "needed": REFERRALS_PER_CREDIT - progress_toward_next,
    }


async def process_pending_credit(referrer_id: int, bot) -> None:
    """
    Check whether the referrer has reached REFERRALS_PER_CREDIT uncredited
    joined referrals and issue a slot credit if so.
    Notifies the referrer via DM on each credit earned.
    """
    uncredited = get_uncredited_joined_referrals(referrer_id)
    while len(uncredited) >= REFERRALS_PER_CREDIT:
        batch = [row["referred_user_id"] for row in uncredited[:REFERRALS_PER_CREDIT]]
        mark_referrals_credited(batch)
        new_total = add_extra_slot(referrer_id)
        with suppress(TelegramError):
            await bot.send_message(
                chat_id=referrer_id,
                text=(
                    f"🎉 <b>Referral Credit Earned!</b>\n\n"
                    f"You reached {REFERRALS_PER_CREDIT} successful referrals and earned "
                    f"<b>+1 extra VPS slot</b>.\n"
                    f"Total extra slots: <b>{new_total}</b>\n\n"
                    f"Use /deploy to create your bonus VPS."
                ),
                parse_mode=ParseMode.HTML,
            )
        uncredited = get_uncredited_joined_referrals(referrer_id)


# ---------------------------------------------------------------------------
# Force-channel DB helpers
# ---------------------------------------------------------------------------

def db_add_force_channel(channel_id: str, name: str, url: str) -> None:
    with get_db_connection() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO force_channels (channel_id, name, url) VALUES (?, ?, ?)",
            (channel_id.strip(), name.strip(), url.strip()),
        )


def db_remove_force_channel(channel_id: str) -> bool:
    with get_db_connection() as conn:
        cur = conn.execute(
            "DELETE FROM force_channels WHERE channel_id = ?", (channel_id.strip(),)
        )
        return cur.rowcount > 0


def db_list_force_channels() -> list:
    with get_db_connection() as conn:
        return conn.execute(
            "SELECT channel_id, name, url FROM force_channels ORDER BY added_at"
        ).fetchall()


def add_vps(
    user_id: int,
    container_id: str,
    container_name: str,
    os_type: str,
    hostname: str,
    ssh_command: str,
    ram: str = DEFAULT_RAM,
    cpu: str = DEFAULT_CPU,
    disk: str = DEFAULT_DISK,
) -> None:
    with get_db_connection() as conn:
        conn.execute(
            """
            INSERT INTO vps (
                user_id, container_id, container_name, os_type, hostname,
                status, ssh_command, ram, cpu, disk, suspended
            ) VALUES (?, ?, ?, ?, ?, 'running', ?, ?, ?, ?, 0)
            """,
            (user_id, container_id, container_name, os_type, hostname, ssh_command, ram, cpu, disk),
        )


def get_user_vps(user_id: int) -> list[sqlite3.Row]:
    with get_db_connection() as conn:
        return conn.execute(
            "SELECT * FROM vps WHERE user_id = ? ORDER BY created_at DESC", (user_id,)
        ).fetchall()


def count_user_vps(user_id: int) -> int:
    return len(get_user_vps(user_id))


def effective_server_limit(user_id: int) -> int:
    """Base limit plus any referral-earned bonus slots."""
    return SERVER_LIMIT + get_extra_slots(user_id)


def get_vps_by_identifier(user_id: int, identifier: Optional[str]) -> Optional[sqlite3.Row]:
    vps_list = get_user_vps(user_id)
    if not identifier:
        return vps_list[0] if vps_list else None
    needle = identifier.lower()
    for vps in vps_list:
        if needle in vps["container_id"].lower() or needle in vps["container_name"].lower():
            return vps
    return None


def update_vps_status(container_id: str, status: str) -> None:
    with get_db_connection() as conn:
        conn.execute("UPDATE vps SET status = ? WHERE container_id = ?", (status, container_id))


def update_vps_ssh(container_id: str, ssh_command: str) -> None:
    with get_db_connection() as conn:
        conn.execute("UPDATE vps SET ssh_command = ? WHERE container_id = ?", (ssh_command, container_id))


def update_vps_suspended(container_id: str, suspended: int) -> None:
    with get_db_connection() as conn:
        conn.execute("UPDATE vps SET suspended = ? WHERE container_id = ?", (suspended, container_id))


def delete_vps(container_id: str) -> None:
    with get_db_connection() as conn:
        conn.execute("DELETE FROM vps WHERE container_id = ?", (container_id,))


def get_total_instances() -> int:
    with get_db_connection() as conn:
        return conn.execute('SELECT COUNT(*) FROM vps WHERE status = "running"').fetchone()[0]


def get_all_vps() -> list[sqlite3.Row]:
    with get_db_connection() as conn:
        return conn.execute(
            """
            SELECT u.user_id, u.username, v.container_id, v.container_name, v.os_type,
                   v.hostname, v.status, v.ram, v.cpu, v.disk, v.suspended, v.created_at
            FROM vps v JOIN users u ON v.user_id = u.user_id
            ORDER BY v.created_at DESC
            """
        ).fetchall()


def get_users_overview() -> list[sqlite3.Row]:
    with get_db_connection() as conn:
        return conn.execute(
            """
            SELECT u.user_id, u.username, COUNT(v.id) AS total_vps,
                   SUM(CASE WHEN v.status = 'running' THEN 1 ELSE 0 END) AS running_vps
            FROM users u LEFT JOIN vps v ON u.user_id = v.user_id
            GROUP BY u.user_id, u.username
            ORDER BY total_vps DESC
            """
        ).fetchall()


def get_bot_stats() -> dict[str, float | int]:
    with get_db_connection() as conn:
        total_users = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        total_vps = conn.execute("SELECT COUNT(*) FROM vps").fetchone()[0]
        total_running = conn.execute('SELECT COUNT(*) FROM vps WHERE status = "running"').fetchone()[0]
        total_banned = conn.execute("SELECT COUNT(*) FROM bans").fetchone()[0]
        resource_rows = conn.execute('SELECT ram, cpu, disk FROM vps WHERE status = "running"').fetchall()
    return {
        "users": total_users,
        "vps": total_vps,
        "running": total_running,
        "banned": total_banned,
        "cpu": sum(float(row["cpu"]) for row in resource_rows),
        "ram": sum(parse_gb(row["ram"]) for row in resource_rows),
        "disk": sum(parse_gb(row["disk"]) for row in resource_rows),
    }


# ---------------------------------------------------------------------------
# Docker and operating-system helpers
# ---------------------------------------------------------------------------
def get_docker_client() -> docker.DockerClient:
    global _docker_client
    if _docker_client is None:
        _docker_client = docker.from_env()
    return _docker_client


def parse_gb(resource_str: str) -> float:
    match = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*([mMgG])?\s*", str(resource_str))
    if not match:
        return 0.0
    value = float(match.group(1))
    return value / 1024.0 if (match.group(2) or "g").lower() == "m" else value


def validate_resource_format(ram: str, cpu: str, disk: str) -> Optional[str]:
    if parse_gb(ram) <= 0:
        return "RAM must be a positive value such as <code>2g</code> or <code>512m</code>."
    try:
        if float(cpu) <= 0:
            raise ValueError
    except (TypeError, ValueError):
        return "CPU must be a positive number, such as <code>1</code> or <code>0.5</code>."
    if parse_gb(disk) <= 0:
        return "Disk must be a positive value such as <code>10G</code>."
    return None


def get_uptime(container_id: str) -> str:
    try:
        output = subprocess.check_output(
            ["docker", "inspect", "-f", "{{.State.StartedAt}}", container_id], stderr=subprocess.STDOUT
        ).decode().strip()
        if output == "<no value>" or output.startswith("0001-01-01"):
            return "Not running"
        start_time = datetime.fromisoformat(output.replace("Z", "+00:00"))
        uptime = datetime.now(timezone.utc) - start_time
        days = uptime.days
        hours, remainder = divmod(uptime.seconds, 3600)
        minutes, _ = divmod(remainder, 60)
        return f"{days}d {hours}h {minutes}m"
    except Exception as exc:
        logger.warning("Could not obtain uptime for %s: %s", container_id, exc)
        return "Unknown"


def get_stats(container_id: str) -> dict[str, str]:
    try:
        output = subprocess.check_output(
            ["docker", "stats", "--no-stream", "--format", "{{.CPUPerc}}\t{{.MemUsage}}\t{{.NetIO}}", container_id],
            stderr=subprocess.STDOUT,
        ).decode().strip()
        parts = output.split("\t")
        if len(parts) == 3:
            return {"cpu": parts[0], "mem": parts[1], "net": parts[2]}
    except Exception as exc:
        logger.warning("Could not obtain stats for %s: %s", container_id, exc)
    return {"cpu": "N/A", "mem": "N/A", "net": "N/A"}


def get_logs(container_id: str, lines: int = 50) -> str:
    lines = max(1, min(lines, 500))
    try:
        output = subprocess.check_output(
            ["docker", "logs", "--tail", str(lines), container_id], stderr=subprocess.STDOUT
        ).decode(errors="replace")
        return output[-3200:] or "No log output."
    except Exception as exc:
        logger.warning("Could not obtain logs for %s: %s", container_id, exc)
        return "Failed to fetch logs."


def get_container_status(container_id: str) -> Optional[str]:
    try:
        return subprocess.check_output(
            ["docker", "inspect", "-f", "{{.State.Status}}", container_id], stderr=subprocess.STDOUT
        ).decode().strip()
    except subprocess.CalledProcessError:
        return None


async def async_docker_run(image: str, hostname: str, ram: str, cpu: str, container_name: str) -> Optional[str]:
    cmd = [
        "docker", "run", "-d",
        "--privileged", "--cap-add=ALL",  # Kept for compatibility with the source bot.
        "--restart", "unless-stopped",
        f"--memory={ram}",
        f"--cpus={cpu}",
        f"--hostname={hostname}",
        f"--name={container_name}",
        image,
        "tail", "-f", "/dev/null",
    ]
    try:
        process = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=60)
        if process.returncode != 0:
            logger.error("Docker run failed: %s", stderr.decode(errors="replace").strip())
            return None
        return stdout.decode().strip()
    except asyncio.TimeoutError:
        logger.error("Docker run timed out")
    except Exception as exc:
        logger.exception("Docker run error: %s", exc)
    return None


async def _docker_action(container_id: str, action: str, timeout: float = 30) -> bool:
    try:
        process = await asyncio.create_subprocess_exec(
            "docker", action, container_id,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
        if process.returncode != 0:
            logger.warning("Docker %s failed for %s: %s", action, container_id, stderr.decode(errors="replace"))
        return process.returncode == 0
    except asyncio.TimeoutError:
        logger.warning("Docker %s timed out for %s", action, container_id)
    except Exception as exc:
        logger.exception("Docker %s error for %s: %s", action, container_id, exc)
    return False


async def async_docker_start(container_id: str) -> bool:
    return await _docker_action(container_id, "start")


async def async_docker_stop(container_id: str) -> bool:
    success = await _docker_action(container_id, "stop")
    if not success:
        await _docker_action(container_id, "kill", timeout=15)
    return success


async def async_docker_restart(container_id: str) -> bool:
    return await _docker_action(container_id, "restart")


async def async_docker_rm(container_id: str) -> bool:
    try:
        process = await asyncio.create_subprocess_exec(
            "docker", "rm", "-f", container_id,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await asyncio.wait_for(process.communicate(), timeout=30)
        if process.returncode != 0:
            logger.warning("Docker rm failed for %s: %s", container_id, stderr.decode(errors="replace"))
        return process.returncode == 0
    except Exception as exc:
        logger.exception("Docker rm error for %s: %s", container_id, exc)
        return False


async def async_install_web_ssh(container_id: str) -> bool:
    """Install openssh-server and prerequisites inside the container."""
    install_cmd = (
        "apt-get update -qq && "
        "DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends "
        "openssh-server openssh-client curl wget sudo ca-certificates && "
        "mkdir -p /run/sshd /root/.ssh && chmod 700 /root/.ssh"
    )
    try:
        process = await asyncio.create_subprocess_exec(
            "docker", "exec", container_id, "bash", "-c", install_cmd,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await asyncio.wait_for(process.communicate(), timeout=240)
        if process.returncode != 0:
            logger.warning("Web-SSH install failed for %s: %s", container_id, stderr.decode(errors="replace"))
            return False
        return True
    except asyncio.TimeoutError:
        logger.error("Web-SSH install timed out for %s", container_id)
    except Exception as exc:
        logger.exception("Web-SSH install error for %s: %s", container_id, exc)
    return False


async def async_setup_web_access(container_id: str) -> tuple[Optional[str], Optional[str]]:
    """
    Generate an SSH keypair inside the container, start openssh-server,
    then launch dash.freestyle.sh and capture its web URL.

    Returns (web_url, private_key_pem) or (None, None) on failure.
    """
    # 1. Generate ed25519 keypair and authorise it.
    keygen_cmd = (
        "ssh-keygen -t ed25519 -f /root/.ssh/id_ed25519 -N '' -q && "
        "cat /root/.ssh/id_ed25519.pub >> /root/.ssh/authorized_keys && "
        "chmod 600 /root/.ssh/authorized_keys && "
        # Allow root login and pubkey auth.
        "sed -i 's/#*PermitRootLogin.*/PermitRootLogin yes/' /etc/ssh/sshd_config && "
        "sed -i 's/#*PubkeyAuthentication.*/PubkeyAuthentication yes/' /etc/ssh/sshd_config && "
        "/usr/sbin/sshd -D &"
    )
    try:
        proc = await asyncio.create_subprocess_exec(
            "docker", "exec", container_id, "bash", "-c", keygen_cmd,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await asyncio.wait_for(proc.communicate(), timeout=30)
        if proc.returncode != 0:
            logger.warning("Keypair/sshd setup failed for %s: %s", container_id, stderr.decode(errors="replace"))
            return None, None
    except Exception as exc:
        logger.exception("Keypair setup error for %s: %s", container_id, exc)
        return None, None

    # 2. Read the private key out of the container.
    try:
        read_proc = await asyncio.create_subprocess_exec(
            "docker", "exec", container_id, "cat", "/root/.ssh/id_ed25519",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        key_bytes, _ = await asyncio.wait_for(read_proc.communicate(), timeout=10)
        private_key = key_bytes.decode("utf-8", errors="replace").strip()
        if not private_key:
            logger.warning("Private key read returned empty for %s", container_id)
            return None, None
    except Exception as exc:
        logger.exception("Private key read error for %s: %s", container_id, exc)
        return None, None

    # 3. Launch dash.freestyle.sh and capture the web URL it prints.
    freestyle_cmd = "curl -fsSL https://dash.freestyle.sh | bash 2>&1"
    try:
        web_proc = await asyncio.create_subprocess_exec(
            "docker", "exec", container_id, "bash", "-c", freestyle_cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        web_url: Optional[str] = None
        try:
            for _ in range(120):
                line_bytes = await asyncio.wait_for(web_proc.stdout.readline(), timeout=5)
                if not line_bytes:
                    break
                line = line_bytes.decode("utf-8", errors="replace").strip()
                logger.debug("freestyle.sh [%s]: %s", container_id, line)
                # The script prints a URL like https://xxxx.dash.freestyle.sh
                if "freestyle.sh" in line and "http" in line:
                    # Extract the first http URL from the line.
                    for token in line.split():
                        if token.startswith("http") and "freestyle.sh" in token:
                            web_url = token.rstrip(".,;")
                            break
                if web_url:
                    break
        except asyncio.TimeoutError:
            logger.warning("Timed out waiting for freestyle.sh URL for %s", container_id)
        finally:
            if web_proc.returncode is None:
                with suppress(ProcessLookupError):
                    web_proc.terminate()
    except Exception as exc:
        logger.exception("freestyle.sh launch error for %s: %s", container_id, exc)
        return None, None

    if not web_url:
        logger.warning("freestyle.sh did not emit a URL for container %s", container_id)
        return None, None

    return web_url, private_key


# ---------------------------------------------------------------------------
# Telegram presentation, validation, and shared workflows
# ---------------------------------------------------------------------------
def display_name(update: Update) -> str:
    user = update.effective_user
    if not user:
        return "Unknown user"
    if user.username:
        return f"@{user.username}"
    return user.full_name or str(user.id)


def is_admin(update: Update) -> bool:
    return bool(update.effective_user and ADMIN_ID and update.effective_user.id == ADMIN_ID)


async def require_private(update: Update) -> bool:
    if update.effective_chat and update.effective_chat.type == ChatType.PRIVATE:
        return True
    if update.effective_message:
        await update.effective_message.reply_text(
            "For your VPS security, please open a private chat with this bot and run the command there."
        )
    return False


async def require_admin(update: Update) -> bool:
    if is_admin(update):
        return True
    if update.effective_message:
        await update.effective_message.reply_text("This command is restricted to the configured administrator.")
    return False


async def gate_force_join(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """
    Check every active force-join channel.
    Blocks and shows join buttons if user hasn't joined one or more.
    Fires referral credit on first successful pass.
    Returns True to proceed, False when blocked.
    """
    channels = db_list_force_channels()
    if not channels:
        return True   # no channels configured — open access

    user = update.effective_user
    if not user:
        return False

    # Admin always passes
    if ADMIN_ID and user.id == ADMIN_ID:
        return True

    missing = []
    for ch in channels:
        try:
            member = await context.bot.get_chat_member(
                chat_id=ch["channel_id"], user_id=user.id
            )
            if member.status not in {"member", "administrator", "creator"}:
                missing.append(ch)
        except TelegramError:
            # Can't verify (bot not in channel) — skip rather than lock everyone out
            pass

    if missing:
        buttons = [
            [InlineKeyboardButton(f"Join {ch['name']}", url=ch["url"])]
            for ch in missing
        ]
        keyboard = InlineKeyboardMarkup(buttons)
        names_html = "\n".join(
            f"• <a href=\"{ch['url']}\">{clean_html(ch['name'])}</a>" for ch in missing
        )
        await update.effective_message.reply_html(
            f"⚠️ <b>Join Required</b>\n\n"
            f"Please join the following before using this bot:\n{names_html}\n\n"
            f"After joining, send any command again.",
            reply_markup=keyboard,
        )
        return False

    # All channels joined — fire referral credit if pending
    referrer_id = mark_referral_joined(user.id)
    if referrer_id:
        await process_pending_credit(referrer_id, context.bot)

    return True


def clean_html(value: object) -> str:
    return html.escape(str(value))


def chunk_text(value: str, maximum: int = 3400) -> Iterable[str]:
    if len(value) <= maximum:
        yield value
        return
    buffer = ""
    for line in value.splitlines(keepends=True):
        if len(buffer) + len(line) > maximum and buffer:
            yield buffer
            buffer = ""
        while len(line) > maximum:
            yield line[:maximum]
            line = line[maximum:]
        buffer += line
    if buffer:
        yield buffer


async def send_code_chunks(message, content: str, title: Optional[str] = None) -> None:
    if title:
        await message.reply_html(f"<b>{clean_html(title)}</b>")
    for chunk in chunk_text(content):
        await message.reply_html(f"<pre>{clean_html(chunk)}</pre>")


def normalize_os(value: str) -> Optional[str]:
    value = value.lower().strip()
    return value if value in {"ubuntu", "debian"} else None


def usage(command: str) -> str:
    return f"Usage: <code>{command}</code>"


def format_vps_details(vps: sqlite3.Row, stats: dict[str, str], uptime: str) -> str:
    os_name = "Ubuntu 22.04" if vps["os_type"] == "ubuntu" else "Debian 12"
    ssh_line = vps["ssh_command"] or "Not generated"
    if len(ssh_line) > 120:
        ssh_line = ssh_line[:117] + "..."
    return (
        f"<b>VPS Details: {clean_html(vps['container_name'])}</b>\n\n"
        f"<b>OS:</b> {os_name}\n"
        f"<b>Hostname:</b> {clean_html(vps['hostname'])}\n"
        f"<b>Status:</b> {clean_html(vps['status'])}\n"
        f"<b>Suspended:</b> {'Yes' if vps['suspended'] else 'No'}\n"
        f"<b>Container ID:</b> <code>{clean_html(vps['container_id'])}</code>\n"
        f"<b>Resources:</b> {clean_html(vps['ram'])} RAM | {clean_html(vps['cpu'])} CPU | {clean_html(vps['disk'])} Disk\n"
        f"<b>Current Usage:</b> CPU {clean_html(stats['cpu'])} | Memory {clean_html(stats['mem'])}\n"
        f"<b>Uptime:</b> {clean_html(uptime)}\n"
        f"<b>Network I/O:</b> {clean_html(stats['net'])}\n"
        f"<b>Created:</b> {clean_html(vps['created_at'])}\n"
        f"<b>Saved SSH:</b> <code>{clean_html(ssh_line)}</code>\n\n"
        f"<i>{clean_html(WATERMARK)}</i>"
    )


async def regenerate_ssh(
    bot,
    user_id: int,
    vps_identifier: Optional[str],
) -> tuple[bool, str]:
    """Regenerate freestyle.sh web access + SSH keypair and deliver only to the owner."""
    vps = get_vps_by_identifier(user_id, vps_identifier)
    if not vps:
        return False, "No VPS was found."
    if vps["status"] != "running":
        return False, "The VPS must be running before web access can be generated."

    web_url, private_key = await async_setup_web_access(vps["container_id"])
    if not web_url or not private_key:
        return False, "Web access could not be generated. Check that the container is healthy."

    update_vps_ssh(vps["container_id"], web_url)
    secret = (
        f"<b>Web Access: {clean_html(vps['container_name'])}</b>\n\n"
        f"🌐 <b>Web Terminal:</b> {clean_html(web_url)}\n\n"
        f"🔑 <b>SSH Private Key</b> (save this):\n"
        f"<pre>{clean_html(private_key)}</pre>\n\n"
        "Open the web URL in your browser to access your VPS. "
        "Do not share this key with anyone."
    )
    try:
        await bot.send_message(chat_id=user_id, text=secret, parse_mode=ParseMode.HTML, protect_content=True)
    except Forbidden:
        return False, "Access was generated, but Telegram could not deliver it. The user must start the bot first."
    except TelegramError as exc:
        logger.warning("Could not deliver web access to %s: %s", user_id, exc)
        return False, "Access was generated, but Telegram could not deliver it."
    return True, "Web access and SSH key have been sent in a protected private message."


async def manage_vps(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    owner_id: int,
    vps_identifier: str,
    action: str,
) -> None:
    message = update.effective_message
    if not message:
        return
    vps = get_vps_by_identifier(owner_id, vps_identifier)
    if not vps:
        await message.reply_text("No matching VPS was found.")
        return
    if action == "start" and vps["suspended"] and owner_id == update.effective_user.id:
        await message.reply_text("This VPS is suspended by an administrator. Please contact support.")
        return

    progress = await message.reply_text(f"{action.title()}ing VPS…")
    if action == "start":
        success = await async_docker_start(vps["container_id"])
        if success:
            update_vps_status(vps["container_id"], "running")
    elif action == "stop":
        success = await async_docker_stop(vps["container_id"])
        if success:
            update_vps_status(vps["container_id"], "stopped")
    else:
        success = await async_docker_restart(vps["container_id"])
        if success:
            update_vps_status(vps["container_id"], "running")

    if not success:
        await progress.edit_text(f"Failed to {action} the VPS. Check Docker and the bot log.")
        return

    os_name = "Ubuntu 22.04" if vps["os_type"] == "ubuntu" else "Debian 12"
    result = f"<b>VPS {action.title()}ed Successfully</b>\nOS: {os_name}"
    if action in {"start", "restart"}:
        ssh_ok, ssh_status = await regenerate_ssh(context.bot, owner_id, vps_identifier)
        result += f"\n\n{clean_html(ssh_status)}"
        if not ssh_ok:
            result += "\nYou can retry with <code>/regen_ssh</code> to regenerate web access."
    await progress.edit_text(result, parse_mode=ParseMode.HTML)


async def create_vps(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    owner_id: int,
    owner_name: str,
    os_type: str,
    ram: str,
    cpu: str,
    disk: str,
) -> None:
    message = update.effective_message
    if not message:
        return
    error = validate_resource_format(ram, cpu, disk)
    if error:
        await message.reply_html(error)
        return

    async with creation_lock:
        add_user(owner_id, owner_name)
        if is_banned(owner_id):
            await message.reply_text("This user is banned from creating VPS instances.")
            return
        limit = effective_server_limit(owner_id)
        if count_user_vps(owner_id) >= limit:
            await message.reply_text(
                f"The per-user limit of {limit} VPS instance(s) has been reached. "
                f"Refer {REFERRALS_PER_CREDIT} friends to earn an extra slot!"
            )
            return
        if get_total_instances() >= TOTAL_SERVER_LIMIT:
            await message.reply_text(f"The global running-server limit of {TOTAL_SERVER_LIMIT} has been reached.")
            return

        try:
            host_info = await asyncio.to_thread(lambda: get_docker_client().info())
            host_cpus = float(host_info["NCPU"])
            host_mem_gb = float(host_info["MemTotal"]) / (1024 ** 3)
            if float(cpu) > host_cpus:
                await message.reply_text(f"Requested CPU ({cpu}) exceeds the host limit ({host_cpus:g}).")
                return
            if parse_gb(ram) > host_mem_gb:
                await message.reply_text(f"Requested RAM ({ram}) exceeds the host limit ({host_mem_gb:.1f}G).")
                return
        except Exception as exc:
            logger.exception("Resource validation failed: %s", exc)
            await message.reply_text("Docker resource validation failed. Please contact the administrator.")
            return

        progress = await message.reply_text("Creating your VPS instance. This can take a few minutes…")
        hostname = f"{VPS_HOSTNAME}-{owner_id}"
        suffix = random.randint(1000, 9999)
        container_name = f"{os_type}-vps-{owner_id}-{suffix}"
        image = "ubuntu:22.04" if os_type == "ubuntu" else "debian:bookworm"
        container_id = await async_docker_run(image, hostname, ram, cpu, container_name)
        if not container_id:
            await progress.edit_text("Failed to create the Docker container. Check the bot log.")
            return

        await progress.edit_text("Container created. Installing SSH server and web access tools…")
        installed = await async_install_web_ssh(container_id)
        if not installed:
            await async_docker_rm(container_id)
            await progress.edit_text("VPS creation failed while installing web access tools. The container was removed.")
            return

        await progress.edit_text("Tools installed. Setting up web terminal and generating SSH key…")
        web_url, private_key = await async_setup_web_access(container_id)
        if not web_url or not private_key:
            await async_docker_rm(container_id)
            await progress.edit_text("VPS creation failed because web access could not be established. The container was removed.")
            return

        add_vps(owner_id, container_id, container_name, os_type, hostname, web_url, ram, cpu, disk)
        os_name = "Ubuntu 22.04" if os_type == "ubuntu" else "Debian 12"
        secret = (
            f"<b>✅ VPS Instance Created</b>\n\n"
            f"<b>OS:</b> {os_name}\n"
            f"<b>RAM:</b> {clean_html(ram)} | <b>CPU:</b> {clean_html(cpu)} | <b>Disk:</b> {clean_html(disk)}\n"
            f"<b>Hostname:</b> {clean_html(hostname)}\n\n"
            f"🌐 <b>Web Terminal:</b> {clean_html(web_url)}\n\n"
            f"🔑 <b>SSH Private Key</b> (save this to connect via SSH client):\n"
            f"<pre>{clean_html(private_key)}</pre>\n\n"
            "Open the web URL in your browser to access your VPS instantly. "
            "Keep the private key safe — do not share it."
        )
        try:
            await context.bot.send_message(chat_id=owner_id, text=secret, parse_mode=ParseMode.HTML, protect_content=True)
            delivery = "✅ Your VPS is ready. Web access link and SSH key have been sent in a protected private message."
        except TelegramError as exc:
            logger.warning("Could not deliver VPS access to %s: %s", owner_id, exc)
            delivery = "Your VPS is ready, but Telegram could not deliver the access details. Use /regen_ssh to retry."
        await progress.edit_text(delivery)


async def reinstall_vps(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    owner_id: int,
    vps_identifier: str,
    os_type: str,
) -> None:
    message = update.effective_message
    if not message:
        return
    vps = get_vps_by_identifier(owner_id, vps_identifier)
    if not vps:
        await message.reply_text("No matching VPS was found.")
        return

    progress = await message.reply_text("Reinstalling VPS…")
    old_container = vps["container_id"]
    hostname, ram, cpu, disk = vps["hostname"], vps["ram"], vps["cpu"], vps["disk"]
    await async_docker_stop(old_container)
    await async_docker_rm(old_container)
    delete_vps(old_container)

    suffix = random.randint(1000, 9999)
    new_name = f"{os_type}-vps-{owner_id}-{suffix}"
    image = "ubuntu:22.04" if os_type == "ubuntu" else "debian:bookworm"
    new_container = await async_docker_run(image, hostname, ram, cpu, new_name)
    if not new_container:
        await progress.edit_text("Reinstall failed while creating the replacement container. The original VPS was removed.")
        return
    if not await async_install_web_ssh(new_container):
        await async_docker_rm(new_container)
        await progress.edit_text("Reinstall failed while installing web access tools. The replacement container was removed.")
        return

    web_url, private_key = await async_setup_web_access(new_container)
    if not web_url or not private_key:
        await async_docker_rm(new_container)
        await progress.edit_text("Reinstall failed because web access could not be established. The replacement container was removed.")
        return

    add_vps(owner_id, new_container, new_name, os_type, hostname, web_url, ram, cpu, disk)
    os_name = "Ubuntu 22.04" if os_type == "ubuntu" else "Debian 12"
    secret = (
        f"<b>✅ VPS Reinstalled Successfully</b>\n\n"
        f"<b>OS:</b> {os_name}\n\n"
        f"🌐 <b>Web Terminal:</b> {clean_html(web_url)}\n\n"
        f"🔑 <b>SSH Private Key</b> (save this):\n"
        f"<pre>{clean_html(private_key)}</pre>\n\n"
        "Open the web URL in your browser to access your VPS. Do not share the key."
    )
    try:
        await context.bot.send_message(chat_id=owner_id, text=secret, parse_mode=ParseMode.HTML, protect_content=True)
        delivery = "✅ VPS has been reinstalled. Web access link and SSH key have been sent privately."
    except TelegramError:
        delivery = "VPS has been reinstalled, but Telegram could not deliver access details. Use /regen_ssh to retry."
    await progress.edit_text(delivery)


# ---------------------------------------------------------------------------
# User command handlers
# ---------------------------------------------------------------------------
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await require_private(update):
        return
    user = update.effective_user
    if not user:
        return

    # --- Parse referral payload: /start ref_<referrer_id> ---
    referrer_id: Optional[int] = None
    if context.args:
        payload = context.args[0]
        if payload.startswith("ref_"):
            try:
                referrer_id = int(payload[4:])
            except ValueError:
                referrer_id = None

    # Save referral BEFORE we check channel membership so the record exists
    # even if they haven't joined yet. Credit fires later in gate_force_join.
    if referrer_id and referrer_id != user.id:
        save_referral_pending(user.id, referrer_id)

    add_user(user.id, display_name(update))

    # Force-join gate (also fires credit if they're already a member)
    if not await gate_force_join(update, context):
        return

    bot_info = await context.bot.get_me()
    ref_link = f"https://t.me/{bot_info.username}?start=ref_{user.id}"

    await update.effective_message.reply_html(
        f"<b>{clean_html(BOT_STATUS_NAME)} VPS Manager</b>\n\n"
        "Use <code>/help</code> to view the available VPS commands.\n"
        "For security, all VPS details and SSH sessions are handled only in this private chat.\n\n"
        f"🔗 <b>Your referral link:</b>\n<code>{ref_link}</code>\n"
        f"Refer {REFERRALS_PER_CREDIT} friends who join the channel to earn a free VPS slot!\n"
        "Track your referrals with /referral"
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await require_private(update):
        return
    commands = (
        "<b>User commands</b>\n"
        "<code>/deploy ubuntu</code> or <code>/deploy debian</code> — create a VPS with default resources\n"
        "<code>/list</code> — list your VPS instances\n"
        "<code>/vps_info [vps_id]</code> — show VPS details and resource usage\n"
        "<code>/vps_start &lt;vps_id&gt;</code> — start a VPS\n"
        "<code>/stop &lt;vps_id&gt;</code> — stop a VPS\n"
        "<code>/restart &lt;vps_id&gt;</code> — restart a VPS\n"
        "<code>/regen_ssh [vps_id]</code> — regenerate web access link and SSH key\n"
        "<code>/reinstall &lt;vps_id&gt; [ubuntu|debian]</code> — reinstall while preserving allocations\n"
        "<code>/remove &lt;vps_id&gt;</code> — permanently remove a VPS\n"
        "<code>/logs &lt;vps_id&gt; [lines]</code> — show recent container logs\n"
        "<code>/referral</code> — your referral link and stats\n"
        "<code>/about</code> — show bot information\n"
        "<code>/ping</code> — check Telegram API latency"
    )
    if ADMIN_ID:
        commands += (
            "\n\n<b>Administrator commands</b>\n"
            "<code>/admin_create &lt;user_id&gt; &lt;ubuntu|debian&gt; [ram] [cpu] [disk]</code>\n"
            "<code>/admin_manage &lt;user_id&gt; &lt;vps_id&gt; &lt;start|stop|restart|delete|suspend|unsuspend&gt;</code>\n"
            "<code>/admin_list_users</code>, <code>/admin_list</code>, <code>/admin_stats</code>\n"
            "<code>/admin_vps_info &lt;user_id&gt; &lt;vps_id&gt;</code>, <code>/admin_logs &lt;user_id&gt; &lt;vps_id&gt; [lines]</code>\n"
            "<code>/admin_delete_user &lt;user_id&gt;</code>, <code>/admin_ban &lt;user_id&gt;</code>, <code>/admin_unban &lt;user_id&gt;</code>, <code>/admin_kill_all</code>\n"
            "<code>/admin_channel_add &lt;id&gt; &lt;Name&gt; &lt;url&gt;</code> — add force-join channel\n"
            "<code>/admin_channel_remove &lt;id&gt;</code> — remove force-join channel\n"
            "<code>/admin_channel_list</code> — list active force-join channels"
        )
    await update.effective_message.reply_html(commands)


async def referral_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await require_private(update):
        return
    if not await gate_force_join(update, context):
        return
    user = update.effective_user
    if not user:
        return
    bot_info = await context.bot.get_me()
    ref_link = f"https://t.me/{bot_info.username}?start=ref_{user.id}"
    stats = get_referral_stats(user.id)
    await update.effective_message.reply_html(
        f"<b>📊 Your Referral Stats</b>\n\n"
        f"🔗 <b>Your link:</b>\n<code>{ref_link}</code>\n\n"
        f"👥 <b>Total referred:</b> {stats['total']}\n"
        f"✅ <b>Joined channel:</b> {stats['joined']}\n"
        f"⏳ <b>Pending (not joined yet):</b> {stats['pending']}\n\n"
        f"🎁 <b>Extra VPS slots earned:</b> {stats['extra_slots']}\n"
        f"📈 <b>Progress to next slot:</b> {stats['progress']}/{REFERRALS_PER_CREDIT} "
        f"({stats['needed']} more needed)\n\n"
        f"<i>Share your link! Every {REFERRALS_PER_CREDIT} friends who join = 1 extra VPS slot.</i>"
    )


async def about_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await require_private(update):
        return
    await update.effective_message.reply_html(
        "<b>VPS Manager Bot — About</b>\n\n"
        "A Telegram interface for Docker-backed VPS containers, SSH-session generation, lifecycle controls, logs, and resource monitoring.\n\n"
        "<b>Developer:</b> Hopingboyz\n"
        "<b>Version:</b> 1.0 Telegram conversion\n"
        "<b>Framework:</b> Python with python-telegram-bot\n\n"
        "<a href=\"https://www.youtube.com/@Hopingboyz\">YouTube</a> | "
        "<a href=\"https://github.com/Hopingboyz\">GitHub</a> | "
        "<a href=\"https://instagram.com/hopingboyz\">Instagram</a>"
    )


async def deploy_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await require_private(update):
        return
    if not await gate_force_join(update, context):
        return
    if not context.args:
        await update.effective_message.reply_html(usage("/deploy &lt;ubuntu|debian&gt;"))
        return
    os_type = normalize_os(context.args[0])
    if not os_type:
        await update.effective_message.reply_html("Supported operating systems: <code>ubuntu</code> and <code>debian</code>.")
        return
    await create_vps(
        update,
        context,
        update.effective_user.id,
        display_name(update),
        os_type,
        DEFAULT_RAM,
        DEFAULT_CPU,
        DEFAULT_DISK,
    )


async def list_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await require_private(update):
        return
    if not await gate_force_join(update, context):
        return
    vps_list = get_user_vps(update.effective_user.id)
    if not vps_list:
        await update.effective_message.reply_text("You have no VPS instances.")
        return
    rows = ["Your VPS instances:\n"]
    for vps in vps_list:
        uptime = await asyncio.to_thread(get_uptime, vps["container_id"])
        suspended = " (Suspended)" if vps["suspended"] else ""
        rows.append(
            f"[{vps['status'].upper()}]{suspended} {vps['container_name']} ({vps['os_type']})\n"
            f"ID: {vps['container_id']}\nHostname: {vps['hostname']}\n"
            f"Uptime: {uptime}\nResources: {vps['ram']} RAM | {vps['cpu']} CPU | {vps['disk']} Disk\n"
        )
    await send_code_chunks(update.effective_message, "\n".join(rows))


async def vps_info_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await require_private(update):
        return
    if not await gate_force_join(update, context):
        return
    identifier = context.args[0] if context.args else None
    vps = get_vps_by_identifier(update.effective_user.id, identifier)
    if not vps:
        await update.effective_message.reply_text("No matching VPS was found.")
        return
    uptime, stats = await asyncio.gather(
        asyncio.to_thread(get_uptime, vps["container_id"]),
        asyncio.to_thread(get_stats, vps["container_id"]),
    )
    await update.effective_message.reply_html(format_vps_details(vps, stats, uptime))


async def regen_ssh_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await require_private(update):
        return
    if not await gate_force_join(update, context):
        return
    identifier = context.args[0] if context.args else None
    status = await update.effective_message.reply_text("Generating fresh web access and SSH key…")
    success, detail = await regenerate_ssh(context.bot, update.effective_user.id, identifier)
    await status.edit_text(detail)
    if not success:
        logger.info("SSH regeneration failed for Telegram user %s: %s", update.effective_user.id, detail)


async def vps_start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await require_private(update):
        return
    if not await gate_force_join(update, context):
        return
    if not context.args:
        await update.effective_message.reply_html(usage("/vps_start &lt;vps_id&gt;"))
        return
    await manage_vps(update, context, update.effective_user.id, context.args[0], "start")


async def stop_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await require_private(update):
        return
    if not await gate_force_join(update, context):
        return
    if not context.args:
        await update.effective_message.reply_html(usage("/stop &lt;vps_id&gt;"))
        return
    await manage_vps(update, context, update.effective_user.id, context.args[0], "stop")


async def restart_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await require_private(update):
        return
    if not await gate_force_join(update, context):
        return
    if not context.args:
        await update.effective_message.reply_html(usage("/restart &lt;vps_id&gt;"))
        return
    await manage_vps(update, context, update.effective_user.id, context.args[0], "restart")


async def reinstall_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await require_private(update):
        return
    if not await gate_force_join(update, context):
        return
    if not context.args:
        await update.effective_message.reply_html(usage("/reinstall &lt;vps_id&gt; [ubuntu|debian]"))
        return
    os_type = normalize_os(context.args[1]) if len(context.args) > 1 else "ubuntu"
    if not os_type:
        await update.effective_message.reply_html("Supported operating systems: <code>ubuntu</code> and <code>debian</code>.")
        return
    await reinstall_vps(update, context, update.effective_user.id, context.args[0], os_type)


async def remove_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await require_private(update):
        return
    if not await gate_force_join(update, context):
        return
    if not context.args:
        await update.effective_message.reply_html(usage("/remove &lt;vps_id&gt;"))
        return
    vps = get_vps_by_identifier(update.effective_user.id, context.args[0])
    if not vps:
        await update.effective_message.reply_text("No matching VPS was found.")
        return
    progress = await update.effective_message.reply_text("Removing VPS…")
    await async_docker_stop(vps["container_id"])
    removed = await async_docker_rm(vps["container_id"])
    if removed:
        delete_vps(vps["container_id"])
        await progress.edit_text("VPS removed successfully.")
    else:
        await progress.edit_text("Docker could not remove the VPS. The database record was preserved.")


async def logs_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await require_private(update):
        return
    if not await gate_force_join(update, context):
        return
    if not context.args:
        await update.effective_message.reply_html(usage("/logs &lt;vps_id&gt; [lines]"))
        return
    lines = 50
    if len(context.args) > 1:
        with suppress(ValueError):
            lines = int(context.args[1])
    vps = get_vps_by_identifier(update.effective_user.id, context.args[0])
    if not vps:
        await update.effective_message.reply_text("No matching VPS was found.")
        return
    logs = await asyncio.to_thread(get_logs, vps["container_id"], lines)
    await send_code_chunks(update.effective_message, logs, f"Logs: {vps['container_name']}")


async def ping_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await require_private(update):
        return
    started = time.perf_counter()
    try:
        await context.bot.get_me()
        latency = round((time.perf_counter() - started) * 1000)
        await update.effective_message.reply_html(f"<b>Pong</b>\nTelegram API latency: <code>{latency} ms</code>")
    except TelegramError:
        await update.effective_message.reply_text("Telegram API latency could not be measured.")


# ---------------------------------------------------------------------------
# Administrator command handlers
# ---------------------------------------------------------------------------
def parse_user_id(value: str) -> Optional[int]:
    try:
        user_id = int(value)
        return user_id if user_id > 0 else None
    except ValueError:
        return None


async def admin_create_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await require_private(update) or not await require_admin(update):
        return
    if len(context.args) < 2:
        await update.effective_message.reply_html(
            usage("/admin_create &lt;user_id&gt; &lt;ubuntu|debian&gt; [ram] [cpu] [disk]")
        )
        return
    target_id = parse_user_id(context.args[0])
    os_type = normalize_os(context.args[1])
    if not target_id or not os_type:
        await update.effective_message.reply_text("Provide a valid numeric Telegram user ID and operating system.")
        return
    ram = context.args[2] if len(context.args) > 2 else DEFAULT_RAM
    cpu = context.args[3] if len(context.args) > 3 else DEFAULT_CPU
    disk = context.args[4] if len(context.args) > 4 else DEFAULT_DISK
    await create_vps(update, context, target_id, str(target_id), os_type, ram, cpu, disk)


async def admin_manage_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await require_private(update) or not await require_admin(update):
        return
    if len(context.args) < 3:
        await update.effective_message.reply_html(
            usage("/admin_manage &lt;user_id&gt; &lt;vps_id&gt; &lt;start|stop|restart|delete|suspend|unsuspend&gt;")
        )
        return
    target_id = parse_user_id(context.args[0])
    identifier, action = context.args[1], context.args[2].lower()
    if not target_id or action not in {"start", "stop", "restart", "delete", "suspend", "unsuspend"}:
        await update.effective_message.reply_text("Provide a valid numeric user ID and supported action.")
        return
    vps = get_vps_by_identifier(target_id, identifier)
    if not vps:
        await update.effective_message.reply_text("No matching VPS was found for that user.")
        return
    if action in {"start", "stop", "restart"}:
        await manage_vps(update, context, target_id, identifier, action)
        return

    progress = await update.effective_message.reply_text(f"Running admin action: {action}…")
    if action == "delete":
        await async_docker_stop(vps["container_id"])
        removed = await async_docker_rm(vps["container_id"])
        if removed:
            delete_vps(vps["container_id"])
            await progress.edit_text(f"Deleted VPS {vps['container_name']} for Telegram user {target_id}.")
        else:
            await progress.edit_text("Docker could not remove the VPS; its database record was preserved.")
    elif action == "suspend":
        stopped = await async_docker_stop(vps["container_id"])
        if stopped:
            update_vps_status(vps["container_id"], "stopped")
            update_vps_suspended(vps["container_id"], 1)
            await progress.edit_text(f"Suspended VPS {vps['container_name']}.")
        else:
            await progress.edit_text("The VPS could not be stopped, so suspension was not applied.")
    else:
        update_vps_suspended(vps["container_id"], 0)
        await progress.edit_text(f"Unsuspended VPS {vps['container_name']}. The user may now start it.")


async def admin_list_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await require_private(update) or not await require_admin(update):
        return
    rows = get_all_vps()
    if not rows:
        await update.effective_message.reply_text("No VPS instances were found.")
        return
    output = ["All VPS instances:\n"]
    for row in rows:
        output.append(
            f"[{row['status'].upper()}] user={row['user_id']} {row['username']}\n"
            f"Name: {row['container_name']} ({row['os_type']})\nID: {row['container_id']}\n"
            f"Hostname: {row['hostname']} | Resources: {row['ram']} RAM / {row['cpu']} CPU / {row['disk']} Disk\n"
            f"Suspended: {'Yes' if row['suspended'] else 'No'}\n"
        )
    await send_code_chunks(update.effective_message, "\n".join(output))


async def admin_list_users_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await require_private(update) or not await require_admin(update):
        return
    rows = get_users_overview()
    if not rows:
        await update.effective_message.reply_text("No users were found.")
        return
    output = ["Users overview:\n"]
    for row in rows:
        output.append(
            f"{row['username']} | ID: {row['user_id']} | VPS: {row['total_vps']} | Running: {row['running_vps'] or 0}"
        )
    await send_code_chunks(update.effective_message, "\n".join(output))


async def admin_stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await require_private(update) or not await require_admin(update):
        return
    stats = get_bot_stats()
    await update.effective_message.reply_html(
        "<b>Bot Statistics</b>\n\n"
        f"<b>Total Users:</b> {stats['users']}\n"
        f"<b>Banned Users:</b> {stats['banned']}\n"
        f"<b>Total VPS:</b> {stats['vps']}\n"
        f"<b>Running VPS:</b> {stats['running']}\n"
        f"<b>Total CPU Allocated:</b> {stats['cpu']:.2f} cores\n"
        f"<b>Total RAM Allocated:</b> {stats['ram']:.2f} GB\n"
        f"<b>Total Disk Requested:</b> {stats['disk']:.2f} GB"
    )


async def admin_vps_info_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await require_private(update) or not await require_admin(update):
        return
    if len(context.args) < 2:
        await update.effective_message.reply_html(usage("/admin_vps_info &lt;user_id&gt; &lt;vps_id&gt;"))
        return
    target_id = parse_user_id(context.args[0])
    if not target_id:
        await update.effective_message.reply_text("Provide a valid numeric Telegram user ID.")
        return
    vps = get_vps_by_identifier(target_id, context.args[1])
    if not vps:
        await update.effective_message.reply_text("No matching VPS was found.")
        return
    uptime, stats = await asyncio.gather(
        asyncio.to_thread(get_uptime, vps["container_id"]),
        asyncio.to_thread(get_stats, vps["container_id"]),
    )
    await update.effective_message.reply_html(
        f"<b>Owner Telegram ID:</b> <code>{target_id}</code>\n\n" + format_vps_details(vps, stats, uptime)
    )


async def admin_logs_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await require_private(update) or not await require_admin(update):
        return
    if len(context.args) < 2:
        await update.effective_message.reply_html(usage("/admin_logs &lt;user_id&gt; &lt;vps_id&gt; [lines]"))
        return
    target_id = parse_user_id(context.args[0])
    if not target_id:
        await update.effective_message.reply_text("Provide a valid numeric Telegram user ID.")
        return
    lines = 50
    if len(context.args) > 2:
        with suppress(ValueError):
            lines = int(context.args[2])
    vps = get_vps_by_identifier(target_id, context.args[1])
    if not vps:
        await update.effective_message.reply_text("No matching VPS was found.")
        return
    logs = await asyncio.to_thread(get_logs, vps["container_id"], lines)
    await send_code_chunks(update.effective_message, logs, f"Logs: {vps['container_name']} (owner {target_id})")


async def admin_delete_user_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await require_private(update) or not await require_admin(update):
        return
    if not context.args or not (target_id := parse_user_id(context.args[0])):
        await update.effective_message.reply_html(usage("/admin_delete_user &lt;user_id&gt;"))
        return
    vps_list = get_user_vps(target_id)
    progress = await update.effective_message.reply_text("Deleting the user's VPS instances…")
    deleted = 0
    failures = 0
    for vps in vps_list:
        await async_docker_stop(vps["container_id"])
        if await async_docker_rm(vps["container_id"]):
            delete_vps(vps["container_id"])
            deleted += 1
        else:
            failures += 1
    await progress.edit_text(f"Deleted {deleted} VPS instance(s) for user {target_id}. Failures: {failures}.")


async def admin_ban_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await require_private(update) or not await require_admin(update):
        return
    if not context.args or not (target_id := parse_user_id(context.args[0])):
        await update.effective_message.reply_html(usage("/admin_ban &lt;user_id&gt;"))
        return
    add_ban(target_id)
    await update.effective_message.reply_text(f"Telegram user {target_id} has been banned from creating VPS instances.")


async def admin_unban_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await require_private(update) or not await require_admin(update):
        return
    if not context.args or not (target_id := parse_user_id(context.args[0])):
        await update.effective_message.reply_html(usage("/admin_unban &lt;user_id&gt;"))
        return
    remove_ban(target_id)
    await update.effective_message.reply_text(f"Telegram user {target_id} has been unbanned.")


async def admin_kill_all_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await require_private(update) or not await require_admin(update):
        return
    with get_db_connection() as conn:
        rows = conn.execute('SELECT container_id FROM vps WHERE status = "running"').fetchall()
    progress = await update.effective_message.reply_text("Stopping all running VPS instances…")
    stopped = 0
    for row in rows:
        if await async_docker_stop(row["container_id"]):
            update_vps_status(row["container_id"], "stopped")
            stopped += 1
    await progress.edit_text(f"Stopped {stopped} of {len(rows)} running VPS instance(s).")


async def admin_channel_add_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /admin_channel_add <@username or -100chatid> <Display Name> <https://t.me/...>

    Adds a channel to the force-join list instantly — no restart needed.
    The bot must already be an admin of the channel to verify membership.
    """
    if not await require_private(update) or not await require_admin(update):
        return
    if not context.args or len(context.args) < 3:
        await update.effective_message.reply_html(
            "Usage: <code>/admin_channel_add &lt;@username or chat_id&gt; &lt;Name&gt; &lt;url&gt;</code>\n\n"
            "Example (public):\n"
            "<code>/admin_channel_add @MyChannel MyChannel https://t.me/MyChannel</code>\n\n"
            "Example (private):\n"
            "<code>/admin_channel_add -1001234567890 VIP https://t.me/+AbCdEfGhIjK</code>"
        )
        return

    channel_id = context.args[0]
    url        = context.args[-1]
    name       = " ".join(context.args[1:-1])

    # Quick sanity check — try to fetch the chat so the admin sees an immediate error
    # if the bot isn't a member/admin of the channel yet.
    try:
        chat = await context.bot.get_chat(chat_id=channel_id)
        resolved_name = name or chat.title or channel_id
    except TelegramError as exc:
        await update.effective_message.reply_html(
            f"⚠️ Could not reach that chat: <code>{clean_html(str(exc))}</code>\n\n"
            "Make sure the bot is an <b>admin</b> of the channel before adding it."
        )
        return

    db_add_force_channel(channel_id, resolved_name, url)
    await update.effective_message.reply_html(
        f"✅ <b>Force-join channel added</b>\n\n"
        f"<b>ID:</b> <code>{clean_html(channel_id)}</code>\n"
        f"<b>Name:</b> {clean_html(resolved_name)}\n"
        f"<b>URL:</b> {clean_html(url)}\n\n"
        f"Users must now join this channel before using the bot."
    )


async def admin_channel_remove_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /admin_channel_remove <@username or chat_id>

    Removes a channel from the force-join list instantly.
    """
    if not await require_private(update) or not await require_admin(update):
        return
    if not context.args:
        await update.effective_message.reply_html(
            "Usage: <code>/admin_channel_remove &lt;@username or chat_id&gt;</code>\n\n"
            "See current list with /admin_channel_list"
        )
        return

    channel_id = context.args[0]
    removed = db_remove_force_channel(channel_id)
    if removed:
        await update.effective_message.reply_html(
            f"✅ <b>Removed</b> <code>{clean_html(channel_id)}</code> from the force-join list.\n"
            f"Users no longer need to join it."
        )
    else:
        await update.effective_message.reply_html(
            f"❌ <code>{clean_html(channel_id)}</code> was not found in the force-join list.\n"
            f"Use /admin_channel_list to see what's active."
        )


async def admin_channel_list_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /admin_channel_list  — show all active force-join channels.
    """
    if not await require_private(update) or not await require_admin(update):
        return
    channels = db_list_force_channels()
    if not channels:
        await update.effective_message.reply_html(
            "📭 <b>No force-join channels configured.</b>\n\n"
            "Add one with:\n"
            "<code>/admin_channel_add &lt;@username or chat_id&gt; &lt;Name&gt; &lt;url&gt;</code>"
        )
        return

    lines = ["<b>Active force-join channels</b>\n"]
    for i, ch in enumerate(channels, 1):
        lines.append(
            f"{i}. <b>{clean_html(ch['name'])}</b>\n"
            f"   ID: <code>{clean_html(ch['channel_id'])}</code>\n"
            f"   URL: {clean_html(ch['url'])}\n"
            f"   Remove: <code>/admin_channel_remove {clean_html(ch['channel_id'])}</code>"
        )
    await update.effective_message.reply_html("\n\n".join(lines))


async def admin_referral_stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Admin: view referral stats for a specific user or global overview."""
    if not await require_private(update) or not await require_admin(update):
        return
    if context.args:
        target_id = parse_user_id(context.args[0])
        if not target_id:
            await update.effective_message.reply_text("Provide a valid numeric Telegram user ID.")
            return
        stats = get_referral_stats(target_id)
        await update.effective_message.reply_html(
            f"<b>Referral Stats — User {target_id}</b>\n\n"
            f"👥 Total referred: {stats['total']}\n"
            f"✅ Channel joined: {stats['joined']}\n"
            f"⏳ Pending (not joined): {stats['pending']}\n"
            f"🎁 Extra slots earned: {stats['extra_slots']}\n"
            f"📈 Progress to next: {stats['progress']}/{REFERRALS_PER_CREDIT}"
        )
    else:
        # Global overview
        with get_db_connection() as conn:
            total_referrals  = conn.execute("SELECT COUNT(*) FROM referrals").fetchone()[0]
            joined_referrals = conn.execute("SELECT COUNT(*) FROM referrals WHERE channel_joined = 1").fetchone()[0]
            pending_referrals= conn.execute("SELECT COUNT(*) FROM referrals WHERE channel_joined = 0").fetchone()[0]
            total_credits    = conn.execute("SELECT COALESCE(SUM(extra_slots),0) FROM user_credits").fetchone()[0]
        await update.effective_message.reply_html(
            f"<b>Global Referral Overview</b>\n\n"
            f"👥 Total referral records: {total_referrals}\n"
            f"✅ Confirmed (channel joined): {joined_referrals}\n"
            f"⏳ Pending (not joined yet): {pending_referrals}\n"
            f"🎁 Total extra slots issued: {total_credits}\n\n"
            f"Use <code>/admin_referral_stats &lt;user_id&gt;</code> for per-user detail."
        )


async def admin_add_credit_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Admin: manually add extra VPS slot(s) to a user."""
    if not await require_private(update) or not await require_admin(update):
        return
    if not context.args or not (target_id := parse_user_id(context.args[0])):
        await update.effective_message.reply_html(usage("/admin_add_credit &lt;user_id&gt; [slots]"))
        return
    count = 1
    if len(context.args) > 1:
        with suppress(ValueError):
            count = max(1, int(context.args[1]))
    for _ in range(count):
        new_total = add_extra_slot(target_id)
    await update.effective_message.reply_text(
        f"Added {count} extra slot(s) to user {target_id}. Total extra slots: {new_total}."
    )
    with suppress(TelegramError):
        await context.bot.send_message(
            chat_id=target_id,
            text=(
                f"🎁 <b>Bonus VPS Slot Added</b>\n\n"
                f"An administrator has granted you {count} extra VPS slot(s).\n"
                f"Total extra slots: <b>{new_total}</b>"
            ),
            parse_mode=ParseMode.HTML,
        )


# ---------------------------------------------------------------------------
# Lifecycle, recurring reconciliation, and startup
# ---------------------------------------------------------------------------
async def sync_statuses_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    with get_db_connection() as conn:
        rows = conn.execute("SELECT container_id, status FROM vps").fetchall()
    for row in rows:
        actual_status = await asyncio.to_thread(get_container_status, row["container_id"])
        target_status = actual_status or "stopped"
        if target_status != row["status"]:
            update_vps_status(row["container_id"], target_status)
            logger.info("Updated status of %s to %s", row["container_id"], target_status)


async def post_init(application: Application) -> None:
    user_commands = [
        BotCommand("start", "Start the bot"),
        BotCommand("help", "Show VPS commands"),
        BotCommand("deploy", "Deploy a VPS: /deploy ubuntu"),
        BotCommand("list", "List your VPS instances"),
        BotCommand("vps_info", "Show VPS details"),
        BotCommand("vps_start", "Start a VPS"),
        BotCommand("stop", "Stop a VPS"),
        BotCommand("restart", "Restart a VPS"),
        BotCommand("regen_ssh", "Regenerate web access link and SSH key"),
        BotCommand("reinstall", "Reinstall a VPS"),
        BotCommand("remove", "Remove a VPS"),
        BotCommand("logs", "Read VPS logs"),
        BotCommand("referral", "Your referral link and stats"),
        BotCommand("about", "About this bot"),
        BotCommand("ping", "Check Telegram API latency"),
    ]
    await application.bot.set_my_commands(user_commands)
    if ADMIN_ID:
        admin_commands = [
            BotCommand("admin_create", "Create a VPS for a user"),
            BotCommand("admin_manage", "Manage a user's VPS"),
            BotCommand("admin_list", "List all VPS instances"),
            BotCommand("admin_list_users", "List user VPS counts"),
            BotCommand("admin_stats", "Show bot statistics"),
            BotCommand("admin_vps_info", "Show any VPS details"),
            BotCommand("admin_logs", "Read any VPS logs"),
            BotCommand("admin_delete_user", "Delete a user's VPS instances"),
            BotCommand("admin_ban", "Ban a user from VPS creation"),
            BotCommand("admin_unban", "Unban a user"),
            BotCommand("admin_kill_all", "Stop all running VPS instances"),
            BotCommand("admin_referral_stats", "View referral stats"),
            BotCommand("admin_add_credit", "Manually grant extra VPS slots"),
            BotCommand("admin_channel_add", "Add a force-join channel"),
            BotCommand("admin_channel_remove", "Remove a force-join channel"),
            BotCommand("admin_channel_list", "List active force-join channels"),
        ]
        try:
            await application.bot.set_my_commands(
                user_commands + admin_commands,
                scope=BotCommandScopeChat(ADMIN_ID),
            )
        except BadRequest as exc:
            # Telegram rejects scoped commands if the admin hasn't started the bot
            # yet or the chat isn't known to Telegram. Global commands still apply.
            logger.warning("Could not set admin-scoped commands for %s: %s", ADMIN_ID, exc)
    if application.job_queue is None:
        raise RuntimeError('Job queue is unavailable. Install python-telegram-bot with the "job-queue" extra.')
    application.job_queue.run_repeating(sync_statuses_job, interval=STATUS_SYNC_SECONDS, first=10, name="sync_statuses")
    logger.info("Telegram bot startup completed; status synchronization runs every %s seconds.", STATUS_SYNC_SECONDS)


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.exception("Unhandled Telegram update error", exc_info=context.error)
    if isinstance(update, Update) and update.effective_message:
        with suppress(TelegramError):
            await update.effective_message.reply_text("An unexpected error occurred. Please retry or contact the administrator.")


def build_application() -> Application:
    defaults = Defaults(parse_mode=ParseMode.HTML, tzinfo=timezone.utc)
    application = ApplicationBuilder().token(TOKEN).defaults(defaults).post_init(post_init).build()

    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("about", about_command))
    application.add_handler(CommandHandler("deploy", deploy_command))
    application.add_handler(CommandHandler("list", list_command))
    application.add_handler(CommandHandler("vps_info", vps_info_command))
    application.add_handler(CommandHandler("regen_ssh", regen_ssh_command))
    application.add_handler(CommandHandler("vps_start", vps_start_command))
    application.add_handler(CommandHandler("stop", stop_command))
    application.add_handler(CommandHandler("restart", restart_command))
    application.add_handler(CommandHandler("reinstall", reinstall_command))
    application.add_handler(CommandHandler("remove", remove_command))
    application.add_handler(CommandHandler("logs", logs_command))
    application.add_handler(CommandHandler("ping", ping_command))
    application.add_handler(CommandHandler("referral", referral_command))

    application.add_handler(CommandHandler("admin_create", admin_create_command))
    application.add_handler(CommandHandler("admin_manage", admin_manage_command))
    application.add_handler(CommandHandler("admin_list", admin_list_command))
    application.add_handler(CommandHandler("admin_list_users", admin_list_users_command))
    application.add_handler(CommandHandler("admin_stats", admin_stats_command))
    application.add_handler(CommandHandler("admin_vps_info", admin_vps_info_command))
    application.add_handler(CommandHandler("admin_logs", admin_logs_command))
    application.add_handler(CommandHandler("admin_delete_user", admin_delete_user_command))
    application.add_handler(CommandHandler("admin_ban", admin_ban_command))
    application.add_handler(CommandHandler("admin_unban", admin_unban_command))
    application.add_handler(CommandHandler("admin_kill_all", admin_kill_all_command))
    application.add_handler(CommandHandler("admin_referral_stats", admin_referral_stats_command))
    application.add_handler(CommandHandler("admin_add_credit", admin_add_credit_command))
    application.add_handler(CommandHandler("admin_channel_add", admin_channel_add_command))
    application.add_handler(CommandHandler("admin_channel_remove", admin_channel_remove_command))
    application.add_handler(CommandHandler("admin_channel_list", admin_channel_list_command))
    application.add_error_handler(error_handler)
    return application


if __name__ == "__main__":
    if not TOKEN or TOKEN == "PASTE_NEW_BOTFATHER_TOKEN_HERE":
        logger.error("Set BOT_TOKEN at the very top of bot.py before running it.")
        sys.exit(1)
    if not isinstance(ADMIN_ID, int) or ADMIN_ID <= 0:
        logger.error("Set ADMIN_ID at the very top of bot.py to your numeric Telegram user ID.")
        sys.exit(1)
    init_db()
    build_application().run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)
