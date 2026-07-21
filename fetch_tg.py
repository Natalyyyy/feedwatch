"""Сбор постов Telegram-каналов: веб-превью t.me/s (без ключей) или TGStat API."""
import html as html_module
import re

import requests

TG_WEB_URL = "https://t.me/s/{}"
HEADERS = {"User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                          "AppleWebKit/537.36 (KHTML, like Gecko) "
                          "Chrome/120.0 Safari/537.36")}
PREVIEW_UNAVAILABLE = ("веб-превью недоступно (канал скрытый, приватный или "
                       "не существует) — попробуй источник tgstat")


def parse_count(text):
    """'13K' → 13000, '1.2M' → 1200000, '419' → 419. Мусор → None."""
    if text is None:
        return None
    t = text.strip().replace("\xa0", "").replace(" ", "").replace(",", ".")
    try:
        if t[-1:].lower() == "k":
            return int(float(t[:-1]) * 1000)
        if t[-1:].lower() == "m":
            return int(float(t[:-1]) * 1000000)
        return int(float(t))
    except ValueError:
        return None


def _strip_html(fragment):
    text = re.sub(r"<br\s*/?>", "\n", fragment)
    text = re.sub(r"<[^>]+>", "", text)
    return html_module.unescape(text).strip()


def parse_page(page_html, channel):
    """Одна страница t.me/s → (records, min_post_id). Платные реакции (звёзды) не считаем."""
    records, min_id = [], None
    for block in page_html.split('class="tgme_widget_message_wrap')[1:]:
        m = re.search(r'data-post="[^"/]+/(\d+)"', block)
        time_m = re.search(r'<time datetime="([^"]+)"', block)
        if not m or not time_m:
            continue
        post_id = int(m.group(1))
        min_id = post_id if min_id is None else min(min_id, post_id)
        text_m = re.search(r'tgme_widget_message_text[^>]*>(.*?)</div>', block, re.S)
        views_m = re.search(r'tgme_widget_message_views">([^<]+)<', block)
        reactions = re.findall(
            r'<span class="tgme_reaction">.*?</i>\s*([\d.,KMkm\xa0 ]+)</span>',
            block, re.S)
        likes = None
        if reactions:
            parsed = [parse_count(r) for r in reactions]
            likes = sum(v for v in parsed if v is not None)
        records.append({
            "post_id": "tg:{}:{}".format(channel, post_id),
            "account": channel,
            "platform": "telegram",
            "caption": _strip_html(text_m.group(1)) if text_m else "",
            "posted_at": time_m.group(1),
            "likes": likes,
            "comments": None,   # веб-превью счётчик комментов не отдаёт
            "views": parse_count(views_m.group(1)) if views_m else None,
            "permalink": "https://t.me/{}/{}".format(channel, post_id),
        })
    return records, min_id


def parse_subscribers(page_html):
    m = re.search(
        r'counter_value">([^<]+)</span>\s*<span class="counter_type">subscriber',
        page_html)
    return parse_count(m.group(1)) if m else None


def _fetch_channel_web(http, channel, limit):
    resp = http.get(TG_WEB_URL.format(channel), headers=HEADERS, timeout=30)
    resp.raise_for_status()
    records, min_id = parse_page(resp.text, channel)
    subs = parse_subscribers(resp.text)
    while records and len(records) < limit and min_id and min_id > 1:
        resp = http.get(TG_WEB_URL.format(channel), params={"before": min_id},
                        headers=HEADERS, timeout=30)
        resp.raise_for_status()
        more, new_min = parse_page(resp.text, channel)
        known = {r["post_id"] for r in records}
        more = [r for r in more if r["post_id"] not in known]
        if not more:
            break
        records += more
        min_id = new_min
    return records, subs


def fetch_web(channels, limit, session=None):
    """Посты каналов из веб-превью. → (records, errors, subs)."""
    http = session or requests
    records, errors, subs = [], {}, {}
    for channel in channels:
        channel = channel.lower()
        try:
            chan_records, chan_subs = _fetch_channel_web(http, channel, limit)
        except requests.RequestException as exc:
            errors[channel] = "сеть/HTTP: {}".format(exc)
            continue
        if not chan_records:
            errors[channel] = PREVIEW_UNAVAILABLE
            continue
        records += chan_records[:limit]
        if chan_subs is not None:
            subs[channel] = chan_subs
    return records, errors, subs
