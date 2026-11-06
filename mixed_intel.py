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

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "").strip()

TELEGRAM_THREAD_ID = (
    os.environ.get("TELEGRAM_MIXED_THREAD_ID", "").strip()
    or os.environ.get("TELEGRAM_THREAD_MIXED", "").strip()
    or os.environ.get("TELEGRAM_THREAD_ID", "").strip()
)

LOCAL_TZ = ZoneInfo("Europe/Berlin")
HISTORY_FILE = "mixed_history.json"

SOURCE_FILES = {
    "Soccer": "pending_soccer.json",
    "NBA": "nba_history.json",
    "NHL": "nhl_history.json",
    "NFL": "nfl_history.json",
    "Tennis": "tennis_history.json",
    "Darts": "darts_history.json",
    "Euro-Hoops": "euro_history.json",
    "US College": "college_history.json"
}

def send_telegram(text, reply_to=None):
    if send_to_sport_channel:
        msg_id = send_to_sport_channel(text, sport="mixed", reply_to=reply_to)
        if msg_id:
            return msg_id

    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("[Telegram] FEHLER: Credentials fehlen.")
        return None

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    max_len = 3900
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

    last_msg_id = None
    for chunk in chunks:
        payload = {
            "chat_id": TELEGRAM_CHAT_ID,
            "text": chunk,
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
            if res.status_code != 200:
                payload.pop("parse_mode", None)
                res2 = requests.post(url, json=payload, timeout=25)
                if res2.status_code == 200:
                    last_msg_id = res2.json().get("result", {}).get("message_id")
            else:
                last_msg_id = res.json().get("result", {}).get("message_id")
        except Exception as e:
            print(f"[Telegram] Netzwerkfehler: {e}")

    return last_msg_id

def load_history():
    if not os.path.exists(HISTORY_FILE):
        return {"settled": [], "pending": []}
    try:
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, dict):
                data.setdefault("settled", [])
                data.setdefault("pending", [])
                return data
            return {"settled": [], "pending": []}
    except Exception as e:
        print(f"Fehler beim Laden von {HISTORY_FILE}: {e}")
        return {"settled": [], "pending": []}

