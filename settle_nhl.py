import os
import sys
import json
import time
import requests
import re
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo

ODDS_API_KEY = os.environ.get("ODDS_API_KEY", "").strip()
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "").strip()

TELEGRAM_THREAD_ID = (
    os.environ.get("TELEGRAM_THREAD_NHL", "").strip()
    or os.environ.get("TELEGRAM_THREAD_ID", "").strip()
)

LOCAL_TZ = ZoneInfo("Europe/Berlin")
PENDING_FILE = "pending_nhl.json"

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
            print(f"Ungueltige Thread-ID fuer NHL: {TELEGRAM_THREAD_ID}")

    try:
        res = requests.post(url, json=payload, timeout=25)
        if res.status_code != 200:
            payload.pop("parse_mode", None)
            requests.post(url, json=payload, timeout=25)
    except Exception as e:
        print(f"Telegram-Fehler: {e}")

def deduplicate_picks(items):
    seen = set()
    unique = []
    for item in items:
        key = (
            str(item.get("date", "")).strip().lower(),
            str(item.get("match", "")).strip().lower(),
            str(item.get("pick", "")).strip().lower()
        )
        if key not in seen:
            seen.add(key)
            unique.append(item)
    return unique

def load_pending():
    if not os.path.exists(PENDING_FILE):
        return []
    try:
        with open(PENDING_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            raw = data if isinstance(data, list) else data.get("pending", [])
            return deduplicate_picks(raw)
    except Exception as e:
        print(f"Fehler beim Laden von {PENDING_FILE}: {e}")
        return []

def save_pending(pending_list):
    try:
        unique_list = deduplicate_picks(pending_list)
        with open(PENDING_FILE, "w", encoding="utf-8") as f:
            json.dump(unique_list, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"Fehler beim Speichern von {PENDING_FILE}: {e}")

def fetch_nhl_odds():
    url = "https://api.the-odds-api.com/v4/sports/icehockey_nhl/odds/"
    params = {
        "apiKey": ODDS_API_KEY,
        "regions": "eu,us",
        "markets": "h2h,totals",
        "oddsFormat": "decimal"
    }
    try:
        res = requests.get(url, params=params, timeout=15)
        if res.status_code == 200:
            events = []
            now_utc = datetime.now(timezone.utc)
            cutoff = now_utc + timedelta(hours=18)
            for m in res.json():
                commence = datetime.fromisoformat(m["commence_time"].replace("Z", "+00:00"))
                if now_utc <= commence <= cutoff:
                    time_str = commence.astimezone(LOCAL_TZ).strftime("%H:%M Uhr")
                    bookies = m.get("bookmakers", [])
                    if not bookies:
                        continue
                    m_details = []
                    for mk in bookies[0].get("markets", []):
                        outcomes = [f"{o['name']} ({o.get('point', '')}): {o['price']}" for o in mk.get("outcomes", [])]
                        m_details.append(f"{mk.get('key')}: {', '.join(outcomes)}")
                    events.append(f"{m['home_team']} vs. {m['away_team']} ({time_str}) | {' // '.join(m_details)}")
            return "\n".join(events[:40])
    except Exception as e:
        print(f"Fehler bei NHL Odds: {e}")
    return ""

def run_nhl_intel():
    odds_data = fetch_nhl_odds()
    if not odds_data:
        print("Keine NHL-Spiele im Zeitfenster gefunden.")
        return

    now_dt = datetime.now(LOCAL_TZ)
    today_str = now_dt.strftime("%d.%m.%Y")
    today_iso = now_dt.strftime("%Y-%m-%d")

    prompt = f"""
Du bist 'JARVIS NHL QUANT' – Spezialist für quantitative NHL-Modellierung, Goalie-Matchups und Quoten-Diskrepanzen.
Erstelle für heute ({today_str}) das NHL-Dossier.

VERFÜGBARE PARTIEN & ECHTE BUCHMACHERQUOTEN:
{odds_data}

REGELN:
- Wähle ausschließlich Partien aus der obigen Liste.
- WICHTIG: Es handelt sich um Eishockey (NHL) – Tore und Assists ergeben Punkte. Alle Siegwetten inkl. OT/SO ausweisen.
- Analysiere Starting Goalies, Special Teams (PP%/PK%), Corsi/Fenwick und Rest Advantage via Google Search.
- Erstelle:
  1x Pick of the Day (1.5u)
  1x Value Acca (Kombi mit 2-3 Spielen, 0.75u)
  1x Totals Spotlight (0.75u)
  1x Player Prop (Punkte/Tore/Schüsse - nur Over, keine Under!, 0.5u).

FORMATIERUNGS-REGELN FÜR TELEGRAM:
- Keine doppelten Leerzeilen.
- Beginne jede Aufzählung direkt mit '• ' (Unicode Bullet) OHNE Zeilenumbruch nach dem Bullet!
- Schreibe Pfeile direkt vor den Text: '➔ <b>Haupt-Pick:</b> ...' OHNE Leerzeile davor.
- Trennlinien exakt: '━━━━━━━━━━━━━━━━━━━━'
- Am Ende MUSS der exakte Parser-Block '---JSON_TRACKING---' folgen.

REPORT-HTML:
🏒 <b>JARVIS NHL INTEL DOSSIER</b>
<i>Advanced Analytics • xG-Models • Goalie Confirmation</i>

━━━━━━━━━━━━━━━━━━━━
⭐ <b>NHL PICK OF THE DAY (Single Bet)</b>
- <b>Match:</b> [Uhrzeit] Uhr | [Heimteam] vs. [Auswärtsteam]
➔ <b>Haupt-Pick:</b> <b>[Sieg inkl. OT / 60-Min / Total]</b> @ [Quote]
🔄 <b>Buchmacher-Alternative:</b> [Klassische Linie] @ [Quote]
⚠️ <b>Value-Grenze:</b> Spielbar bis @ [Quote] | 💰 <b>Einsatz:</b> 1.5 Units
📊 <b>Quant-Daten:</b> Modell-Chance: [XX.X]% | Fair Odds: ~[X.XX] (<b>+[X.X]% EV</b>)
🔍 <b>Edge:</b> [Goalie Net-Rating, 5v5 Expected Goals, Rest Discrepancy]

━━━━━━━━━━━━━━━━━━━━
🔥 <b>QUANT VALUE ACCA (Kombi)</b>
- [Uhrzeit] Uhr | [Heim] vs. [Gast] ➔ <b>[Tipp 1]</b> @ [Quote]
- [Uhrzeit] Uhr | [Heim] vs. [Gast] ➔ <b>[Tipp 2]</b> @ [Quote]
📈 <b>Gesamtquote:</b> <b>@[Quote]</b>
⚠️ <b>Value-Grenze:</b> Kombi spielbar bis @ [Quote]
💰 <b>Einsatz:</b> 0.75 Units
🔍 <b>Kombi-Logik:</b> [Warum diese Kombination rechnerischen Value bietet]

━━━━━━━━━━━━━━━━━━━━
🎯 <b>TOTALS & PACE SPOTLIGHT</b>
- <b>Match:</b> [Uhrzeit] Uhr | [Heimteam] vs. [Auswärtsteam]
➔ <b>Pick:</b> <b>[Over/Under Total inkl. OT]</b> @ [Quote]
🔄 <b>Buchmacher-Alternative:</b> [Standard 5.5/6.0 Linie] @ [Quote]
⚠️ <b>Value-Grenze:</b> Spielbar bis @ [Quote] | 💰 <b>Einsatz:</b> 0.75 Units
🔍 <b>Rationale:</b> [Pace, High Danger Chances, Backup Goalies, Powerplay Efficiency]

━━━━━━━━━━━━━━━━━━━━
👟 <b>NHL PLAYER PROP SPOTLIGHT</b>
- <b>Match:</b> [Uhrzeit] Uhr | [Heimteam] vs. [Auswärtsteam]
➔ <b>Pick:</b> <b>[Spieler: 1+ Punkt / 3+ SOG / 1+ Tor]</b> @ [Quote]
🔄 <b>Buchmacher-Alternative:</b> [Alternative Linie] @ [Quote]
⚠️ <b>Value-Grenze:</b> Spielbar bis @ [Quote] | 💰 <b>Einsatz:</b> 0.5 Units
🔍 <b>Rationale:</b> [Top PP-Line Time on Ice, Shots per 60, gegnerische Penalty Kill Vulnerability]

---JSON_TRACKING---
[
  {{
    "match": "Team A vs Team B",
    "sport": "NHL",
    "category": "POTD",
    "pick": "Team A Sieg (inkl. OT)",
    "odds": 1.85,
    "stake": 1.5,
    "date": "{today_iso}",
    "is_kombi": false
  }},
  {{
    "match": "Team A vs Team B // Team C vs Team D",
    "sport": "NHL",
    "category": "ACCA",
    "pick": "Team A ML + Team C ML",
    "odds": 2.80,
    "stake": 0.75,
    "date": "{today_iso}",
    "is_kombi": true
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
                        pending = load_pending()
                        for np in new_picks:
                            np["status"] = "PENDING"
                            np["sport"] = "NHL"
                            try:
                                np["odds"] = float(str(np.get("odds", 1.85)).replace(",", "."))
                            except ValueError:
                                np["odds"] = 1.85
                            try:
                                np["stake"] = float(str(np.get("stake", 1.0)).replace(",", "."))
                            except ValueError:
                                np["stake"] = 1.0
                        pending.extend(new_picks)
                        save_pending(pending)
                        print(f"{len(new_picks)} NHL-Picks getrackt.")
                    except Exception as je:
                        print(f"Fehler beim Parsen der NHL-Picks: {je}")

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

def main():
    now_berlin = datetime.now(LOCAL_TZ)
    current_hour = now_berlin.hour
    print(f"=== JARVIS NHL INTEL START [{now_berlin.strftime('%Y-%m-%d %H:%M:%S %Z')}] ===")
    
    if current_hour >= 16:
        run_nhl_intel()
    else:
        print(f"Aktuelle Zeit: {current_hour}:00 Uhr. NHL-Dossier wird erst ab 16:00 Uhr generiert.")

if __name__ == "__main__":
    main()
