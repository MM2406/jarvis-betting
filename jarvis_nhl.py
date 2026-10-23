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

def fetch_nhl_matches():
    matches_summary = []
    now_utc = datetime.now(timezone.utc)
    cutoff = now_utc + timedelta(hours=24)

    url_odds = "https://api.the-odds-api.com/v4/sports/icehockey_nhl/odds/"
    params = {
        "apiKey": ODDS_API_KEY,
        "regions": "eu,us",
        "markets": "h2h,spreads,totals",
        "oddsFormat": "decimal"
    }

    try:
        res = requests.get(url_odds, params=params, timeout=15)
        if res.status_code != 200:
            print(f"Fehler beim NHL-Abruf: {res.status_code} - {res.text}")
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
                    details.append("Puck-Line: " + ", ".join([f"{o['name']} {o.get('point', '')} ({o['price']})" for o in m.get("outcomes", [])]))
                elif m_key == "totals":
                    details.append("Totals: " + ", ".join([f"{o['name']} {o.get('point', '')} ({o['price']})" for o in m.get("outcomes", [])]))

            line = f"[NHL] {match['home_team']} vs. {match['away_team']} ({time_str}) | {' // '.join(details)}"
            matches_summary.append(line)

    print(f"NHL-Spiele im Fenster: {len(matches_summary)}")
    return "\n".join(matches_summary)

def analyze_nhl(matches_text):
    client = genai.Client(api_key=GEMINI_API_KEY)

    prompt = """
Du bist 'JARVIS NHL ANALYST', ein quantitativer Eishockey-Experte.
Hier sind die realen anstehenden NHL-Spiele mit Buchmacher-Linien:
""" + matches_text + """

DEINE AUFGABE & REGELN:
1. Wähle AUSSCHLIESSLICH aus den oben gelisteten realen NHL-Spielen.
2. Nutze die Google-Suche aktiv für:
   - Offiziell bestätigte Starting Goalies (DailyFaceoff / LeftWingLock). Ein Backup-Goalie verändert Sieg- und Totals-Chancen drastisch!
   - Powerplay- vs. Penalty-Kill-Effizienz, B2B-Müdigkeit auf Roadtrips.
   - Reale Player-Prop-Trends: Anytime Goalscorer (Tore), Über/Unter Punkte (Goals+Assists), Über/Unter Assists.
3. Erstelle 3 differenzierte, mathematisch fundierte Kombiwetten.

FORMAT (Telegram-HTML: <b>fett</b>, <i>kursiv</i> - KEIN Markdown, keine Sterne, keine Raute):
<b>🏒 JARVIS NHL ICE INTEL & VALUE REPORT</b>
<i>Analysierte Partien für die anstehenden Spiele</i>

<b>━━━━━━━━━━━━━━━━━━━━</b>
<b>1. DIE BANKER-KOMBI (2er-Double)</b>
<i>Solide Kanten: ML Favoriten oder Puck-Line Absicherung (+1.5) (Quote ca. 2.10 - 2.70)</i>
- <b>Spiel 1: [Team vs. Team]</b> -> Pick: <b>[ML oder Puck-Line]</b> (Quote)
- <b>Spiel 2: [Team vs. Team]</b> -> Pick: <b>[ML oder Over/Under 5.5/6.5]</b> (Quote)
<b>Gesamtquote: [Quote]</b>
<i>Edge:</i> [Bestätigter Starting Goalie & Form]

<b>━━━━━━━━━━━━━━━━━━━━</b>
<b>2. PUCK-LINE & TOTALS VALUE TICKET (3er-Kombi)</b>
<i>Ausgewogene 3er-Kombination aus Totals und Spreads (Quote ca. 4.00 - 6.50)</i>
- <b>Spiel 1: [Pick]</b> (Quote)
- <b>Spiel 2: [Pick]</b> (Quote)
- <b>Spiel 3: [Pick]</b> (Quote)
<b>Gesamtquote: [Quote]</b>
<i>Edge:</i> [Matchup- und Tempovorteil / Special Teams]

<b>━━━━━━━━━━━━━━━━━━━━</b>
<b>3. SKATERS POINT & ASSIST TICKET (Player-Props 2er- bis 3er-Kombi)</b>
<i>Reine Spieler-Wetten (Punkte, Assists, Tore - Quote ca. 3.00 - 5.50)</i>
- <b>Spieler A (Team): [z.B. Over 0.5 Punkte / Over 0.5 Assists]</b> (Quote)
- <b>Spieler B (Team): [z.B. Over 1.5 Punkte / Anytime Goalscorer]</b> (Quote)
- <i>(Optional Spieler C)</i>: [Pick] (Quote)
<b>Gesamtquote: [Quote]</b>
<i>Edge:</i> [Powerplay-Unit-Nutzung, Matchup gegen schwache Defensiv-Reihen]

<b>━━━━━━━━━━━━━━━━━━━━</b>
<b>4. ANYTIME GOALSCORER / SPECIAL VALUE</b>
- <b>Spieler (Team): Anytime Goalscorer</b> | Quote: <b>[Quote]</b>
  <i>Spotlight:</i> [Schussvolumen, First-Line-Minuten, gegnerische Gegentorquote]

<i>Puck drop, Sir. Möge das Eis glatt und die Goalies wachsam sein.</i>
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
    matches = fetch_nhl_matches()
    if not matches:
        send_telegram_message("🏒 <b>Jarvis NHL Status:</b> Keine anstehenden NHL-Spiele im 24-Stunden-Fenster gefunden.")
    else:
        report = analyze_nhl(matches)
        send_telegram_message(report)
