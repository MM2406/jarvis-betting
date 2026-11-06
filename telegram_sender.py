import os
import requests
from typing import Optional

try:
    from telegram_formatter import send_to_sport_channel, edit_sport_channel_message
except ImportError:
    send_to_sport_channel = None
    edit_sport_channel_message = None

def split_message(text: str, max_len: int = 3500):
    """
    Teilt lange Texte an Absätzen auf, um das Telegram-Limit einzuhalten.
    """
    chunks = []
    while len(text) > max_len:
        split_idx = text.rfind("\n\n", 0, max_len)
        if split_idx == -1:
            split_idx = text.rfind("\n", 0, max_len)
        if split_idx == -1:
            split_idx = max_len
        chunks.append(text[:split_idx].strip())
        text = text[split_idx:].strip()
    if text:
        chunks.append(text)
    return chunks

def resolve_sport_from_env_var(env_var: Optional[str]) -> str:
    """Ermittelt den internen Sport-Key aus dem Namen der Umgebungsvariable."""
    if not env_var:
        return ""
    v = env_var.upper()
    if "SOCCER" in v:
        return "soccer"
    if "NBA" in v or "BASKETBALL" in v:
        return "nba"
    if "NHL" in v or "HOCKEY" in v:
        return "nhl"
    if "NFL" in v:
        return "nfl"
    if "TENNIS" in v:
        return "tennis"
    if "DARTS" in v:
        return "darts"
    if "EURO" in v:
        return "euro"
    if "COLLEGE" in v:
        return "college"
    if "MONEYRACE" in v:
        return "moneyrace"
    if "ANALYTICS" in v:
        return "analytics"
    return ""

def send_to_telegram(text: str, thread_env_var: Optional[str] = None, default_thread_id: Optional[str] = None, allow_main_chat: bool = False, reply_to: Optional[int] = None) -> Optional[int]:
    """
    Universeller Telegram-Sender. Leitet bevorzugt über telegram_formatter weiter
    und verhindert fehlerhafte Cross-Sport-Posts in fremde Kanäle.
    """
    sport = resolve_sport_from_env_var(thread_env_var)
    if sport and send_to_sport_channel:
        return send_to_sport_channel(text, sport=sport, reply_to=reply_to)

    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()

    if not token or not chat_id:
        print("[Telegram] FEHLER: Bot-Token oder Chat-ID fehlt.")
        return None

    # Strikte Thread-ID Ermittlung (KEIN wildes Vermischen von Sportarten mehr)
    thread_id = None
    if thread_env_var:
        thread_id = os.environ.get(thread_env_var, "").strip()

    if not thread_id and default_thread_id:
        thread_id = str(default_thread_id).strip()

    if not thread_id:
        thread_id = os.environ.get("TELEGRAM_THREAD_ID", "").strip()

    if not thread_id and not allow_main_chat:
        print(f"[Telegram] ABBRUCH: Keine passende Thread-ID ({thread_env_var}) gefunden. Hauptchat-Post gesperrt.")
        return None

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    chunks = split_message(text)
    first_msg_id = None

    for idx, chunk in enumerate(chunks):
        payload = {
            "chat_id": chat_id,
            "text": chunk,
            "parse_mode": "HTML",
            "disable_web_page_preview": True
        }
        if thread_id:
            try:
                payload["message_thread_id"] = int(thread_id)
            except ValueError:
                pass
        if reply_to and idx == 0:
            payload["reply_to_message_id"] = int(reply_to)

        try:
            res = requests.post(url, json=payload, timeout=25)
            if res.status_code == 200:
                m_id = res.json().get("result", {}).get("message_id")
                if first_msg_id is None:
                    first_msg_id = m_id
            else:
                payload.pop("parse_mode", None)
                res2 = requests.post(url, json=payload, timeout=25)
                if res2.status_code == 200:
                    m_id = res2.json().get("result", {}).get("message_id")
                    if first_msg_id is None:
                        first_msg_id = m_id
                else:
                    print(f"[Telegram] Send-Fehler ({res2.status_code}): {res2.text}")
        except Exception as e:
            print(f"[Telegram] Netzwerkfehler: {e}")

    return first_msg_id
