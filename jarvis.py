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

def fetch_soccer_data():
    leagues = [
        "soccer_germany_bundesliga",
        "soccer_epl",
        "soccer_spain_la_liga",
        "soccer_italy_serie_a",
        "soccer_france_ligue_one",
        "soccer_austria_bundesliga"
    ]
    matches_summary = []
    now_utc = datetime.now(timezone.utc)
    cutoff = now_utc + timedelta(hours=36)

    for league in leagues:
        url = f"https://api.the-odds-api.com/v4/sports/{league}/odds/"
        params = {
            "apiKey": ODDS_API_KEY,
            "regions": "eu",
            "markets": "h2h,totals",
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
                                details.append("1X2: " + ", ".join([f"{o['name']} ({o['price']})" for o in m.get("outcomes", [])]))
                            elif m_key == "totals":
                                details.append("Totals: " + ", ".join([f"{o['name']} {o.get('point', '')} ({o['price']})" for o in m.get("outcomes", [])]))
                        matches_summary.append(f"[{league}] {match['home_team']} vs. {match['away_team']} ({time_str}) | {' // '.join(details)}")
        except Exception as e:
            print(f"Fehler bei Liga {league}: {e}")

    print(f"Fussball/Soccer-Partien gesammelt: {len(matches_summary)}")
    return "\n".join(matches_summary)

def analyze_soccer(matches_text):
    prompt = f"""
Du bist 'JARVIS SOCCER QUANT PRO', spezialisiert auf quantitative Fussball-Analysen (+EV, xG-Modelle, Ligen-Ineffizienzen).
WICHTIG: Verwende in Überschriften und Text ausschließlich 'SOCCER' oder 'FUSSBALL' – NIEMALS 'Football', um jede Verwechslung mit American Football (NFL) auszuschließen!

Hier sind die realen Partien mit Quoten:
{matches_text}

ANALYSE-REGELN & TICKET-STRUKTUR:
1. MATHEMATISCHER EDGE (+EV): P(Win) > (1 / Quote).
2. TICKET-AUFBAU:
   - ⭐ PICK OF THE DAY (Single Bet, Quote 1.70 - 2.25): Die absolut stärkste Einzelwette des Spieltags.
   - 1. SOCCER BANKER TICKET (Strikt 2er-Double): Höchste Trefferwahrscheinlichkeit (1X2, Over 1.5, Doppelchance). Quote 2.00 - 2.70.
   - 2. DYNAMIC GOALS & BTTS VALUE TICKET (Freie Größe: 2 bis 5 Picks): Ineffiziente Tor-Märkte (Over/Under, BTTS). Wähle dynamisch die Anzahl basierend auf echten Kanten.
   - 3. DYNAMIC MULTI-LEAGUE VALUE TICKET (Freie Größe: 2 bis 5 Picks): Ligenübergreifende Kanten. Wähle dynamisch die Anzahl basierend auf echten Kanten.
   - 4. VALUE TORSCHÜTZE / SPECIAL PICK: Optional ein starker Torschützen-Pick oder Match-Special.

FORMAT-VORGABE (Telegram-HTML: <b>fett</b>, <i>kursiv</i>):
<b>⚽ JARVIS SOCCER INTEL & VALUE REPORT</b>
<i>Quantitatives Dossier • +EV Filter • Spieltags-Analysen</i>

<b>━━━━━━━━━━━━━━━━━━━━</b>
⭐ <b>PICK OF THE DAY (Single Bet)</b>
- <b>[Uhrzeit] [Liga] Heim vs. Auswärts</b> -> Pick: <b>[Pick]</b> (Quote: [Quote])
<i>Fair Odds:</i> ~[Faire Quote] | <i>Chance:</i> [X]%
<i>Edge:</i> [Begründung mit xG / Matchup]

<b>━━━━━━━━━━━━━━━━━━━━</b>
1. <b>SOCCER BANKER TICKET (2er-Double)</b>
- <b>[Uhrzeit] [Liga] Heim vs. Auswärts</b> -> Pick: <b>[Pick]</b> (Quote)
- <b>[Uhrzeit] [Liga] Heim vs. Auswärts</b> -> Pick: <b>[Pick]</b> (Quote)
<b>Gesamtquote: [Produkt aller Quoten]</b>

<b>━━━━━━━━━━━━━━━━━━━━</b>
2. <b>DYNAMIC GOALS & BTTS VALUE TICKET ([Anzahl]-Kombi)</b>
[Für jedes Spiel:]
- <b>[Uhrzeit] [Liga] Heim vs. Auswärts</b> -> Pick: <b>[Pick]</b> (Quote)
<b>Gesamtquote: [Produkt aller Quoten]</b>

<b>━━━━━━━━━━━━━━━━━━━━</b>
3. <b>DYNAMIC MULTI-LEAGUE VALUE TICKET ([Anzahl]-Kombi)</b>
[Für jedes Spiel:]
- <b>[Uhrzeit] [Liga] Heim vs. Auswärts</b> -> Pick: <b>[Pick]</b> (Quote)
<b>Gesamtquote: [Produkt aller Quoten]</b>

<b>━━━━━━━━━━━━━━━━━━━━</b>
4. <b>VALUE TORSCHÜTZE / SPECIAL PICK</b>
- <b>[Spieler / Pick]</b> (Quote: [Quote])
<i>Spotlight:</i> [Begründung]

---JSON_DATA---
{{
  "date": "{datetime.now(LOCAL_TZ).strftime('%Y-%m-%d')}",
  "potd": {{"match": "Heim vs Auswärts", "pick": "Pick", "odds": 1.90}},
  "banker": {{"odds": 2.20, "picks": [{{"match": "M1", "pick": "Pick", "odds": 1.48}}, {{"match": "M2", "pick": "Pick", "odds": 1.49}}]}},
  "goals": {{"odds": 5.00, "picks": [{{"match": "M1", "pick": "Pick", "odds": 1.70}}, {{"match": "M2", "pick": "Pick", "odds": 1.75}}]}},
  "multi_league": {{"odds": 5.00, "picks": [{{"match": "M1", "pick": "Pick", "odds": 1.70}}, {{"match": "M2", "pick": "Pick", "odds": 1.80}}]}},
  "scorer": {{"odds": 1.85, "picks": [{{"player": "Spieler", "pick": "Pick", "odds": 1.85}}]}}
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
            with open("pending_soccer.json", "w", encoding="utf-8") as f:
                json.dump(bet_data, f, ensure_ascii=False, indent=2)
            print("Picks in pending_soccer.json gespeichert.")
        except Exception as e:
            print(f"JSON Parsing-Fehler: {e}")
        return report_text
    return full_text

if __name__ == "__main__":
    matches = fetch_soccer_data()
    if not matches:
        send_telegram_message("⚽ <b>Jarvis Soccer Status:</b> Keine Spiele im Zeitfenster.")
    else:
        raw_output = analyze_soccer(matches)
        if raw_output != "ERROR":
            send_telegram_message(parse_and_save_bets(raw_output))
            print("✅ Soccer Report erfolgreich gesendet.")
        else:
            send_telegram_message("⚠️ <b>Jarvis Soccer Error:</b> KI-Generierung fehlgeschlagen.")
            sys.exit(1)
