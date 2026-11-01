import os
import sys
import json
import glob
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
import requests
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

LOCAL_TZ = ZoneInfo("Europe/Berlin")

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "").strip()

# Topic 'weekly & monthly Performance & Recaps' (ID: 134)
TELEGRAM_ANALYTICS_THREAD = (
    os.environ.get("TELEGRAM_ANALYTICS_THREAD_ID", "").strip()
    or "134"
)

SPORT_FILES = {
    "Soccer": "soccer_history.json",
    "NBA": "nba_history.json",
    "NHL": "nhl_history.json",
    "NFL": "nfl_history.json",
    "Euro-Hoops & Ice": "euro_history.json",
    "US College": "college_history.json",
    "Darts": "darts_history.json"
}

def load_all_history():
    all_bets = []
    for sport, filename in SPORT_FILES.items():
        if os.path.exists(filename):
            try:
                with open(filename, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, list):
                        for item in data:
                            item["sport"] = sport
                            all_bets.append(item)
                    elif isinstance(data, dict):
                        for k, v in data.items():
                            if isinstance(v, list):
                                for item in v:
                                    item["sport"] = sport
                                    all_bets.append(item)
            except Exception as e:
                print(f"[Warnung] Konnte {filename} nicht laden: {e}")
    return all_bets

def filter_bets(bets, timeframe="weekly"):
    now = datetime.now(timezone.utc)
    if timeframe == "monthly":
        start_date = now - timedelta(days=30)
    else:
        start_date = now - timedelta(days=7)

    filtered = []
    for b in bets:
        date_str = b.get("date") or b.get("settled_at") or b.get("commence_time")
        if not date_str:
            continue
        try:
            if "T" in date_str:
                dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
            else:
                dt = datetime.strptime(date_str[:10], "%Y-%m-%d").replace(tzinfo=timezone.utc)
            
            if dt >= start_date:
                filtered.append(b)
        except Exception:
            continue
    return filtered

def compute_metrics(bets):
    total_bets = len(bets)
    if total_bets == 0:
        return None

    wins = sum(1 for b in bets if b.get("status") in ["WON", "HIT"])
    losses = sum(1 for b in bets if b.get("status") in ["LOST", "MISS"])
    pushes = sum(1 for b in bets if b.get("status") in ["PUSH", "VOID"])
    
    total_stake = 0.0
    total_profit = 0.0
    by_sport = {}
    clv_list = []

    for b in bets:
        sport = b.get("sport", "Sonstige")
        if sport not in by_sport:
            by_sport[sport] = {"bets": 0, "profit": 0.0, "stake": 0.0, "wins": 0}

        stake = float(b.get("stake", 1.0))
        pnl = float(b.get("profit", 0.0))
        status = b.get("status", "")

        total_stake += stake
        total_profit += pnl

        by_sport[sport]["bets"] += 1
        by_sport[sport]["profit"] += pnl
        by_sport[sport]["stake"] += stake
        if status in ["WON", "HIT"]:
            by_sport[sport]["wins"] += 1

        if "clv" in b and b["clv"] is not None:
            try:
                clv_list.append(float(b["clv"]))
            except ValueError:
                pass

    roi = (total_profit / total_stake * 100) if total_stake > 0 else 0.0
    win_rate = (wins / (wins + losses) * 100) if (wins + losses) > 0 else 0.0
    avg_clv = (sum(clv_list) / len(clv_list)) if clv_list else 0.0

    return {
        "total_bets": total_bets,
        "wins": wins,
        "losses": losses,
        "pushes": pushes,
        "total_stake": total_stake,
        "total_profit": total_profit,
        "roi": roi,
        "win_rate": win_rate,
        "avg_clv": avg_clv,
        "by_sport": by_sport
    }

def generate_performance_chart(bets, metrics, timeframe):
    plt.style.use("dark_background")
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 5.5))

    # Linker Plot: Equity-Kurve
    cumulative_pnl = [0.0]
    running = 0.0
    for b in bets:
        running += float(b.get("profit", 0.0))
        cumulative_pnl.append(running)

    ax1.plot(cumulative_pnl, color="#00ffcc", linewidth=2.5, marker="o", markersize=3)
    ax1.axhline(0, color="#666666", linestyle="--", linewidth=1)
    ax1.set_title(f"JARVIS Equity-Kurve ({timeframe.upper()})", fontsize=12, fontweight="bold", color="#ffffff")
    ax1.set_xlabel("Wetten", color="#aaaaaa")
    ax1.set_ylabel("Profit (Units)", color="#aaaaaa")
    ax1.grid(True, linestyle=":", alpha=0.3)

    # Rechter Plot: P&L nach Sportart
    sports = list(metrics["by_sport"].keys())
    pnls = [metrics["by_sport"][s]["profit"] for s in sports]
    colors = ["#00ffcc" if p >= 0 else "#ff3366" for p in pnls]

    bars = ax2.barh(sports, pnls, color=colors, height=0.55)
    ax2.axvline(0, color="#666666", linestyle="--", linewidth=1)
    ax2.set_title("P&L nach Sportart (Units)", fontsize=12, fontweight="bold", color="#ffffff")
    ax2.set_xlabel("Profit / Verlust", color="#aaaaaa")
    ax2.grid(True, linestyle=":", alpha=0.3)

    for bar in bars:
        width = bar.get_width()
        text_x = width + (0.1 if width >= 0 else -0.3)
        ax2.annotate(f"{width:+.2f}u",
                     xy=(text_x, bar.get_y() + bar.get_height() / 2),
                     va="center", color="#ffffff", fontsize=9, fontweight="bold")

    plt.tight_layout()
    chart_path = "performance_recap.png"
    plt.savefig(chart_path, dpi=200, bbox_inches="tight")
    plt.close()
    return chart_path

