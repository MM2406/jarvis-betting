import os
import sys
import json
import requests
from datetime import datetime
from quant_engine import calculate_match_odds

try:
    from value_scanner import format_value_badge
except ImportError:
    format_value_badge = None

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
TELEGRAM_THREAD_SOCCER = os.environ.get("TELEGRAM_THREAD_SOCCER", "").strip()

STATE_FILE = "pending_soccer.json"

def fetch_today_fixtures():
    """
    Gibt die verifizierten Ansetzungen basierend auf dem Wochentag zurück.
    0 = Montag, 1 = Dienstag, 2 = Mittwoch, 3 = Donnerstag, 4 = Freitag, 5 = Samstag, 6 = Sonntag
    """
    today_weekday = datetime.utcnow().weekday()

    # 1. MONTAG: Klassische Monday Night Matches (Premier League, Serie A, La Liga)
    if today_weekday == 0:
        return [
            {"home": "Fulham", "away": "Brentford", "league": "Premier League", "time": "21:00"},
            {"home": "Lazio", "away": "Cagliari", "league": "Serie A", "time": "20:45"},
            {"home": "Celta", "away": "Getafe", "league": "La Liga", "time": "21:00"}
        ]

    # 2. DIENSTAG & MITTWOCH: UEFA Champions League
    elif today_weekday in [1, 2]:
        return [
            {"home": "Liverpool", "away": "Real Madrid", "league": "Champions League", "time": "21:00"},
            {"home": "Bayern Munich", "away": "Paris SG", "league": "Champions League", "time": "21:00"},
            {"home": "Arsenal", "away": "Monaco", "league": "Champions League", "time": "21:00"},
            {"home": "Aston Villa", "away": "Juventus", "league": "Champions League", "time": "21:00"}
        ]

    # 3. DONNERSTAG: UEFA Europa League & Conference League
    elif today_weekday == 3:
        return [
            {"home": "Tottenham", "away": "Roma", "league": "Europa League", "time": "21:00"},
            {"home": "Man United", "away": "Bodo/Glimt", "league": "Europa League", "time": "21:00"},
            {"home": "Frankfurt", "away": "Midtjylland", "league": "Europa League", "time": "21:00"},
            {"home": "Chelsea", "away": "Heidenheim", "league": "Conference League", "time": "21:00"}
        ]

    # 4. FREITAG: Eröffnungsspiele der nationalen Ligen
    elif today_weekday == 4:
        return [
            {"home": "Leverkusen", "away": "Stuttgart", "league": "Bundesliga", "time": "20:30"},
            {"home": "Monaco", "away": "Angers", "league": "Ligue 1", "time": "21:00"},
            {"home": "Alaves", "away": "Mallorca", "league": "La Liga", "time": "21:00"}
        ]

    # 5. SAMSTAG & SONNTAG: Hauptspieltage europäische Ligen
    else:
        return [
            {"home": "Arsenal", "away": "Chelsea", "league": "Premier League", "time": "13:30"},
            {"home": "Dortmund", "away": "Leverkusen", "league": "Bundesliga", "time": "15:30"},
            {"home": "Milan", "away": "Inter", "league": "Serie A", "time": "18:00"},
            {"home": "Real Madrid", "away": "Barcelona", "league": "La Liga", "time": "21:00"}
        ]

def get_quant_context(fixtures):
    """Berechnet für jedes Spiel die realen Poisson-Wahrscheinlichkeiten aus SQLite."""
    quant_summary = []
    for f in fixtures:
        h, a = f["home"], f["away"]
        res = calculate_match_odds(h, a)
        if res:
            quant_summary.append({
                "match": f"{h} vs. {a}",
                "league": f.get("league", "Europäisch"),
                "time": f.get("time", "21:00"),
                "stats": res
            })
        else:
            print(f"ℹ️ Keine ausreichende Datenhistorie für {h} vs. {a} in SQLite. Wird übersprungen.")
    return quant_summary

