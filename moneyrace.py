import os
import sys
import json
import time
import requests
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo

try:
    from telegram_formatter import send_to_sport_channel
except ImportError:
    send_to_sport_channel = None

ODDS_API_KEY = os.environ.get("ODDS_API_KEY", "").strip()
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "").strip()

TELEGRAM_THREAD_ID = (
    os.environ.get("TELEGRAM_MONEYRACE_THREAD_ID", "").strip()
    or os.environ.get("TELEGRAM_THREAD_MONEYRACE", "").strip()
    or os.environ.get("TELEGRAM_THREAD_ID", "").strip()
)

LOCAL_TZ = ZoneInfo("Europe/Berlin")
STATE_FILE = "moneyrace_state.json"

# Vollständig harmonisierte Ligenliste (inkl. korrekter API-Keys)
MONEYRACE_SPORTS = [
    # Top-Fussball Ligen & Erweiterungen
    "soccer_germany_bundesliga",
    "soccer_germany_bundesliga2",
    "soccer_austria_bundesliga",
    "soccer_epl",
    "soccer_efl_champ",                  # Korrigiert: statt soccer_england_championship
    "soccer_spain_la_liga",
    "soccer_italy_serie_a",
    "soccer_france_ligue_one",
    "soccer_netherlands_eredivisie",
    "soccer_belgium_first_div",
    "soccer_portugal_primeira_liga",
    "soccer_switzerland_superleague",     # Neu hinzugefügt
    # UEFA Wettbewerbe
    "soccer_uefa_champs_league",
    "soccer_uefa_europa_league",
    "soccer_uefa_europa_conference_league",
    # Eishockey (Top Ligen Europa & USA)
    "icehockey_nhl",
    "icehockey_germany_del",
    "icehockey_sweden_shl",
    "icehockey_liiga",
    # Basketball & Darts
    "basketball_euroleague",
    "basketball_nba",
    "darts_pdc_world_championship",
    "darts_premier_league"
]

def send_telegram(text, reply_to=None):
    if send_to_sport_channel:
        msg_id = send_to_sport_channel(text, sport="moneyrace", reply_to=reply_to)
        if msg_id:
            return msg_id

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
            pass
    if reply_to:
        payload["reply_to_message_id"] = int(reply_to)

    try:
        res = requests.post(url, json=payload, timeout=25)
        if res.status_code == 200:
            return res.json().get("result", {}).get("message_id")
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
            data = json.load(f)
            return data if isinstance(data, dict) else default_state
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
1. Prüfe sorgfältig, ob das Spiel bereits regulär beendet ist (inkl. möglicher Overtime/Penaltys/Satzstände). Falls noch nicht begonnen, verschoben, wegen Regen unterbrochen oder live, antworte zwingend mit PENDING.
2. Wenn der Tipp gewonnen hat, antworte mit 'RESULT: WON'.
3. Wenn der Tipp verloren hat, antworte mit 'RESULT: LOST'.
4. Bei Push / Void / Absage antworte mit 'RESULT: VOID'.

