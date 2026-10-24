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

def fetch_nfl_matches():
    matches_summary = []
    now_utc = datetime.now(timezone.utc)
    cutoff = now_utc + timedelta(hours=48)

    url = "https://api.the-odds-api.com/v4/sports/americanfootball_nfl/odds/"
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
                    line = f"[NFL] {match['home_team']} vs. {match['away_team']} ({time_str}) | {' // '.join(details)}"
                    matches_summary.append(line)
    except Exception as e:
        print(f"Odds API Fehler: {e}")

    print(f"NFL-Partien gefunden: {len(matches_summary)}")
    return "\n".join(matches_summary)

def analyze_nfl(matches_text):
    prompt = f"""
Du bist 'JARVIS NFL QUANT PRO', spezialisiert auf quantitative NFL-Analysen (+EV, Key Numbers bei Spreads [3, 7], EPA/Play, QB/Offensive Line Injuries).
Hier sind die Spiele mit Quoten, Spreads und Totals:
{matches_text}

REGELN:
1. MATHEMATISCHER EDGE (+EV): P(Win) muss > (1 / Quote) sein.
2. PICK OF THE DAY: Stärkste Einzelwette (1.75 - 2.20).
3. TICKETS:
   - POTD (Single Bet)
   - Gridiron Banker (2er-Double, Quote ca. 2.00 - 2.50)
   - Key Number Spread Ticket (2er-Kombi)
   - Over/Under Totals Ticket (2er-Kombi)

FORMAT-VORGABE (Telegram-HTML: <b>fett</b>, <i>kursiv</i>):
<b>🏈 JARVIS NFL INTEL & VALUE REPORT</b>
<i>Quantitatives Dossier • Key Numbers • EPA & Matchup-Edges</i>

<b>━━━━━━━━━━━━━━━━━━━━</b>
⭐ <b>PICK OF THE DAY (Single Bet)</b>
- <b>[Uhrzeit] Heim vs. Auswärts</b> -> Pick: <b>[Pick]</b> (Quote: [Quote])
<i>Fair Odds:</i> ~[Faire Quote] | <i>Chance:</i> [X]%
<i>Edge:</i> [Matchup-Diskrepanz, EPA/Play, QB-Status]

<b>━━━━━━━━━━━━━━━━━━━━</b>
1. <b>NFL BANKER DOUBLE (2er-Double)</b>
- <b>[Uhrzeit] Heim vs. Auswärts</b> -> Pick: <b>[Pick]</b> (Quote)
- <b>[Uhrzeit] Heim vs. Auswärts</b> -> Pick: <b>[Pick]</b> (Quote)
<b>Gesamtquote: [Quote]</b>

<b>━━━━━━━━━━━━━━━━━━━━</b>
2. <b>KEY NUMBER SPREAD TICKET (2er-Kombi)</b>
- <b>[Uhrzeit] Heim vs. Auswärts</b> -> Pick: <b>[Pick]</b> (Quote)
- <b>[Uhrzeit] Heim vs. Auswärts</b> -> Pick: <b>[Pick]</b> (Quote)
<b>Gesamtquote: [Quote]</b>

<b>━━━━━━━━━━━━━━━━━━━━</b>
3. <b>GAME TOTALS (OVER/UNDER) TICKET</b>
- <b>[Uhrzeit] Heim vs. Auswärts</b> -> Pick: <b>[Pick]</b> (Quote)
- <b>[Uhrzeit] Heim vs. Auswärts</b> -> Pick: <b>[Pick]</b> (Quote)
<b>Gesamtquote: [Quote]</b>

---JSON_DATA---
{{
  "date": "{datetime.now(LOCAL_TZ).strftime('%Y-%m-%d')}",
  "potd": {{"match": "Heim vs Auswärts", "pick": "Pick", "odds": 1.90}},
  "banker": {{"odds": 2.25, "picks": [{{"match": "M1", "pick": "Pick", "odds": 1.50}}, {{"match": "M2", "pick": "Pick", "odds": 1.50}}]}},
  "spread_ticket": {{"odds": 3.65, "picks": [{{"match": "M1", "pick": "Pick", "odds": 1.90}}, {{"match": "M2", "pick": "Pick", "odds": 1.92}}]}},
  "totals_ticket": {{"odds": 3.65, "picks": [{{"match": "M1", "pick": "Pick", "odds": 1.91}}, {{"match": "M2", "pick": "Pick", "odds": 1.91}}]}}
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
            with open("pending_nfl.json", "w", encoding="utf-8") as f:
                json.dump(bet_data, f, ensure_ascii=False, indent=2)
            print("Picks in pending_nfl.json gespeichert.")
        except Exception as e:
            print(f"JSON Parsing-Fehler: {e}")
        return report_text
    return full_text

if __name__ == "__main__":
    matches = fetch_nfl_matches()
    if not matches:
        msg = "🏈 <b>Jarvis NFL Status:</b> Keine Spiele im aktuellen Zeitfenster."
        print(msg)
        send_telegram_message(msg)
    else:
        raw_output = analyze_nfl(matches)
        if raw_output != "ERROR":
            send_telegram_message(parse_and_save_bets(raw_output))
            print("✅ NFL Report erfolgreich gesendet.")
        else:
            send_telegram_message("⚠️ <b>Jarvis NFL Error:</b> KI-Generierung fehlgeschlagen.")
            sys.exit(1)