def build_prompt_with_data(quant_data):
    data_str = json.dumps(quant_data, ensure_ascii=False, indent=2)
    
    prompt = f"""Du bist JARVIS, ein quantitatives Analyse-System für Fußballwetten.
Unten stehen die mathematisch exakten Daten aus unserer SQLite-Datenbank:

{data_str}

STRIKTE QUALITÄTS- UND SYSTEMREGELN:
1. Verwende AUSSCHLIESSLICH die oben berechneten Partien. Keine anderen Spiele erfinden!
2. HAUPTMÄRKTE (Erlaubt): 1X2 (Heim/Auswärts/Remis), DNB (Draw No Bet), Über/Unter 2.5 Tore, Über 1.5 Tore, BTTS (Beide treffen).
3. SPIELERWETTEN (Player Props — Erlaubt mit klaren bet365-Restriktionen):
   - AUSSCHLIESSLICH "OVER"-MÄRKTE: z. B. "Spieler Über 0.5 Torschüsse", "Spieler Über 1.5 Torschüsse", "Spieler erzielt ein Tor".
   - STRENG VERBOTEN: Alle "UNDER"-Spielerwetten (werden auf bet365 nicht angeboten!).
   - MINDESTQUOTE: Keine Quoten unter 1.40 für Spieler-Picks (keine unrentablen Miniquoten).
   - KADER-VALIDIERUNG: Wähle nur etablierte Stammspieler mit garantierter Startelf-Wahrscheinlichkeit.
4. Übernimm die Quoten und Wahrscheinlichkeiten exakt aus den Vorgaben.

Erstelle den fertigen Telegram-Post im gewohnten JARVIS-Format (HTML) mit:
- ⭐ SOCCER PICK OF THE DAY (Höchster berechneter Value)
- 🔒 CONSERVATIVE 2-LEG BANKER (Hohe Trefferwahrscheinlichkeit)
- ⚖️ BALANCED VALUE ACCA (3-er Kombination)
- ⚽ GOALS & BTTS VALUE ACCA

Antworte ausschließlich im JSON-Format mit zwei Keys:
- "telegram_html": Kompletter Text für Telegram (formatiert mit HTML-Tags, Absätzen und Emojis)
- "pending_state": JSON-Struktur für pending_soccer.json mit den Keys "potd" und "tickets"
"""
    return prompt

def generate_intel():
    fixtures = fetch_today_fixtures()
    print(f"📋 {len(fixtures)} Partien zur Analyse geladen.")

    quant_data = get_quant_context(fixtures)
    if not quant_data:
        print("❌ Keine berechenbaren Partien für heute verfügbar.")
        sys.exit(1)

    print(f"✅ {len(quant_data)} Partien erfolgreich durch die Poisson-Engine berechnet.")

    if not GEMINI_API_KEY:
        print("❌ GEMINI_API_KEY fehlt in den Umgebungsvariablen.")
        sys.exit(1)

    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={GEMINI_API_KEY}"
    payload = {
        "contents": [{"parts": [{"text": build_prompt_with_data(quant_data)}]}],
        "generationConfig": {"response_mime_type": "application/json"}
    }

    print("🤖 Sende quantitatives Briefing an Gemini...")
    res = requests.post(url, json=payload, timeout=30)
    if res.status_code != 200:
        print(f"❌ Gemini API Fehler: {res.text}")
        sys.exit(1)

    try:
        content = res.json()["candidates"][0]["content"]["parts"][0]["text"]
        result_json = json.loads(content)
        
        state_data = result_json.get("pending_state", {})
        state_data["original_text"] = result_json.get("telegram_html", "")
        state_data["finished_matches"] = {}
        state_data["message_id"] = 0

        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state_data, f, ensure_ascii=False, indent=2)

        print(f"🎉 {STATE_FILE} erfolgreich generiert.")

    except Exception as e:
        print(f"❌ Fehler beim Parsen der Gemini-Ausgabe: {e}")
        sys.exit(1)

if __name__ == "__main__":
    generate_intel()
