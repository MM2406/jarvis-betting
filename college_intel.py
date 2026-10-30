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
TELEGRAM_THREAD_ID = os.environ.get("TELEGRAM_COLLEGE_THREAD_ID", "").strip()

LOCAL_TZ = ZoneInfo("Europe/Berlin")
HISTORY_FILE = "college_history.json"

COLLEGE_SPORTS = [
    "basketball_ncaab",
    "americanfootball_ncaaf"
]

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
        print("Keine offenen College-Picks zur Auswertung.")
        return history

    still_pending = []
    settled_now = []

    for item in pending:
        prompt_settle = f"""
Recherchiere via Google Search das offizielle Endergebnis für folgendes College-Spiel:
Match: {item.get('match')}
Sport: {item.get('sport')}
Tipp: {item.get('pick')}
Datum: {item.get('date')}

REGELN:
1. Prüfe, ob das Match bereits regulär beendet ist. Falls noch nicht begonnen oder live, antworte mit PENDING.
2. Markiere mit 'WON', wenn der Tipp aufgegangen ist, sonst 'LOST'.
3. Bei Push (z.B. Spread genau getroffen) gib 'VOID' aus.

Antworte exakt:
RESULT: WON oder LOST oder PENDING oder VOID
SCORE: Endergebnis
INFO: Kurze Begründung.
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
            print(f"Fehler bei College-Settle {item.get('match')}: {e}")
            still_pending.append(item)

    if settled_now:
        history["settled"].extend(settled_now)
        history["pending"] = still_pending
        save_history(history)

        won_count = sum(1 for p in settled_now if p["status"] == "WON")
        total_count = len(settled_now)

        msg = f"📊 <b>JARVIS US COLLEGE ABRECHNUNG</b>\nAusgewertete Tipps: <b>{won_count}/{total_count}</b> Treffer.\n"
        for p in settled_now:
            icon = "✅" if p["status"] == "WON" else ("❌" if p["status"] == "LOST" else "🟡")
            msg += f"\n{icon} <b>{p['match']}</b>\nTipp: {p['pick']} (@ {p.get('odds', 'N/A')})"
        send_telegram(msg)

    return history

def fetch_college_odds():
    all_events = []
    now_utc = datetime.now(timezone.utc)
    cutoff = now_utc + timedelta(hours=18)

    for sport in COLLEGE_SPORTS:
        url = f"https://api.the-odds-api.com/v4/sports/{sport}/odds/"
        params = {
            "apiKey": ODDS_API_KEY,
            "regions": "us,eu",
            "markets": "h2h,spreads,totals",
            "oddsFormat": "decimal"
        }
        try:
            res = requests.get(url, params=params, timeout=12)
            if res.status_code == 200:
                for match in res.json():
                    commence_utc = datetime.fromisoformat(match["commence_time"].replace("Z", "+00:00"))
                    if now_utc <= commence_utc <= cutoff:
                        time_str = commence_utc.astimezone(LOCAL_TZ).strftime("%H:%M Uhr")
                        bookies = match.get("bookmakers", [])
                        if not bookies:
                            continue
                        odds_details = []
                        for m in bookies[0].get("markets", []):
                            outcomes = [f"{o['name']} ({o.get('point', '')}): {o['price']}" for o in m.get("outcomes", [])]
                            odds_details.append(f"{m.get('key')}: {', '.join(outcomes)}")
                        all_events.append(f"[{sport}] {match['home_team']} vs. {match['away_team']} ({time_str}) | {' // '.join(odds_details)}")
        except Exception as e:
            print(f"Fehler bei {sport}: {e}")

    print(f"Gefundene College-Partien: {len(all_events)}")
    return "\n".join(all_events[:45])

def run_college_report():
    history = load_history()
    settle_pending_picks(history)

    now_hour = datetime.now(LOCAL_TZ).hour
    if now_hour < 12:
        print("Morgen-Run: Nur Abrechnung durchgeführt.")
        return

    odds_data = fetch_college_odds()
    if not odds_data:
        print("Keine relevanten College-Partien gefunden.")
        return

    today_str = datetime.now(LOCAL_TZ).strftime("%d.%m.%Y")
    today_iso = datetime.now(LOCAL_TZ).strftime("%Y-%m-%d")

    prompt = f"""
Du bist 'JARVIS US COLLEGE QUANT' – Experte für NCAA Basketball & Football.
Erstelle für heute ({today_str}) ein präzises Value-Dossier.

VERFÜGBARE PARTIEN & QUOTEN:
{odds_data}

RICHTLINIEN & BUCHMACHER-KOMPATIBILITÄT:
- Wähle ausschließlich Partien aus der obigen Liste.
- Analysiere KenPom/Torvik-Trends, Home-Court Advantage und Spreads.
- Gib immer eine Standard-Buchmacher-Alternative an.
- Weise immer eine Value-Grenze ('Spielbar bis @ X.XX') und Units (1.0 bis 2.0) aus.
- Telegram-HTML ZUERST, danach der exakte JSON-Block.

REPORT-HTML:
🎓 <b>JARVIS US COLLEGE INTEL DOSSIER</b>
<i>NCAA Analytics • KenPom Edge • Market Discrepancies</i>

━━━━━━━━━━━━━━━━━━━━
⭐ <b>COLLEGE PICK OF THE DAY</b>
• [Uhrzeit] | [Sport] Heim vs. Gast
  ➔ <b>Pick: [Spread / Total / Moneyline]</b> @ X.XX
🔄 <b>Buchmacher-Alternative:</b> [Klassische Standard-Linie] @ X.XX
⚠️ <b>Value-Grenze:</b> Spielbar bis @ X.XX | <b>Einsatz:</b> [1.0 - 2.0] Units
<b>Modell-Chance:</b> XX.X% | <b>Fair Odds:</b> ~X.XX (<b>+X.X% EV</b>)
<b>Edge:</b> [Effizienz-Ratings, Tempo-Matchup, Turnover-Rates]

━━━━━━━━━━━━━━━━━━━━
🔥 <b>VALUE DOUBLE TICKET (2er-Kombi)</b>
• Heim vs. Gast ➔ <b>[Tipp 1]</b> @ X.XX (Alt: [Alternative])
• Heim vs. Gast ➔ <b>[Tipp 2]</b> @ X.XX (Alt: [Alternative])
<b>Gesamtquote: X.XX</b> | <b>Einsatz:</b> 1.0 Units
<b>Rationale:</b> [Kompakte taktische Begründung beider Auswahlen]

━━━━━━━━━━━━━━━━━━━━
🎯 <b>TEMPO &amp; UPSET SPOTLIGHT</b>
• [Uhrzeit] | Heim vs. Gast
  ➔ <b>Pick: [Tipp]</b> @ X.XX
⚠️ <b>Value-Grenze:</b> Spielbar bis @ X.XX | <b>Einsatz:</b> 1.0 Units
<b>Rationale:</b> [Mismatches im Rebounding / 3PT-Defense]

---JSON_TRACKING---
[
  {{
    "match": "Team A vs Team B",
    "sport": "basketball_ncaab",
    "pick": "Team A -4.5",
    "odds": "1.90",
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
                        print(f"{len(new_picks)} College-Picks hinzugefügt.")
                    except Exception as je:
                        print(f"Fehler beim Parsen der Tracking-Picks: {je}")

                report = report.replace("```html", "").replace("```", "").strip()
                send_telegram(report)
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
    run_college_report()
