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
    "Euro-Hoops": "euro_history.json",
    "US College": "college_history.json",
    "Darts": "darts_history.json"
}

SPORT_ALIAS_MAP = {
    "soccer": "Soccer",
    "nba": "NBA",
    "nhl": "NHL",
    "nfl": "NFL",
    "darts": "Darts",
    "darts_pdc_world_championship": "Darts",
    "darts_premier_league": "Darts",
    "basketball_euroleague": "Euro-Hoops",
    "icehockey_germany_del": "Euro-Hoops",
    "icehockey_sweden_shl": "Euro-Hoops",
    "euro-hoops & ice": "Euro-Hoops",
    "euro-hoops": "Euro-Hoops",
    "ncaaf": "US College",
    "ncaab": "US College",
    "americanfootball_ncaaf": "US College",
    "basketball_ncaab": "US College",
    "us college": "US College",
    "college": "US College"
}

SPORT_ICONS = {
    "Soccer": "⚽",
    "NBA": "🏀",
    "NHL": "🏒",
    "NFL": "🏈",
    "Euro-Hoops": "🇪🇺",
    "US College": "🎓",
    "Darts": "🎯"
}

def make_mini_bar(percentage, segments=5):
    clamped = max(0.0, min(100.0, float(percentage)))
    filled = int(round((clamped / 100.0) * segments))
    empty = segments - filled
    return f"[{'🟩' * filled}{'⬜' * empty}]"

def normalize_sport_name(sport_raw, fallback="Sonstige"):
    if not sport_raw:
        return fallback
    key = str(sport_raw).strip().lower()
    return SPORT_ALIAS_MAP.get(key, str(sport_raw).strip())

def load_all_history():
    all_bets = []
    for default_sport, filename in SPORT_FILES.items():
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
                            raw_sport = item_copy.get("sport") or default_sport
                            item_copy["sport"] = normalize_sport_name(raw_sport, default_sport)
                            all_bets.append(item_copy)
            except Exception as e:
                print(f"[Warnung] Konnte {filename} nicht laden: {e}")
    return all_bets

def filter_bets(bets, timeframe="weekly"):
    now = datetime.now(timezone.utc)
    start_date = now - timedelta(days=30 if timeframe == "monthly" else 7)

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
    if not bets:
        return None

    wins = sum(1 for b in bets if str(b.get("status", "")).upper() in ["WON", "HIT", "WIN"])
    losses = sum(1 for b in bets if str(b.get("status", "")).upper() in ["LOST", "MISS", "LOSS"])
    pushes = sum(1 for b in bets if str(b.get("status", "")).upper() in ["PUSH", "VOID"])
    
    by_sport = {}
    for b in bets:
        sport = normalize_sport_name(b.get("sport"), "Sonstige")
        if sport not in by_sport:
            by_sport[sport] = {"total": 0, "wins": 0, "losses": 0}

        status = str(b.get("status", "")).upper()
        by_sport[sport]["total"] += 1
        if status in ["WON", "HIT", "WIN"]:
            by_sport[sport]["wins"] += 1
        elif status in ["LOST", "MISS", "LOSS"]:
            by_sport[sport]["losses"] += 1

    total_valid = wins + losses
    win_rate = (wins / total_valid * 100) if total_valid > 0 else 0.0

    return {
        "total_bets": len(bets),
        "wins": wins,
        "losses": losses,
        "pushes": pushes,
        "win_rate": win_rate,
        "by_sport": by_sport
    }

