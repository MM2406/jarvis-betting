import os
import requests
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
from google import genai
from google.genai import types

# --- API Keys & Credentials ---
ODDS_API_KEY = os.environ["ODDS_API_KEY"]
GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]
TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]

LOCAL_TZ = ZoneInfo("Europe/Berlin")

def fetch_nba_matches():
    matches_summary = []
    now_utc = datetime.now(timezone.utc)
    cutoff = now_utc + timedelta(hours=24)

    url_odds = "https://api.the-odds-api.com/v4/sports/basketball_nba/odds/"
    params = {
        "apiKey": ODDS_API_KEY,
        "regions": "eu,us",
        "markets": "h2h,spreads,totals",
        "oddsFormat": "decimal"
    }
    
    try:
        res = requests.get(url_odds, params=params, timeout=15)
        if res.status_code != 200:
            print(f"Fehler beim NBA-Abruf: {res.status_code} - {res.text}")
            return ""
        data = res.json()
    except requests.RequestException as e:
        print(f"Netzwerkfehler: {e}")
        return ""

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

    print(f"NBA-Spiele gefunden: {len(matches_summary)}")
    return "\n".join(matches_summary)

def analyze_nba(matches_text):
    client = genai.Client(api_key=GEMINI_API_KEY)
    
    prompt = """
Du bist 'JARVIS NBA ELITE', ein spezialisierter Basketball-Quantitative-Analyst.
Hier sind die heutigen realen NBA-Partien mit Buchmacher-Linien:
""" + matches_text + """

DEINE AUFGABE & REGELN:
1. Wähle AUSSCHLIESSLICH aus den oben gelisteten realen NBA-Spielen.
2. Nutze die Google-Suche aktiv für:
   - Den aktuellen offiziellen NBA Injury Report (wer ist Out/Questionable?).
   - Pace-Matchups, Defensive Rating gegen bestimmte Positionen, B2B-Müdigkeit.
   - Aktuelle Player-Prop-Linien und Trends (Punkte, Rebounds, Assists, PRA = Points+Rebounds+Assists, Double-Doubles).
3. Disziplin: Begründe jede Empfehlung mit harten Daten (z.B. "Gegner lässt die 3.-meisten Rebounds an Center zu", "Spieler X erzielte in 4 der letzten 5 Spiele ein Double-Double").

FORMAT (Telegram-HTML: <b>fett</b>, <i>kursiv</i> - KEIN Markdown, keine Sterne, keine Raute):
<b>🏀 JARVIS NBA INTEL & VALUE REPORT</b>
<i>Analysierte Partien für die heutige Nacht</i>

<b>━━━━━━━━━━━━━━━━━━━━</b>
<b>1. GAME PICKS (ML / SPREAD / TOTALS)</b>
- <b>Team A vs. Team B (Uhrzeit)</b>
  Pick: <b>[z.B. Spread Team A -4.5 ODER Over 224.5]</b> | Quote: <b>[Quote]</b>
  <i>Edge:</i> [Präzise Begründung: Pace, Defensiv-Schwächen, Form]

<b>━━━━━━━━━━━━━━━━━━━━</b>
<b>2. DIE NBA SPREAD & TOTAL KOMBI (2er-Kombi)</b>
- <b>Spiel 1: [Pick]</b> (Quote)
- <b>Spiel 2: [Pick]</b> (Quote)
<b>Gesamtquote: [Quote ca. 2.50 - 3.50]</b>

<b>━━━━━━━━━━━━━━━━━━━━</b>
<b>3. PLAYER PROPS BOARD (Punkte, PRA, Rebounds)</b>
- <b>Spieler (Team) vs. Gegner</b>
  Prop: <b>[z.B. Over 24.5 Punkte ODER Over 38.5 PRA ODER Over 10.5 Rebounds]</b> | Indikative Quote: <b>[Quote]</b>
  <i>Matchup-Vorteil:</i> [1-2 Sätze zu Spielzeit, gegnerischer Defense und Ausfällen]

- <b>Spieler (Team) vs. Gegner</b>
  Prop: <b>[Zweiter starker Prop-Tipp]</b> | Indikative Quote: <b>[Quote]</b>
  <i>Matchup-Vorteil:</i> [1-2 Sätze]

<b>━━━━━━━━━━━━━━━━━━━━</b>
<b>4. SPECIAL: DOUBLE-DOUBLE / LUKRATIVE VALUE PROP</b>
- <b>Spieler (Team): [z.B. Ja Morant Double-Double / X Spieler 3+ Dreier]</b> | Quote: <b>[Quote]</b>
  <i>Begründung:</i> [Warum dieser Spot mathematischen Mehrwert bietet]

<i>Protokoll abgeschlossen. Möge der Basketball-Gott auf unserer Seite sein.</i>
"""
    config = types.GenerateContentConfig(
        tools=[types.Tool(google_search=types.GoogleSearch())],
        temperature=0.2
    )
    response = client.models.generate_content(
        model="gemini-3.8-flash",
        contents=prompt,
        config=config
    )
    return response.text

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
        res = requests.post(url, json=payload, timeout=10)
        if res.status_code != 200:
            payload.pop("parse_mode", None)
            requests.post(url, json=payload, timeout=10)

if __name__ == "__main__":
    matches = fetch_nba_matches()
    if not matches:
        send_telegram_message("ℹ️ <b>Jarvis NBA:</b> Keine NBA-Spiele im 24-Stunden-Fenster angesetzt.")
    else:
        report = analyze_nba(matches)
        send_telegram_message(report)
