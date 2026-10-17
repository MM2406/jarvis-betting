import os
import requests
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
from google import genai
from google.genai import types

ODDS_API_KEY = os.environ["ODDS_API_KEY"]
GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]
TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]

LOCAL_TZ = ZoneInfo("Europe/Berlin")

def fetch_matches():
    url = f"https://api.the-odds-api.com/v4/sports/?apiKey={ODDS_API_KEY}"
    res = requests.get(url)
    if res.status_code != 200:
        return "Keine API-Verbindung möglich."
    
    target_sports = ["soccer", "basketball", "americanfootball", "handball", "tennis", "icehockey"]
    selected_sports = [s["key"] for s in res.json() if s.get("active") and any(k in s["key"] for k in target_sports)]

    matches_summary = []
    now_utc = datetime.now(timezone.utc)
    # Einheitliches 20-Stunden-Fenster für verlässliche Spielauswahl
    cutoff = now_utc + timedelta(hours=20)

    for sport in selected_sports:
        url_odds = f"https://api.the-odds-api.com/v4/sports/{sport}/odds/"
        params = {"apiKey": ODDS_API_KEY, "regions": "eu", "markets": "h2h,totals", "oddsFormat": "decimal"}
        res_odds = requests.get(url_odds, params=params)
        if res_odds.status_code != 200:
            continue
            
        for match in res_odds.json():
            commence_utc = datetime.fromisoformat(match["commence_time"].replace("Z", "+00:00"))
            if now_utc <= commence_utc <= cutoff:
                bookies = match.get("bookmakers", [])
                if not bookies:
                    continue
                time_str = commence_utc.astimezone(LOCAL_TZ).strftime("%d.%m. %H:%M Uhr")
                details = []
                for m in bookies[0].get("markets", []):
                    if m.get("key") == "h2h":
                        details.append("H2H: " + ", ".join([f"{o['name']} ({o['price']})" for o in m.get("outcomes", [])]))
                    elif m.get("key") == "totals":
                        details.append("Totals: " + ", ".join([f"{o['name']} {o.get('point', '')} ({o['price']})" for o in m.get("outcomes", [])]))
                matches_summary.append(f"[{match['sport_title']}] {match['home_team']} vs. {match['away_team']} ({time_str}) | {' // '.join(details)}")
                
    return "\n".join(matches_summary[:200])

def analyze_with_jarvis(matches_text):
    client = genai.Client(api_key=GEMINI_API_KEY)
    prompt = f"""
Du bist 'JARVIS', KI-Sportwettenanalyst. Hier sind die anstehenden Partien aus der Buchmacher-API mit Quoten und lokaler Zeit:
{matches_text}

STRIKTE REGELN (ABSOLUTE PRIORITÄT):
1. **NUR DIESE SPIELE:** Wähle AUSSCHLIESSLICH Partien aus der obigen Liste aus! Erfinde NIEMALS eigene Spiele und übernimm keine Spiele aus dem Web, die nicht oben aufgeführt sind.
2. **Recherche:** Nutze die Google-Suche NUR, um für die oben genannten Teams Ausfälle, Form und Matchups zu prüfen.
3. **HYBRID-KOMBINATION:** Jede Kombi (Double, 3er, 4er) MUSS intern aus verschiedenen Sportarten UND verschiedenen Märkten bestehen (z.B. Fußball-Bank + NBA/NHL Totals oder Player-Props).
4. **Märkte:** Bei NBA, NHL, NFL bevorzuge Totals (Over/Under) oder starke Player-Props. Einzelquoten solide zwischen 1.30 und 1.75.

FORMAT (Telegram-HTML: <b>fett</b>, <i>kursiv</i> - KEIN Markdown):
<b>Guten Tag, Sir. Hier ist Ihr optimiertes Sportwetten-Dossier:</b>

<b>━━━━━━━━━━━━━━━━━━━━</b>
<b>1. DAS HYBRID-DOUBLE (2er-Kombi)</b> (Zielquote 1.80 - 2.40)
• <b>[Liga] Team A vs. Team B (Datum um Uhrzeit)</b>
  Tipp: <b>[Wette]</b> | Quote: <b>[Quote]</b>
  <i>Fakten:</i> [1-2 präzise Sätze]
<b>Gesamtquote: [Quote]</b>

<b>━━━━━━━━━━━━━━━━━━━━</b>
<b>2. DIE CROSS-SPORT 3er-KOMBI</b> (Zielquote 2.80 - 4.50)
[Gleicher Aufbau mit 3 Picks]
<b>Gesamtquote: [Quote]</b>

<b>━━━━━━━━━━━━━━━━━━━━</b>
<b>3. DIE HIGH-VALUE 4er-KOMBI</b> (Zielquote 4.50 - 8.00)
[Gleicher Aufbau mit 4 Picks]
<b>Gesamtquote: [Quote]</b>

<b>━━━━━━━━━━━━━━━━━━━━</b>
<b>4. PLAYER-PROPS SPECIAL (Solo)</b>
• <b>[Liga] Spielername (Team) – [Wette] (Datum um Uhrzeit)</b>
  Indikative Quote: <b>[Quote]</b>
  <i>Matchup-Analyse:</i> [1-2 Sätze]

<i>Protokoll abgeschlossen. Möge die mathematische Varianz heute zu Ihren Gunsten ausfallen, Sir.</i>
"""
    config = types.GenerateContentConfig(tools=[types.Tool(google_search=types.GoogleSearch())], temperature=0.2)
    response = client.models.generate_content(model="gemini-3.8-flash", contents=prompt, config=config)
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
        res = requests.post(url, json=payload)
        if res.status_code != 200:
            payload.pop("parse_mode", None)
            requests.post(url, json=payload)

if __name__ == "__main__":
    matches = fetch_matches()
    if not matches:
        matches = "Keine passenden Spiele im Zeitfenster gefunden."
    analysis = analyze_with_jarvis(matches)
    send_telegram_message(analysis)
