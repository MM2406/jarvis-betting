import os
import requests
from datetime import datetime, timezone, timedelta
from google import genai
from google.genai import types

# 1. API-Schlüssel laden
ODDS_API_KEY = os.environ["ODDS_API_KEY"]
GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]
TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]

def fetch_matches():
    """Holt relevante Spiele basierend auf den optimierten Ligen (ohne NHL)."""
    url = f"https://api.the-odds-api.com/v4/sports/?apiKey={ODDS_API_KEY}"
    res = requests.get(url)
    if res.status_code != 200:
        return "Keine API-Verbindung möglich."
    
    all_sports = res.json()
    
    # Erwünschte Ligen/Sportarten (Fussball, Eishockey [DEL/ICE etc.], Basketball, Football, Handball, Tennis)
    # NHL ist bewusst ausgeschlossen!
    target_keywords = [
        "soccer", "basketball", "americanfootball", "handball", 
        "tennis", "icehockey_germany", "icehockey_austria", "icehockey_switzerland"
    ]
    
    selected_sports = []
    for s in all_sports:
        key = s["key"]
        if s["active"] and any(k in key for k in target_keywords):
            # Ausschluss von NHL
            if "nhl" not in key:
                selected_sports.append(key)

    matches_summary = []
    now = datetime.now(timezone.utc)
    tomorrow = now + timedelta(hours=24)

    for sport in selected_sports[:12]: # Max 12 Ligen abfragen, um API-Credits zu sparen
        url_odds = f"https://api.the-odds-api.com/v4/sports/{sport}/odds/"
        params = {
            "apiKey": ODDS_API_KEY,
            "regions": "eu",
            "markets": "h2h",
            "oddsFormat": "decimal"
        }
        res_odds = requests.get(url_odds, params=params)
        if res_odds.status_code != 200:
            continue
            
        data = res_odds.json()
        for match in data:
            commence = datetime.fromisoformat(match["commence_time"].replace("Z", "+00:00"))
            if now <= commence <= tomorrow:
                bookies = match.get("bookmakers", [])
                if not bookies:
                    continue
                outcomes = bookies[0]["markets"][0]["outcomes"]
                odds_str = ", ".join([f"{o['name']}: {o['price']}" for o in outcomes])
                time_str = commence.strftime("%d.%m. %H:%M UTC")
                matches_summary.append(
                    f"[{match['sport_title']}] {match['home_team']} vs. {match['away_team']} ({time_str}) | Quoten: {odds_str}"
                )
                
    return "\n".join(matches_summary[:50])

def analyze_with_jarvis(matches_text):
    """Analysiert die Spiele flexibel nach bestem Angebot."""
    client = genai.Client(api_key=GEMINI_API_KEY)
    
    prompt = f"""
    Du bist 'JARVIS', ein hochpräziser Sportwetten-Analyst.
    Hier sind die anstehenden Spiele der nächsten 24 Stunden mit Buchmacher-Quoten:
    
    {matches_text}
    
    DEINE ANWEISUNGEN:
    1. **Fakten-Check:** Nutze zwingend die Google-Suche, um für die spannendsten Spiele tagesaktuelle Fakten zu prüfen (Verletzungen, Sperren, Formkurve der letzten Spiele, Heim-/Auswärtsstärke, H2H).
    2. **Keine NHL!** (Die Eishockey-Spiele aus der NHL wurden bewusst ausgeschlossen, fokussiere dich stattdessen auf europäischen Club-Hockey [DEL, ICE, etc.], Fussball, Tennis, Basketball, Handball oder NFL/MLS).
    3. **Flexibles Angebot:** Zwänge dich nicht in ein starres Korsett. Analysiere das tatsächliche Angebot des heutigen Tages:
       - Wenn das Angebot herausragend ist, erstelle mehrere starke Kombi-Vorschläge.
       - Wenn der Tag dünn ist, mach lieber weniger, aber dafür umso besser belegte Tipps.
       - Die Ziel-Gesamtquote für die Kombis sollte sich idealerweise im Bereich zwischen **2.00 und 5.00** bewegen (kann bei absoluten Top-Gelegenheiten auch leicht abweichen).
    4. **Begründung:** Jeder Tipp in einer Kombi braucht 2-3 präzise Fakten-Sätze, warum er statistisch und durch aktuelle News untermauert ist.
    
    FORMATIERUNG FÜR TELEGRAM:
    - Starte mit: "Guten Tag, Sir. Hier ist Ihr Sportwetten-Dossier:"
    - Stelle die Kombis übersichtlich dar (inkl. Einzelquoten und berechneter Gesamtquote).
    """

    config = types.GenerateContentConfig(
        tools=[types.Tool(google_search=types.GoogleSearch())],
        temperature=0.3
    )

    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=prompt,
        config=config
    )
    return response.text

def send_telegram_message(text):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    chunks = [text[i:i+4000] for i in range(0, len(text), 4000)]
    for chunk in chunks:
        requests.post(url, json={
            "chat_id": TELEGRAM_CHAT_ID,
            "text": chunk
        })

if __name__ == "__main__":
    matches = fetch_matches()
    if not matches:
        matches = "Keine API-Spiele im Zeitfenster. Bitte recherchiere die heutigen Top-Spiele in Fussball, europäischem Eishockey, Tennis, Handball, Basketball und NFL/MLS über Google Search."
    analysis = analyze_with_jarvis(matches)
    send_telegram_message(analysis)
