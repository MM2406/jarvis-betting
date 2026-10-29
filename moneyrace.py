import os
import sys
import json
import time
import requests
from datetime import datetime
from zoneinfo import ZoneInfo

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
TELEGRAM_THREAD_ID = os.environ.get("TELEGRAM_MONEYRACE_THREAD_ID", "").strip()

LOCAL_TZ = ZoneInfo("Europe/Berlin")
STATE_FILE = "moneyrace_state.json"

def send_telegram(text):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "HTML"}
    if TELEGRAM_THREAD_ID:
        try:
            payload["message_thread_id"] = int(TELEGRAM_THREAD_ID)
        except ValueError:
            pass
    try:
        requests.post(url, json=payload, timeout=20)
    except Exception as e:
        print(f"Telegram-Fehler: {e}")

def load_state():
    if not os.path.exists(STATE_FILE):
        return {
            "active": True,
            "level": 1,
            "bankroll": 5.0,
            "target": 100.0,
            "pending_pick": None,
            "history": []
        }
    with open(STATE_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def save_state(state):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)

def run_moneyrace():
    state = load_state()
    
    if not state.get("active", True):
        print("Moneyrace pausiert oder beendet.")
        return

    # 1. AUSWERTUNG eines noch offenen Picks
    if state.get("pending_pick"):
        pick = state["pending_pick"]
        prompt_settle = f"""
Recherchiere via Google Search das Endergebnis für folgende Sportwette:
Event: {pick.get('event')}
Sportart: {pick.get('sport')}
Tipp: {pick.get('selection')} (Quote: {pick.get('odds')})
Datum: {pick.get('date')}

REGELN:
1. Prüfe, ob die Partie bereits offiziell beendet ist. Falls noch nicht begonnen oder laufend, gib 'PENDING' aus.
2. Markiere mit 'WON', wenn der Tipp aufgegangen ist, oder 'LOST', wenn er verloren ging.
3. Bei Spielabsage oder Push gib 'VOID' aus.

Antworte strikt in diesem Format:
RESULT: WON oder LOST oder PENDING oder VOID
INFO: Kurze Begründung mit dem exakten Endergebnis.
"""
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-3.8-flash:generateContent?key={GEMINI_API_KEY}"
        payload = {
            "contents": [{"parts": [{"text": prompt_settle}]}],
            "tools": [{"googleSearch": {}}],
            "generationConfig": {"temperature": 0.1}
        }
        
        reply = ""
        for attempt in range(1, 4):
            try:
                res = requests.post(url, json=payload, timeout=60)
                if res.status_code == 200:
                    reply = res.json()["candidates"][0]["content"]["parts"][0]["text"]
                    break
                time.sleep(5)
            except Exception as e:
                print(f"Versuch {attempt}/3 Fehlgeschlagen: {e}")
                time.sleep(5)

        if "RESULT: WON" in reply:
            return_amt = round(state["bankroll"] * float(pick["odds"]), 2)
            state["history"].append({
                "level": state["level"],
                "pick": pick,
                "result": "WON",
                "return": return_amt
            })
            state["bankroll"] = return_amt
            state["level"] += 1
            state["pending_pick"] = None

            if state["bankroll"] >= state["target"]:
                msg = f"""🏆 <b>MONEYRACE ERFOLGREICH BEENDET!</b> 🎯

Ziel erreicht: <b>{state['bankroll']:.2f} €</b> (von Start 5,00 €)
Alle Stufen erfolgreich absolviert!"""
                send_telegram(msg)
                state["active"] = False
                save_state(state)
                return
            else:
                msg = f"""✅ <b>MONEYRACE STUFE {state['level'] - 1} GEWONNEN!</b>

📌 <b>Tipp:</b> {pick['selection']} @ {pick['odds']}
💰 <b>Neuer Kontostand:</b> <b>{state['bankroll']:.2f} €</b>
➔ Weiter geht es mit <b>Stufe {state['level']}</b>!"""
                send_telegram(msg)
                save_state(state)

        elif "RESULT: LOST" in reply:
            state["history"].append({
                "level": state["level"],
                "pick": pick,
                "result": "LOST"
            })
            msg = f"""❌ <b>MONEYRACE CRASH IN STUFE {state['level']}</b>

📌 <b>Verlorener Pick:</b> {pick['selection']} ({pick['event']})
Einsatz: {state['bankroll']:.2f} € verloren.
🔄 <b>Reset:</b> Zurück zu Stufe 1 mit 5,00 €."""
            send_telegram(msg)
            state["level"] = 1
            state["bankroll"] = 5.0
            state["pending_pick"] = None
            save_state(state)

        elif "RESULT: VOID" in reply:
            msg = f"""🟡 <b>MONEYRACE PICK VOID / ABGESAGT</b>
Spiel: {pick['event']} wurde verschoben oder storniert. Einsatz bleibt bei {state['bankroll']:.2f} €."""
            send_telegram(msg)
            state["pending_pick"] = None
            save_state(state)
        else:
            print("Spiel noch offen oder läuft. Keine Aktion.")
            return

    # 2. NEUEN PICK AUSWÄHLEN (wenn kein Spiel aussteht)
    prompt_pick = f"""
Du bist 'JARVIS MONEYRACE QUANT'.
Wir spielen ein Moneyrace von 5 € auf 100 €. 
Aktueller Status:
- Stufe: {state['level']}
- Einsatz: {state['bankroll']:.2f} € (All-In)
- Ziel: {state['target']:.2f} €

Recherchiere via Google Search nach den anstehenden Partien des heutigen Tages (Fussball, NBA, NHL, NFL, Darts oder Tennis).
Wähle den EINEN Pick mit der höchsten statistischen Eintrittswahrscheinlichkeit (+EV).

STRIKTE VORGABEN:
1. Mindestquote: 1.50 | Maximalquote: 1.75
2. Erlaubte Märkte: Moneyline (Sieg), Over/Under Tore/Punkte, Handicap / Spreads oder Doppelchance.
3. Nur Spiele wählen, die innerhalb der nächsten 18 Stunden starten.

FORMATIERE AM ENDE EXAKT EIN JSON-OBJEKT:
---JSON---
{{
  "sport": "Fussball/NBA/NHL/NFL/Tennis/Darts",
  "event": "Team A vs Team B",
  "date": "{datetime.now(LOCAL_TZ).strftime('%Y-%m-%d')}",
  "selection": "Exakter Wettmarkt und Tipp",
  "odds": 1.55,
  "reason": "Prägnante Begründung des mathematischen Vorteils"
}}
"""
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-3.8-flash:generateContent?key={GEMINI_API_KEY}"
    payload = {
        "contents": [{"parts": [{"text": prompt_pick}]}],
        "tools": [{"googleSearch": {}}],
        "generationConfig": {"temperature": 0.2}
    }

    try:
        res = requests.post(url, json=payload, timeout=90)
        res.raise_for_status()
        raw_text = res.json()["candidates"][0]["content"]["parts"][0]["text"]

        if "---JSON---" in raw_text:
            json_str = raw_text.split("---JSON---")[1].strip()
            new_pick = json.loads(json_str)
            state["pending_pick"] = new_pick
            save_state(state)

            pot_return = round(state["bankroll"] * float(new_pick["odds"]), 2)
            msg = f"""🎯 <b>JARVIS MONEYRACE • STUFE {state['level']}</b>
Einsatz: <b>{state['bankroll']:.2f} €</b> (All-In)
Ziel: <b>{state['target']:.2f} €</b>

━━━━━━━━━━━━━━━━━━━━
📌 <b>Match:</b> {new_pick['event']}
🏆 <b>Sport:</b> {new_pick['sport']}
🎯 <b>Tipp:</b> <b>{new_pick['selection']}</b>
📈 <b>Quote:</b> {new_pick['odds']}
💰 <b>Möglicher Gewinn:</b> <b>{pot_return:.2f} €</b>

🔍 <b>Edge & Begründung:</b>
<i>{new_pick['reason']}</i>"""
            send_telegram(msg)
            print("Neuer Moneyrace-Pick erfolgreich gesetzt.")
    except Exception as e:
        print(f"Fehler bei Pick-Generierung: {e}")
        sys.exit(1)

if __name__ == "__main__":
    run_moneyrace()
