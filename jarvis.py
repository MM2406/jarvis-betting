import os
import requests
from datetime import datetime, timezone, timedelta
from google import genai
from google.genai import types

# 1. API-Schlüssel & Telegram-Konfiguration laden
ODDS_API_KEY = os.environ["ODDS_API_KEY"]
GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]
TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]

def fetch_matches():
    # Alle aktiven Sportarten von The Odds API abrufen
    url = f"https://api.the-odds-api.com/v4/sports/?apiKey={ODDS_API_KEY}"
    res = requests.get(url)
    if res.status_code != 200:
        return "Keine API-Verbindung zu The Odds API möglich."
    
    all_sports = res.json()
    target_keywords = [
        "soccer", "basketball", "americanfootball", "handball", 
        "tennis", "icehockey"
    ]
    
    # Relevante Sportarten filtern (NHL und Eishockey voll integriert)
    selected_sports = []
    for s in all_sports:
        key = s["key"]
        if s.get("active") and any(k in key for k in target_keywords):
            selected_sports.append(key)

    matches_summary = []
    now = datetime.now(timezone.utc)
    
    # Am Wochenende (Fr=4, Sa=5, So=6): 12 Stunden Fokus
    # Unter der Woche (Mo-Do): 20 Stunden für den gesamten Spieltag
    if now.weekday() in [4, 5, 6]:
        time_window = timedelta(hours=12)
    else:
        time_window = timedelta(hours=20)
        
    cutoff_time = now + time_window

    # Quoten abrufen inklusive Siegwetten (h2h) und Over/Under (totals)
    for sport in selected_sports:
        url_odds = f"https://api.the-odds-api.com/v4/sports/{sport}/odds/"
        params = {
            "apiKey": ODDS_API_KEY,
            "regions": "eu",
            "markets": "h2h,totals",
            "oddsFormat": "decimal"
        }
        res_odds = requests.get(url_odds, params=params)
        if res_odds.status_code != 200:
            continue
            
        data = res_odds.json()
        for match in data:
            commence = datetime.fromisoformat(match["commence_time"].replace("Z", "+00:00"))
            if now <= commence <= cutoff_time:
                bookies = match.get("bookmakers", [])
                if not bookies:
                    continue
                
                market_details = []
                for market in bookies[0].get("markets", []):
                    m_key = market.get("key")
                    outcomes = market.get("outcomes", [])
                    if m_key == "h2h":
                        h2h_str = "H2H: " + ", ".join([f"{o['name']} ({o['price']})" for o in outcomes])
                        market_details.append(h2h_str)
                    elif m_key == "totals":
                        tot_str = "Totals: " + ", ".join([f"{o['name']} {o.get('point', '')} ({o['price']})" for o in outcomes])
                        market_details.append(tot_str)
                
                time_str = commence.strftime("%d.%m. %H:%M UTC")
                match_line = f"[{match['sport_title']}] {match['home_team']} vs. {match['away_team']} ({time_str}) | {' // '.join(market_details)}"
                matches_summary.append(match_line)
                
    return "\n".join(matches_summary[:200])

def analyze_with_jarvis(matches_text):
    client = genai.Client(api_key=GEMINI_API_KEY)
    
    prompt = f"""
    Du bist 'JARVIS', ein hochpräziser Sportwetten-Analyst und Cyber-Butler.
    Hier sind die anstehenden Partien des aktuellen Zeitfensters inklusive Buchmacher-Quoten (H2H und Over/Under Totals):
    
    {matches_text}
    
    DEINE STRATEGIE & WETTLOGIK:
    1. **Fakten-Check:** Nutze zwingend die Google-Suche, um für deine Auswahlen tagesaktuelle News, Ausfälle, Formkurven, Taktik und Matchups zu prüfen.
    2. **Sportarten-Regeln:**
       - **NBA, NHL, NFL:** Nutze hier primär die **Over/Under-Linien (Totals)**! Reine Siegwetten in diesen Ligen nur bei überwältigender Faktenlage.
       - **Spielerwetten (Player Props):** Recherchiere für herausragende Spiele in NFL, NBA oder NHL gezielt starke Player-Props via Google-Suche (z. B. NFL Anytime Touchdown Scorer, Rushing/Receiving Yards, NHL Scorer-Punkte, NBA Spieler-Punkte Over/Under).
       - **Fußball:** Favoriten-Siegwetten, Doppelte Chance oder Tor-Totals (Over/Under).
    3. **Kombi-Architektur:** 
       - Erstelle mindestens zwei größere Kombiwetten (eine 3er-Kombi und eine 4er-Kombi).
       - Achte bei den Kombis auf solide Einzelquoten (ca. 1.30 bis 1.70), um Umfaller zu minimieren.
       - Durchmische die Sportarten (z. B. Fußball-Bank + NBA Over/Under + NHL Tore).
    
    STRUKTUR DES DOSSIERS:
    - **1. Das Cross-Sport Double (2er-Kombi):** Höchste Trefferwahrscheinlichkeit (Zielquote 1.80 - 2.40).
    - **2. Die Cross-Sport 3er-Kombi:** Starke Mischung aus Fußball und US-Sport/Eishockey (Zielquote 2.80 - 4.50).
    - **3. Die High-Value 4er-Kombi:** 4 Top-Auswahlen quer über alle Sportarten (Zielquote 4.50 - 8.00).
    - **4. Das Totals-Spezial (3er-Kombi nur Over/Under):** Reiner Fokus auf Punkte & Tore in NBA/NHL/Fußball.
    - **5. Das Player-Props Special (1-2 Solo-Tipps):** Konkrete Spielerwetten (z. B. TD-Scorer NFL, Scorer-Punkte NHL/NBA) inklusive detaillierter Matchup-Begründung.
    
    FORMATIERUNG FÜR TELEGRAM:
    - Starte mit: "Guten Tag, Sir. Hier ist Ihr optimiertes Sportwetten-Dossier:"
    - Gib bei jeder Auswahl die exakte Wettart (z. B. 'Over 5.5 Tore', 'Sieg Team A', 'Player X Over 22.5 Pts'), die Quote und 1-2 präzise Fakten-Sätze an.
    - Zeige am Ende jeder Kombi die berechnete Gesamtquote.
    """

    config = types.GenerateContentConfig(
        tools=[types.Tool(google_search=types.GoogleSearch())],
        temperature=0.25
    )

    response = client.models.generate_content(
        model="gemini-3.8-flash",
        contents=prompt,
        config=config
    )
    return response.text

def send_telegram_message(text):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    
    # Telegram-Nachrichtenlimit: 4096 Zeichen. Automatischer Splitt bei langen Dossiers.
    max_length = 4000
    chunks = [text[i:i+max_length] for i in range(0, len(text), max_length)]
    
    for idx, chunk in enumerate(chunks, 1):
        payload = {
            "chat_id": TELEGRAM_CHAT_ID,
            "text": chunk
        }
        response = requests.post(url, json=payload)
        print(f"Teil {idx}/{len(chunks)} - Status Code: {response.status_code}")
        if response.status_code != 200:
            print(f"Antwort: {response.text}")
            raise Exception(f"Fehler beim Telegram-Versand (Teil {idx}): {response.text}")

if __name__ == "__main__":
    matches = fetch_matches()
    if not matches:
        matches = "Keine passenden Spiele im Zeitfenster gefunden."
    analysis = analyze_with_jarvis(matches)
    send_telegram_message(analysis)
