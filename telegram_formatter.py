import os
import requests
from typing import Dict, List, Optional, Any

# Exaktes Mapping passend zu deinen GitHub Repository Secrets
SPORT_CONFIG = {
    "soccer": {
        "name": "SOCCER",
        "icon": "⚽",
        "secret_key": "TELEGRAM_THREAD_SOCCER"
    },
    "nba": {
        "name": "BASKETBALL (NBA)",
        "icon": "🏀",
        "secret_key": "TELEGRAM_THREAD_NBA"
    },
    "nhl": {
        "name": "ICE HOCKEY (NHL)",
        "icon": "🏒",
        "secret_key": "TELEGRAM_THREAD_NHL"
    },
    "nfl": {
        "name": "AMERICAN FOOTBALL (NFL)",
        "icon": "🏈",
        "secret_key": "TELEGRAM_THREAD_NFL"
    },
    "tennis": {
        "name": "TENNIS",
        "icon": "🎾",
        "secret_key": "TELEGRAM_TENNIS_THREAD_ID"
    },
    "darts": {
        "name": "DARTS",
        "icon": "🎯",
        "secret_key": "TELEGRAM_DARTS_THREAD_ID"
    },
    "euro": {
        "name": "EURO LEAGUES",
        "icon": "🏆",
        "secret_key": "TELEGRAM_EURO_THREAD_ID"
    },
    "college": {
        "name": "COLLEGE SPORTS (NCAA)",
        "icon": "🎓",
        "secret_key": "TELEGRAM_COLLEGE_THREAD_ID"
    },
    "moneyrace": {
        "name": "MONEYRACE",
        "icon": "🚀",
        "secret_key": "TELEGRAM_MONEYRACE_THREAD_ID"
    },
    "analytics": {
        "name": "ANALYTICS",
        "icon": "📈",
        "secret_key": "TELEGRAM_ANALYTICS_THREAD_ID"
    }
}

def shorten_tag(tag: str) -> str:
    t = str(tag).strip().upper()
    mapping = {
        "CONSERVATIVE 2-LEG BANKER": "BANKER",
        "BALANCED VALUE ACCA": "BALANCED",
        "HYBRID QUANT MULTI": "HYBRID",
        "GOALS & BTTS VALUE ACCA": "GOALS",
        "PLAYER PROP SPOTLIGHT / MULTI-TICKET": "PROPS",
        "PLAYER PROPS MULTI": "PROPS",
        "PLAYER PROP MULTI": "PROPS",
        "HIGH VALUE ACCA": "VALUE",
        "POTD": "POTD",
        "⭐ POTD": "POTD"
    }
    return mapping.get(t, t)

def get_ticket_icon(ticket_name: str) -> str:
    name = ticket_name.upper()
    if "POTD" in name:
        return "⭐"
    if "BANKER" in name:
        return "🔥"
    if "BALANCED" in name or "VALUE" in name:
        return "⚖️"
    if "PROP" in name:
        return "🎯"
    if "GOAL" in name or "OVER" in name:
        return "⚽"
    if "HYBRID" in name:
        return "⚡"
    return "📌"

def format_picks_first_post(
    sport: str,
    date_str: str,
    potd: Optional[Dict[str, Any]] = None,
    tickets: Optional[List[Dict[str, Any]]] = None,
    analyses: Optional[Any] = None,
    max_char_limit: int = 4000
) -> str:
    cfg = SPORT_CONFIG.get(sport.lower(), {
        "name": sport.upper(),
        "icon": "🎯",
        "secret_key": "TELEGRAM_THREAD_ID"
    })

    header = (
        f"{cfg['icon']} <b>JARVIS {cfg['name']} — TAGESEMPFEHLUNGEN ({date_str})</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"📋 <b>WETTSCHEINE AUF EINEN BLICK:</b>\n"
    )

    picks_block_lines = []

    # 1. POTD (Pick of the Day) ganz oben
    if potd and isinstance(potd, dict):
        match = potd.get("match", "").strip()
        pick = potd.get("pick", "").strip()
        player = potd.get("player")
        odds = float(potd.get("odds", 1.80))
        stake = float(potd.get("stake", 1.50))

        display_pick = f"{player}: {pick}" if player else pick
        picks_block_lines.append(f"⭐ <b>POTD (<code>{stake:.2f}u</code> | <code>@{odds:.2f}</code>)</b>")
        picks_block_lines.append(f"• <b>{match}</b> ➔ <i>{display_pick}</i>\n")

    # 2. Tickets & Kombis
    if tickets:
        for t in tickets:
            t_name = shorten_tag(t.get("ticket_name", "Kombi"))
            t_odds = float(t.get("odds", 2.00))
            stake = float(t.get("stake", 1.00))
            icon = get_ticket_icon(t_name)

            picks_block_lines.append(f"{icon} <b>{t_name} (<code>{stake:.2f}u</code> | Gesamt: <code>@{t_odds:.2f}</code>)</b>")

            raw_picks = t.get("picks", [])
            for p in raw_picks:
                if isinstance(p, dict):
                    m = p.get("match", "").strip()
                    pick_text = p.get("pick", "").strip()
                    player = p.get("player")
                    if player:
                        picks_block_lines.append(f"• {player} ➔ <i>{pick_text}</i>")
                    else:
                        picks_block_lines.append(f"• {m} ➔ <i>{pick_text}</i>")
                elif isinstance(p, str):
                    picks_block_lines.append(f"• {p}")

            picks_block_lines.append("")

    picks_block = "\n".join(picks_block_lines).strip()

    # 3. Analysen & Deep Dive
    analysis_block_lines = [
        "━━━━━━━━━━━━━━━━━━━━",
        "📊 <b>ANALYSEN & MODELL-LOGIK (DEEP DIVE)</b>\n"
    ]

    if isinstance(analyses, list):
        for a in analyses:
            if isinstance(a, dict):
                title = a.get("title", "").strip()
                edge = a.get("edge", "").strip()
                logic = a.get("logic", "").strip()
                analysis_block_lines.append(f"🔎 <b>{title}</b>")
                if edge:
                    analysis_block_lines.append(f"• <b>Edge:</b> <i>{edge}</i>")
                if logic:
                    analysis_block_lines.append(f"• <b>Logik:</b> {logic}")
                analysis_block_lines.append("")
            elif isinstance(a, str) and a.strip():
                analysis_block_lines.append(a.strip())
                analysis_block_lines.append("")
    elif isinstance(analyses, str) and analyses.strip():
        analysis_block_lines.append(analyses.strip())

    analysis_block = "\n".join(analysis_block_lines).strip()

    full_post = f"{header}\n{picks_block}\n\n{analysis_block}".strip()

    # Absicherung Telegram-Limit (4.096 Zeichen)
    if len(full_post) > max_char_limit:
        excess = len(full_post) - max_char_limit
        allowed_analysis_len = max(200, len(analysis_block) - excess - 60)
        truncated_analysis = analysis_block[:allowed_analysis_len].rsplit("\n", 1)[0]
        full_post = f"{header}\n{picks_block}\n\n{truncated_analysis}\n\n<i>[...Analysen gekürzt für Mobile-Vorschau...]</i>"

    return full_post

