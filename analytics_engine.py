import os
import sys
import json
import glob
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
import requests
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

LOCAL_TZ = ZoneInfo("Europe/Berlin")

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "").strip()

TELEGRAM_ANALYTICS_THREAD = (
    os.environ.get("TELEGRAM_ANALYTICS_THREAD_ID", "").strip()
    or os.environ.get("TELEGRAM_THREAD_ID", "").strip()
)

def make_progress_bar(percentage, segments=10):
    clamped = max(0.0, min(100.0, float(percentage)))
    filled = int(round((clamped / 100.0) * segments))
    empty = segments - filled
    return f"[{'🟩' * filled}{'⬜' * empty}]"

def send_telegram_photo(caption, image_path, thread_id=None):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("[Telegram] Fehler: Credentials fehlen.")
        return

    tid = thread_id or TELEGRAM_ANALYTICS_THREAD
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendPhoto"
    
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "caption": caption,
        "parse_mode": "HTML"
    }
    if tid:
        payload["message_thread_id"] = int(tid)

    try:
        with open(image_path, "rb") as img:
            res = requests.post(url, data=payload, files={"photo": img}, timeout=30)
            if res.status_code != 200:
                print(f"[Telegram] Fehler beim Senden des Fotos: {res.text}")
            else:
                print("[Telegram] Chart erfolgreich gesendet.")
    except Exception as e:
        print(f"[Telegram] Exception beim Foto-Upload: {e}")

def load_all_settled_bets():
    """Liest alle abgeschlossenen Wetten aus *_history.json."""
    all_bets = []
    
    history_files = [
        ("Euro-Hoops/Ice", "euro_history.json"),
        ("US College", "college_history.json"),
        ("Darts", "darts_history.json"),
        ("Soccer", "soccer_history.json"),
        ("NBA", "nba_history.json"),
        ("NHL", "nhl_history.json"),
        ("NFL", "nfl_history.json")
    ]
    
    for category, filepath in history_files:
        if os.path.exists(filepath):
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    content = json.load(f)
                    settled = content.get("settled", []) if isinstance(content, dict) else content
                    if isinstance(settled, list):
                        for b in settled:
                            if isinstance(b, dict):
                                b["category"] = category
                                all_bets.append(b)
            except Exception as e:
                print(f"Fehler beim Laden von {filepath}: {e}")

    return all_bets

