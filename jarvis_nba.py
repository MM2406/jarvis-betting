import os
import sys
import json
import requests
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo

ODDS_API_KEY = os.environ.get("ODDS_API_KEY", "").strip()
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "").strip()

LOCAL_TZ = ZoneInfo("Europe/Berlin")

def send_telegram_message(text):
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
        payload = {"chat_id": TELEGRAM_CHAT_ID, "text": chunk, "parse_mode": "HTML"}
        res = requests.post(url, json=payload, timeout=20)
        if res.status_code != 200:
            payload.pop("parse_mode", None)
            res2 = requests.post(url, json=payload, timeout=20)
            if res2.status_code != 200:
                print(f"Telegram Fehler: {res2.text}")

def fetch_nba_matches():
    matches_summary = []
    now_utc = datetime.now(timezone.utc)
    cutoff = now_utc + timedelta(hours=30)

    url = "https://api.the-odds-api.com/v4/sports/basketball_nba/odds/"
    params = {
        "apiKey": ODDS_API_KEY,
        "regions": "us,eu",
        "markets": "h2h,spreads,totals",
        "oddsFormat": "decimal"
    }
    try:
        res = requests.get(url, params=params, timeout=15)
        if res.status_code == 200:
            data = res.json()
            for match in data:
                commence_utc = datetime.fromisoformat(match["commence_time"].replace("Z", "+00:00"))
                if now_utc <= commence_utc <= cutoff:
                    bookies = match.get("bookmakers", [])
                    if not bookies:
                        continue
                    time_str = commence_utc.astimezone(LOCAL_TZ).strftime("%d.%m. %H:%M Uhr")
                    details = []
                    for m in bookies[0].get("markets", []):
                        m_key = m.get("key")
                        if m_key == "h2h":
                            details.append("ML: " + ", ".join([f"{o['name']} ({o['price']})" for o in m.get("outcomes", [])]))
                        elif m_key == "spreads":
                            details.append("Spread: " + ", ".join([f"{o['name']} {o.get('point', '')} ({o['price']})" for o in m.get("outcomes", [])]))
                        elif m_key == "totals":
                            details.append("Totals: " + ", ".join([f"{o['name']} {o.get('point', '')} ({o['price']})" for o in m.get("outcomes", [])]))
                    line = f"[NBA] {match['home_team']} vs. {match['away_team']} ({time_str}) | {' // '.join(details)}"
                    matches_summary.append(line)
    except Exception as e:
        print(f"Odds API Fehler: {e}")

    print(f"NBA-Partien gefunden: {len(matches_summary)}")
    return "\n".join(matches_summary)

