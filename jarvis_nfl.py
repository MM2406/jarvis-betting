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

def fetch_nfl_data():
    url = "https://api.the-odds-api.com/v4/sports/americanfootball_nfl/odds/"
    params = {
        "apiKey": ODDS_API_KEY,
        "regions": "us,eu",
        "markets": "h2h,spreads,totals",
        "oddsFormat": "decimal"
    }
    matches_summary = []
    now_utc = datetime.now(timezone.utc)
    cutoff = now_utc + timedelta(hours=36)

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
                            details.append("Spread: " + ", ".join([f"{o['name']} {o.get('point', '')} ({o['price']})" for o in m.get("outcomes", [])]))
                        elif m_key == "totals":
                            details.append("Totals: " + ", ".join([f"{o['name']} {o.get('point', '')} ({o['price']})" for o in m.get("outcomes", [])]))
                    matches_summary.append(f"{match['home_team']} vs. {match['away_team']} ({time_str}) | {' // '.join(details)}")
    except Exception as e:
        print(f"Fehler bei NFL Odds: {e}")

    print(f"NFL Spiele gesammelt: {len(matches_summary)}")
    return "\n".join(matches_summary)

def analyze_nfl(matches_text):
    prompt = f"""
Du bist 'JARVIS NFL QUANT PRO', spezialisiert auf quantitative NFL-Modelle (EPA/Play, Inactives, Key Numbers, Redzone-Target-Share, Rushing Yards vs. Run Funnel Defenses).
Recherchiere über Google Search nach offiziellen Inactives, Wetter (Wind) und gängigen Player Props (Anytime Touchdown Scorer, Passing/Rushing/Receiving Yards).

Spiele & Quoten:
{matches_text}

TICKET-STRUKTUR:
1. ⭐ NFL PICK OF THE DAY (Single Bet, Quote 1.80 - 2.15): Die stärkste Kante über Key Numbers oder EPA-Differenzen.
2. 1. NFL BANKER TICKET (Strikt 2er-Double): Höchste Zuverlässigkeit aus Moneyline / Short Spreads. Quote 2.10 - 2.80.
3. 2. DYNAMIC TOTALS VALUE COMBO (Freie Größe: 2 bis 5 Picks): Ineffiziente Over/Under Totals nach Key Numbers (41, 44, 47, 51) und Wetter. Dynamisch gewählt.
4. 3. DYNAMIC NFL PLAYER PROPS MULTI-TICKET (Freie Größe: 2 bis 5 Picks):
   - Baue eine reine NFL-Spieler-Kombi (Anytime Touchdowns, Passing Yards, Rushing Yards, Receiving Yards, Receptions).
   - Wähle frei und dynamisch zwischen 2er-, 3er-, 4er- oder 5er-Kombi, je nachdem wie viele echte Kanten (CB vs WR Mismatches, verletzter RB1) vorliegen.
   - Nenne für jeden Pick: Spieler, Team, Line, Quote und Begründung.

FORMAT (Telegram-HTML: <b>fett</b>, <i>kursiv</i>):
<b>🏈 JARVIS NFL INTEL & VALUE REPORT</b>
<i>Quantitatives NFL-Modell • EPA/Play & Inactives • Dynamische Kombis</i>

<b>━━━━━━━━━━━━━━━━━━━━</b>
⭐ <b>PICK OF THE DAY (Single Bet)</b>
- <b>[Uhrzeit] Heim vs. Auswärts</b> -> Pick: <b>[Pick]</b> (Quote: [Quote])
<i>Fair Odds:</i> ~[Faire Quote] | <i>Modell-Kante:</i> [X]%
<i>Trench / Matchup Edge:</i> [Begründung mit EPA/Inactives]

<b>━━━━━━━━━━━━━━━━━━━━</b>
1. <b>NFL BANKER TICKET (2er-Double)</b>
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
- <b>[Spielername] ([Team])</b> -> Pick: <b>[z.B. Over 68.5 Receiving Yards / Anytime TD]</b> (Quote: [Quote])
  <i>Matchup Edge:</i> [Begründung mit Target-Share / Coverage-Schwäche]
<b>Gesamtquote: [Produkt aller Quoten]</b>

---JSON_DATA---
{{
  "date": "{datetime.now(LOCAL_TZ).strftime('%Y-%m-%d')}",
  "potd": {{"match": "Match", "pick": "Pick", "odds": 1.90}},
  "banker": {{"odds": 2.50, "picks": [{{"match": "M1", "pick": "Pick", "odds": 1.55}}, {{"match": "M2", "pick": "Pick", "odds": 1.60}}]}},
  "totals": {{"odds": 3.60, "picks": [{{"match": "M1", "pick": "Pick", "odds": 1.90}}, {{"match": "M2", "pick": "Pick", "odds": 1.90}}]}},
  "player_props": {{"odds": 5.50, "picks": [{{"player": "Spieler 1", "pick": "Anytime Touchdown", "odds": 2.10}}, {{"player": "Spieler 2", "pick": "Over 64.5 Rush Yds", "odds": 1.85}}]}}
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
            with open("pending_nfl.json", "w", encoding="utf-8") as f:
                json.dump(bet_data, f, ensure_ascii=False, indent=2)
            print("Picks in pending_nfl.json gespeichert.")
        except Exception as e:
            print(f"JSON Parsing-Fehler: {e}")
        return report_text
    return full_text

if __name__ == "__main__":
    matches = fetch_nfl_data()
    if not matches:
        send_telegram_message("🏈 <b>Jarvis NFL Status:</b> Keine Spiele im aktuellen Zeitfenster.")
    else:
        raw_output = analyze_nfl(matches)
        if raw_output != "ERROR":
            send_telegram_message(parse_and_save_bets(raw_output))
            print("✅ NFL Report gesendet.")
        else:
            send_telegram_message("⚠️ <b>Jarvis NFL Error:</b> Analyse fehlgeschlagen.")
            sys.exit(1)
