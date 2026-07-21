import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import fetch_tg

POSTS_OK = {"status": "ok", "response": {"items": [
    {"id": 4174011852, "date": 1784476800, "views": 1500,
     "text": "<b>жирный</b> пост", "link": "https://t.me/ch/419"},
]}}
INFO_OK = {"status": "ok", "response": {"participants_count": 36300}}
ERR = {"status": "error", "error": "channel_not_found"}


class FakeResp:
    def __init__(self, payload):
        self._payload = payload
    def json(self):
        return self._payload


def test_fetch_tgstat_ok(monkeypatch):
    calls = []
    def fake_get(url, params=None, timeout=None):
        calls.append((url, params))
        return FakeResp(INFO_OK if url.endswith("channels/get") else POSTS_OK)
    monkeypatch.setattr(fetch_tg.requests, "get", fake_get)
    records, errors, subs = fetch_tg.fetch_tgstat(["Ch"], 25, "tok", subscribers=True)
    assert errors == {} and subs == {"ch": 36300}
    r = records[0]
    assert r["post_id"] == "tg:ch:4174011852"
    assert r["platform"] == "telegram" and r["views"] == 1500
    assert r["likes"] is None and r["comments"] is None
    assert r["caption"] == "жирный пост"
    assert r["permalink"] == "https://t.me/ch/419"
    assert r["posted_at"].startswith("2026-07-19")
    assert calls[0][1]["channelId"] == "@Ch" and calls[0][1]["token"] == "tok"


def test_fetch_tgstat_error_per_channel(monkeypatch):
    monkeypatch.setattr(fetch_tg.requests, "get",
                        lambda url, params=None, timeout=None: FakeResp(ERR))
    records, errors, subs = fetch_tg.fetch_tgstat(["ghost"], 25, "tok")
    assert records == [] and "channel_not_found" in errors["ghost"]


def test_fetch_tgstat_no_subscribers_no_extra_request(monkeypatch):
    calls = []
    def fake_get(url, params=None, timeout=None):
        calls.append(url)
        return FakeResp(POSTS_OK)
    monkeypatch.setattr(fetch_tg.requests, "get", fake_get)
    fetch_tg.fetch_tgstat(["ch"], 25, "tok", subscribers=False)
    assert len(calls) == 1 and calls[0].endswith("channels/posts")


POSTS_ONE_MALFORMED = {"status": "ok", "response": {"items": [
    {"id": 4174011852, "date": 1784476800, "views": 1500,
     "text": "<b>жирный</b> пост", "link": "https://t.me/ch/419"},
    {"views": 5},   # служебный/битый элемент — без id и date
]}}


def test_fetch_tgstat_skips_malformed_item(monkeypatch):
    monkeypatch.setattr(fetch_tg.requests, "get",
                        lambda url, params=None, timeout=None: FakeResp(POSTS_ONE_MALFORMED))
    records, errors, subs = fetch_tg.fetch_tgstat(["ch"], 25, "tok")
    assert len(records) == 1
    assert records[0]["post_id"] == "tg:ch:4174011852"
    assert errors == {}