def format_standalone_live_ticker(
    sport: str,
    active_cards: List[str],
    pending_list: List[str]
) -> str:
    cfg = SPORT_CONFIG.get(sport.lower(), {"name": sport.upper(), "icon": "⏱️"})

    sections = [
        f"{cfg['icon']} <b>JARVIS {cfg['name']} • LIVE-TRACKER & FORTSCHRITT</b>\n"
    ]

    if active_cards:
        sections.append("\n".join(active_cards))

    if pending_list:
        separator = "\n━━━━━━━━━━━━━━━━━━━━\n" if active_cards else ""
        sections.append(f"{separator}⏳ <b>AUSSTEHEND (Startet in Kürze)</b>\n" + "\n".join(pending_list))

    ticker_body = "\n".join(sections).strip()

    if len(ticker_body) > 4000:
        ticker_body = ticker_body[:3950].rsplit("\n", 1)[0] + "\n\n<i>[...weitere Partien in Auswertung...]</i>"

    return ticker_body

def format_daily_settlement(
    sport: str,
    ticket_results: List[str],
    tickets_won: int,
    tickets_lost: int,
    tickets_push: int,
    tickets_manual: int,
    total_profit: float,
    history_file_name: str = "history.csv"
) -> str:
    cfg = SPORT_CONFIG.get(sport.lower(), {"name": sport.upper(), "icon": "🏁"})
    net_sign = "+" if total_profit > 0 else ""
    profit_color = "🟢" if total_profit > 0 else ("🔴" if total_profit < 0 else "⚪")

    push_str = f" - {tickets_push}P" if tickets_push > 0 else ""
    manual_str = f" ({tickets_manual} offen/Props)" if tickets_manual > 0 else ""
    tickets_summary = "\n".join(ticket_results)

    summary_msg = (
        f"{cfg['icon']} <b>JARVIS {cfg['name']} — TAGESABSCHLUSS</b>\n\n"
        f"<b>Ticket-Auswertung:</b>\n"
        f"{tickets_summary}\n\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"📊 <b>Bilanz Tickets:</b> <b>{tickets_won}W - {tickets_lost}L{push_str}</b>{manual_str}\n"
        f"{profit_color} <b>Netto-Ergebnis:</b> <b>{net_sign}{total_profit:.2f} Units</b>\n\n"
        f"📁 <i>Alle Tickets wurden in {history_file_name} archiviert.</i>"
    )
    return summary_msg

def send_to_sport_channel(text: str, sport: str, reply_to: Optional[int] = None) -> Optional[int]:
    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()

    if not bot_token or not chat_id:
        print(f"[{sport.upper()}] Fehler: TELEGRAM_BOT_TOKEN oder TELEGRAM_CHAT_ID fehlt.")
        return None

    cfg = SPORT_CONFIG.get(sport.lower(), {})
    secret_key = cfg.get("secret_key", "TELEGRAM_THREAD_ID")
    thread_id = os.environ.get(secret_key, "").strip()

    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True
    }

    if thread_id:
        payload["message_thread_id"] = int(thread_id)
    if reply_to:
        payload["reply_to_message_id"] = int(reply_to)

    try:
        res = requests.post(url, json=payload, timeout=15)
        if res.status_code == 200:
            return res.json().get("result", {}).get("message_id")
        print(f"[{sport.upper()}] Telegram Send-Fehler ({res.status_code}): {res.text}")
    except Exception as e:
        print(f"[{sport.upper()}] Telegram Send Exception: {e}")

    return None

def edit_sport_channel_message(message_id: int, text: str) -> bool:
    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()

    if not bot_token or not chat_id or not message_id:
        return False

    url = f"https://api.telegram.org/bot{bot_token}/editMessageText"
    payload = {
        "chat_id": chat_id,
        "message_id": int(message_id),
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True
    }

    try:
        res = requests.post(url, json=payload, timeout=15)
        if res.status_code == 200 or "message is not modified" in res.text:
            return True
        payload.pop("parse_mode", None)
        res2 = requests.post(url, json=payload, timeout=15)
        return res2.status_code == 200 or "message is not modified" in res2.text
    except Exception as e:
        print(f"[Telegram Edit Exception]: {e}")
        return False
