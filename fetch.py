"""Сбор постов Instagram (Apify или Meta Graph API) → SQLite."""
import argparse
import sys

import requests

import common

APIFY_URL = ("https://api.apify.com/v2/acts/apify~instagram-scraper/"
             "run-sync-get-dataset-items")
GRAPH_URL = "https://graph.facebook.com/v21.0/{ig_id}"


class TokenExpiredError(Exception):
    """Meta Graph API вернул код 190 — long-lived токен протух."""


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
