"""Отчёты instawatch: ежедневный пульс и еженедельный разбор."""
import argparse
import subprocess
import sys
from datetime import timedelta
from pathlib import Path

import requests

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


PLATFORM_TITLES = {"instagram": "📸 Instagram", "telegram": "✈️ Telegram"}
METRIC_RU = {"likes": "лайкам", "comments": "комментам", "views": "просмотрам"}


def stats_line(p):
    if p["platform"] == "telegram":
        stats = "👁 {}".format(p["views"] if p["views"] is not None else "—")
        if p["likes"] is not None:
            stats += " ❤️ {}".format(p["likes"])
        return stats
    likes = "—" if p["likes"] is None else p["likes"]
    stats = "❤️ {} 💬 {}".format(likes, p["comments"])
    if p.get("views"):
        stats += " ▶️ {}".format(p["views"])
    return stats


def pulse_signals(con, cfg, now=None):
    now = now or common.now_utc()
    k = cfg["pulse_multiplier"]
    signals = []
    for platform, account in common.active_accounts(cfg):
        med = common.account_medians(con, account, cfg, now=now, platform=platform)
        for post in common.latest_metrics(con, account, platform=platform):
            if post_age_days(post, now) > cfg["pulse_max_age_days"]:
                continue
            if common.was_alerted(con, post["post_id"]):
                continue
            likes_hidden = False
            if platform == "telegram":
                ratio, metric = format_ratio(post["views"], med["views"]), "views"
            else:
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
    lines = ["🔥 Пульс: залетает выше медианы", ""]
    platforms = {s["platform"] for s in signals}
    for platform in ("instagram", "telegram"):
        group = [s for s in signals if s["platform"] == platform]
        if not group:
            continue
        if len(platforms) > 1:
            lines.append(PLATFORM_TITLES[platform])
            lines.append("")
        for s in group:
            hidden = " (лайки скрыты)" if s["likes_hidden"] else ""
            lines.append("@{}{} — ×{:.1f} от медианы по {}".format(
                s["account"], hidden, s["ratio"], METRIC_RU[s["metric"]]))
            lines.append(stats_line(s))
            if preview(s["caption"]):
                lines.append(preview(s["caption"]))
            lines.append(s["permalink"])
            lines.append("")
    return "\n".join(lines).strip()


TOKEN_EXPIRED_MSG = (
    "⚠️ instawatch: токен Meta Graph API протух (он живёт 60 дней).\n"
    "Скажи Claude: «обнови токен инстаграма» — он проведёт по шагам."
)

FETCH_ERROR_MSG = (
    "⚠️ instawatch: не удалось собрать данные (проблема с сетью, токеном или "
    "кредитами источника). Проверь .env и баланс Apify."
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
            fetch.run_fetch(limit, cfg=cfg, env=env, con=con, subscribers=(args.mode == "weekly"))
        except fetch.TokenExpiredError:
            if args.send and env.get("TELEGRAM_BOT_TOKEN"):
                telegram.send(TOKEN_EXPIRED_MSG, env["TELEGRAM_BOT_TOKEN"],
                              env["TELEGRAM_CHAT_ID"])
            print(TOKEN_EXPIRED_MSG, file=sys.stderr)
            sys.exit(1)
        except (fetch.ConfigError, requests.RequestException) as exc:
            msg = str(exc) if isinstance(exc, fetch.ConfigError) else FETCH_ERROR_MSG
            if args.send and env.get("TELEGRAM_BOT_TOKEN"):
                telegram.send(msg, env["TELEGRAM_BOT_TOKEN"], env["TELEGRAM_CHAT_ID"])
            print(msg, file=sys.stderr)
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


def weekly_data(con, cfg, now=None):
    now = now or common.now_utc()
    week_ago = now - timedelta(days=7)
    active = {a.lower() for a in cfg["accounts"]}
    per_account, quiet = {}, []
    for account in cfg["accounts"]:
        account = account.lower()
        med = common.account_medians(con, account, cfg, now=now)
        posts = [p for p in common.latest_metrics(con, account)
                 if common.parse_ts(p["posted_at"]) >= week_ago]
        for p in posts:
            p["like_ratio"] = format_ratio(p["likes"], med["likes"])
            p["comment_ratio"] = format_ratio(p["comments"], med["comments"])
            p["fresh"] = post_age_days(p, now) < cfg["median_min_age_days"]
        if posts:
            per_account[account] = posts
        else:
            quiet.append(account)
    unavailable = [dict(r) for r in con.execute(
        "SELECT account, last_error FROM account_status WHERE last_error IS NOT NULL")
        if r["account"] in active]
    unavailable_accounts = {u["account"] for u in unavailable}
    quiet = [a for a in quiet if a not in unavailable_accounts]
    return per_account, quiet, unavailable


def format_top(all_posts, key, title, emoji, n=10):
    ranked = sorted((p for p in all_posts if p[key] is not None),
                    key=lambda p: p[key], reverse=True)
    lines = ["{} {}".format(emoji, title), ""]
    for p in ranked[:n]:
        growing = " ⏳ ещё растёт" if p["fresh"] else ""
        likes = "—" if p["likes"] is None else p["likes"]
        lines.append("@{} — ×{:.1f} от медианы{}".format(p["account"], p[key], growing))
        stats = "❤️ {} 💬 {}".format(likes, p["comments"])
        if p.get("views"):
            stats += " ▶️ {}".format(p["views"])
        lines.append(stats)
        if preview(p["caption"]):
            lines.append(preview(p["caption"]))
        lines.append(p["permalink"])
        lines.append("")
    return lines


def claude_summary(per_account, prompt_path):
    """Тематическая выжимка недели через headless Claude. Любой сбой → None."""
    digest = []
    for account, posts in per_account.items():
        digest.append("## @{}".format(account))
        digest.extend("- " + preview(p["caption"], 500) for p in posts)
    prompt = Path(prompt_path).read_text(encoding="utf-8") + "\n\n" + "\n".join(digest)
    try:
        result = subprocess.run(
            ["claude", "-p", "--output-format", "text"],
            input=prompt, capture_output=True, text=True, timeout=300,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        pass
    return None


def build_weekly(con, cfg, now=None):
    per_account, quiet, unavailable = weekly_data(con, cfg, now=now)
    all_posts = [p for posts in per_account.values() for p in posts]
    lines = ["📊 Инстаграм за неделю", ""]
    if per_account:
        summary = claude_summary(per_account, common.ROOT / "prompts" / "weekly.md")
        if summary:
            lines += ["🧠 О чём писали", "", summary, ""]
    if all_posts:
        lines += format_top(all_posts, "like_ratio", "Топ по лайкам (×N от медианы аккаунта)", "❤️")
        lines += format_top(all_posts, "comment_ratio", "Топ по комментам (×N от медианы аккаунта)", "💬")
    else:
        lines.append("За неделю ни одного нового поста.")
    if quiet:
        lines.append("😴 Молчали: " + ", ".join("@{}".format(a) for a in quiet))
    if unavailable:
        lines.append("⚠️ Не удалось получить: " + "; ".join(
            "@{} ({})".format(u["account"], u["last_error"]) for u in unavailable))
    return "\n".join(lines).strip()


if __name__ == "__main__":
    main()
