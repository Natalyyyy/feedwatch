"""Сбор постов Instagram (Apify или Meta Graph API) → SQLite."""
import argparse
import sys

import requests

import common
import fetch_tg

APIFY_URL = ("https://api.apify.com/v2/acts/apify~instagram-scraper/"
             "run-sync-get-dataset-items")
GRAPH_URL = "https://graph.facebook.com/v21.0/{ig_id}"


class TokenExpiredError(Exception):
    """Meta Graph API вернул код 190 — long-lived токен протух."""


class ConfigError(Exception):
    """Не хватает обязательного ключа в .env."""


def _require_env(env, keys):
    missing = [k for k in keys if not env.get(k)]
    if not missing:
        return
    if len(missing) == 1:
        raise ConfigError(
            "Не найден {} в .env — заполни его по образцу .env.example".format(missing[0])
        )
    raise ConfigError(
        "Не найдены {} в .env — заполни их по образцу .env.example".format(", ".join(missing))
    )


def normalize_apify(item):
    likes = item.get("likesCount")
    if likes is not None and likes < 0:  # -1 = лайки скрыты
        likes = None
    return {
        "post_id": item["shortCode"],
        "account": item["ownerUsername"].lower(),
        "caption": item.get("caption") or "",
        "posted_at": item["timestamp"].replace("Z", "+00:00"),
        "likes": likes,
        "comments": item.get("commentsCount"),
        "views": item.get("videoPlayCount") or item.get("videoViewCount"),
        "permalink": item.get("url")
                     or "https://www.instagram.com/p/{}/".format(item["shortCode"]),
    }


def fetch_apify(accounts, limit, token):
    payload = {
        "directUrls": ["https://www.instagram.com/{}/".format(a) for a in accounts],
        "resultsType": "posts",
        "resultsLimit": limit,
    }
    resp = requests.post(APIFY_URL, params={"token": token}, json=payload, timeout=600)
    resp.raise_for_status()
    records, errors = [], {}
    for item in resp.json():
        if item.get("error"):
            errors[str(item.get("username", "?")).lower()] = str(item["error"])
            continue
        if "shortCode" not in item:
            continue
        records.append(normalize_apify(item))
    got = {r["account"] for r in records}
    for a in accounts:
        if a.lower() not in got and a.lower() not in errors:
            errors[a.lower()] = "нет данных (закрыт / переименован / не найден?)"
    return records, errors


def normalize_graph(account, media):
    return {
        "post_id": media["id"],
        "account": account.lower(),
        "caption": media.get("caption") or "",
        "posted_at": media["timestamp"],  # parse_ts переварит '+0000' при чтении
        "likes": media.get("like_count"),  # нет поля = лайки скрыты
        "comments": media.get("comments_count"),
        "views": None,  # business_discovery не отдаёт просмотры по чужим аккаунтам
        "permalink": media["permalink"],
    }


def fetch_graph(accounts, limit, ig_id, token):
    records, errors = [], {}
    for account in accounts:
        fields = ("business_discovery.username({}){{media.limit({})"
                  "{{id,caption,like_count,comments_count,permalink,timestamp}}}}"
                  ).format(account, limit)
        resp = requests.get(GRAPH_URL.format(ig_id=ig_id),
                            params={"fields": fields, "access_token": token},
                            timeout=60)
        data = resp.json()
        if "error" in data:
            err = data["error"]
            if err.get("code") == 190:
                raise TokenExpiredError(err.get("message", "token expired"))
            errors[account.lower()] = err.get("message", "неизвестная ошибка")
            continue
        media = data.get("business_discovery", {}).get("media", {}).get("data", [])
        records.extend(normalize_graph(account, m) for m in media)
    return records, errors


def run_fetch(limit, cfg=None, env=None, con=None, subscribers=False):
    cfg = cfg or common.load_config()
    env = env or common.load_env()
    con = con or common.connect()
    ig = cfg.get("instagram") or {}
    tg = cfg.get("telegram") or {}
    if not ig.get("accounts") and not tg.get("channels"):
        raise ConfigError("В config.json не настроена ни одна платформа — "
                          "заполни секцию instagram и/или telegram "
                          "по образцу config.example.json")
    records, errors = [], {}
    if ig.get("accounts"):
        accounts = ig["accounts"]
        if ig.get("source", "apify") == "apify":
            _require_env(env, ["APIFY_TOKEN"])
            recs, errs = fetch_apify(accounts, limit, env["APIFY_TOKEN"])
        else:
            _require_env(env, ["IG_ACCESS_TOKEN", "IG_BUSINESS_ID"])
            recs, errs = fetch_graph(accounts, limit,
                                     env["IG_BUSINESS_ID"], env["IG_ACCESS_TOKEN"])
        records += recs
        common.save_posts(con, recs)
        for a in accounts:
            a = a.lower()
            errors[("instagram", a)] = errs.get(a)
            common.set_account_status(con, a, error=errs.get(a))
    if tg.get("channels"):
        channels = tg["channels"]
        if tg.get("source", "web") == "web":
            recs, errs, subs = fetch_tg.fetch_web(channels, limit)
        else:
            _require_env(env, ["TGSTAT_TOKEN"])
            recs, errs, subs = fetch_tg.fetch_tgstat(channels, limit,
                                                     env["TGSTAT_TOKEN"],
                                                     subscribers=subscribers)
        records += recs
        common.save_posts(con, recs)
        for c in channels:
            c = c.lower()
            errors[("telegram", c)] = errs.get(c)
            common.set_account_status(con, c, error=errs.get(c),
                                      platform="telegram", subscribers=subs.get(c))
    return records, {k: v for k, v in errors.items() if v}


def main():
    ap = argparse.ArgumentParser(description="Сбор постов в базу instawatch")
    ap.add_argument("--limit", type=int, default=12,
                    help="постов на аккаунт (30 для холодного старта)")
    args = ap.parse_args()
    records, errors = run_fetch(args.limit)
    print("Сохранено постов: {}".format(len(records)))
    for (platform, a), e in errors.items():
        print("⚠️ [{}] @{}: {}".format(platform, a, e), file=sys.stderr)


if __name__ == "__main__":
    main()
