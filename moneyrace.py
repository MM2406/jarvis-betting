import os
import sys
import json
import time
import requests
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo

# Sichere Anbindung der zentralen Telegram-Hilfsfunktion
try:
    from telegram_sender import send_to_telegram
except ImportError:
    send_to_telegram = None

ODDS_API_KEY = os.environ.get("ODDS_API_KEY", "").strip()
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "").strip()

# Sicheres Routing ins Moneyrace-Thema
TELEGRAM_THREAD_ID = (
    os.environ.get("TELEGRAM_MONEYRACE_THREAD_ID", "").strip()
    or os.environ.get("TELEGRAM_THREAD_MONEYRACE", "").strip()
    or os.environ.get("TELEGRAM_THREAD_ID", "").strip()
)

LOCAL_TZ = ZoneInfo("Europe/Berlin")
STATE_FILE = "moneyrace_state.json"

MONEYRACE_SPORTS = [
    # Top-Fussball Ligen
    "soccer_germany_bundesliga",
    "soccer_germany_bundesliga2",
    "soccer_epl",
    "soccer_england_championship",
    "soccer_spain_la_liga",
    "soccer_italy_serie_a",
    "soccer_france_ligue_one",
    "soccer_netherlands_eredivisie",
    "soccer_portugal_primeira_liga",
    "soccer_austria_bundesliga",
    "soccer_belgium_first_div",
    # UEFA Wettbewerbe
    "soccer_uefa_champs_league",
    "soccer_uefa_europa_league",
    "soccer_uefa_europa_conference_league",
    # Eishockey (Top 4 Ligen)
    "icehockey_nhl",
    "icehockey_germany_del",
    "icehockey_sweden_shl",
    "icehockey_liiga",
    # 2-Weg Basketball & Darts
    "basketball_euroleague",
    "basketball_nba",
    "darts_pdc_world_championship",
    "darts_premier_league"
]

def send_telegram(text):
    if send_to_telegram:
        return send_to_telegram(text, thread_env_var="TELEGRAM_MONEYRACE_THREAD_ID")

    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("Telegram Credentials fehlen.")
        return None

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True
    }
    if TELEGRAM_THREAD_ID:
        try:
            payload["message_thread_id"] = int(TELEGRAM_THREAD_ID)
        except ValueError:
            print(f"Ungueltige Moneyrace Thread-ID: {TELEGRAM_THREAD_ID}")

    try:
        res = requests.post(url, json=payload, timeout=25)
        if res.status_code == 200:
            return res.json().get("result", {}).get("message_id")
        else:
            payload.pop("parse_mode", None)
            res2 = requests.post(url, json=payload, timeout=25)
            if res2.status_code == 200:
                return res2.json().get("result", {}).get("message_id")
    except Exception as e:
        print(f"Telegram-Fehler: {e}")
    return None

def load_state():
    default_state = {
        "current_step": 0,
        "bankroll": 5.00,
        "start_amount": 5.00,
        "target_amount": 100.00,
        "history": [],
        "active_pick": None,
        "last_run_date": ""
    }
    if not os.path.exists(STATE_FILE):
        return default_state
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"Fehler beim Laden von {STATE_FILE}: {e}")
        return default_state

def save_state(state):
    try:
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"Fehler beim Speichern von {STATE_FILE}: {e}")

def make_progress_bar(step, total_steps=7):
    filled = min(step, total_steps)
    empty = total_steps - filled
    return f"[{'🟩' * filled}{'⬜' * empty}]"

