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

def fetch_nfl_matches():
    matches_summary = []
    now_utc = datetime.now(timezone.utc)
    # 36-Stunden-Fenster erfasst von Sonntag bis Montagmorgen alle anstehenden Partien
    cutoff = now_utc + timedelta(hours=36)

    url_odds = "https://api.the-odds-api.com/v4/sports/americanfootball_nfl/odds/"
    params = {
        "apiKey": ODDS_API_KEY,
        "regions": "eu,us",
        "markets": "h2h,spreads,totals",
        "oddsFormat": "decimal"
    }

    try:
        res = requests.get(url_odds, params=params, timeout=15)
        if res.status_code != 200:
            print(f"Fehler beim NFL-Abruf: {res.status_code} - {res.text}")
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

            line = f"[NFL] {match['home_team']} vs. {match['away_team']} ({time_str}) | {' // '.join(details)}"
            matches_summary.append(line)

    print(f"NFL-Spiele im Zeitfenster: {len(matches_summary)}")
    return "\n".join(matches_summary)

def analyze_nfl(matches_text):
    client = genai.Client(api_key=GEMINI_API_KEY)

    prompt = """
Du bist 'JARVIS NFL PRO', ein analytischer Experte fuer American Football und Sportwetten.
Hier sind die realen anstehenden NFL-Spiele mit Buchmacher-Linien:
""" + matches_text + """

DEINE AUFGABE & REGELN:
1. Waehle AUSSCHLIESSLICH Partien aus der obigen Liste aus.
2. Nutze die Google-Suche aktiv fuer:
   - Offiziellen NFL Injury Report (Schluesselspieler, O-Line, Quarterbacks, Inactive Lists).
   - Wetterberichte (Wind ueber 15-20 mph drueckt Totals/Passing Yards nach unten).
   - Reale Player-Prop-Trends: Anytime Touchdown (ATTD), Passing/Rushing/Receiving Yards.
3. Klare Begruendung: Nenne konkrete Fakten (Run-Defense-Ranking, Red-Zone-Nutzung, Matchup gegen Man/Zone-Coverage).

FORMAT (Telegram-HTML: <b>fett</b>, <i>kursiv</i> - KEIN Markdown, keine Sterne, keine Raute):
<b>🏈 JARVIS NFL GAMEPLAN & VALUE REPORT</b>
<i>Analysen und Prognosen fuer den Spieltag</i>

<b>━━━━━━━━━━━━━━━━━━━━</b>
<b>1. BEST SPREAD & TOTAL PICKS</b>
- <b>Team A vs. Team B (Datum um Uhrzeit)</b>
  Pick: <b>[Spread oder Over/Under]</b> | Quote: <b>[Quote]</b>
  <i>Analyse:</i> [1-2 praezise Saetze zu Matchup, Tempo und Taktik]

- <b>Team C vs. Team D (Datum um Uhrzeit)</b>
  Pick: <b>[Spread oder Over/Under]</b> | Quote: <b>[Quote]</b>
  <i>Analyse:</i> [1-2 Saetze]

<b>━━━━━━━━━━━━━━━━━━━━</b>
<b>2. NFL 2er-VALUE-KOMBI</b>
- <b>Spiel 1: [Pick]</b> (Quote)
- <b>Spiel 2: [Pick]</b> (Quote)
<b>Gesamtquote: [Quote ca. 2.50 - 3.50]</b>

<b>━━━━━━━━━━━━━━━━━━━━</b>
<b>3. PLAYER PROPS (Yards & Completions)</b>
- <b>Spieler (Team, Position) vs. Gegner</b>
  Prop: <b>[z.B. Over 68.5 Rushing Yards / Over 1.5 Passing TDs]</b> | Indikative Quote: <b>[Quote]</b>
  <i>Edge:</i> [Begruendung ueber gegnerische Schwaeche oder Spielvolumen]

- <b>Spieler (Team, Position) vs. Gegner</b>
  Prop: <b>[Zweiter starker Prop-Tipp]</b> | Indikative Quote: <b>[Quote]</b>
  <i>Edge:</i> [Begruendung]

<b>━━━━━━━━━━━━━━━━━━━━</b>
<b>4. ANYTIME TOUCHDOWN SCORER (ATTD) VALUE</b>
- <b>Spieler (Team): Anytime Touchdown Scorer</b> | Quote: <b>[Quote]</b>
  <i>Begruendung:</i> [Red-Zone-Touches, Goal-Line-Snaps, gegnerische Anfaelligkeit]

<i>Touchdown, Sir. Moegen die Key-Numbers heute auf unserer Seite stehen.</i>
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
    matches = fetch_nfl_matches()
    if not matches:
        print("Keine NFL-Spiele im Zeitfenster gefunden. Keine Nachricht gesendet.")
    else:
        report = analyze_nfl(matches)
        send_telegram_message(report)
