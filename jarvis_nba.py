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

def fetch_nba_data():
    matches_summary = []
    player_props_summary = []
    now_utc = datetime.now(timezone.utc)
    cutoff = now_utc + timedelta(hours=30)

    url = "https://api.the-odds-api.com/v4/sports/basketball_nba/odds/"
    params = {
        "apiKey": ODDS_API_KEY,
        "regions": "us",
        "markets": "h2h,spreads,totals",
        "oddsFormat": "decimal"
    }
    events_to_fetch_props = []
    try:
        res = requests.get(url, params=params, timeout=15)
        if res.status_code == 200:
            data = res.json()
            for match in data:
                commence_utc = datetime.fromisoformat(match["commence_time"].replace("Z", "+00:00"))
                if now_utc <= commence_utc <= cutoff:
                    events_to_fetch_props.append(match)
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
                    matches_summary.append(f"[NBA] {match['home_team']} vs. {match['away_team']} ({time_str}) | {' // '.join(details)}")
    except Exception as e:
        print(f"Odds API Fehler bei Main Markets: {e}")

    prop_markets = "player_points,player_assists,player_rebounds"
    for match in events_to_fetch_props[:4]:
        event_id = match.get("id")
        m_title = f"{match.get('home_team')} vs. {match.get('away_team')}"
        p_url = f"https://api.the-odds-api.com/v4/sports/basketball_nba/events/{event_id}/odds"
        p_params = {
            "apiKey": ODDS_API_KEY,
            "regions": "us",
            "markets": prop_markets,
            "oddsFormat": "decimal"
        }
        try:
            p_res = requests.get(p_url, params=p_params, timeout=15)
            if p_res.status_code == 200:
                p_data = p_res.json()
                for bk in p_data.get("bookmakers", []):
                    for mk in bk.get("markets", []):
                        m_name = mk.get("key")
                        for oc in mk.get("outcomes", []):
                            p_name = oc.get("description", oc.get("name", "Unknown"))
                            p_type = oc.get("name")
                            point = oc.get("point")
                            price = oc.get("price")
                            if point and price and 1.65 <= price <= 2.25:
                                player_props_summary.append(f"{m_title} | {p_name} ({m_name}): {p_type} {point} @ {price}")
                    break
        except Exception as e:
            print(f"Fehler bei Props für Event {event_id}: {e}")

    print(f"NBA-Partien: {len(matches_summary)} | Player Props gesammelt: {len(player_props_summary)}")
    return "\n".join(matches_summary), "\n".join(player_props_summary[:40])

def analyze_nba(matches_text, props_text):
    prompt = f"""
Du bist 'JARVIS NBA QUANT PRO', spezialisiert auf quantitative NBA-Analysen (+EV, Rest-Days, Matchup-Pace und Player Props).
Hier sind die realen Partien mit Quoten:
{matches_text}

Hier sind ECHTE BUCHMACHER-LINIEN für Spielerwetten (Points, Assists, Rebounds):
{props_text}

ANALYSE-REGELN & TICKET-STRUKTUR:
1. MATHEMATISCHER EDGE (+EV): Jedes Bein muss einen plausiblen statistischen Vorteil haben.
2. DYNAMISCHE KOMBIWETTEN:
   - ⭐ PICK OF THE DAY (Single Bet, Quote 1.70 - 2.25): Die absolut stärkste Einzelwette des Tages.
   - 1. DYNAMIC BANKER TICKET: Wähle autonom 2 bis 3 Spiele mit sehr hoher Eintrittswahrscheinlichkeit (ML oder Spread). Zielquote: 1.85 - 2.60.
   - 2. DYNAMIC MARKET VALUE TICKET: Wähle autonom 2 bis 3 Kanten aus Spreads/Totals, wo der Markt schief bewertet ist. Zielquote: 2.60 - 4.50.
   - 🎯 3. AUTONOMES PLAYER PROPS TICKET: Wähle frei zwischen 2 und maximal 4 Spielerwetten aus den realen Buchmacher-Linien. Entscheide selbst anhand der Matchup-Vorteile über die Anzahl der Beine (2er-, 3er- oder 4er-Kombi). Keine erzwungenen Beine!

FORMAT-VORGABE (Telegram-HTML: <b>fett</b>, <i>kursiv</i>):
<b>🏀 JARVIS NBA INTEL & VALUE REPORT</b>
<i>Quantitatives Dossier • Rest-Advantage • Real Player Props</i>

<b>━━━━━━━━━━━━━━━━━━━━</b>
⭐ <b>PICK OF THE DAY (Single Bet)</b>
- <b>[Uhrzeit] Heim vs. Auswärts</b> -> Pick: <b>[Pick]</b> (Quote: [Quote])
<i>Fair Odds:</i> ~[Faire Quote] | <i>Chance:</i> [X]%
<i>Edge:</i> [Begründung]

<b>━━━━━━━━━━━━━━━━━━━━</b>
1. <b>NBA BANKER TICKET ([Anzahl]-Kombi)</b>
[Füge hier für jedes gewählte Spiel eine Zeile ein:]
- <b>[Uhrzeit] Heim vs. Auswärts</b> -> Pick: <b>[Pick]</b> (Quote)
<b>Gesamtquote: [Produkt aller Quoten]</b>

<b>━━━━━━━━━━━━━━━━━━━━</b>
2. <b>MARKET VALUE TICKET ([Anzahl]-Kombi)</b>
[Füge hier für jedes gewählte Spiel eine Zeile ein:]
- <b>[Uhrzeit] Heim vs. Auswärts</b> -> Pick: <b>[Pick]</b> (Quote)
<b>Gesamtquote: [Produkt aller Quoten]</b>

<b>━━━━━━━━━━━━━━━━━━━━</b>
🎯 3. <b>AUTONOMOUS PLAYER PROPS TICKET ([Anzahl]-Kombi)</b>
[Füge hier für jeden ausgewählten Spieler eine Zeile ein:]
- <b>[Spieler] ([Team])</b> -> Pick: <b>[z.B. Über 24.5 Punkte]</b> (Quote: [Quote])
  <i>Edge:</i> [Matchup-Metrik / Begründung]
<b>Gesamtquote: [Produkt aller Quoten]</b>

---JSON_DATA---
{{
  "date": "{datetime.now(LOCAL_TZ).strftime('%Y-%m-%d')}",
  "potd": {{"match": "Heim vs Auswärts", "pick": "Pick", "odds": 1.90}},
  "banker": {{"odds": 2.20, "picks": [{{"match": "M1", "pick": "Pick", "odds": 1.48}}]}},
  "market_value": {{"odds": 3.40, "picks": [{{"match": "M1", "pick": "Pick", "odds": 1.85}}]}},
  "player_props": {{"odds": 3.80, "picks": [{{"player": "Spieler 1", "pick": "Über X.X Stat", "odds": 1.85}}]}}
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
    matches, props = fetch_nba_data()
    if not matches:
        send_telegram_message("🏀 <b>Jarvis NBA Status:</b> Keine Spiele im Zeitfenster.")
    else:
        raw_output = analyze_nba(matches, props)
        if raw_output != "ERROR":
            send_telegram_message(parse_and_save_bets(raw_output))
            print("✅ NBA Report gesendet.")
        else:
            send_telegram_message("⚠️ <b>Jarvis NBA Error:</b> KI-Generierung fehlgeschlagen.")
            sys.exit(1)
