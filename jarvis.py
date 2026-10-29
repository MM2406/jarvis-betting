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
    "soccer_germany_bundesliga",
    "soccer_germany_bundesliga2",
    "soccer_germany_dfb_pokal",
    "soccer_epl",
    "soccer_spain_la_liga",
    "soccer_italy_serie_a",
    "soccer_france_ligue_one",
    "soccer_uefa_champs_league",
    "soccer_uefa_europa_league",
    "soccer_austria_bundesliga",
    "soccer_usa_mls"
]

def send_telegram(text):
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
        print(f"Fehler beim Laden der History: {e}")
        return {"settled": [], "pending": []}

def save_history(history):
    try:
        with open(HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump(history, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"Fehler beim Speichern der History: {e}")

def settle_pending_picks(history):
    pending = history.get("pending", [])
    if not pending:
        print("Keine offenen Soccer-Picks zur Abrechnung.")
        return history

    still_pending = []
    settled_now = []

    for item in pending:
        prompt_settle = f"""
Recherchiere via Google Search das offizielle Endergebnis für folgende Fußballwette:
Spiel: {item.get('match')}
Tipp / Markt: {item.get('pick')}
Datum: {item.get('date')}

REGELN:
1. Prüfe, ob die Partie bereits beendet ist. Falls noch nicht begonnen oder laufend, antworte mit PENDING.
2. Markiere mit 'WON', wenn die Wette gewonnen hat, oder 'LOST', wenn sie verloren ging.
3. Bei Spielabsage oder Push (z.B. Asian Handicap Draw) antworte mit VOID.

Antworte strikt in diesem Format:
RESULT: WON oder LOST oder PENDING oder VOID
SCORE: Exaktes Endergebnis (z.B. 2:1)
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
        settle_msg = f"📊 <b>JARVIS SOCCER ABRECHNUNG</b>\nAusgewertete Wetten: {won_count}/{total_count} gewonnen.\n"
        for p in settled_now:
            icon = "✅" if p["status"] == "WON" else ("❌" if p["status"] == "LOST" else "🟡")
            settle_msg += f"\n{icon} <b>{p['match']}</b>: {p['pick']} (Quote: {p.get('odds', 'N/A')})"
        send_telegram(settle_msg)

    return history

def fetch_soccer_data():
    all_matches = []
    now_utc = datetime.now(timezone.utc)
    # 12 STUNDEN FILTER: Reicht bei 18:00 Uhr exakt bis 06:00 Uhr morgens (deckt MLS vollständig ab, schließt Folgetag aus)
    cutoff = now_utc + timedelta(hours=12)

    for league in SOCCER_LEAGUES:
        url = f"https://api.the-odds-api.com/v4/sports/{league}/odds/"
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
                        
                        odds_summary = []
                        for m in bookies[0].get("markets", []):
                            m_key = m.get("key")
                            outcomes = [f"{o['name']} ({o.get('point', '')}): {o['price']}" for o in m.get("outcomes", [])]
                            odds_summary.append(f"{m_key}: {', '.join(outcomes)}")

                        all_matches.append(
                            f"[{league}] {match['home_team']} vs. {match['away_team']} ({time_str}) | Quoten: {' // '.join(odds_summary)}"
                        )
        except Exception as e:
            print(f"Fehler bei Liga {league}: {e}")

    return "\n".join(all_matches[:60])

def generate_soccer_report():
    history = load_history()
    settle_pending_picks(history)

    odds_data = fetch_soccer_data()
    if not odds_data:
        print("Keine relevanten Fußballspiele im 12-Stunden-Fenster gefunden.")
        return

    today_str = datetime.now(LOCAL_TZ).strftime("%d.%m.%Y")
    prompt = f"""
Du bist 'JARVIS SOCCER QUANT' – professioneller Sportwetten-Analyst für europäischen Spitzenfußball und MLS.
Erstelle ein fundiertes Value- und Spieltags-Dossier für die heutigen Abend- und Nachtspiele ({today_str}).

STRIKTE ZEIT- & SPIELTAGSVORGABE:
- Wähle AUSNAHMSLOS Partien aus der folgenden Liste, die HEUTE ABEND oder in der DIREKT FOLGENDEN NACHT (z.B. MLS bis max. 05:30 Uhr morgens MEZ) angepfiffen werden.
- Partien des morgigen Abends sind STRIKT VERBOTEN und dürfen unter keinen Umständen im Report erscheinen.

VERFÜGBARE PARTIEN & ECHTE QUOTEN:
{odds_data}

FORMATIERUNG & STRUKTUR (Exaktes HTML für Telegram):
⚽ <b>JARVIS SOCCER INTEL &amp; VALUE REPORT</b>
<i>Quantitatives Dossier • +EV Filter • Spieltags-Analysen</i>

━━━━━━━━━━━━━━━━━━━━
⭐ <b>PICK OF THE DAY (Single Bet)</b>
- [Uhrzeit] [Liga] Heim vs. Gast ➔ <b>Pick: [Markt &amp; Tipp]</b> (Quote: X.XX)
Fair Odds: ~X.XX | Chance: XX.X%
Edge: [Präzise quantitative Begründung: xG-Vorteil, Spielstil, Pressing-Resistenz, taktische Kante]

━━━━━━━━━━━━━━━━━━━━
1️⃣ <b>SOCCER BANKER TICKET (2er-Double)</b>
- [Uhrzeit] [Liga] Heim vs. Gast ➔ Pick: [Tipp] (Quote: X.XX)
- [Uhrzeit] [Liga] Heim vs. Gast ➔ Pick: [Tipp] (Quote: X.XX)
<b>Gesamtquote: X.XX</b>
Modell-Edge: [Kompakte Begründung]

━━━━━━━━━━━━━━━━━━━━
2️⃣ <b>DYNAMIC GOALS &amp; BTTS VALUE TICKET (2er-Kombi)</b>
- [Uhrzeit] [Liga] Heim vs. Gast ➔ Pick: [Under/Over/BTTS] (Quote: X.XX)
- [Uhrzeit] [Liga] Heim vs. Gast ➔ Pick: [Under/Over/BTTS] (Quote: X.XX)
<b>Gesamtquote: X.XX</b>
Modell-Edge: [xG-Verteilung, defensive Matchups]

━━━━━━━━━━━━━━━━━━━━
3️⃣ <b>DYNAMIC MULTI-LEAGUE / MLS VALUE TICKET (2er-Kombi)</b>
- [Uhrzeit] [Liga] Heim vs. Gast ➔ Pick: [Tipp] (Quote: X.XX)
- [Uhrzeit] [Liga] Heim vs. Gast ➔ Pick: [Tipp] (Quote: X.XX)
<b>Gesamtquote: X.XX</b>
Modell-Edge: [Kompakte Begründung]

━━━━━━━━━━━━━━━━━━━━
4️⃣ <b>VALUE TORSCHÜTZE / SPECIAL PICK</b>
- Spieler (Team) – [Markt z. B. Trifft zu beliebigem Zeitpunkt] (Quote: X.XX)
Spotlight: [xG/90min, Strafraumpräsenz, gegnerische Defensivschwächen]

Gib AUSSCHLIESSLICH den fertigen HTML-Report aus (kein einleitendes Bla-Bla, kein Markdown, keine Backticks ```html).
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
                print("Soccer Report erfolgreich generiert und versendet.")
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
