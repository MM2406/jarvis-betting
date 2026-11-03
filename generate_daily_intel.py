import os
import sys
import json
import requests
from quant_engine import calculate_match_odds

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
TELEGRAM_THREAD_SOCCER = os.environ.get("TELEGRAM_THREAD_SOCCER", "").strip()

STATE_FILE = "pending_soccer.json"

def get_quant_context(fixtures):
    """Berechnet für eine Liste von Spielen die echten Poisson-Zahlen aus der SQLite-DB."""
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
    return quant_summary

def build_prompt_with_data(quant_data):
    """Erstellt den System-Prompt mit harten Fakten."""
    data_str = json.dumps(quant_data, ensure_ascii=False, indent=2)
    
    prompt = f"""Du bist JARVIS, eine quantitative Sportwetten-Analyse-Engine.
Hier sind die mathematisch berechneten Zahlen aus unserer internen SQLite-Datenbank:

{data_str}

STRIKTE REGELN (BEI VERSTOSS WIRD DER LAUF ABGEBROCHEN):
1. Verwende AUSSCHLIESSLICH die oben genannten Partien. Erfinde KEINE anderen Paarungen!
2. KEINE SPIELERWETTEN (Player Props wie Torschüsse, Scorer, Karten). Diese sind strengstens verboten!
3. Verwende ausschließlich Märkte: 1X2 (Heimsieg/Auswärtssieg), DNB (Draw No Bet), Über/Unter 2.5 Tore, BTTS (Beide treffen).
4. Übernimm die Wahrscheinlichkeiten und fairen Quoten exakt aus den obigen Daten.

Formatiere die Analyse im gewohnten JARVIS-Telegram-Format (HTML) mit:
- ⭐ SOCCER PICK OF THE DAY (Höchster mathematischer Value)
- 🔒 CONSERVATIVE 2-LEG BANKER (Hohe Wahrscheinlichkeit)
- ⚖️ BALANCED VALUE ACCA (3-er Kombi)
- ⚽ GOALS & BTTS VALUE ACCA

Antworte im JSON-Format mit zwei Keys:
- "telegram_html": Der vollständige, fertige Telegram-Post (inklusive Emojis und HTML-Tags)
- "pending_state": Das vollständige JSON für pending_soccer.json (mit potd und tickets)
"""
    return prompt

def generate_intel():
    # Beispielhafte Paarungen für den heutigen Tag (Ground Truth)
    # Später kann diese Liste per API oder CSV automatisch morgens befüllt werden
    fixtures = [
        {"home": "Liverpool", "away": "Real Madrid", "league": "Champions League", "time": "21:00"},
        {"home": "Bayern Munich", "away": "Paris Saint Germain", "league": "Champions League", "time": "21:00"},
        {"home": "Arsenal", "away": "Monaco", "league": "Champions League", "time": "21:00"},
        {"home": "Aston Villa", "away": "Juventus", "league": "Champions League", "time": "21:00"}
    ]

    print("🔍 Berechne Poisson-Metriken aus SQLite...")
    quant_data = get_quant_context(fixtures)
    if not quant_data:
        print("❌ Keine Daten für die Paarungen in der Datenbank gefunden.")
        sys.exit(1)

    print(f"✅ {len(quant_data)} Partien erfolgreich mathematisch berechnet.")

    if not GEMINI_API_KEY:
        print("❌ GEMINI_API_KEY fehlt.")
        sys.exit(1)

    # Gemini API Call mit den harten Fakten als Prompt
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

        # In pending_soccer.json speichern
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state_data, f, ensure_ascii=False, indent=2)

        print(f"🎉 {STATE_FILE} erfolgreich mit quantitativen Daten erstellt!")

    except Exception as e:
        print(f"❌ Fehler beim Verarbeiten der Antwort: {e}")
        sys.exit(1)

if __name__ == "__main__":
    generate_intel()