def settle_active_pick(state):
    active = state.get("active_pick")
    if not active:
        print("Kein aktiver Moneyrace-Pick zur Auswertung vorhanden.")
        return state

    print(f"Prüfe Abrechnung für Stufe {active.get('step')}: {active.get('match')}...")
    
    prompt_settle = f"""
Recherchiere via Google Search das offizielle Endergebnis für folgende Sportwette:
Match: {active.get('match')}
Tipp: {active.get('pick')}
Datum: {active.get('date')}

REGELN:
1. Prüfe sorgfältig, ob das Spiel bereits regulär beendet ist (inkl. möglicher Overtime/Penaltys). Falls noch nicht begonnen, verschoben oder live, antworte zwingend mit PENDING.
2. Wenn der Tipp gewonnen hat, antworte mit 'RESULT: WON'.
3. Wenn der Tipp verloren hat, antworte mit 'RESULT: LOST'.
4. Bei Push / Void / Absage (Quote 1.0) antworte mit 'RESULT: VOID'.

Format:
RESULT: WON oder LOST oder PENDING oder VOID
SCORE: Endergebnis (z.B. 4:2)
INFO: Kurze Begründung.
"""
    host = "generativelanguage.googleapis.com"
    path = "v1beta/models/gemini-3.8-flash:generateContent"
    api_url = f"https://{host}/{path}?key={GEMINI_API_KEY}"

    payload = {
        "contents": [{"parts": [{"text": prompt_settle}]}],
        "tools": [{"googleSearch": {}}],
        "generationConfig": {"temperature": 0.1}
    }

    try:
        res = requests.post(api_url, json=payload, timeout=60)
        if res.status_code == 200:
            text = res.json()["candidates"][0]["content"]["parts"][0]["text"]
            
            try:
                stake_val = float(str(active.get("stake", 5.0)).replace(",", "."))
            except ValueError:
                stake_val = 5.0
            try:
                odds_val = float(str(active.get("odds", 1.5)).replace(",", "."))
            except ValueError:
                odds_val = 1.5

            if "RESULT: WON" in text:
                ret = round(stake_val * odds_val, 2)
                profit = round(ret - stake_val, 2)
                step_done = active["step"]
                
                state["bankroll"] = ret
                state["current_step"] = step_done
                active["status"] = "WON"
                active["return"] = ret
                state["history"].append(active)
                state["active_pick"] = None
                save_state(state)

                pct = round((ret / state["target_amount"]) * 100, 1)
                bar = make_progress_bar(step_done)

                if ret >= state["target_amount"]:
                    msg = (
                        f"🏆 <b>MONEYRACE ZIEL ERREICHT!</b>\n\n"
                        f"Stufe {step_done} gemeistert!\n"
                        f"📌 Letzter Tipp: {active['pick']} (@ {odds_val:.2f}) ➔ TREFFER!\n"
                        f"💰 Endstand: <b>{ret:.2f} €</b>\n\n"
                        f"Die 100 € Challenge wurde erfolgreich abgeschlossen! 🎉"
                    )
                else:
                    msg = (
                        f"✅ <b>MONEYRACE STUFE {step_done} GEWONNEN!</b>\n\n"
                        f"• <b>Tipp:</b> {active['pick']} (@ {odds_val:.2f}) ➔ <b>TREFFER!</b>\n"
                        f"• <b>Rücklauf:</b> +{profit:.2f} €\n"
                        f"• <b>Neuer Kontostand:</b> <b>{ret:.2f} €</b>\n\n"
                        f"Progress: {bar} {pct}%\n"
                        f"➔ Weiter mit Stufe {step_done + 1}!"
                    )
                send_telegram(msg)

            elif "RESULT: LOST" in text:
                step_lost = active["step"]
                active["status"] = "LOST"
                active["return"] = 0.0
                state["history"].append(active)
                
                state["active_pick"] = None
                state["bankroll"] = state["start_amount"]
                state["current_step"] = 0
                save_state(state)

                msg = (
                    f"❌ <b>MONEYRACE STUFE {step_lost} LEIDER VERLOREN</b>\n\n"
                    f"• <b>Match:</b> {active['match']}\n"
                    f"• <b>Tipp:</b> {active['pick']} (@ {odds_val:.2f})\n\n"
                    f"Die Challenge wird zurückgesetzt. Wir starten beim nächsten Durchlauf frisch mit Stufe 1 ({state['start_amount']:.2f} €)."
                )
                send_telegram(msg)

            elif "RESULT: VOID" in text:
                active["status"] = "VOID"
                state["active_pick"] = None
                save_state(state)

                msg = (
                    f"🟡 <b>MONEYRACE STUFE {active['step']} UNENTSCHIEDEN / VOID</b>\n\n"
                    f"• <b>Match:</b> {active['match']}\n"
                    f"• <b>Tipp:</b> {active['pick']}\n"
                    f"Einsatz von {stake_val:.2f} € erstattet. Stufe {active['step']} wird wiederholt."
                )
                send_telegram(msg)
            else:
                print("Spielergebnis noch nicht final oder unklar. Bleibt PENDING.")
    except Exception as e:
        print(f"Fehler bei Abrechnung: {e}")

    return state

