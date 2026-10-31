import os
import requests

def send_to_telegram(text, thread_env_var=None, default_thread_id=None):
    """
    Sendet Nachrichten strikt in das vorgesehene Forum-Topic.
    Verhindert das unabsichtliche Posten in den Hauptchat.
    """
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()

    if not token or not chat_id:
        print("[Telegram] FEHLER: Bot-Token oder Chat-ID nicht konfiguriert.")
        return None

    # Thread-ID aus Umgebungsvariablen ermitteln
    thread_id = None
    if thread_env_var:
        thread_id = os.environ.get(thread_env_var, "").strip()
    
    if not thread_id:
        thread_id = (
            os.environ.get("TELEGRAM_THREAD_ID", "").strip()
            or default_thread_id
        )

    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True
    }

    if thread_id:
        try:
            payload["message_thread_id"] = int(thread_id)
        except ValueError:
            print(f"[Telegram] Ungueltige Thread-ID: {thread_id}")

    url = f"https://api.telegram.org/bot{token}/sendMessage"

    try:
        res = requests.post(url, json=payload, timeout=25)
        if res.status_code == 200:
            return res.json().get("result", {}).get("message_id")
        else:
            # Fallback ohne HTML-Formatting falls Tags fehlerhaft waren
            print(f"[Telegram] HTML-Senden fehlgeschlagen ({res.status_code}). Sende Text plain...")
            payload.pop("parse_mode", None)
            res2 = requests.post(url, json=payload, timeout=25)
            if res2.status_code == 200:
                return res2.json().get("result", {}).get("message_id")
            else:
                print(f"[Telegram] API-Fehler: {res2.text}")
    except Exception as e:
        print(f"[Telegram] Netzwerkfehler: {e}")
    return None