def generate_ai_recap(metrics, timeframe):
    now_str = datetime.now(LOCAL_TZ).strftime("%d.%m.%Y")
    label = "WÖCHENTLICHER" if timeframe == "weekly" else "MONATLICHER"

    prompt = f"""
Du bist 'JARVIS QUANT META-ANALYST'.
Erstelle den {label} RECAP & PERFORMANCE-BERICHT zum Stichtag {now_str}.

METRIKEN:
- Ausgewertete Wetten: {metrics['total_bets']} (Wins: {metrics['wins']}, Losses: {metrics['losses']}, Push: {metrics['pushes']})
- Win-Rate: {metrics['win_rate']:.1f}%
- Total P&L: {metrics['total_profit']:+.2f} Units | ROI: {metrics['roi']:+.2f}%
- Durchschnittlicher CLV (Closing Line Value): {metrics['avg_clv']:+.2f}%
- Aufschlüsselung nach Sportarten: {json.dumps(metrics['by_sport'], ensure_ascii=False)}

VORGABEN FÜR DIE TELEGRAM-HTML-AUSGABE:
- Professioneller Quant-/Hedgefonds-Stil.
- HTML-Tags: <b>, <i>, <code>. Keine Markdown-Backticks!
- Analysiere kurz die Top-Performer-Sportart und Problembereiche.
- Beziehe dich kurz auf den CLV (ob der Markt geschlagen wurde).
- Schließe mit einem fokussierten Fazit für die nächste Periode.
"""
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-3.8-flash:generateContent?key={GEMINI_API_KEY}"
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.2}
    }

    try:
        res = requests.post(url, json=payload, timeout=60)
        if res.status_code == 200:
            text = res.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
            return text.replace("```html", "").replace("```", "").strip()
    except Exception as e:
        print(f"[AI Error] {e}")

    return f"""📊 <b>JARVIS QUANT {label} RECAP</b>
Stichtag: {now_str}

━━━━━━━━━━━━━━━━━━━━
📈 <b>Performance-Kennzahlen:</b>
• <b>P&L:</b> <code>{metrics['total_profit']:+.2f} Units</code>
• <b>ROI:</b> <code>{metrics['roi']:+.2f}%</code>
• <b>Win-Rate:</b> <code>{metrics['win_rate']:.1f}%</code> ({metrics['wins']}W - {metrics['losses']}L)
• <b>Avg CLV:</b> <code>{metrics['avg_clv']:+.2f}%</code>"""

def send_telegram_recap(metrics, recap_text, image_path, timeframe):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("[Telegram] FEHLER: Credentials fehlen.")
        return

    thread_id = int(TELEGRAM_ANALYTICS_THREAD) if TELEGRAM_ANALYTICS_THREAD else None
    now_str = datetime.now(LOCAL_TZ).strftime("%d.%m.%Y")
    label = "WÖCHENTLICHER" if timeframe == "weekly" else "MONATLICHER"

    # 1. Foto mit kompakter Caption senden (unter 1.024 Zeichen)
    photo_caption = (
        f"📊 <b>JARVIS QUANT {label} RECAP</b> • {now_str}\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"• <b>P&L:</b> <code>{metrics['total_profit']:+.2f} Units</code>\n"
        f"• <b>ROI:</b> <code>{metrics['roi']:+.2f}%</code> | <b>Win-Rate:</b> <code>{metrics['win_rate']:.1f}%</code>\n"
        f"• <b>Avg CLV:</b> <code>{metrics['avg_clv']:+.2f}%</code>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"📈 <i>Performance-Chart & Sportart-Aufschlüsselung anbei. Detaillierter Quant-Report folgt unten:</i>"
    )

    photo_url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendPhoto"
    photo_payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "caption": photo_caption,
        "parse_mode": "HTML"
    }
    if thread_id:
        photo_payload["message_thread_id"] = thread_id

    try:
        with open(image_path, "rb") as img:
            files = {"photo": img}
            res = requests.post(photo_url, data=photo_payload, files=files, timeout=30)
            if res.status_code != 200:
                print(f"[Telegram] Fehler beim Foto-Upload: {res.text}")
            else:
                print(f"[Telegram] Performance-Chart erfolgreich an Topic {thread_id} gesendet.")
    except Exception as e:
        print(f"[Telegram Foto Exception] {e}")

    # 2. Ausführlichen KI-Bericht als Textnachricht senden (erlaubt bis zu 4.096 Zeichen)
    msg_url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    msg_payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": recap_text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True
    }
    if thread_id:
        msg_payload["message_thread_id"] = thread_id

    try:
        res2 = requests.post(msg_url, json=msg_payload, timeout=25)
        if res2.status_code != 200:
            print(f"[Telegram] Fehler beim Text-Recap: {res2.text}")
        else:
            print(f"[Telegram] Ausführlicher Recap erfolgreich an Topic {thread_id} gesendet.")
    except Exception as e:
        print(f"[Telegram Text Exception] {e}")

def main():
    timeframe = sys.argv[1].lower() if len(sys.argv) > 1 else "weekly"
    print(f"Starte JARVIS Analytics Engine ({timeframe})...")

    bets = load_all_history()
    recent_bets = filter_bets(bets, timeframe=timeframe)

    if not recent_bets:
        print(f"Keine abgerechneten Wetten im Zeitraum ({timeframe}) gefunden.")
        return

    metrics = compute_metrics(recent_bets)
    if not metrics:
        print("Keine validen Metriken ermittelbar.")
        return

    chart_file = generate_performance_chart(recent_bets, metrics, timeframe)
    recap_text = generate_ai_recap(metrics, timeframe)
    send_telegram_recap(metrics, recap_text, chart_file, timeframe)

if __name__ == "__main__":
    main()