def fetch_moneyrace_odds():
    all_events = []
    now_utc = datetime.now(timezone.utc)
    now_hour = datetime.now(LOCAL_TZ).hour
    
    window_hours = 6 if now_hour < 15 else 9
    cutoff = now_utc + timedelta(hours=window_hours)

    for sport in MONEYRACE_SPORTS:
        url = f"https://api.the-odds-api.com/v4/sports/{sport}/odds/"
        params = {
            "apiKey": ODDS_API_KEY,
            "regions": "eu",
            "markets": "h2h,totals,spreads",
            "oddsFormat": "decimal"
        }
        try:
            res = requests.get(url, params=params, timeout=12)
            if res.status_code == 200:
                for match in res.json():
                    commence_utc = datetime.fromisoformat(match["commence_time"].replace("Z", "+00:00"))
                    if now_utc <= commence_utc <= cutoff:
                        time_str = commence_utc.astimezone(LOCAL_TZ).strftime("%d.%m. %H:%M Uhr")
                        bookies = match.get("bookmakers", [])
                        if not bookies:
                            continue
                        odds_details = []
                        for m in bookies[0].get("markets", []):
                            outcomes = [f"{o['name']} ({o.get('point', '')}): {o['price']}" for o in m.get("outcomes", [])]
                            odds_details.append(f"{m.get('key')}: {', '.join(outcomes)}")
                        all_events.append(f"[{sport}] {match['home_team']} vs. {match['away_team']} ({time_str}) | {' // '.join(odds_details)}")
        except Exception as e:
            print(f"Fehler bei {sport}: {e}")

    print(f"Gefundene Moneyrace-Kandidaten: {len(all_events)}")
    return "\n".join(all_events[:60])

