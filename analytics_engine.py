import os
import sys
import json
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
import requests
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

LOCAL_TZ = ZoneInfo("Europe/Berlin")

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
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
                    items_list = []
                    if isinstance(data, list):
                        items_list = data
                    elif isinstance(data, dict):
                        if "settled" in data and isinstance(data["settled"], list):
                            items_list = data["settled"]
                        else:
                            for k, v in data.items():
                                if isinstance(v, list):
                                    items_list.extend(v)

                    for item in items_list:
                        if isinstance(item, dict):
                            item_copy = dict(item)
                            item_copy.setdefault("sport", sport)
                            all_bets.append(item_copy)
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
            date_clean = str(date_str).strip()
            if "T" in date_clean:
                dt = datetime.fromisoformat(date_clean.replace("Z", "+00:00"))
            else:
                dt = datetime.strptime(date_clean[:10], "%Y-%m-%d").replace(tzinfo=timezone.utc)
            
            if dt >= start_date:
                filtered.append(b)
        except Exception:
            continue
    return filtered

def compute_metrics(bets):
    total_bets = len(bets)
    if total_bets == 0:
        return None

    wins = sum(1 for b in bets if str(b.get("status", "")).upper() in ["WON", "HIT", "WIN"])
    losses = sum(1 for b in bets if str(b.get("status", "")).upper() in ["LOST", "MISS", "LOSS"])
    pushes = sum(1 for b in bets if str(b.get("status", "")).upper() in ["PUSH", "VOID"])
    
    total_stake = 0.0
    total_profit = 0.0
    by_sport = {}
    clv_list = []

    for b in bets:
        sport = b.get("sport", "Sonstige")
        if sport not in by_sport:
            by_sport[sport] = {"bets": 0, "profit": 0.0, "stake": 0.0, "wins": 0}

        try:
            stake = float(str(b.get("stake", 1.0)).replace(",", "."))
        except (ValueError, TypeError):
            stake = 1.0

        status = str(b.get("status", "")).upper()
        
        raw_odds = b.get("odds") or b.get("price") or 1.0
        try:
            odds = float(str(raw_odds).replace(",", "."))
        except (ValueError, TypeError):
            odds = 1.0

        # Robuste P&L-Erkennung
        if "profit" in b and b["profit"] is not None:
            try:
                pnl = float(str(b["profit"]).replace(",", "."))
            except ValueError:
                pnl = 0.0
        elif "pnl" in b and b["pnl"] is not None:
            try:
                pnl = float(str(b["pnl"]).replace(",", "."))
            except ValueError:
                pnl = 0.0
        else:
            if status in ["WON", "HIT", "WIN"]:
                pnl = (odds - 1.0) * stake
            elif status in ["LOST", "MISS", "LOSS"]:
                pnl = -stake
            else:
                pnl = 0.0

        b["calculated_pnl"] = pnl
        total_stake += stake
        total_profit += pnl

        by_sport[sport]["bets"] += 1
        by_sport[sport]["profit"] += pnl
        by_sport[sport]["stake"] += stake
        if status in ["WON", "HIT", "WIN"]:
            by_sport[sport]["wins"] += 1

        if "clv" in b and b["clv"] is not None:
            try:
                clv_list.append(float(str(b["clv"]).replace(",", ".")))
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
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(13, 5))

    cumulative_pnl = [0.0]
    running = 0.0
    for b in bets:
        running += float(b.get("calculated_pnl", 0.0))
        cumulative_pnl.append(running)

    ax1.plot(cumulative_pnl, color="#00ffcc", linewidth=2.5, marker="o", markersize=3)
    ax1.axhline(0, color="#666666", linestyle="--", linewidth=1)
    ax1.set_title(f"JARVIS Equity-Kurve ({timeframe.upper()})", fontsize=11, fontweight="bold", color="#ffffff")
    ax1.set_xlabel("Abgeschlossene Wetten", color="#aaaaaa")
    ax1.set_ylabel("Profit (Units)", color="#aaaaaa")
    ax1.grid(True, linestyle=":", alpha=0.3)

    sports = list(metrics["by_sport"].keys())
    pnls = [metrics["by_sport"][s]["profit"] for s in sports]
    colors = ["#00ffcc" if p >= 0 else "#ff3366" for p in pnls]

    bars = ax2.barh(sports, pnls, color=colors, height=0.5)
    ax2.axvline(0, color="#666666", linestyle="--", linewidth=1)
    ax2.set_title("P&L nach Sportart (Units)", fontsize=11, fontweight="bold", color="#ffffff")
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

def build_compact_caption(metrics, timeframe):
    now_str = datetime.now(LOCAL_TZ).strftime("%d.%m.%Y")
    label = "WÖCHENTLICHER" if timeframe == "weekly" else "MONATLICHER"
    pnl_sign = "+" if metrics['total_profit'] >= 0 else ""
    roi_sign = "+" if metrics['roi'] >= 0 else ""
    clv_sign = "+" if metrics['avg_clv'] >= 0 else ""

    sport_lines = []
    for sport, data in metrics["by_sport"].items():
        if data["bets"] > 0:
            s_pnl = f"{'+' if data['profit'] >= 0 else ''}{data['profit']:.2f}u"
            sport_lines.append(f"• <b>{sport}:</b> {s_pnl} ({data['wins']}/{data['bets']} Treffer)")

    sports_text = "\n".join(sport_lines) if sport_lines else "• Keine Daten"

    caption = f"""📊 <b>JARVIS QUANT {label} RECAP</b> • {now_str}
━━━━━━━━━━━━━━━━━━━━
💰 <b>Net P&L:</b> <code>{pnl_sign}{metrics['total_profit']:.2f} Units</code>
📈 <b>ROI:</b> <code>{roi_sign}{metrics['roi']:.2f}%</code>
🎯 <b>Trefferquote:</b> <code>{metrics['win_rate']:.1f}%</code> ({metrics['wins']}W - {metrics['losses']}L - {metrics['pushes']}P)
⚡ <b>Avg. CLV:</b> <code>{clv_sign}{metrics['avg_clv']:.2f}%</code>

━━━━━━━━━━━━━━━━━━━━
🏆 <b>Sportarten-Übersicht:</b>
{sports_text}"""
    return caption

def send_telegram_recap(caption, image_path):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("[Telegram] FEHLER: Credentials fehlen.")
        return

    thread_id = int(TELEGRAM_ANALYTICS_THREAD) if TELEGRAM_ANALYTICS_THREAD else None
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendPhoto"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "caption": caption,
        "parse_mode": "HTML"
    }
    if thread_id:
        payload["message_thread_id"] = thread_id

    try:
        with open(image_path, "rb") as img:
            files = {"photo": img}
            res = requests.post(url, data=payload, files=files, timeout=30)
            if res.status_code != 200:
                print(f"[Telegram] Fehler: {res.text}")
            else:
                print(f"[Telegram] Kompaktes Recap-Dashboard erfolgreich an Topic {thread_id} gesendet.")
    except Exception as e:
        print(f"[Telegram Exception] {e}")

def main():
    timeframe = sys.argv[1].lower() if len(sys.argv) > 1 else "weekly"
    print(f"Starte kompakte Analytics Engine ({timeframe})...")

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
    compact_caption = build_compact_caption(metrics, timeframe)
    send_telegram_recap(compact_caption, chart_file)

if __name__ == "__main__":
    main()