def generate_performance_chart(metrics, timeframe):
    plt.style.use("dark_background")
    fig, ax = plt.subplots(figsize=(8, 4))

    sports = sorted(
        list(metrics["by_sport"].keys()),
        key=lambda s: (metrics["by_sport"][s]["wins"] / metrics["by_sport"][s]["total"]) if metrics["by_sport"][s]["total"] > 0 else 0,
        reverse=False
    )
    
    wins = [metrics["by_sport"][s]["wins"] for s in sports]
    totals = [metrics["by_sport"][s]["total"] for s in sports]
    losses = [totals[i] - wins[i] for i in range(len(sports))]

    y_pos = range(len(sports))
    ax.barh(y_pos, wins, color="#00ffcc", height=0.5, label="Gewonnen (Won)")
    ax.barh(y_pos, losses, left=wins, color="#ff3366", height=0.5, label="Verloren (Lost)")

    ax.set_yticks(y_pos)
    ax.set_yticklabels(sports, fontsize=10, fontweight="bold", color="#ffffff")
    ax.set_xlabel("Anzahl Picks", color="#aaaaaa")
    ax.set_title(f"JARVIS Treffer nach Sportart ({timeframe.upper()})", fontsize=11, fontweight="bold", color="#ffffff")
    ax.legend(loc="lower right")
    ax.grid(True, linestyle=":", alpha=0.3, axis="x")

    for i in y_pos:
        w = wins[i]
        t = totals[i]
        pct = (w / t * 100) if t > 0 else 0
        ax.annotate(f"{w}/{t} ({pct:.0f}%)",
                    xy=(t + 0.3, i),
                    va="center", color="#ffffff", fontsize=9, fontweight="bold")

    plt.tight_layout()
    chart_path = "performance_recap.png"
    plt.savefig(chart_path, dpi=200, bbox_inches="tight")
    plt.close()
    return chart_path

def build_simple_caption(metrics, timeframe):
    now_str = datetime.now(LOCAL_TZ).strftime("%d.%m.%Y")
    label = "WÖCHENTLICHER" if timeframe == "weekly" else "MONATLICHER"
    total_bar = make_mini_bar(metrics["win_rate"], segments=10)

    # Sortierung nach Trefferquote absteigend
    sorted_sports = sorted(
        metrics["by_sport"].items(),
        key=lambda x: (x[1]["wins"] / x[1]["total"] if x[1]["total"] > 0 else 0),
        reverse=True
    )

    sport_lines = []
    for sport, data in sorted_sports:
        if data["total"] > 0:
            icon = SPORT_ICONS.get(sport, "📌")
            pct = (data["wins"] / data["total"] * 100)
            bar = make_mini_bar(pct, segments=5)
            # Saubere Formatierung ohne Umbrüche
            sport_lines.append(f"{icon} <b>{sport}:</b> <code>{data['wins']:>2}/{data['total']:<2}</code> ({pct:>3.0f}%) {bar}")

    sports_text = "\n".join(sport_lines) if sport_lines else "• Keine Daten"

    caption = f"""📊 <b>JARVIS {label} RECAP</b>
🗓️ <i>Stand: {now_str}</i>
━━━━━━━━━━━━━━━━━━━━
🎯 <b>Gesamt-Treffer:</b> <b>{metrics['wins']}/{metrics['total_bets']}</b> ({metrics['win_rate']:.1f}%)
{total_bar}
📦 <b>Bilanz:</b> <code>{metrics['wins']} Won • {metrics['losses']} Lost • {metrics['pushes']} Void</code>

━━━━━━━━━━━━━━━━━━━━
🏆 <b>Sportarten-Trefferquote:</b>
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
                print(f"[Telegram] Recap erfolgreich an Topic {thread_id} gesendet.")
    except Exception as e:
        print(f"[Telegram Exception] {e}")

def main():
    timeframe = sys.argv[1].lower() if len(sys.argv) > 1 else "weekly"
    print(f"Starte einfache Analytics Engine ({timeframe})...")

    bets = load_all_history()
    recent_bets = filter_bets(bets, timeframe=timeframe)

    if not recent_bets:
        print(f"Keine Wetten im Zeitraum ({timeframe}) gefunden.")
        return

    metrics = compute_metrics(recent_bets)
    if not metrics:
        print("Keine validen Metriken ermittelbar.")
        return

    chart_file = generate_performance_chart(metrics, timeframe)
    caption = build_simple_caption(metrics, timeframe)
    send_telegram_recap(caption, chart_file)

if __name__ == "__main__":
    main()
