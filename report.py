"""Отчёты instawatch: ежедневный пульс и еженедельный разбор."""
import argparse
import subprocess
import sys
from datetime import timedelta
from pathlib import Path

import common
import fetch
import telegram


def format_ratio(value, median):
    if value is None or median is None or median == 0:
        return None
    return value / median


def post_age_days(post, now):
    return (now - common.parse_ts(post["posted_at"])).total_seconds() / 86400


def preview(caption, limit=120):
    text = " ".join((caption or "").split())
    return text[:limit] + ("…" if len(text) > limit else "")


def pulse_signals(con, cfg, now=None):
    now = now or common.now_utc()
    k = cfg["pulse_multiplier"]
    signals = []
    for account in cfg["accounts"]:
        account = account.lower()
        med = common.account_medians(con, account, cfg, now=now)
        for post in common.latest_metrics(con, account):
            if post_age_days(post, now) > cfg["pulse_max_age_days"]:
                continue
            if common.was_alerted(con, post["post_id"]):
                continue
            likes_hidden = post["likes"] is None
            if likes_hidden:
                ratio, metric = format_ratio(post["comments"], med["comments"]), "comments"
            else:
                ratio, metric = format_ratio(post["likes"], med["likes"]), "likes"
            if ratio is not None and ratio >= k:
                signals.append({**post, "ratio": ratio, "metric": metric,
                                "likes_hidden": likes_hidden})
    return signals


def format_pulse(signals):
    lines = ["🔥 Инстаграм-пульс: залетает выше медианы", ""]
    for s in signals:
        metric_ru = "комментам" if s["metric"] == "comments" else "лайкам"
        hidden = " (лайки скрыты)" if s["likes_hidden"] else ""
        likes = "—" if s["likes"] is None else s["likes"]
        lines.append("@{}{} — ×{:.1f} от медианы по {}".format(
            s["account"], hidden, s["ratio"], metric_ru))
        stats = "❤️ {} 💬 {}".format(likes, s["comments"])
        if s.get("views"):
            stats += " ▶️ {}".format(s["views"])
        lines.append(stats)
        if preview(s["caption"]):
            lines.append(preview(s["caption"]))
        lines.append(s["permalink"])
        lines.append("")
    return "\n".join(lines).strip()


TOKEN_EXPIRED_MSG = (
    "⚠️ instawatch: токен Meta Graph API протух (он живёт 60 дней).\n"
    "Скажи Claude: «обнови токен инстаграма» — он проведёт по шагам."
)


def main():
    ap = argparse.ArgumentParser(description="Отчёты instawatch")
    ap.add_argument("mode", choices=["pulse", "weekly"])
    ap.add_argument("--send", action="store_true", help="отправить в Telegram")
    ap.add_argument("--no-fetch", action="store_true", help="только по данным из базы")
    args = ap.parse_args()

    cfg, env, con = common.load_config(), common.load_env(), common.connect()

    if not args.no_fetch:
        limit = cfg["fetch_limit_pulse"] if args.mode == "pulse" else cfg["fetch_limit_weekly"]
        try:
            fetch.run_fetch(limit, cfg=cfg, env=env, con=con)
        except fetch.TokenExpiredError:
            if args.send and env.get("TELEGRAM_BOT_TOKEN"):
                telegram.send(TOKEN_EXPIRED_MSG, env["TELEGRAM_BOT_TOKEN"],
                              env["TELEGRAM_CHAT_ID"])
            print(TOKEN_EXPIRED_MSG, file=sys.stderr)
            sys.exit(1)

    if args.mode == "pulse":
        signals = pulse_signals(con, cfg)
        if not signals:
            print("Тихо: сигналов нет.")
            return
        text = format_pulse(signals)
        common.mark_alerted(con, [s["post_id"] for s in signals])
    else:
        text = build_weekly(con, cfg)  # Task 8

    print(text)
    if args.send and env.get("TELEGRAM_BOT_TOKEN"):
        telegram.send(text, env["TELEGRAM_BOT_TOKEN"], env["TELEGRAM_CHAT_ID"])


if __name__ == "__main__":
    main()