Format:
RESULT: WON oder LOST oder PENDING oder VOID
SCORE: Endergebnis (z. B. 4:2 oder 6:4, 6:3)
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

            main_msg_id = active.get("message_id")

            if "RESULT: WON" in text:
                ret = round(stake_val * odds_val, 2)
                profit = round(ret - stake_val, 2)
                step_done = active["step"]
                
                state["bankroll"] = ret
                state["current_step"] = step_done
                active["status"] = "WON"
                active["return"] = ret
                state.setdefault("history", []).append(active)
                state["active_pick"] = None
                save_state(state)

                pct = round((ret / state["target_amount"]) * 100, 1)
                bar = make_progress_bar(step_done)

                if ret >= state["target_amount"]:
                    msg = (
                        f"🏆 <b>MONEYRACE — ZIEL ERREICHT!</b>\n\n"
                        f"Stufe {step_done} gemeistert!\n"
                        f"📌 Letzter Tipp: {active['pick']} (<code>@{odds_val:.2f}</code>) ➔ <b>TREFFER!</b>\n"
                        f"💰 Endstand: <b>{ret:.2f} €</b>\n\n"
                        f"Die 100 € Challenge wurde erfolgreich abgeschlossen! 🎉"
                    )
                else:
                    msg = (
                        f"✅ <b>MONEYRACE — STUFE {step_done} GEWONNEN!</b>\n\n"
                        f"• <b>Tipp:</b> {active['pick']} (<code>@{odds_val:.2f}</code>) ➔ <b>TREFFER!</b>\n"
                        f"• <b>Rücklauf:</b> <b>+{profit:.2f} €</b>\n"
                        f"• <b>Neuer Kontostand:</b> <b>{ret:.2f} €</b>\n\n"
                        f"Fortschritt: {bar} {pct}%\n"
                        f"➔ <i>Weiter mit Stufe {step_done + 1}!</i>"
                    )
                send_telegram(msg, reply_to=main_msg_id)

            elif "RESULT: LOST" in text:
                step_lost = active["step"]
                active["status"] = "LOST"
                active["return"] = 0.0
                state.setdefault("history", []).append(active)
                
                state["active_pick"] = None
                state["bankroll"] = state["start_amount"]
                state["current_step"] = 0
                save_state(state)

                msg = (
                    f"❌ <b>MONEYRACE — STUFE {step_lost} LEIDER VERLOREN</b>\n\n"
                    f"• <b>Match:</b> {active['match']}\n"
                    f"• <b>Tipp:</b> {active['pick']} (<code>@{odds_val:.2f}</code>)\n\n"
                    f"Die Challenge wird zurückgesetzt. Neustart bei Stufe 1 (<b>{state['start_amount']:.2f} €</b>)."
                )
                send_telegram(msg, reply_to=main_msg_id)

            elif "RESULT: VOID" in text:
                active["status"] = "VOID"
                state["active_pick"] = None
                save_state(state)

                msg = (
                    f"🟡 <b>MONEYRACE — STUFE {active['step']} PUSH / VOID</b>\n\n"
                    f"• <b>Match:</b> {active['match']}\n"
                    f"• <b>Tipp:</b> {active['pick']}\n"
                    f"Einsatz von {stake_val:.2f} € erstattet. Stufe {active['step']} wird wiederholt."
                )
                send_telegram(msg, reply_to=main_msg_id)
            else:
                print("Spielergebnis noch nicht final oder unklar. Bleibt PENDING.")
    except Exception as e:
        print(f"Fehler bei Abrechnung: {e}")

    return state

def fetch_moneyrace_odds():
    all_events = []
    now_utc = datetime.now(timezone.utc)
    now_hour = datetime.now(LOCAL_TZ).hour
    
    # 6 Stunden Vorlauf am Mittag, 9 Stunden am Abend
    window_hours = 6 if now_hour < 15 else 9
    cutoff = now_utc + timedelta(hours=window_hours)

    sports_to_query = list(MONEYRACE_SPORTS)

    try:
        sports_url = "https://api.the-odds-api.com/v4/sports/"
        res_sports = requests.get(sports_url, params={"apiKey": ODDS_API_KEY}, timeout=10)
        if res_sports.status_code == 200:
            active_remote = {s.get("key") for s in res_sports.json() if s.get("active", False)}
            # Nur remote tatsächlich aktive Ligen abfragen
            sports_to_query = [s for s in sports_to_query if s in active_remote]
            # Dynamische Tennis-Turniere hinzufügen
            for s in res_sports.json():
                if s.get("group") == "Tennis" and s.get("active", False):
                    sports_to_query.append(s.get("key"))
    except Exception as e:
        print(f"Hinweis beim Abruf aktiver Sportarten: {e}")

    for sport in sports_to_query:
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
                        time_str = commence_utc.astimezone(LOCAL_TZ).strftime("%H:%M Uhr")
                        bookies = match.get("bookmakers", [])
                        if not bookies:
                            continue
                        odds_details = []
                        for m in bookies[0].get("markets", []):
                            outcomes = [f"{o['name']} ({o.get('point', '')}): {o['price']}" for o in m.get("outcomes", [])]
                            odds_details.append(f"{m.get('key')}: {', '.join(outcomes)}")
                        all_events.append(f"[{sport}] [{time_str}] {match['home_team']} vs. {match['away_team']} | {' // '.join(odds_details)}")
        except Exception as e:
            print(f"Fehler bei {sport}: {e}")

    print(f"Gefundene Moneyrace-Kandidaten: {len(all_events)}")
    return "\n".join(all_events[:70])