def analyze_nba(matches_text):
    prompt = f"""
Du bist 'JARVIS NBA QUANT PRO', spezialisiert auf quantitative NBA-Analysen (+EV, Pace, Rest-Days, B2B-Faktoren).
Hier sind die Spiele mit Quoten, Spreads und Totals:
{matches_text}

REGELN:
1. MATHEMATISCHER EDGE (+EV): P(Win) muss > (1 / Quote) sein.
2. PICK OF THE DAY: Stärkste Einzelwette (1.75 - 2.20).
3. TICKETS:
   - POTD (Single Bet)
   - Banker Double (2er-Kombi, Quote 2.00 - 2.40)
   - Spread Value Ticket (2er-Kombi)
   - Points/Totals Ticket (Over/Under 2er- oder 3er-Kombi)

FORMAT-VORGABE (Telegram-HTML: <b>fett</b>, <i>kursiv</i>):
<b>🏀 JARVIS NBA INTEL & VALUE REPORT</b>
<i>Quantitatives Dossier • Rest-Advantage • Matchup-Pace</i>

<b>━━━━━━━━━━━━━━━━━━━━</b>
⭐ <b>PICK OF THE DAY (Single Bet)</b>
- <b>[Uhrzeit] Heim vs. Auswärts</b> -> Pick: <b>[Pick]</b> (Quote: [Quote])
<i>Fair Odds:</i> ~[Faire Quote] | <i>Chance:</i> [X]%
<i>Edge:</i> [Pace, B2B-Vorteil, Verletzungen]

<b>━━━━━━━━━━━━━━━━━━━━</b>
1. <b>NBA BANKER DOUBLE (2er-Double)</b>
- <b>[Uhrzeit] Heim vs. Auswärts</b> -> Pick: <b>[Pick]</b> (Quote)
- <b>[Uhrzeit] Heim vs. Auswärts</b> -> Pick: <b>[Pick]</b> (Quote)
<b>Gesamtquote: [Quote]</b>

<b>━━━━━━━━━━━━━━━━━━━━</b>
2. <b>SPREAD VALUE TICKET (2er-Kombi)</b>
- <b>[Uhrzeit] Heim vs. Auswärts</b> -> Pick: <b>[Pick]</b> (Quote)
- <b>[Uhrzeit] Heim vs. Auswärts</b> -> Pick: <b>[Pick]</b> (Quote)
<b>Gesamtquote: [Quote]</b>

<b>━━━━━━━━━━━━━━━━━━━━</b>
3. <b>TOTALS / OVER-UNDER TICKET</b>
- <b>[Uhrzeit] Heim vs. Auswärts</b> -> Pick: <b>[Pick]</b> (Quote)
- <b>[Uhrzeit] Heim vs. Auswärts</b> -> Pick: <b>[Pick]</b> (Quote)
<b>Gesamtquote: [Quote]</b>

---JSON_DATA---
{{
  "date": "{datetime.now(LOCAL_TZ).strftime('%Y-%m-%d')}",
  "potd": {{"match": "Heim vs Auswärts", "pick": "Pick", "odds": 1.90}},
  "banker": {{"odds": 2.20, "picks": [{{"match": "M1", "pick": "Pick", "odds": 1.48}}, {{"match": "M2", "pick": "Pick", "odds": 1.49}}]}},
  "spread_ticket": {{"odds": 3.60, "picks": [{{"match": "M1", "pick": "Pick", "odds": 1.90}}, {{"match": "M2", "pick": "Pick", "odds": 1.90}}]}},
  "totals_ticket": {{"odds": 3.60, "picks": [{{"match": "M1", "pick": "Pick", "odds": 1.90}}, {{"match": "M2", "pick": "Pick", "odds": 1.90}}]}}
}}
"""
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-3.8-flash:generateContent?key={GEMINI_API_KEY}"
    payload = {"contents": [{"parts": [{"text": prompt}]}], "generationConfig": {"temperature": 0.2}}
    try:
        res = requests.post(url, json=payload, timeout=120)
        res.raise_for_status()
        return res.json()["candidates"][0]["content"]["parts"][0]["text"]
    except Exception as e:
        print(f"API Fehler: {e}")
        return "ERROR"

def parse_and_save_bets(full_text):
    if "---JSON_DATA---" in full_text:
        parts = full_text.split("---JSON_DATA---")
        report_text = parts[0].strip()
        try:
            bet_data = json.loads(parts[1].strip())
            with open("pending_nba.json", "w", encoding="utf-8") as f:
                json.dump(bet_data, f, ensure_ascii=False, indent=2)
            print("Picks in pending_nba.json gespeichert.")
        except Exception as e:
            print(f"JSON Parsing-Fehler: {e}")
        return report_text
    return full_text

if __name__ == "__main__":
    matches = fetch_nba_matches()
    if not matches:
        msg = "🏀 <b>Jarvis NBA Status:</b> Keine Spiele im aktuellen Zeitfenster."
        print(msg)
        send_telegram_message(msg)
    else:
        raw_output = analyze_nba(matches)
        if raw_output != "ERROR":
            send_telegram_message(parse_and_save_bets(raw_output))
            print("✅ NBA Report erfolgreich gesendet.")
        else:
            send_telegram_message("⚠️ <b>Jarvis NBA Error:</b> KI-Generierung fehlgeschlagen.")
            sys.exit(1)
