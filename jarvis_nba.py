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
Du bist 'JARVIS NBA ELITE', ein hochspezialisierter Basketball-Quantitative-Analyst.
Hier sind die heutigen realen NBA-Partien mit Buchmacher-Linien:
""" + matches_text + """

DEINE AUFGABE & REGELN:
1. Wähle AUSSCHLIESSLICH aus den oben gelisteten realen NBA-Spielen.
2. Nutze die Google-Suche aktiv für:
   - Offiziellen NBA Injury Report (Out, Questionable, Game-Time Decisions).
   - Pace, Off/Def-Ratings, B2B-Müdigkeit und Defensiv-Matchups gegen bestimmte Positionen.
   - Reale Player-Prop-Linien (Punkte, Rebounds, Assists, PRA).
3. Baue ein breites, mathematisch fundiertes Wettspektrum mit Fokus auf mehrere lukrative Kombiwetten auf.

FORMAT (Telegram-HTML: <b>fett</b>, <i>kursiv</i> - KEIN Markdown, keine Sterne, keine Raute):
<b>🏀 JARVIS NBA INTEL & VALUE REPORT</b>
<i>Analysierte Partien und Kombi-Pakete für die heutige Nacht</i>

<b>━━━━━━━━━━━━━━━━━━━━</b>
<b>1. DIE BANKER-KOMBI (2er-Double)</b>
<i>Solide Kanten mit hoher Eintrittswahrscheinlichkeit (Quote ca. 2.20 - 2.80)</i>
- <b>Spiel 1: [Team vs. Team]</b> -> Pick: <b>[ML oder moderater Spread]</b> (Quote)
- <b>Spiel 2: [Team vs. Team]</b> -> Pick: <b>[ML oder Totals]</b> (Quote)
<b>Gesamtquote: [Quote]</b>
<i>Edge:</i> [1 Satz zur Begründung]

<b>━━━━━━━━━━━━━━━━━━━━</b>
<b>2. VALUE SPREAD & TOTAL KOMBI (3er-Ticket)</b>
<i>Ausgewogene Value-Kombi aus Spreads und Über/Unter (Quote ca. 4.00 - 6.50)</i>
- <b>Spiel 1: [Pick]</b> (Quote)
- <b>Spiel 2: [Pick]</b> (Quote)
- <b>Spiel 3: [Pick]</b> (Quote)
<b>Gesamtquote: [Quote]</b>
<i>Edge:</i> [Kurze Begründung zum Pace- und Matchup-Vorteil]

<b>━━━━━━━━━━━━━━━━━━━━</b>
<b>3. PLAYER-PROP TICKET (2er- bis 3er-Kombi)</b>
<i>Reine Spieler-Statistiken kombiniert (Punkte, PRA, Rebounds - Quote ca. 3.00 - 5.50)</i>
- <b>Spieler A (Team): [z.B. Over 23.5 Punkte / Over 8.5 Rebounds]</b> (Quote)
- <b>Spieler B (Team): [z.B. Over 34.5 PRA / Over 6.5 Assists]</b> (Quote)
- <i>(Optional Spieler C)</i>: [Pick] (Quote)
<b>Gesamtquote: [Quote]</b>
<i>Edge:</i> [Warum diese Rollen/Spielzeiten heute dominieren]

<b>━━━━━━━━━━━━━━━━━━━━</b>
<b>4. SPECIAL VALUE / DOUBLE-DOUBLE</b>
- <b>Spieler (Team): [z.B. Double-Double / 3+ Dreier]</b> | Quote: <b>[Quote]</b>
  <i>Spotlight:</i> [Statistischer Ausreißer]

<i>Protokoll abgeschlossen. Voller Fokus auf die heutigen Lines.</i>
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
