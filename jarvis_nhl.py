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
TELEGRAM_THREAD_ID = os.environ.get("TELEGRAM_THREAD_ID", "").strip()

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
        if TELEGRAM_THREAD_ID:
            try:
                payload["message_thread_id"] = int(TELEGRAM_THREAD_ID)
            except ValueError:
                pass

        res = requests.post(url, json=payload, timeout=20)
        if res.status_code != 200:
            payload.pop("parse_mode", None)
            res2 = requests.post(url, json=payload, timeout=20)
            if res2.status_code != 200:
                print(f"Telegram Fehler: {res2.text}")

def fetch_nhl_data():
    url = "https://api.the-odds-api.com/v4/sports/icehockey_nhl/odds/"
    params = {
        "apiKey": ODDS_API_KEY,
        "regions": "us,eu",
        "markets": "h2h,spreads,totals",
        "oddsFormat": "decimal"
    }
    matches_summary = []
    now_utc = datetime.now(timezone.utc)
    cutoff = now_utc + timedelta(hours=30)

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
                            details.append("Moneyline: " + ", ".join([f"{o['name']} ({o['price']})" for o in m.get("outcomes", [])]))
                        elif m_key == "spreads":
                            details.append("Puck Line: " + ", ".join([f"{o['name']} {o.get('point', '')} ({o['price']})" for o in m.get("outcomes", [])]))
                        elif m_key == "totals":
                            details.append("Totals: " + ", ".join([f"{o['name']} {o.get('point', '')} ({o['price']})" for o in m.get("outcomes", [])]))
                    matches_summary.append(f"{match['home_team']} vs. {match['away_team']} ({time_str}) | {' // '.join(details)}")
    except Exception as e:
        print(f"Fehler bei NHL Odds: {e}")

    print(f"NHL Partien gesammelt: {len(matches_summary)}")
    return "\n".join(matches_summary)

def analyze_nhl(matches_text):
    prompt = f"""
Du bist 'JARVIS NHL QUANT PRO', spezialisiert auf Eishockey-Analysen (Starting Goalies, Schussvolumen/Corsi, Powerplay-Units, xG).
Recherchiere über Google Search bestätigte Starting Goalies und aktuelle Player Props (Anytime Goalscorer, Spieler-Punkte, Shots on Goal).

Partien & Quoten:
{matches_text}

TICKET-STRUKTUR:
1. ⭐ NHL PICK OF THE DAY (Single Bet, Quote 1.70 - 2.25): Höchster Value.
2. 1. NHL BANKER TICKET (Strikt 2er-Double): Höchste Zuverlässigkeit (Moneyline / Puck Line +1.5). Quote 2.10 - 2.80.
3. 2. DYNAMIC TOTALS VALUE COMBO (Freie Größe: 2 bis 5 Picks): Ineffiziente Over/Under Goal-Lines (5.5, 6.0, 6.5). Dynamisch nach Kantenstärke.
4. 3. DYNAMIC NHL PLAYER PROPS MULTI-TICKET (Freie Größe: 2 bis 5 Picks):
   - Baue eine reine Spieler-Kombi aus Goalscorern, Points (Over 0.5/1.5) oder Shots on Goal (SOG).
   - Wähle die Anzahl flexibel nach Stärke der Kanten gegen den jeweiligen Goalie.
   - Nenne für jeden Spieler: Name, Team, Pick, Quote und Matchup-Begründung.

FORMAT (Telegram-HTML: <b>fett</b>, <i>kursiv</i>):
<b>🏒 JARVIS NHL INTEL & VALUE REPORT</b>
<i>Quantitatives Eishockey-Modell • Starting Goalies & xG • Dynamische Kombis</i>

<b>━━━━━━━━━━━━━━━━━━━━</b>
⭐ <b>PICK OF THE DAY (Single Bet)</b>
- <b>[Uhrzeit] Heim vs. Auswärts</b> -> Pick: <b>[Pick]</b> (Quote: [Quote])
<i>Fair Odds:</i> ~[Faire Quote] | <i>Modell-Kante:</i> [X]%
<i>Goalie Matchup & Edge:</i> [Begründung]

<b>━━━━━━━━━━━━━━━━━━━━</b>
1. <b>NHL BANKER TICKET (2er-Double)</b>
- <b>[Uhrzeit] Heim vs. Auswärts</b> -> Pick: <b>[Pick]</b> (Quote)
- <b>[Uhrzeit] Heim vs. Auswärts</b> -> Pick: <b>[Pick]</b> (Quote)
<b>Gesamtquote: [Produkt]</b>

<b>━━━━━━━━━━━━━━━━━━━━</b>
2. <b>DYNAMIC TOTALS VALUE COMBO ([Anzahl]-Kombi)</b>
[Picks einfügen]
<b>Gesamtquote: [Produkt]</b>

<b>━━━━━━━━━━━━━━━━━━━━</b>
3. <b>DYNAMIC PLAYER PROPS MULTI-TICKET ([Anzahl]-Kombi)</b>
[Für jeden Spieler-Pick:]
- <b>[Spielername] ([Team])</b> -> Pick: <b>[z.B. Anytime Goalscorer / Over 2.5 SOG]</b> (Quote: [Quote])
  <i>Matchup Edge:</i> [Begründung gegen Torwart / PP-Vorteil]
<b>Gesamtquote: [Produkt aller Quoten]</b>

---JSON_DATA---
{{
  "date": "{datetime.now(LOCAL_TZ).strftime('%Y-%m-%d')}",
  "potd": {{"match": "Match", "pick": "Pick", "odds": 1.90}},
  "banker": {{"odds": 2.50, "picks": [{{"match": "M1", "pick": "Pick", "odds": 1.55}}, {{"match": "M2", "pick": "Pick", "odds": 1.60}}]}},
  "totals": {{"odds": 3.60, "picks": [{{"match": "M1", "pick": "Pick", "odds": 1.90}}, {{"match": "M2", "pick": "Pick", "odds": 1.90}}]}},
  "player_props": {{"odds": 5.00, "picks": [{{"player": "Spieler 1", "pick": "Over 2.5 Shots on Goal", "odds": 1.80}}, {{"player": "Spieler 2", "pick": "Anytime Goalscorer", "odds": 2.40}}]}}
}}
"""
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-3.8-flash:generateContent?key={GEMINI_API_KEY}"
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "tools": [{"googleSearch": {}}],
        "generationConfig": {"temperature": 0.2}
    }
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
            with open("pending_nhl.json", "w", encoding="utf-8") as f:
                json.dump(bet_data, f, ensure_ascii=False, indent=2)
            print("Picks in pending_nhl.json gespeichert.")
        except Exception as e:
            print(f"JSON Parsing-Fehler: {e}")
        return report_text
    return full_text

if __name__ == "__main__":
    matches = fetch_nhl_data()
    if not matches:
        send_telegram_message("🏒 <b>Jarvis NHL Status:</b> Keine Spiele im aktuellen Zeitfenster.")
    else:
        raw_output = analyze_nhl(matches)
        if raw_output != "ERROR":
            send_telegram_message(parse_and_save_bets(raw_output))
            print("✅ NHL Report gesendet.")
        else:
            send_telegram_message("⚠️ <b>Jarvis NHL Error:</b> Analyse fehlgeschlagen.")
            sys.exit(1)
