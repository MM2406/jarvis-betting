import os
import sys
import json
import requests
from datetime import datetime
from zoneinfo import ZoneInfo

# Sichere Anbindung an telegram_sender.py
try:
    from telegram_sender import send_to_telegram
except ImportError:
    send_to_telegram = None

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "").strip()

# Sichere Fallback-Kette für das NBA-Topic
TELEGRAM_THREAD_ID = (
    os.environ.get("TELEGRAM_THREAD_NBA", "").strip()
    or os.environ.get("TELEGRAM_THREAD_ID", "").strip()
)

LOCAL_TZ = ZoneInfo("Europe/Berlin")

def make_progress_bar(percentage, segments=10):
    clamped = max(0.0, min(100.0, float(percentage)))
    filled = int(round((clamped / 100.0) * segments))
    empty = segments - filled
    return f"[{'🟩' * filled}{'⬜' * empty}]"

def send_telegram_message(text):
    if send_to_telegram:
        return send_to_telegram(text, thread_env_var="TELEGRAM_THREAD_NBA")

    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("[Telegram] FEHLER: Credentials fehlen.")
        return None

    if not TELEGRAM_THREAD_ID:
        print("[Telegram] ABBRUCH: Keine NBA Thread-ID vorhanden. Senden in Hauptchat blockiert.")
        return None

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    max_len = 3800
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

    for chunk in chunks:
        payload = {
            "chat_id": TELEGRAM_CHAT_ID,
            "text": chunk,
            "parse_mode": "HTML",
            "message_thread_id": int(TELEGRAM_THREAD_ID)
        }
        res = requests.post(url, json=payload, timeout=20)
        if res.status_code != 200:
            payload.pop("parse_mode", None)
            res2 = requests.post(url, json=payload, timeout=20)
            if res2.status_code != 200:
                print(f"Telegram Fehler: {res2.text}")

def settle_nba_bets():
    file_path = "pending_nba.json"
    if not os.path.exists(file_path):
        print("Keine offenen NBA Wetten gefunden (pending_nba.json fehlt).")
        return

    with open(file_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    if not data:
        print("pending_nba.json ist leer. Keine Wetten zum Abrechnen.")
        return

    # Robuste Datumserkennung
    date_display = datetime.now(LOCAL_TZ).strftime("%d.%m.%Y")
    if isinstance(data, dict):
        date_display = data.get("date", date_display)
    elif isinstance(data, list) and len(data) > 0 and isinstance(data[0], dict):
        d_val = data[0].get("date", "")
        if d_val:
            try:
                date_display = datetime.strptime(d_val, "%Y-%m-%d").strftime("%d.%m.%Y")
            except Exception:
                date_display = str(d_val)

    # Workaround für Markdown-Darstellung
    bt = "```"

    prompt = f"""
Du bist 'JARVIS NBA SETTLEMENT AGENT'.
Recherchiere über Google Search die finalen Ergebnisse, Boxscores und individuellen Spielerstatistiken (Punkte, Rebounds, Assists, 3PM) der NBA für folgende Wetten:

Offene NBA-Wetten:
{json.dumps(data, ensure_ascii=False, indent=2)}

REGELN:
1. Prüfe, ob alle Spiele beendet sind (FINAL).
2. Markiere beendete Tipps mit ✅ WON, ❌ LOST oder 🟡 PUSH/VOID.
3. Bei Kombiwetten: Zeige jedes Bein (Leg) mit Ergebnis und Status (z.B. [✅] Spieler A über X Pkt, [❌] Team B Sieg).
4. Berechne Netto-Units (Einsatz: 1.00 Unit pro Wette/Schein).

Am Ende MUSS zwingend dieser maschinenlesbare JSON-Block folgen:
{bt}json
{{
  "tickets_total": 4,
  "tickets_won": 3,
  "picks_total": 6,
  "picks_won": 5,
  "total_staked": 4.0,
  "total_returned": 5.91,
  "net_profit": 1.91,
  "roi": 47.75,
  "is_complete": true
}}
{bt}

FORMAT-VORLAGE FÜR TELEGRAM:
<b>🏀 JARVIS NBA SETTLEMENT & RECAP</b>
<i>Abrechnung der NBA-Slate vom {date_display}</i>

<b>━━━━━━━━━━━━━━━━━━━━</b>
[Hier die abgerechneten Wetten und Kombis mit ihren Ergebnissen aufführen]
"""
    
    url = f"[https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key=](https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key=){GEMINI_API_KEY}"
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "tools": [{"googleSearch": {}}],
        "generationConfig": {"temperature": 0.1}
    }

    try:
        res = requests.post(url, json=payload, timeout=120)
        res.raise_for_status()
        raw_text = res.json()["candidates"][0]["content"]["parts"][0]["text"]
        
        json_metrics = None
        if f"{bt}json" in raw_text:
            try:
                parts = raw_text.split(f"{bt}json")
                json_content = parts[1].split(bt)[0].strip()
                json_metrics = json.loads(json_content)
                clean_text = parts[0].strip()
            except Exception as pe:
                print(f"Metrik-JSON Parse-Fehler: {pe}")
                clean_text = raw_text
        else:
            clean_text = raw_text

        # Dashboard mit Fortschrittsbalken deterministisch berechnen
        if json_metrics:
            t_total = json_metrics.get("tickets_total", 0)
            t_won = json_metrics.get("tickets_won", 0)
            t_rate = (t_won / t_total * 100) if t_total > 0 else 0.0

            p_total = json_metrics.get("picks_total", 0)
            p_won = json_metrics.get("picks_won", 0)
            p_rate = (p_won / p_total * 100) if p_total > 0 else 0.0

            staked = json_metrics.get("total_staked", 0.0)
            returned = json_metrics.get("total_returned", 0.0)
            profit = json_metrics.get("net_profit", 0.0)
            roi = json_metrics.get("roi", 0.0)
            sign = "+" if profit >= 0 else ""

            dashboard = "\n\n━━━━━━━━━━━━━━━━━━━━\n"
            dashboard += "📊 <b>PERFORMANCE DASHBOARD & METRIKEN</b>\n"
            dashboard += f"• <b>Ticket Win-Rate:</b> {t_won}/{t_total} ({t_rate:.1f}%) {make_progress_bar(t_rate)}\n"
            dashboard += f"• <b>Pick Hit-Rate:</b>   {p_won}/{p_total} ({p_rate:.1f}%) {make_progress_bar(p_rate)}\n"
            dashboard += f"• <b>Einsatz / Return:</b> {staked:.2f}U ➔ {returned:.2f}U\n"
            dashboard += f"• <b>Netto-Profit:</b>     <b>{sign}{profit:.2f} Units</b>\n"
            dashboard += f"• <b>Tages-ROI:</b>        <b>{sign}{roi:.1f}%</b>\n"
            dashboard += "━━━━━━━━━━━━━━━━━━━━"

            final_message = clean_text + dashboard
            is_complete = json_metrics.get("is_complete", True)
        else:
            final_message = clean_text
            is_complete = "---STATUS: COMPLETE---" in raw_text

        send_telegram_message(final_message)

        if is_complete:
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump([], f, indent=2)
            print("Alle NBA Wetten final beendet. pending_nba.json geleert.")
        else:
            print("Noch NBA Spiele offen. pending_nba.json bleibt erhalten.")

    except Exception as e:
        print(f"Fehler bei NBA Settlement: {e}")
        sys.exit(1)

if __name__ == "__main__":
    settle_nba_bets()
