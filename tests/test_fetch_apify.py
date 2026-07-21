import fetch

APIFY_ITEM = {
    "shortCode": "Cxyz1",
    "ownerUsername": "SomeBlog",
    "caption": "Запустили новый продукт!",
    "timestamp": "2026-07-19T10:00:00.000Z",
    "likesCount": 500,
    "commentsCount": 40,
    "url": "https://www.instagram.com/p/Cxyz1/",
}


def test_normalize_apify():
    r = fetch.normalize_apify(APIFY_ITEM)
    assert r["post_id"] == "Cxyz1"
    assert r["account"] == "someblog"           # lower
    assert r["posted_at"] == "2026-07-19T10:00:00.000+00:00"
    assert r["likes"] == 500 and r["comments"] == 40
    assert r["views"] is None                    # фото — просмотров нет
    assert r["permalink"] == "https://www.instagram.com/p/Cxyz1/"


def test_normalize_apify_hidden_likes():
    assert fetch.normalize_apify({**APIFY_ITEM, "likesCount": -1})["likes"] is None


def test_normalize_apify_reel_views():
    r = fetch.normalize_apify({**APIFY_ITEM, "videoPlayCount": 10000})
    assert r["views"] == 10000
    # фолбэк на videoViewCount, если play-счётчика нет
    r2 = fetch.normalize_apify({**APIFY_ITEM, "videoViewCount": 7000})
    assert r2["views"] == 7000


class FakeResp:
    status_code = 200
    def __init__(self, payload): self._payload = payload
    def raise_for_status(self): pass
    def json(self): return self._payload


def test_fetch_apify_missing_account_is_error(monkeypatch):
    monkeypatch.setattr(fetch.requests, "post", lambda *a, **kw: FakeResp([APIFY_ITEM]))
    records, errors = fetch.fetch_apify(["someblog", "ghost"], limit=12, token="t")
    assert len(records) == 1
    assert "ghost" in errors
