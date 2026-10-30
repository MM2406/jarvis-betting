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
TELEGRAM_THREAD_ID = os.environ.get("TELEGRAM_SOCCER_THREAD_ID", "").strip()

LOCAL_TZ = ZoneInfo("Europe/Berlin")
HISTORY_FILE = "soccer_history.json"

SOCCER_LEAGUES = [
    "soccer_uefa_champs_league",
    "soccer_uefa_europa_league",
    "soccer_uefa_europa_conference_league",
    "soccer_germany_bundesliga",
    "soccer_germany_bundesliga2",
    "soccer_epl",
    "soccer_spain_la_liga",
    "soccer_italy_serie_a",
    "soccer_france_ligue_one",
    "soccer_austria_bundesliga",
    "soccer_usa_mls"
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
        print("Keine offenen Soccer-Picks zur Auswertung.")
        return history

    still_pending = []
    settled_now = []

    for item in pending:
        prompt_settle = f"""
Recherchiere via Google Search das offizielle Endergebnis für folgendes Fußballspiel:
Match: {item.get('match')}
Wettbewerb: {item.get('league')}
Tipp: {item.get('pick')}
Datum: {item.get('date')}

REGELN:
1. Prüfe, ob das Match regulär beendet ist (nach 90 Min). Falls noch nicht begonnen oder live, antworte mit PENDING.
2. Markiere mit 'WON', wenn der Tipp aufgegangen ist, sonst 'LOST'.
3. Bei Push (z.B. Handicap Unentschieden / Draw No Bet Push) gib 'VOID' aus.

Format:
RESULT: WON oder LOST oder PENDING oder VOID
SCORE: Endergebnis (z.B. 2:1)
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
            print(f"Fehler bei Abrechnung {item.get('match')}: {e}")
            still_pending.append(item)

    if settled_now:
        history["settled"].extend(settled_now)
        history["pending"] = still_pending
        save_history(history)

        won_count = sum(1 for p in settled_now if p["status"] == "WON")
        total_count = len(settled_now)

        msg = f"📊 <b>JARVIS SOCCER ABRECHNUNG</b>\nAusgewertete Tipps: <b>{won_count}/{total_count}</b> Treffer.\n"
        for p in settled_now:
            icon = "✅" if p["status"] == "WON" else ("❌" if p["status"] == "LOST" else "🟡")
            msg += f"\n{icon} <b>{p['match']}</b>\nTipp: {p['pick']} (@ {p.get('odds', 'N/A')})"
        send_telegram(msg)

    return history

def fetch_soccer_odds(already_tracked_matches):
    all_events = []
    now_utc = datetime.now(timezone.utc)
    now_hour = datetime.now(LOCAL_TZ).hour

    # Fenster je nach Schicht:
    # Vor 15 Uhr: Nachmittagsspiele (nächste 7 Std)
    # Nach 15 Uhr: Abendschlager (nächste 9 Std)
    window_hours = 7 if now_hour < 15 else 9
    cutoff = now_utc + timedelta(hours=window_hours)

    for sport in SOCCER_LEAGUES:
        url = f"https://api.the-odds-api.com/v4/sports/{sport}/odds/"
        params = {
            "apiKey": ODDS_API_KEY,
            "regions": "eu",
            "markets": "h2h,totals,spreads",
            "oddsFormat": "decimal"
        }
        try:
            res = requests.get(url, params=params, timeout=12)
            if res.status_code == 200:
                data = res.json()
                for match in data:
                    match_name = f"{match['home_team']} vs. {match['away_team']}"
                    # Bereits getrackte Partien nicht nochmals analysieren
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
                            m_key = m.get("key")
                            outcomes = [f"{o['name']} ({o.get('point', '')}): {o['price']}" for o in m.get("outcomes", [])]
                            odds_details.append(f"{m_key}: {', '.join(outcomes)}")

                        all_events.append(
                            f"[{sport}] {match_name} ({time_str}) | Quoten: {' // '.join(odds_details)}"
                        )
        except Exception as e:
            print(f"Fehler bei {sport}: {e}")

    print(f"Gefundene Fußball-Partien für dieses Zeitfenster: {len(all_events)}")
    return "\n".join(all_events[:45])

def generate_soccer_report():
    history = load_history()
    settle_pending_picks(history)

    now_hour = datetime.now(LOCAL_TZ).hour
    # Morgens vor 10:00 Uhr: Nur Abrechnung
    if now_hour < 10:
        print("Morgen-Run: Abrechnung erledigt. Keine Picks vor 11:00 Uhr.")
        return

    tracked_matches = {p.get("match") for p in history.get("pending", [])}
    odds_data = fetch_soccer_odds(tracked_matches)

    if not odds_data:
        print(f"Keine passenden Fußballspiele für dieses Zeitfenster ({now_hour} Uhr) gefunden.")
        return

    edition = "MITTAGS-EDITION (Nachmittagsspiele)" if now_hour < 15 else "ABEND-EDITION (Flutlicht & Topspiele)"
    today_str = datetime.now(LOCAL_TZ).strftime("%d.%m.%Y")
    today_iso = datetime.now(LOCAL_TZ).strftime("%Y-%m-%d")

    prompt = f"""
Du bist 'JARVIS SOCCER INTEL' – Quantitativer Wettexperte für Spitzenfußball.
Erstelle für heute ({today_str}) die {edition}.

VERFÜGBARE PARTIEN & ECHTE BUCHMACHERQUOTEN:
{odds_data}

RICHTLINIEN & BUCHMACHER-KOMPATIBILITÄT:
- Wähle ausschließlich Partien aus der obigen Liste.
- Analysiere xG-Werte, Poisson-Modelle und weise den prozentualen mathematischen Vorteil (+EV %) aus.
- BUCHMACHER-ALTERNATIVE: Gib für jeden Pick immer eine klassische Standard-Alternative für bet365/Tipico an (z. B. wenn der Haupttipp Under 3.25 ist, nenne Under 2.5 oder Under 3.5).
- VALUE-GRENZE: Gib für jeden Pick 'Spielbar bis Mindestquote @ X.XX' an.
- UNITS: Vergib eine feste Einsatzempfehlung (1.0 bis 2.0 Units).

FORMATIERUNG:
Telegram-HTML ZUERST, danach der exakte JSON-Block.

REPORT-HTML:
⚽ <b>JARVIS SOCCER INTEL • {edition}</b>
<i>Quantitative Match-Modelle • xG Edge • Value-Picks</i>

━━━━━━━━━━━━━━━━━━━━
⭐ <b>SOCCER PICK OF THE DAY (Single Bet)</b>
• [Uhrzeit] | Heim vs. Gast
  ➔ <b>Pick: [Markt &amp; Tipp]</b> @ X.XX
🔄 <b>Buchmacher-Alternative:</b> [Klassische Standard-Linie] @ X.XX
⚠️ <b>Value-Grenze:</b> Spielbar bis @ X.XX | <b>Einsatz:</b> [1.0 - 2.0] Units
<b>Modell-Chance:</b> XX.X% | <b>Fair Odds:</b> ~X.XX (<b>+X.X% EV</b>)
<b>Edge:</b> [xG-Dominanz, Matchup-Analyse, Defensiv-Ratings]

━━━━━━━━━━━━━━━━━━━━
🔥 <b>VALUE DOUBLE TICKET (2er-Kombi)</b>
• Heim vs. Gast ➔ <b>[Tipp 1]</b> @ X.XX (Alt: [Alternative])
• Heim vs. Gast ➔ <b>[Tipp 2]</b> @ X.XX (Alt: [Alternative])
<b>Gesamtquote: X.XX</b> | <b>Einsatz:</b> 1.0 Units
<b>Rationale:</b> [Kompakte Begründung beider Auswahlen]

---JSON_TRACKING---
[
  {{
    "match": "Team A vs Team B",
    "league": "soccer_epl",
    "pick": "Team A Sieg",
    "odds": "1.75",
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
                        print(f"{len(new_picks)} Soccer-Picks getrackt.")
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
    generate_soccer_report()
