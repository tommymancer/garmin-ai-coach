#!/usr/bin/env python3
"""
Interactive installer for garmin-ai-coach.

Run it and answer the prompts:

    python3 setup.py

It creates a virtual environment, installs dependencies, writes your .env
(secrets are typed directly here — they never leave your machine), helps you
find your Telegram chat ID, and records the activity baseline.

Safe to run more than once: it won't overwrite an existing .env unless you say so.
"""

import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from getpass import getpass
from pathlib import Path

REPO = Path(__file__).resolve().parent
ENV_PATH = REPO / ".env"
IS_WINDOWS = os.name == "nt"
VENV_DIR = REPO / ".venv"
VENV_PYTHON = VENV_DIR / ("Scripts" if IS_WINDOWS else "bin") / (
    "python.exe" if IS_WINDOWS else "python"
)


def info(msg):
    print(f"\n\033[1m{msg}\033[0m" if sys.stdout.isatty() else f"\n{msg}")


def ok(msg):
    print(f"  ✅ {msg}")


def warn(msg):
    print(f"  ⚠️  {msg}")


def die(msg):
    print(f"\n❌ {msg}\n")
    sys.exit(1)


# --------------------------------------------------------------------------- steps
def check_python():
    if sys.version_info < (3, 10):
        die(f"Python 3.10+ required, you have {sys.version.split()[0]}.")
    ok(f"Python {sys.version.split()[0]}")


def make_venv():
    if VENV_PYTHON.exists():
        ok("virtual environment already exists")
        return
    info("Creating virtual environment (.venv)...")
    subprocess.run([sys.executable, "-m", "venv", str(VENV_DIR)], check=True)
    ok("virtual environment created")


def install_deps():
    info("Installing dependencies...")
    subprocess.run([str(VENV_PYTHON), "-m", "pip", "install", "-q", "--upgrade", "pip"],
                   check=True)
    subprocess.run([str(VENV_PYTHON), "-m", "pip", "install", "-q", "-r",
                    str(REPO / "requirements.txt")], check=True)
    ok("dependencies installed (anthropic, garminconnect)")


def _telegram_call(token, method, params=None):
    url = f"https://api.telegram.org/bot{token}/{method}"
    data = json.dumps(params).encode() if params else None
    headers = {"Content-Type": "application/json"} if data else {}
    request = urllib.request.Request(url, data=data, headers=headers)
    with urllib.request.urlopen(request, timeout=20) as response:
        return json.loads(response.read())


def validate_bot_token(token):
    try:
        result = _telegram_call(token, "getMe")
        if result.get("ok"):
            return result["result"].get("username")
    except urllib.error.HTTPError:
        pass
    except Exception as exc:
        warn(f"couldn't reach Telegram: {exc}")
    return None


def find_chat_id(token):
    """Poll getUpdates until the user has messaged the bot."""
    print("\n  Now open Telegram, find your bot, and send it any message.")
    input("  Press Enter here once you've sent a message... ")
    for _ in range(3):
        try:
            updates = _telegram_call(token, "getUpdates").get("result", [])
        except Exception:
            updates = []
        chats = {}
        for update in updates:
            message = update.get("message") or update.get("edited_message") or {}
            chat = message.get("chat") or {}
            if chat.get("id"):
                chats[chat["id"]] = chat
        if chats:
            if len(chats) == 1:
                chat_id, chat = next(iter(chats.items()))
                name = (chat.get("first_name") or "").strip()
                ok(f"found your chat: {name} (id {chat_id})")
                return str(chat_id)
            print("  Found several chats:")
            for chat_id, chat in chats.items():
                print(f"    {chat_id}  {chat.get('first_name', '')}")
            return input("  Paste the chat ID you want to allow: ").strip()
        print("  No message seen yet — send one to the bot, then press Enter.")
        input("  ... ")
    warn("Couldn't find a message. You can add TELEGRAM_CHAT_ID to .env by hand later.")
    return ""


def write_env():
    if ENV_PATH.exists():
        answer = input(f"\n.env already exists. Overwrite it? [y/N] ").strip().lower()
        if answer != "y":
            ok("keeping your existing .env")
            return

    info("Let's fill in your settings. Secrets are written straight to .env "
         "on this machine — nothing is sent anywhere.")

    print("\n1) Garmin Connect login")
    garmin_email = input("   Garmin email: ").strip()
    garmin_password = getpass("   Garmin password (hidden): ")

    print("\n2) Telegram bot")
    print("   Create one: open Telegram, message @BotFather, send /newbot,")
    print("   pick a name and username, and copy the token he gives you.")
    while True:
        telegram_token = getpass("   Bot token (hidden): ").strip()
        username = validate_bot_token(telegram_token)
        if username:
            ok(f"bot @{username} is valid")
            break
        warn("that token didn't work — double-check and paste it again.")

    chat_id = find_chat_id(telegram_token)

    print("\n3) Claude API key")
    print("   Get one at https://console.anthropic.com  →  API keys")
    anthropic_key = getpass("   API key (hidden): ").strip()

    print("\n4) Preferences (press Enter for defaults)")
    language = input("   Language the coach writes in [English]: ").strip() or "English"
    model = input("   Model [claude-sonnet-5]: ").strip() or "claude-sonnet-5"

    ENV_PATH.write_text(
        f"GARMIN_EMAIL={garmin_email}\n"
        f"GARMIN_PASSWORD={garmin_password}\n"
        f"TELEGRAM_BOT_TOKEN={telegram_token}\n"
        f"TELEGRAM_CHAT_ID={chat_id}\n"
        f"ANTHROPIC_API_KEY={anthropic_key}\n"
        f"COACH_LANGUAGE={language}\n"
        f"COACH_MODEL={model}\n"
    )
    try:
        ENV_PATH.chmod(0o600)
    except OSError:
        pass
    ok(f".env written to {ENV_PATH}")


def record_baseline():
    answer = input("\nRecord your Garmin baseline now? (recommended) [Y/n] ").strip().lower()
    if answer == "n":
        return
    info("Logging in to Garmin and recording a baseline...")
    result = subprocess.run([str(VENV_PYTHON), "-m", "coach.feedback"], cwd=str(REPO))
    if result.returncode == 0:
        ok("baseline recorded — no spam for old workouts")
    else:
        warn("that didn't finish cleanly — check the output above.")


def final_instructions():
    py = VENV_PYTHON.relative_to(REPO) if not IS_WINDOWS else VENV_PYTHON
    info("Done! To run the coach:")
    print(f"\n  Feedback after each workout (run on a schedule):")
    print(f"      {py} -m coach.feedback")
    print(f"\n  Chat with your coach (keep this running):")
    print(f"      {py} -m coach.chat")
    print(f"\n  To keep both running automatically, see deploy/README.md")
    print(f"\n  Then message your bot on Telegram — try 'how am I doing?'\n")


def main():
    print("=" * 60)
    print("  garmin-ai-coach — setup")
    print("=" * 60)
    check_python()
    make_venv()
    install_deps()
    write_env()
    record_baseline()
    final_instructions()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        die("cancelled.")
    except subprocess.CalledProcessError as exc:
        die(f"a command failed: {exc}")
