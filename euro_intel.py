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
TELEGRAM_THREAD_ID = os.environ.get("TELEGRAM_EURO_THREAD_ID", "").strip()

LOCAL_TZ = ZoneInfo("Europe/Berlin")

EURO_LEAGUES = [
    # Europäischer Basketball
    "basketball_euroleague",
    "basketball_spain_acb",
    "basketball_germany_bbl",
    # Europäisches Spitzen-Eishockey
    "icehockey_sweden_shl",
    "icehockey_liiga",
    "icehockey_germany_del"
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

def fetch_euro_odds():
    all_events = []
    now_utc = datetime.now(timezone.utc)
    # Scan-Fenster: 8 Stunden (deckt von 16:30 Uhr bis Mitternacht exakt alle Abendpartien ab)
    cutoff = now_utc + timedelta(hours=8)

    for sport in EURO_LEAGUES:
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
                            f"[{sport}] {match['home_team']} vs. {match['away_team']} ({time_str}) | Quoten: {' // '.join(odds_details)}"
                        )
        except Exception as e:
            print(f"Fehler bei {sport}: {e}")

    print(f"Gefundene europäische Abend-Events: {len(all_events)}")
    return "\n".join(all_events[:50])

def generate_euro_report():
    odds_data = fetch_euro_odds()
    if not odds_data:
        print("Keine europäischen Basketball- oder Eishockeyspiele für heute Abend im Fenster.")
        return

    today_str = datetime.now(LOCAL_TZ).strftime("%d.%m.%Y")
    prompt = f"""
Du bist 'JARVIS EURO INTEL' – Quantitativer Wettexperte für europäischen Spitzen-Basketball (EuroLeague, ACB, BBL) und europäisches Eishockey (SHL, Liiga, DEL).
Erstelle für heute Abend ({today_str}) ein präzises Value-Dossier für die Prime-Time (18:00 bis 22:00 Uhr MEZ).

VERFÜGBARE PARTIEN & ECHTE BUCHMACHERQUOTEN:
{odds_data}

RICHTLINIEN:
- Wähle AUSNAHMSLOS Partien aus der obigen Liste. Erfinde keine Partien oder Quoten.
- Suche echte Kanten (+EV) bei Siegen, Spreads/Handicaps oder Over/Under-Linien (Eishockey z. B. 4.5/5.5 Tore, Basketball Gesamtpunkte).

FORMATIERUNG & STRUKTUR (Exaktes HTML für Telegram):
🏀🏒 <b>JARVIS EURO-HOOPS &amp; ICE DOSSIER</b>
<i>EuroLeague • SHL • DEL • Liiga • Prime-Time Value</i>

━━━━━━━━━━━━━━━━━━━━
⭐ <b>EURO PICK OF THE DAY (Single Bet)</b>
- [Uhrzeit] [Liga/Sport] Heim vs. Gast ➔ <b>Pick: [Markt &amp; Tipp]</b> (Quote: X.XX)
Modell-Chance: XX.X% | Fair Odds: ~X.XX
Edge: [Detaillierte taktische &amp; statistische Kante: Goaltending/Pace, Heimvorteil, Rebounding]

━━━━━━━━━━━━━━━━━━━━
🏒 <b>EURO ICE VALUE TICKET (2er-Kombi Eishockey)</b>
- [Uhrzeit] [SHL/DEL/Liiga] Heim vs. Gast ➔ Pick: [Tipp] (Quote: X.XX)
- [Uhrzeit] [SHL/DEL/Liiga] Heim vs. Gast ➔ Pick: [Tipp] (Quote: X.XX)
<b>Gesamtquote: X.XX</b>
Rationale: [Defensivwerte, Special Teams, Powerplay-Effizienz]

━━━━━━━━━━━━━━━━━━━━
🏀 <b>EURO HOOPS VALUE TICKET (2er-Kombi Basketball)</b>
- [Uhrzeit] [EuroLeague/BBL/ACB] Heim vs. Gast ➔ Pick: [Tipp/Spread/Total] (Quote: X.XX)
- [Uhrzeit] [EuroLeague/BBL/ACB] Heim vs. Gast ➔ Pick: [Tipp/Spread/Total] (Quote: X.XX)
<b>Gesamtquote: X.XX</b>
Rationale: [Pace, Offensive Rating, Matchup-Vorteile]

━━━━━━━━━━━━━━━━━━━━
🎯 <b>QUANT LONGSHOT / PLUS-ODDS SPEC</b>
- [Uhrzeit] [Sportart] Match ➔ <b>Pick: [Markt &amp; Tipp]</b> (Quote: 2.XX+)
Kanten-Spotlight: [Warum der Markt den Außenseiter oder die Over/Under-Linie fehlbewertet]

Gib AUSSCHLIESSLICH den fertigen HTML-Report aus (kein Markdown, keine Backticks ```html).
"""
    url = f"[https://generativelanguage.googleapis.com/v1beta/models/gemini-3.8-flash:generateContent?key=](https://generativelanguage.googleapis.com/v1beta/models/gemini-3.8-flash:generateContent?key=){GEMINI_API_KEY}"
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "tools": [{"googleSearch": {}}],
        "generationConfig": {"temperature": 0.2}
    }

    for attempt in range(1, 4):
        try:
            res = requests.post(url, json=payload, timeout=90)
            if res.status_code == 200:
                report = res.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
                report = report.replace("```html", "").replace("```", "").strip()
                send_telegram(report)
                print("Euro Report erfolgreich versendet.")
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
    generate_euro_report()