def run_moneyrace():
    state = load_state()
    state = settle_active_pick(state)

    now_hour = datetime.now(LOCAL_TZ).hour

    if now_hour < 10:
        print("Morgen-Run: Abrechnung abgeschlossen. Picks folgen ab Mittag.")
        return

    if state.get("active_pick"):
        print(f"Stufe {state['active_pick'].get('step')} ({state['active_pick'].get('match')}) ist noch aktiv. Kein neuer Pick.")
        return

    next_step = state.get("current_step", 0) + 1
    stake = round(state.get("bankroll", 5.00), 2)
    target = state.get("target_amount", 100.00)

    odds_data = fetch_moneyrace_odds()
    if not odds_data:
        print("Keine passenden Partien im Zeitfenster gefunden.")
        return

    today_iso = datetime.now(LOCAL_TZ).strftime("%Y-%m-%d")
    today_str = datetime.now(LOCAL_TZ).strftime("%d.%m.%Y")
    bar = make_progress_bar(state.get("current_step", 0))

    prompt = f"""
Du bist 'JARVIS MONEYRACE QUANT' – ein hochkonservativer Bankroll-Algorithmus.
Ziel: Wir verdoppeln schrittweise das Startkapital in 7 Stufen bis zu einem Ziel von {target:.2f} €.
Aktueller Status:
- Stufe: {next_step} von 7
- Aktueller Einsatz (All-In): {stake:.2f} €
- Ziel: {target:.2f} €

VERFÜGBARE PARTIEN & BUCHMACHERQUOTEN:
{odds_data}

================================================================================
STRIKTE REGELN (PICKS FIRST & ANSTOSSZEIT):
================================================================================
1. PICKS FIRST:
   - Die spielfertige Wette steht ganz oben direkt unter dem Header!
   - Gib bei 'Match' immer die genaue Anstoßzeit an (z. B. '[15:30 Uhr] Team A vs. Team B').
   - Erst danach folgt die Trennlinie '━━━━━━━━━━━━━━━━━━━━' und die Deep-Dive-Begründung.
2. SICHERHEIT:
   - Quotenbereich: 1.35 bis 1.70.
   - Bevorzuge hochverlässliche Märkte: Heimsieg, DNB, 1X/X2, Totals mit Puffer (Über 1.5).
   - Bei Eishockey: Nur 2-Weg (inkl. OT/SO), NIEMALS 3-Weg reguläre Spielzeit!
3. KEIN ZWANGSTIPP:
   - Falls kein Match einen klaren mathematischen Vorteil bietet, antworte NUR mit 'NO_PICK'.
4. FORMATIERUNG:
   - Quoten und Beträge in <code>...</code> setzen.
   - Trennlinie IMMER exakt 20 Zeichen: '━━━━━━━━━━━━━━━━━━━━'.

EXAKTES HTML-AUSGABEFORMAT:
🎯 <b>JARVIS MONEYRACE — STUFE {next_step} / 7 ({today_str})</b>
Fortschritt: {bar} (<code>{stake:.2f} €</code> / <code>{target:.2f} €</code>)
━━━━━━━━━━━━━━━━━━━━
📋 <b>WETTE AUF EINEN BLICK:</b>

📌 <b>Match:</b> [HH:MM Uhr] [Heim] vs. [Gast]
⏰ <b>Beginn:</b> [HH:MM Uhr] | 🏆 <b>Liga:</b> [Sportart/Liga]
🎯 <b>Tipp:</b> <b>[Markt & Auswahl]</b> (<code>@[Quote]</code>)
💰 <b>Einsatz:</b> <code>{stake:.2f} €</code> (All-In) ➔ <b>Möglicher Return:</b> <code>[Return] €</code>
⚠️ <b>Value-Grenze:</b> Spielbar bis <code>@[Quote]</code>

━━━━━━━━━━━━━━━━━━━━
📊 <b>ANALYSEN & MODELL-LOGIK (DEEP DIVE)</b>
- <b>Quant-Edge:</b> Modell-Chance: [XX.X]% | Fair Odds: ~[X.XX] (<b>+[X.X]% EV</b>)
- <b>Begründung:</b> [Maximal 2-3 präzise Sätze zur taktischen und statistischen Herleitung]

---JSON_TRACKING---
{{
  "step": {next_step},
  "match": "Team A vs Team B",
  "kickoff": "HH:MM Uhr",
  "sport": "Soccer",
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
                    print("Gemini meldet NO_PICK: Kein Spot erfüllt die Kriterien.")
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