def generate_report(timeframe_days=7, title_tag="WÖCHENTLICHER"):
    bets = load_all_settled_bets()
    if not bets:
        print("Keine Historien-Daten vorhanden.")
        return

    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=timeframe_days)

    filtered_bets = []
    for b in bets:
        d_str = b.get("date", "")
        if not d_str:
            continue
        try:
            if "-" in d_str:
                dt = datetime.strptime(d_str[:10], "%Y-%m-%d").replace(tzinfo=timezone.utc)
            elif "." in d_str:
                dt = datetime.strptime(d_str[:10], "%d.%m.%Y").replace(tzinfo=timezone.utc)
            else:
                continue
            if dt >= cutoff:
                b["parsed_dt"] = dt
                filtered_bets.append(b)
        except Exception:
            continue

    if not filtered_bets:
        print(f"Keine Wetten im Zeitraum der letzten {timeframe_days} Tage gefunden.")
        return

    filtered_bets.sort(key=lambda x: x["parsed_dt"])

    cat_stats = {}
    cum_profit = 0.0
    timeline_dates = []
    timeline_profits = []

    total_staked = 0.0
    total_returned = 0.0
    total_won = 0
    total_void = 0

    for b in filtered_bets:
        cat = b.get("category", "Allgemein")
        if cat not in cat_stats:
            cat_stats[cat] = {"staked": 0.0, "returned": 0.0, "won": 0, "total": 0, "void": 0}

        try:
            odds = float(str(b.get("odds", "1.0")).replace(",", "."))
        except ValueError:
            odds = 1.0

        stake = float(b.get("stake", 1.0))
        status = b.get("status", "LOST")

        cat_stats[cat]["staked"] += stake
        cat_stats[cat]["total"] += 1
        total_staked += stake

        if status == "WON":
            ret = stake * odds
            cat_stats[cat]["returned"] += ret
            cat_stats[cat]["won"] += 1
            total_returned += ret
            total_won += 1
            cum_profit += (ret - stake)
        elif status == "VOID":
            cat_stats[cat]["returned"] += stake
            cat_stats[cat]["void"] += 1
            total_returned += stake
            total_void += 1
        else:
            cum_profit -= stake

        timeline_dates.append(b["parsed_dt"])
        timeline_profits.append(cum_profit)

    net_profit = total_returned - total_staked
    roi = (net_profit / total_staked * 100) if total_staked > 0 else 0.0
    active_bets = len(filtered_bets) - total_void
    hit_rate = (total_won / active_bets * 100) if active_bets > 0 else 0.0
    sign = "+" if net_profit >= 0 else ""

    plt.style.use("dark_background")
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 5), facecolor="#0e1117")

    ax1.set_facecolor("#161b22")
    line_color = "#00e676" if net_profit >= 0 else "#ff5252"
    ax1.plot(timeline_dates, timeline_profits, color=line_color, linewidth=2.5, marker="o", markersize=4)
    ax1.axhline(0, color="#ffffff", linestyle="--", alpha=0.3)
    ax1.set_title(f"Bankroll Equity Curve ({title_tag})", fontsize=12, fontweight="bold", pad=12, color="#ffffff")
    ax1.set_ylabel("Net Profit (Units)", fontsize=10, color="#8b949e")
    ax1.grid(True, linestyle=":", alpha=0.2, color="#8b949e")
    ax1.xaxis.set_major_formatter(mdates.DateFormatter("%d.%m"))

    ax2.set_facecolor("#161b22")
    categories = list(cat_stats.keys())
    cat_profits = [cat_stats[c]["returned"] - cat_stats[c]["staked"] for c in categories]
    bar_colors = ["#00e676" if p >= 0 else "#ff5252" for p in cat_profits]

    bars = ax2.barh(categories, cat_profits, color=bar_colors, height=0.55)
    ax2.axvline(0, color="#ffffff", linestyle="--", alpha=0.3)
    ax2.set_title("P&L nach Sportart (Units)", fontsize=12, fontweight="bold", pad=12, color="#ffffff")
    ax2.set_xlabel("Units", fontsize=10, color="#8b949e")
    ax2.grid(True, linestyle=":", alpha=0.2, color="#8b949e")

    for bar in bars:
        w = bar.get_width()
        sign_bar = "+" if w >= 0 else ""
        ax2.annotate(f"{sign_bar}{w:.2f}U",
                     xy=(w, bar.get_y() + bar.get_height() / 2),
                     xytext=(5 if w >= 0 else -35, 0),
                     textcoords="offset points",
                     ha="left", va="center", color="#ffffff", fontsize=9, fontweight="bold")

    plt.tight_layout()
    chart_filename = f"analytics_{timeframe_days}d.png"
    plt.savefig(chart_filename, dpi=180, facecolor=fig.get_facecolor(), bbox_inches="tight")
    plt.close()

    caption = f"📈 <b>JARVIS QUANT {title_tag} META-RECAP</b>\n"
    caption += f"<i>Performance & Equity-Report der letzten {timeframe_days} Tage</i>\n\n"
    caption += "━━━━━━━━━━━━━━━━━━━━\n"
    caption += f"• <b>Gesamt-Tipps:</b>  {total_won}/{len(filtered_bets)} ({hit_rate:.1f}%) {make_progress_bar(hit_rate)}\n"
    caption += f"• <b>Units Staked:</b>  {total_staked:.2f} U ➔ Return: {total_returned:.2f} U\n"
    caption += f"• <b>Netto-Profit:</b>  <b>{sign}{net_profit:.2f} Units</b>\n"
    caption += f"• <b>Yield / ROI:</b>   <b>{sign}{roi:.1f}%</b>\n\n"
    caption += "<b>📊 AUFSCHLÜSSELUNG NACH SPORTARTEN:</b>\n"

    for c, stats in cat_stats.items():
        c_prof = stats["returned"] - stats["staked"]
        c_sign = "+" if c_prof >= 0 else ""
        c_roi = (c_prof / stats["staked"] * 100) if stats["staked"] > 0 else 0.0
        caption += f"▫️ <b>{c}:</b> {c_sign}{c_prof:.2f}U ({c_sign}{c_roi:.1f}% ROI | {stats['won']}/{stats['total']})\n"

    caption += "━━━━━━━━━━━━━━━━━━━━"

    send_telegram_photo(caption, chart_filename)
    if os.path.exists(chart_filename):
        os.remove(chart_filename)

if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "weekly"
    if mode == "monthly":
        generate_report(timeframe_days=30, title_tag="MONATLICHER")
    else:
        generate_report(timeframe_days=7, title_tag="WÖCHENTLICHER")