def run_moneyrace():
    state = load_state()
    state = settle_active_pick(state)

    now_hour = datetime.now(LOCAL_TZ).hour

    if now_hour < 10:
        print("Morgen-Run: Abrechnung abgeschlossen. Picks folgen ab Mittag.")
        return

    if state.get("active_pick"):
        print(f"Stufe {state['active_pick'].get('step')} ({state['active_pick'].get('match')}) ist noch offen/live. Kein neuer Tipp.")
        return

    next_step = state.get("current_step", 0) + 1
    stake = round(state.get("bankroll", 5.00), 2)
    target = state.get("target_amount", 100.00)

    odds_data = fetch_moneyrace_odds()
    if not odds_data:
        print("Keine passenden Partien im Zeitfenster gefunden.")
        return

    today_iso = datetime.now(LOCAL_TZ).strftime("%Y-%m-%d")
    bar = make_progress_bar(state.get("current_step", 0))

    prompt = f"""
Du bist 'JARVIS MONEYRACE QUANT' – ein hochkonservativer Hedgefonds-Algorithmus.
Ziel: Wir verdoppeln schrittweise das Startkapital in 7 Stufen bis zu einem Ziel von {target:.2f} €.
Aktueller Status:
- Stufe: {next_step} von 7
- Aktueller Einsatz (All-In): {stake:.2f} €
- Ziel: {target:.2f} €

VERFÜGBARE PARTIEN & BUCHMACHERQUOTEN:
{odds_data}

================================================================================
ANALYSE-REGELN FÜR DAS MONEYRACE (QUALITÄT VOR ZWANG):
================================================================================
1. SICHERHEIT VOR HOHEM ERTRAG:
   - Wähle DIE stabilste mathematische Bank aus der Liste (+EV).
   - Ideale Quoten-Spanne: 1.35 bis 1.70 (maximal 1.78 bei überragendem Value).
   - Bevorzuge hochverlässliche Märkte:
     • Fussball: Heimsieg, Draw No Bet (DNB), Doppelte Chance (1X/X2), Totals mit Puffer (Über 1.5 oder Unter 3.5).
     • Basketball: Moneyline (Sieg inkl. OT) oder Spread/Handicap (+4.5 bis +8.5).
     • Darts: Match-Sieg (2-Weg).
   - ZEIT-LOGIK: Bei Läufen vor 15:00 Uhr wähle bevorzugt Partien, die vor 17:30 Uhr beendet sind (Anpfiff 13:00 - 15:30 Uhr).

2. EISHOCKEY-REGELN (STRIKT EINHALTEN!):
   - Erlaubt sind:
     • Moneyline / Sieger (inkl. Overtime & Shootout / 2-Weg)
     • Doppelte Chance (1X / X2)
     • Plus-Handicap / Puckline (+1.5 Tore)
     • Over/Under mit Puffer (z.B. Über 4.5 oder Unter 6.5 inkl. OT)
   - STRIKT VERBOTEN bei Eishockey: Reine 3-Weg-Wetten auf Sieg nach regulärer Spielzeit (60 Min.)! Ein Remis darf die Wette niemals zerstören.

3. KEIN ZWANGSTIPP:
   - Falls in der Liste KEIN EINZIGES Match eine klare, mathematisch robuste Kante bietet, antworte NUR mit 'NO_PICK'.

4. FORMATIERUNG:
   - Beginne Aufzählungen direkt mit '• ' (Unicode Bullet) OHNE Zeilenumbruch danach!
   - Integriere exakt den Initial-Block für den LIVE-TRACKER.
   - Ganz am Ende MUSS der exakte Tracking-Block '---JSON_TRACKING---' folgen (außer bei NO_PICK).

REPORT-HTML:
🎯 <b>JARVIS MONEYRACE • STUFE {next_step} / 7</b>
Progress: {bar} ({stake:.2f} € / {target:.2f} €)

Einsatz:  <b>{stake:.2f} €</b> (All-In)
Ziel:     <b>{target:.2f} €</b>

━━━━━━━━━━━━━━━━━━━━
📌 <b>Match:</b>   [Heimteam] vs. [Auswärtsteam]
🏆 <b>Sport:</b>   [Sportart / Liga]
⏰ <b>Beginn:</b>  [Uhrzeit] Uhr
🎯 <b>Tipp:</b>    <b>[Präziser Markt &amp; Auswahl]</b> @ [Quote]
🔄 <b>Buchmacher-Alternative:</b> [Klassische Standard-Linie] @ [Quote]
⚠️ <b>Value-Grenze:</b> Spielbar bis Mindestquote @ [Quote]
💰 <b>Return:</b>  <b>[Einsatz * Quote] €</b> (+[Reingewinn] €)

━━━━━━━━━━━━━━━━━━━━
🔍 <b>EDGE &amp; QUANT-ANALYSE</b>
- <b>Modell-Chance:</b> [XX.X]% | <b>Fair Odds:</b> ~[X.XX]
- <b>Mathematischer Edge:</b> +[X.X]% EV
- <b>Rationale:</b> [Detaillierte taktische und statistische Herleitung: Warum diese Auswahl als absolut risikoärmster Spot des Tages gewählt wurde.]

━━━━━━━━━━━━━━━━━━━━
⏱️ <b>LIVE-TRACKER • VOR ANPFIFF</b>
[░░░░░░░░░░░░] 0%
- <b>Status:</b> ⏳ Wartet auf Spielbeginn

━━━━━━━━━━━━━━━━━━━━
🗺️ <b>NÄCHSTER SCHRITT</b>
Bei Win geht es mit [Return] € direkt in Stufe {next_step + 1}.

---JSON_TRACKING---
{{
  "step": {next_step},
  "match": "Team A vs Team B",
  "pick": "Auswahl",
  "odds": 1.50,
  "stake": {stake},
  "expected_return": {round(stake * 1.50, 2)},
  "date": "{today_iso}"
}}
"""
    host = "generativelanguage.googleapis.com"
    path = "v1beta/models/gemini-3.8-flash:generateContent"
    api_url = f"https://{host}/{path}?key={GEMINI_API_KEY}"

    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "tools": [{"googleSearch": {}}],
        "generationConfig": {"temperature": 0.2}
    }

    for attempt in range(1, 4):
        try:
            res = requests.post(api_url, json=payload, timeout=90)
            if res.status_code == 200:
                full_reply = res.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
                
                if "NO_PICK" in full_reply and len(full_reply) < 50:
                    print("Gemini meldet NO_PICK: Kein Spot erfüllt die Kriterien. Kein Tipp gepostet.")
                    return

                report = full_reply
                pick_data = None
                if "---JSON_TRACKING---" in full_reply:
                    parts = full_reply.split("---JSON_TRACKING---")
                    report = parts[0].strip()
                    json_str = parts[1].replace("```json", "").replace("```", "").strip()
                    try:
                        pick_data = json.loads(json_str)
                    except Exception as je:
                        print(f"Fehler beim Parsen des JSON-Blocks: {je}")

                report = report.replace("```html", "").replace("```", "").strip()
                
                msg_id = send_telegram(report)
                
                if pick_data:
                    pick_data["message_id"] = msg_id
                    pick_data["original_text"] = report
                    state["active_pick"] = pick_data
                    state["last_run_date"] = today_iso
                    save_state(state)
                    print(f"Moneyrace Stufe {next_step} mit Message-ID {msg_id} gespeichert.")
                return
            elif res.status_code in [500, 502, 503, 504]:
                time.sleep(6)
            else:
                res.raise_for_status()
        except Exception as e:
            print(f"Versuch {attempt}/3 fehlgeschlagen: {e}")
            if attempt < 3:
                time.sleep(6)
            else:
                sys.exit(1)

if __name__ == "__main__":
    run_moneyrace()
