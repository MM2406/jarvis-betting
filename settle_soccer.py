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

# Sichere Fallback-Kette für das Soccer-Topic
TELEGRAM_THREAD_ID = (
    os.environ.get("TELEGRAM_THREAD_SOCCER", "").strip()
    or os.environ.get("TELEGRAM_THREAD_ID", "").strip()
)

LOCAL_TZ = ZoneInfo("Europe/Berlin")
PENDING_FILE = "pending_soccer.json"
HISTORY_FILE = "soccer_history.json"

def make_progress_bar(percentage, segments=10):
    clamped = max(0.0, min(100.0, float(percentage)))
    filled = int(round((clamped / 100.0) * segments))
    empty = segments - filled
    return f"[{'🟩' * filled}{'⬜' * empty}]"

def append_to_history(settled_items):
    """Speichert abgerechnete Wetten dauerhaft für analytics_engine.py ab."""
    if not settled_items:
        return
    history = {"settled": [], "pending": []}
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                content = json.load(f)
                if isinstance(content, dict):
                    history = content
                elif isinstance(content, list):
                    history = {"settled": content, "pending": []}
        except Exception as e:
            print(f"Fehler beim Laden von {HISTORY_FILE}: {e}")

    history.setdefault("settled", []).extend(settled_items)
    try:
        with open(HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump(history, f, ensure_ascii=False, indent=2)
        print(f"[History] {len(settled_items)} Soccer-Picks in {HISTORY_FILE} archiviert.")
    except Exception as e:
        print(f"Fehler beim Speichern in {HISTORY_FILE}: {e}")

def send_telegram_message(text):
    if send_to_telegram:
        return send_to_telegram(text, thread_env_var="TELEGRAM_THREAD_SOCCER")

    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("[Telegram] FEHLER: Credentials fehlen.")
        return None

    if not TELEGRAM_THREAD_ID:
        print("[Telegram] ABBRUCH: Keine Soccer Thread-ID vorhanden. Senden in Hauptchat blockiert.")
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

def settle_soccer_bets():
    if not os.path.exists(PENDING_FILE):
        print("Keine offenen Soccer Wetten gefunden (pending_soccer.json fehlt).")
        return

    with open(PENDING_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)

    if not data:
        print("pending_soccer.json ist leer. Keine Wetten zum Abrechnen.")
        return

    today_iso = datetime.now(LOCAL_TZ).strftime("%Y-%m-%d")
    date_display = data.get("date", datetime.now(LOCAL_TZ).strftime("%d.%m.%Y")) if isinstance(data, dict) else datetime.now(LOCAL_TZ).strftime("%d.%m.%Y")
    bt = "```"

    prompt = f"""
Du bist 'JARVIS SOCCER SETTLEMENT & CLV AGENT'.
Nutze Google Search, um für folgende Fussballwetten die finalen Ergebnisse, Torschützen, Handicaps/Spreads sowie die Schlusquoten kurz vor Spielbeginn (Closing Odds / Pinnacle / Bet365 Schlusquote) zu recherchieren:

Offene Wetten:
{json.dumps(data, ensure_ascii=False, indent=2)}

REGELN:
1. Prüfe, ob alle Spiele regulär beendet sind.
2. Markiere beendete Tipps mit ✅ WON, ❌ LOST oder 🟡 PUSH/VOID.
3. Recherchiere für jeden Tipp die Schlussquote (Closing Line) kurz vor Anpfiff. Falls nicht auffindbar, nimm die Anfangsquote an.
4. Berechne Netto-Units (Einsatz: 1.00 Unit pro Ticket/Schein).

Am Ende MUSS zwingend dieser maschinenlesbare JSON-Block folgen:
{bt}json
{{
  "tickets_total": 4,
  "tickets_won": 3,
  "picks_total": 6,
  "picks_won": 5,
  "total_staked": 4.0,
  "total_returned": 5.80,
  "net_profit": 1.80,
  "roi": 45.0,
  "is_complete": true,
  "picks_details": [
    {{
      "match": "Team A vs Team B",
      "pick": "Team A Sieg",
      "placed_odds": 1.95,
      "closing_odds": 1.82,
      "status": "WON"
    }}
  ]
}}
{bt}

FORMAT-VORLAGE FÜR TELEGRAM:
<b>⚽ JARVIS SOCCER SETTLEMENT & RECAP</b>
<i>Abrechnung der Wetten vom {date_display}</i>

<b>━━━━━━━━━━━━━━━━━━━━</b>
[Hier alle Tickets und Einzel-Picks auflisten mit Resultat und Status]
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

            # CLV berechnen
            clv_list = []
            detailed_picks = json_metrics.get("picks_details", [])
            for p in detailed_picks:
                try:
                    p_odds = float(p.get("placed_odds", 1.0))
                    c_odds = float(p.get("closing_odds", p_odds))
                    if c_odds > 1.0:
                        clv = ((p_odds / c_odds) - 1.0) * 100.0
                        p["clv"] = clv
                        clv_list.append(clv)
                except Exception:
                    pass

            avg_clv_str = ""
            if clv_list:
                avg_clv = sum(clv_list) / len(clv_list)
                clv_icon = "🟢" if avg_clv > 0 else ("🔴" if avg_clv < 0 else "⚪")
                clv_sign = "+" if avg_clv >= 0 else ""
                avg_clv_str = f"• <b>Ø Slate-CLV:</b>       <b>{clv_sign}{avg_clv:.1f}% {clv_icon}</b>\n"

            dashboard = "\n\n━━━━━━━━━━━━━━━━━━━━\n"
            dashboard += "📊 <b>PERFORMANCE DASHBOARD & METRIKEN</b>\n"
            dashboard += f"• <b>Ticket Win-Rate:</b> {t_won}/{t_total} ({t_rate:.1f}%) {make_progress_bar(t_rate)}\n"
            dashboard += f"• <b>Pick Hit-Rate:</b>   {p_won}/{p_total} ({p_rate:.1f}%) {make_progress_bar(p_rate)}\n"
            dashboard += f"• <b>Einsatz / Return:</b> {staked:.2f}U ➔ {returned:.2f}U\n"
            dashboard += f"• <b>Netto-Profit:</b>     <b>{sign}{profit:.2f} Units</b>\n"
            dashboard += f"• <b>Tages-ROI:</b>        <b>{sign}{roi:.1f}%</b>\n"
            if avg_clv_str:
                dashboard += avg_clv_str
            dashboard += "━━━━━━━━━━━━━━━━━━━━"

            final_message = clean_text + dashboard
            is_complete = json_metrics.get("is_complete", True)
        else:
            final_message = clean_text
            is_complete = "---STATUS: COMPLETE---" in raw_text

        send_telegram_message(final_message)

        if is_complete:
            # Für die History aufbereiten
            archived = []
            if json_metrics and "picks_details" in json_metrics:
                for pick_d in json_metrics["picks_details"]:
                    archived.append({
                        "match": pick_d.get("match", "Soccer Match"),
                        "pick": pick_d.get("pick", "Tipp"),
                        "odds": pick_d.get("placed_odds", 1.0),
                        "closing_odds": pick_d.get("closing_odds", 1.0),
                        "clv": pick_d.get("clv", 0.0),
                        "status": pick_d.get("status", "SETTLED"),
                        "date": today_iso,
                        "stake": 1.0
                    })
            else:
                archived.append({
                    "match": "Soccer Slate",
                    "pick": "Tages-Ticket",
                    "odds": 1.0,
                    "status": "WON" if json_metrics and json_metrics.get("net_profit", 0) > 0 else "LOST",
                    "date": today_iso,
                    "stake": 1.0
                })

            append_to_history(archived)

            if os.path.exists(PENDING_FILE):
                os.remove(PENDING_FILE)
            print("Alle Soccer Wetten final beendet. pending_soccer.json archiviert und gelöscht.")
        else:
            print("Noch Soccer Partien offen. pending_soccer.json bleibt erhalten.")

    except Exception as e:
        print(f"Fehler bei Soccer Settlement: {e}")
        sys.exit(1)

if __name__ == "__main__":
    settle_soccer_bets()
