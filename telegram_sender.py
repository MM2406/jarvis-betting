import os
import requests

def split_message(text, max_len=3500):
    """
    Teilt lange Texte sauber an Absätzen oder Zeilenumbrüchen auf,
    um das 4096-Zeichen-Limit der Telegram Bot API nicht zu überschreiten.
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

def send_to_telegram(text, thread_env_var=None, default_thread_id=None, allow_main_chat=False):
    """
    Sendet Nachrichten strikt in das vorgesehene Forum-Topic.
    Verhindert das unabsichtliche Posten in den Hauptchat.
    Teilt Texte automatisch auf, falls sie zu lang sind.
    """
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()

    if not token or not chat_id:
        print("[Telegram] FEHLER: Bot-Token oder Chat-ID nicht konfiguriert.")
        return None

    # 1. Direkte Variable prüfen, falls übergeben
    thread_id = None
    if thread_env_var:
        thread_id = os.environ.get(thread_env_var, "").strip()

    # 2. Automatische Fallback-Kette über deine exakten GitHub-Secret-Namen
    if not thread_id:
        thread_id = (
            os.environ.get("TELEGRAM_THREAD_ID", "").strip()
            or os.environ.get("TELEGRAM_THREAD_SOCCER", "").strip()
            or os.environ.get("TELEGRAM_THREAD_NBA", "").strip()
            or os.environ.get("TELEGRAM_THREAD_NHL", "").strip()
            or os.environ.get("TELEGRAM_THREAD_NFL", "").strip()
            or os.environ.get("TELEGRAM_DARTS_THREAD_ID", "").strip()
            or os.environ.get("TELEGRAM_COLLEGE_THREAD_ID", "").strip()
            or os.environ.get("TELEGRAM_EURO_THREAD_ID", "").strip()
            or os.environ.get("TELEGRAM_MONEYRACE_THREAD_ID", "").strip()
            or (str(default_thread_id).strip() if default_thread_id else None)
        )

    # 3. Schutz vor ungewolltem Hauptchat-Posten
    if not thread_id and not allow_main_chat:
        print("[Telegram] ABBRUCH: Keine Thread-ID ermittelt! Nachricht wird NICHT in den Hauptchat gepostet.")
        return None

    target_thread_id = None
    if thread_id:
        try:
            target_thread_id = int(thread_id)
        except ValueError:
            print(f"[Telegram] Ungueltige Thread-ID: {thread_id}")

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    chunks = split_message(text)
    first_message_id = None

    for idx, chunk in enumerate(chunks):
        payload = {
            "chat_id": chat_id,
            "text": chunk,
            "parse_mode": "HTML",
            "disable_web_page_preview": True
        }
        if target_thread_id:
            payload["message_thread_id"] = target_thread_id

        try:
            res = requests.post(url, json=payload, timeout=25)
            if res.status_code == 200:
                msg_id = res.json().get("result", {}).get("message_id")
                if first_message_id is None:
                    first_message_id = msg_id
            else:
                print(f"[Telegram] Chunk {idx+1}/{len(chunks)} HTML-Senden fehlgeschlagen ({res.status_code}). Sende Text plain...")
                payload.pop("parse_mode", None)
                res2 = requests.post(url, json=payload, timeout=25)
                if res2.status_code == 200:
                    msg_id = res2.json().get("result", {}).get("message_id")
                    if first_message_id is None:
                        first_message_id = msg_id
                else:
                    print(f"[Telegram] API-Fehler bei Chunk {idx+1}: {res2.text}")
        except Exception as e:
            print(f"[Telegram] Netzwerkfehler bei Chunk {idx+1}: {e}")

    return first_message_id
