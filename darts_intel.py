import os
import sys
import json
import time
import requests
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo

ODDS_API_KEY = os.environ.get("ODDS_API_KEY", "").strip()
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
TELEGRAM_THREAD_ID = os.environ.get("TELEGRAM_DARTS_THREAD_ID", "").strip()

LOCAL_TZ = ZoneInfo("Europe/Berlin")
HISTORY_FILE = "darts_history.json"

SPORT_KEY = "darts_pdc"

def send_telegram(text):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("Telegram Credentials fehlen.")
        return

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True
    }
    if TELEGRAM_THREAD_ID:
        try:
            payload["message_thread_id"] = int(TELEGRAM_THREAD_ID)
        except ValueError:
            pass

    try:
        res = requests.post(url, json=payload, timeout=25)
        if res.status_code != 200:
            payload.pop("parse_mode", None)
            requests.post(url, json=payload, timeout=25)
    except Exception as e:
        print(f"Telegram-Fehler: {e}")

def load_history():
    if not os.path.exists(HISTORY_FILE):
        return {"settled": [], "pending": []}
    try:
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"Fehler beim Laden von {HISTORY_FILE}: {e}")
        return {"settled": [], "pending": []}

def save_history(history):
    try:
        with open(HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump(history, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"Fehler beim Speichern von {HISTORY_FILE}: {e}")

def settle_pending_picks(history):
    pending = history.get("pending", [])
    if not pending:
        print("Keine offenen Darts-Picks zur Auswertung.")
        return history

    still_pending = []
    settled_now = []

    for item in pending:
        prompt_settle = f"""
Recherchiere via Google Search das offizielle Endergebnis für folgendes Darts-Match (PDC):
Match: {item.get('match')}
Tipp / Markt: {item.get('pick')}
Datum: {item.get('date')}

REGELN:
1. Prüfe, ob die Partie bereits offiziell beendet ist. Falls noch nicht begonnen oder live, antworte mit PENDING.
2. Markiere mit 'WON', wenn der Tipp (Match-Sieger, Legs Handicap oder 180er) aufgegangen ist, sonst 'LOST'.
3. Bei Walkover, Spielabbruch oder Push gib 'VOID' aus.

Antworte strikt in diesem Format:
RESULT: WON oder LOST oder PENDING oder VOID
SCORE: Exaktes Endergebnis (z.B. 6:4 Legs)
INFO: Kurze Erklärung.
"""
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-3.8-flash:generateContent?key={GEMINI_API_KEY}"
        payload = {
            "contents": [{"parts": [{"text": prompt_settle}]}],
            "tools": [{"googleSearch": {}}],
            "generationConfig": {"temperature": 0.1}
        }

        try:
            res = requests.post(url, json=payload, timeout=60)
            if res.status_code == 200:
                text = res.json()["candidates"][0]["content"]["parts"][0]["text"]
                if "RESULT: WON" in text:
                    item["status"] = "WON"
                    settled_now.append(item)
                elif "RESULT: LOST" in text:
                    item["status"] = "LOST"
                    settled_now.append(item)
                elif "RESULT: VOID" in text:
                    item["status"] = "VOID"
                    settled_now.append(item)
                else:
                    still_pending.append(item)
            else:
                still_pending.append(item)
        except Exception as e:
            print(f"Fehler bei Abrechnung {item.get('match')}: {e}")
            still_pending.append(item)

    if settled_now:
        history["settled"].extend(settled_now)
        history["pending"] = still_pending
        save_history(history)

        won_count = sum(1 for p in settled_now if p["status"] == "WON")
        total_count = len(settled_now)

        msg = f"📊 <b>JARVIS DARTS ABRECHNUNG</b>\nAusgewertete Tipps: <b>{won_count}/{total_count}</b> Treffer.\n"
        for p in settled_now:
            icon = "✅" if p["status"] == "WON" else ("❌" if p["status"] == "LOST" else "🟡")
            msg += f"\n{icon} <b>{p['match']}</b>\nTipp: {p['pick']} (Quote: {p.get('odds', 'N/A')})"
        send_telegram(msg)

    return history

def fetch_darts_odds():
    all_events = []
    now_utc = datetime.now(timezone.utc)
    cutoff = now_utc + timedelta(hours=12)

    url = f"https://api.the-odds-api.com/v4/sports/{SPORT_KEY}/odds/"
    params = {
        "apiKey": ODDS_API_KEY,
        "regions": "eu",
        "markets": "h2h,spreads,totals",
        "oddsFormat": "decimal"
    }
    try:
        res = requests.get(url, params=params, timeout=12)
        if res.status_code == 200:
            data = res.json()
            for match in data:
                commence_utc = datetime.fromisoformat(match["commence_time"].replace("Z", "+00:00"))
                if now_utc <= commence_utc <= cutoff:
                    time_str = commence_utc.astimezone(LOCAL_TZ).strftime("%H:%M Uhr")
                    bookies = match.get("bookmakers", [])
                    if not bookies:
                        continue

                    odds_details = []
                    for m in bookies[0].get("markets", []):
                        m_key = m.get("key")
                        outcomes = [f"{o['name']} ({o.get('point', '')}): {o['price']}" for o in m.get("outcomes", [])]
                        odds_details.append(f"{m_key}: {', '.join(outcomes)}")

                    all_events.append(
                        f"{match['home_team']} vs. {match['away_team']} ({time_str}) | Quoten: {' // '.join(odds_details)}"
                    )
    except Exception as e:
        print(f"Fehler bei {SPORT_KEY}: {e}")

    print(f"Gefundene Darts-Matches: {len(all_events)}")
    return "\n".join(all_events[:40])

def generate_darts_report():
    history = load_history()
    settle_pending_picks(history)

    now_hour = datetime.now(LOCAL_TZ).hour
    if now_hour < 12:
        print("Morgen-Run: Nur Abrechnung durchgeführt.")
        return

    odds_data = fetch_darts_odds()
    if not odds_data:
        print("Heute finden im 12-Stunden-Fenster keine PDC Darts Spiele statt.")
        return

    today_str = datetime.now(LOCAL_TZ).strftime("%d.%m.%Y")
    today_iso = datetime.now(LOCAL_TZ).strftime("%Y-%m-%d")

    prompt = f"""
Du bist 'JARVIS DARTS QUANT' – Experte für PDC Darts (Premier League, European Tour, Majors).
Erstelle für die heutigen Matches ({today_str}) eine quantitative Analyse.

VERFÜGBARE MATCHES & ECHTE BUCHMACHERQUOTEN:
{odds_data}

RICHTLINIEN:
- Wähle AUSNAHMSLOS Partien aus der obigen Liste. Erfinde keine Spiele oder Quoten.
- Nutze statistische Metriken: 3-Dart-Average, Doppel-/Checkout-Quote, 180er-Rate pro Leg, Head-to-Head Form.

FORMATIERUNG & STRUKTUR:
Erstelle ZUERST den HTML-Report für Telegram und füge GANZ AM ENDE den JSON-Block für das Settlement hinzu.

REPORT-HTML:
🎯 <b>JARVIS PDC DARTS INTEL</b>
<i>PDC Tour • 3-Dart-Averages • Checkout-Effizienz • Value</i>

━━━━━━━━━━━━━━━━━━━━
⭐ <b>DARTS MATCH OF THE DAY (Top-Value Single)</b>
- [Uhrzeit] Spieler A vs. Spieler B ➔ <b>Pick: [Markt &amp; Tipp]</b> (Quote: X.XX)
Modell-Chance: XX.X% | Fair Odds: ~X.XX
Edge: [3-Dart-Average Trend, Checkout-Sicherheit, historische H2H-Dominanz]

━━━━━━━━━━━━━━━━━━━━
🎯 <b>DARTS VALUE TICKET (2er-Kombi)</b>
- [Uhrzeit] Spieler A vs. Spieler B ➔ Pick: [Tipp / Leg-Handicap] (Quote: X.XX)
- [Uhrzeit] Spieler C vs. Spieler D ➔ Pick: [Tipp / Leg-Handicap] (Quote: X.XX)
<b>Gesamtquote: X.XX</b>
Rationale: [Scoring-Konstanz, Formkurve]

━━━━━━━━━━━━━━━━━━━━
🔥 <b>MAXIMUM 180s / STATS SPECIAL</b>
- [Uhrzeit] Spieler A vs. Spieler B ➔ <b>Pick: [Most 180s oder Total Legs Over]</b> (Quote: X.XX)
Rationale: [180er pro Leg Raten beider Kontrahenten, Match-Länge]

---JSON_TRACKING---
[
  {{
    "match": "Player A vs Player B",
    "pick": "Player A Win",
    "odds": "1.72",
    "date": "{today_iso}"
  }}
]
"""
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-3.8-flash:generateContent?key={GEMINI_API_KEY}"
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "tools": [{"googleSearch": {}}],
        "generationConfig": {"temperature": 0.2}
    }

    for attempt in range(1, 4):
        try:
            res = requests.post(url, json=payload, timeout=90)
            if res.status_code == 200:
                full_reply = res.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
                report = full_reply
                if "---JSON_TRACKING---" in full_reply:
                    parts = full_reply.split("---JSON_TRACKING---")
                    report = parts[0].strip()
                    json_str = parts[1].replace("```json", "").replace("```", "").strip()
                    try:
                        new_picks = json.loads(json_str)
                        for np in new_picks:
                            np["status"] = "PENDING"
                        history["pending"].extend(new_picks)
                        save_history(history)
                        print(f"{len(new_picks)} Darts-Picks gespeichert.")
                    except Exception as je:
                        print(f"Fehler beim Parsen der Tracking-Picks: {je}")

                report = report.replace("```html", "").replace("```", "").strip()
                send_telegram(report)
                print("Darts Report erfolgreich versendet.")
                return
            elif res.status_code in [500, 502, 503, 504]:
                time.sleep(6)
            else:
                res.raise_for_status()
        except Exception as e:
            print(f"Versuch {attempt}/3 fehlgeschlagen: {e}")
            if attempt < 3:
                time.sleep(6)
            else:
                sys.exit(1)

if __name__ == "__main__":
    generate_darts_report()
