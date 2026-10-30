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

DARTS_SPORTS = [
    "darts_pdc_world_championship",
    "darts_premier_league"
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
        print("Keine offenen Darts-Picks zur Auswertung.")
        return history

    still_pending = []
    settled_now = []

    for item in pending:
        prompt_settle = f"""
Recherchiere via Google Search das offizielle Endergebnis fuer folgendes Darts-Match:
Match: {item.get('match')}
Turnier: PDC Darts
Tipp: {item.get('pick')}
Datum: {item.get('date')}

REGELN:
1. Pruefe, ob das Match bereits beendet ist. Falls noch nicht begonnen oder live, antworte mit PENDING.
2. Markiere mit 'WON', wenn der Tipp aufgegangen ist, sonst 'LOST'.
3. Bei Spielabsage oder Push gib 'VOID' aus.

Antworte exakt:
RESULT: WON oder LOST oder PENDING oder VOID
SCORE: Offizielles Endergebnis (z.B. 6:4 Legs)
INFO: Kurze Begruendung.
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
            print(f"Fehler bei Darts-Settle {item.get('match')}: {e}")
            still_pending.append(item)

    if settled_now:
        history["settled"].extend(settled_now)
        history["pending"] = still_pending
        save_history(history)

        won_count = sum(1 for p in settled_now if p["status"] == "WON")
        total_count = len(settled_now)

        msg = f"📊 <b>JARVIS PDC DARTS ABRECHNUNG</b>\nAusgewertete Tipps: <b>{won_count}/{total_count}</b> Treffer.\n"
        for p in settled_now:
            icon = "✅" if p["status"] == "WON" else ("❌" if p["status"] == "LOST" else "🟡")
            msg += f"\n{icon} <b>{p['match']}</b>\nTipp: {p['pick']} (@ {p.get('odds', 'N/A')})"
        send_telegram(msg)

    return history

def fetch_darts_odds(already_tracked_matches):
    all_events = []
    now_utc = datetime.now(timezone.utc)
    now_hour = datetime.now(LOCAL_TZ).hour

    # Vor 15 Uhr: Nachmittagssession (8 Std Puffer ab 11:15 -> bis 19:15 Uhr)
    # Nach 15 Uhr: Abendsession (9 Std Puffer ab 16:45 -> bis 01:45 Uhr)
    window_hours = 8 if now_hour < 15 else 9
    cutoff = now_utc + timedelta(hours=window_hours)

    for sport in DARTS_SPORTS:
        url = f"https://api.the-odds-api.com/v4/sports/{sport}/odds/"
        params = {
            "apiKey": ODDS_API_KEY,
            "regions": "eu",
            "markets": "h2h,spreads,totals",
            "oddsFormat": "decimal"
        }
        try:
            res = requests.get(url, params=params, timeout=12)
            if res.status_code == 200:
                for match in res.json():
                    match_name = f"{match['home_team']} vs. {match['away_team']}"
                    if match_name in already_tracked_matches:
                        continue

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
                        all_events.append(f"[{sport}] {match_name} ({time_str}) | {' // '.join(odds_details)}")
        except Exception as e:
            print(f"Fehler bei {sport}: {e}")

    print(f"Gefundene Darts-Matches: {len(all_events)}")
    return "\n".join(all_events[:30])

def run_darts_report():
    history = load_history()
    settle_pending_picks(history)

    now_hour = datetime.now(LOCAL_TZ).hour
    if now_hour < 10:
        print("Morgen-Run: Nur Abrechnung durchgefuehrt.")
        return

    tracked_matches = {p.get("match") for p in history.get("pending", [])}
    odds_data = fetch_darts_odds(tracked_matches)

    if not odds_data:
        print(f"Keine relevanten Darts-Matches fuer dieses Zeitfenster ({now_hour} Uhr) gefunden.")
        return

    session_name = "AFTERNOON SESSION" if now_hour < 15 else "EVENING SESSION"
    today_str = datetime.now(LOCAL_TZ).strftime("%d.%m.%Y")
    today_iso = datetime.now(LOCAL_TZ).strftime("%Y-%m-%d")

    prompt = f"""
Du bist 'JARVIS DARTS QUANT' – Experte fuer PDC Darts (3-Dart-Averages, 180s-Statistiken, Checkout-Percentages).
Erstelle fuer heute ({today_str}) die {session_name}.

VERFUEGBARE MATCHES & QUOTEN:
{odds_data}

RICHTLINIEN & MAERKTE:
- Waehle ausschliesslich Matches aus der obigen Liste.
- Analysiere Scoring-Power, Leg-Handicaps, 180s-Maerkte und Quoten-Diskrepanzen via Google Search.
- DYNAMISCHE ACCA: Kombiniere flexibel 2 bis 4 Matches mit rechnerischem Vorteil (+EV). Kein starres 2-Matches-Limit.
- BUCHMACHER-ALTERNATIVE: Gib fuer jeden Tipp immer eine klassische Standard-Alternative an (z. B. Match-Sieg statt Leg-Handicap).
- VALUE-GRENZE: Weise fuer jeden Tipp eine Mindestquote aus ('Spielbar bis @ X.XX').
- UNITS:
  * Match of the Day: 1.0 bis 2.0 Units
  * Value Acca: 0.5 bis 1.0 Units
  * 180s / Special Spotlight: 0.5 bis 1.0 Units

FORMATIERUNGS-REGELN FUER TELEGRAM:
- Keine doppelten Leerzeilen.
- Beginne jede Aufzaehlung direkt mit '• ' (Unicode Bullet) OHNE Zeilenumbruch nach dem Bullet!
- Schreibe Pfeile direkt vor den Text: '➔ <b>Haupt-Pick:</b> ...' OHNE Leerzeile davor.
- Ganz am Ende MUSS der exakte Parser-Block '---JSON_TRACKING---' folgen.

REPORT-HTML:
🎯 <b>JARVIS PDC DARTS INTEL • {session_name}</b>
<i>3-Dart Average Edge • Checkout Efficiency • Value-Picks</i>

━━━━━━━━━━━━━━━━━━━━
⭐ <b>DARTS MATCH OF THE DAY (Single Bet)</b>
• <b>Match:</b> [Uhrzeit] Uhr | [Spieler A] vs. [Spieler B]
➔ <b>Haupt-Pick:</b> <b>[Match-Sieg / Leg-Handicap / 180s]</b> @ [Quote]
🔄 <b>Buchmacher-Alternative:</b> [Klassischer 2-Weg Sieg] @ [Quote]
⚠️ <b>Value-Grenze:</b> Spielbar bis @ [Quote] | 💰 <b>Einsatz:</b> [1.0 - 2.0] Units
📊 <b>Quant-Daten:</b> Modell-Chance: [XX.X]% | Fair Odds: ~[X.XX] (<b>+[X.X]% EV</b>)
🔍 <b>Edge:</b> [Scoring-Konstanz, First 9 Average, Checkout-Quote unter Druck]

━━━━━━━━━━━━━━━━━━━━
🔥 <b>QUANT VALUE ACCA ([Anzahl]-er Kombi)</b>
• [Uhrzeit] Uhr | [Spieler A] vs. [Spieler B] ➔ <b>[Tipp 1]</b> @ [Quote] (Alt: [Alternative] @ [Quote])
• [Uhrzeit] Uhr | [Spieler C] vs. [Spieler D] ➔ <b>[Tipp 2]</b> @ [Quote] (Alt: [Alternative] @ [Quote])
• [Uhrzeit] Uhr | [Spieler E] vs. [Spieler F] ➔ <b>[Tipp 3]</b> @ [Quote] (Alt: [Alternative] @ [Quote])
[... ggf. Bein 4 ergaenzen falls Value vorhanden ...]
📈 <b>Gesamtquote:</b> <b>@[Quote]</b>
⚠️ <b>Value-Grenze:</b> Kombi spielbar bis @ [Quote]
💰 <b>Einsatz:</b> [0.5 - 1.0] Units
🔍 <b>Kombi-Logik:</b> [Warum diese Kombination mathematisch korreliert oder unabhaengig starken Value bietet]

━━━━━━━━━━━━━━━━━━━━
🎯 <b>180s &amp; SCORING SPOTLIGHT</b>
• <b>Match:</b> [Uhrzeit] Uhr | [Spieler A] vs. [Spieler B]
➔ <b>Pick:</b> <b>[Over/Under 180s / Leg-Total / Hoechstes Checkout]</b> @ [Quote]
🔄 <b>Buchmacher-Alternative:</b> [Alternative Linie] @ [Quote]
⚠️ <b>Value-Grenze:</b> Spielbar bis @ [Quote] | 💰 <b>Einsatz:</b> [0.5 - 1.0] Units
🔍 <b>Rationale:</b> [T19/T20 Praeferenzen, Pace des Spiels, Matchlaenge]

---JSON_TRACKING---
[
  {{
    "match": "Player A vs Player B",
    "sport": "darts",
    "pick": "Player A Sieg",
    "odds": "1.70",
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
                        print(f"{len(new_picks)} Darts-Picks hinzugefuegt.")
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
    run_darts_report()