def save_history(history):
    try:
        with open(HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump(history, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"Fehler beim Speichern von {HISTORY_FILE}: {e}")

def collect_daily_picks_pool():
    pool = []
    today_iso = datetime.now(LOCAL_TZ).strftime("%Y-%m-%d")

    for sport_label, filepath in SOURCE_FILES.items():
        if not os.path.exists(filepath):
            continue
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                data = json.load(f)
                
                # Soccer Pending-Struktur
                if sport_label == "Soccer" and isinstance(data, dict):
                    if "potd" in data and isinstance(data["potd"], dict):
                        p = data["potd"]
                        pool.append({
                            "sport": "Soccer",
                            "category": "POTD",
                            "match": p.get("match"),
                            "pick": p.get("pick"),
                            "odds": float(p.get("odds", 1.60)),
                            "is_anchor": True
                        })
                    for t in data.get("tickets", []):
                        t_name = t.get("ticket_name", "Kombi")
                        for p_leg in t.get("picks", []):
                            pool.append({
                                "sport": "Soccer",
                                "category": t_name,
                                "match": p_leg.get("match"),
                                "pick": p_leg.get("pick"),
                                "odds": 1.65,
                                "is_anchor": False
                            })
                    continue

                # Standard history.json Struktur (pending list)
                items = []
                if isinstance(data, dict) and "pending" in data:
                    items = data["pending"]
                elif isinstance(data, list):
                    items = data

                for it in items:
                    if not isinstance(it, dict):
                        continue
                    item_date = str(it.get("date", ""))[:10]
                    if item_date and item_date != today_iso:
                        continue

                    # Nur Einzelbeine in den Pool übernehmen (keine bereits kombinierten Strings)
                    match_str = str(it.get("match", ""))
                    if " // " in match_str or " + " in str(it.get("pick", "")):
                        continue

                    cat = str(it.get("category", "")).upper()
                    is_potd = any(k in cat for k in ["POTD", "MOTD", "TOP", "ANCHOR"])
                    
                    try:
                        odds_val = float(str(it.get("odds", 1.70)).replace(",", "."))
                    except ValueError:
                        odds_val = 1.70

                    pool.append({
                        "sport": sport_label,
                        "category": cat or "SINGLE",
                        "match": match_str,
                        "pick": it.get("pick"),
                        "odds": odds_val,
                        "is_anchor": is_potd
                    })
        except Exception as e:
            print(f"[Pool] Fehler beim Auslesen von {filepath}: {e}")

    # Deduplizieren
    seen = set()
    unique_pool = []
    for p in pool:
        k = (p.get("match", "").strip().lower(), p.get("pick", "").strip().lower())
        if k not in seen and p.get("match") and p.get("pick"):
            seen.add(k)
            unique_pool.append(p)

    return unique_pool

def settle_pending_mixed(history):
    pending = history.get("pending", [])
    if not pending:
        print("Keine offenen Mixed-Kombis zur Abrechnung.")
        return history

    still_pending = []
    settled_now = []

    host = "generativelanguage.googleapis.com"
    path = "v1beta/models/gemini-3.8-flash:generateContent"
    api_url = f"https://{host}/{path}?key={GEMINI_API_KEY}"

    for ticket in pending:
        prompt_settle = f"""
Recherchiere via Google Search die offiziellen Endergebnisse für folgende Kombiwette:
Kategorie: {ticket.get('tier')}
Quote: {ticket.get('odds')}
Auswahl/Beine:
{ticket.get('pick')}
Datum: {ticket.get('date')}

REGELN:
1. Prüfe, ob ALLE Partien regulär beendet sind (FINAL). Wenn auch nur EIN Spiel noch läuft oder ansteht, antworte ZWINGEND mit PENDING.
2. Wenn ALLE Beine der Kombi gewonnen haben: 'RESULT: WON'.
3. Wenn mindestens ein Bein verloren hat: 'RESULT: LOST'.
4. Bei Absagen/Push mit Quotenreduktion: 'RESULT: WON' (falls der Rest traf) oder 'RESULT: VOID'.

Format:
RESULT: WON oder LOST oder PENDING oder VOID
SCORE: [Kurzer Überblick der Ergebnisse]
INFO: [1-2 Sätze Begründung]
"""
        payload = {
            "contents": [{"parts": [{"text": prompt_settle}]}],
            "tools": [{"googleSearch": {}}],
            "generationConfig": {"temperature": 0.1}
        }

        try:
            res = requests.post(api_url, json=payload, timeout=60)
            if res.status_code == 200:
                text = res.json()["candidates"][0]["content"]["parts"][0]["text"]
                score_val = ""
                info_val = ""
                result_val = "PENDING"
                for line in text.splitlines():
                    if line.startswith("SCORE:"):
                        score_val = line.replace("SCORE:", "").strip()
                    elif line.startswith("INFO:"):
                        info_val = line.replace("INFO:", "").strip()
                    elif line.startswith("RESULT:"):
                        result_val = line.replace("RESULT:", "").strip().upper()

                ticket["score"] = score_val
                ticket["info"] = info_val

                if result_val in ["WON", "LOST", "VOID"]:
                    ticket["status"] = result_val
                    odds_val = float(ticket.get("odds", 2.0))
                    stake_val = float(ticket.get("stake", 1.0))

                    if result_val == "WON":
                        ticket["pnl"] = round((odds_val - 1.0) * stake_val, 2)
                    elif result_val == "LOST":
                        ticket["pnl"] = round(-stake_val, 2)
                    else:
                        ticket["pnl"] = 0.0

                    settled_now.append(ticket)
                else:
                    still_pending.append(ticket)
            else:
                still_pending.append(ticket)
        except Exception as e:
            print(f"Fehler bei Mixed-Settle: {e}")
            still_pending.append(ticket)

    if settled_now:
        history["settled"].extend(settled_now)
        history["pending"] = still_pending
        save_history(history)

        total_staked = sum(float(t.get("stake", 1.0)) for t in settled_now)
        total_pnl = sum(float(t.get("pnl", 0.0)) for t in settled_now)
        won_cnt = sum(1 for t in settled_now if t.get("status") == "WON")
        sign = "+" if total_pnl >= 0 else ""
        profit_color = "🟢" if total_pnl >= 0 else "🔴"

        lines = [
            "🏁 <b>JARVIS MIXED & MULTI-ACCA — TAGESABSCHLUSS</b>",
            "━━━━━━━━━━━━━━━━━━━━",
            "📋 <b>TICKET-ERGEBNISSE:</b>\n"
        ]

        for t in settled_now:
            st = t["status"]
            icon = "✅" if st == "WON" else ("🟡" if st == "VOID" else "❌")
            pnl_val = t.get("pnl", 0.0)
            pnl_str = f"+{pnl_val:.2f}u" if pnl_val >= 0 else f"{pnl_val:.2f}u"

            lines.append(f"{icon} <b>{t.get('tier', 'Kombi')}</b> (<code>@{t.get('odds', 1.0):.2f}</code>)")
            lines.append(f"• <b>Auswahl:</b> {t.get('pick')}")
            lines.append(f"• <b>Status:</b> <b>{st}</b> (<code>{pnl_str}</code>)")
            if t.get("info"):
                lines.append(f"• <i>{t.get('info')}</i>")
            lines.append("")

        lines.append("━━━━━━━━━━━━━━━━━━━━")
        lines.append(f"📊 <b>Bilanz:</b> {won_cnt}/{len(settled_now)} getroffen | {profit_color} <b>{sign}{total_pnl:.2f} Units</b>")
        lines.append("\n📁 <i>Archiviert in mixed_history.json</i>")

        send_telegram("\n".join(lines).strip())

    return history

def run_mixed_intel():
    history = load_history()
    settle_pending_mixed(history)

    now_hour = datetime.now(LOCAL_TZ).hour
    if now_hour < 12:
        print("Morgen-Run: Nur Abrechnung durchgeführt.")
        return

    pool = collect_daily_picks_pool()
    if len(pool) < 3:
        print(f"Zu wenige Picks im Tages-Pool ({len(pool)}). Mindestens 3 erforderlich.")
        return

    today_str = datetime.now(LOCAL_TZ).strftime("%d.%m.%Y")
    today_iso = datetime.now(LOCAL_TZ).strftime("%Y-%m-%d")

    pool_text = "\n".join([
        f"[{p['sport']} | {p['category']}] {p['match']} ➔ {p['pick']} (@{p['odds']:.2f}) {'[POTD-ANKER]' if p['is_anchor'] else ''}"
        for p in pool
    ])

    prompt = f"""
Du bist 'JARVIS CROSS-SPORT PORTFOLIO QUANT'.
Deine Aufgabe ist es, aus den heutigen, bereits validierten Sport-Tipps aus verschiedenen Ligen die mathematisch stärksten Cross-Sport-Kombiwetten zu bauen.

VERFÜGBARE VORVALIDIERTE PICKS ({len(pool)} STÜCK):
{pool_text}

================================================================================
STRIKTE PORTFOLIO-ARCHITEKTUR & REGELN:
================================================================================
1. DIE 3 TIER-KATEGORIEN (EXAKT BAUEN):
   🛡️ 1. SAFE HARBOR ACCA:
      - Genau 2 Beine aus 2 verschiedenen Sportarten.
      - Bevorzuge [POTD-ANKER] und hochstabile Picks.
      - Ziel-Gesamtquote: 1.85 bis 2.35. Einsatz: 1.50 Units.

   ⚖️ 2. BALANCED VALUE ACCA:
      - Genau 3 Beine aus 3 verschiedenen Sportarten.
      - Starker mathematischer Edge (+EV).
      - Ziel-Gesamtquote: 3.20 bis 4.60. Einsatz: 0.75 Units.

   🚀 3. MOONSHOT MULTI:
      - 4 bis 5 Beine (maximal 2 Beine aus derselben Sportart).
      - Höhere Hebelwirkung bei kontrolliertem Risiko.
      - Ziel-Gesamtquote: 7.00 bis 14.00+. Einsatz: 0.35 Units.

2. QUANT-VETO-REGELN:
   - Keine Quoten unter 1.30 auf Einzelbeinen!
   - Eishockey NUR 2-Weg (inkl. OT) oder Puckline (+1.5), NIEMALS 3-Weg reguläre Spielzeit!
   - DIVERSITÄT: Mische die Sportarten zwingend (z. B. Fußball + NBA + Darts + NHL).

3. FORMATIERUNG:
   - PICKS FIRST: Alle 3 Scheine stehen komplett spielfertig ganz oben!
   - Trennlinie IMMER exakt 20 Zeichen: '━━━━━━━━━━━━━━━━━━━━'.
   - Quoten und Stakes immer in <code>...</code> setzen.
   - Text vor '---JSON_TRACKING---' maximal 3.400 Zeichen.

EXAKTES HTML-AUSGABEFORMAT:
🎯 <b>JARVIS CROSS-SPORT & MULTI-ACCA ({today_str})</b>
<i>Diversified Portfolio • Uncorrelated Multi-Bets • High-Edge Accas</i>
━━━━━━━━━━━━━━━━━━━━
📋 <b>DIE 3 SCHEINE AUF EINEN BLICK:</b>

🛡️ <b>SAFE HARBOR ACCA (<code>1.50u</code> | Gesamt: <code>@[Quote]</code>)</b>
• [Sport 1] [Match 1] ➔ <i>[Tipp 1]</i> (<code>@[Quote]</code>)
• [Sport 2] [Match 2] ➔ <i>[Tipp 2]</i> (<code>@[Quote]</code>)

⚖️ <b>BALANCED VALUE ACCA (<code>0.75u</code> | Gesamt: <code>@[Quote]</code>)</b>
• [Sport 1] [Match 1] ➔ <i>[Tipp 1]</i> (<code>@[Quote]</code>)
• [Sport 2] [Match 2] ➔ <i>[Tipp 2]</i> (<code>@[Quote]</code>)
• [Sport 3] [Match 3] ➔ <i>[Tipp 3]</i> (<code>@[Quote]</code>)

🚀 <b>MOONSHOT MULTI (<code>0.35u</code> | Gesamt: <code>@[Quote]</code>)</b>
• [Sport 1] [Match 1] ➔ <i>[Tipp 1]</i> (<code>@[Quote]</code>)
• [Sport 2] [Match 2] ➔ <i>[Tipp 2]</i> (<code>@[Quote]</code>)
• [Sport 3] [Match 3] ➔ <i>[Tipp 3]</i> (<code>@[Quote]</code>)
• [Sport 4] [Match 4] ➔ <i>[Tipp 4]</i> (<code>@[Quote]</code>)

━━━━━━━━━━━━━━━━━━━━
📊 <b>PORTFOLIO-LOGIK & DIVERSIFIKATION (DEEP DIVE)</b>
• <b>Safe Harbor:</b> [1-2 Sätze, warum diese 2 Beine unkorreliert das stabilste Fundament bilden]
• <b>Balanced Value:</b> [1-2 Sätze zum mathematischen Edge]
• <b>Moonshot:</b> [1-2 Sätze zur Hebel-Kombination]

---JSON_TRACKING---
[
  {{
    "tier": "🛡️ SAFE HARBOR ACCA",
    "sport": "Mixed",
    "pick": "Tipp 1 (Sport 1) + Tipp 2 (Sport 2)",
    "odds": 2.10,
    "stake": 1.5,
    "date": "{today_iso}"
  }},
  {{
    "tier": "⚖️ BALANCED VALUE ACCA",
    "sport": "Mixed",
    "pick": "Tipp 1 + Tipp 2 + Tipp 3",
    "odds": 3.85,
    "stake": 0.75,
    "date": "{today_iso}"
  }},
  {{
    "tier": "🚀 MOONSHOT MULTI",
    "sport": "Mixed",
    "pick": "Tipp 1 + Tipp 2 + Tipp 3 + Tipp 4",
    "odds": 9.50,
    "stake": 0.35,
    "date": "{today_iso}"
  }}
]
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
                report = full_reply
                if "---JSON_TRACKING---" in full_reply:
                    parts = full_reply.split("---JSON_TRACKING---")
                    report = parts[0].strip()
                    json_str = parts[1].replace("```json", "").replace("```", "").strip()
                    try:
                        new_picks = json.loads(json_str)
                        for np in new_picks:
                            np["status"] = "PENDING"
                            np["sport"] = "Mixed"
                            try:
                                np["odds"] = float(str(np.get("odds", 2.0)).replace(",", "."))
                            except ValueError:
                                np["odds"] = 2.0
                            try:
                                np["stake"] = float(str(np.get("stake", 1.0)).replace(",", "."))
                            except ValueError:
                                np["stake"] = 1.0
                        history["pending"].extend(new_picks)
                        save_history(history)
                        print(f"Mixed-Picks in {HISTORY_FILE} gesichert.")
                    except Exception as je:
                        print(f"Fehler beim Parsen der Mixed-Picks: {je}")

                report = report.replace("```html", "").replace("```", "").strip()
                send_telegram(report)
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
    run_mixed_intel()
