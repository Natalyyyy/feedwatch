import pytest

import common
import fetch

MEDIA = {
    "id": "1789_222",
    "caption": "Пост про запуск",
    "timestamp": "2026-07-19T10:00:00+0000",
    "like_count": 300,
    "comments_count": 25,
    "permalink": "https://www.instagram.com/p/Cabc/",
}


class FakeResp:
    def __init__(self, payload): self._payload = payload
    def json(self): return self._payload


def test_normalize_graph_and_ts():
    r = fetch.normalize_graph("SomeBlog", MEDIA)
    assert r["account"] == "someblog"
    assert common.parse_ts(r["posted_at"]).year == 2026  # '+0000' переварен
    assert r["permalink"] == MEDIA["permalink"]
    assert r["views"] is None  # business_discovery не отдаёт просмотры чужих


def test_normalize_graph_hidden_likes():
    media = {k: v for k, v in MEDIA.items() if k != "like_count"}
    assert fetch.normalize_graph("acc", media)["likes"] is None


def test_token_expired_raises(monkeypatch):
    payload = {"error": {"code": 190, "message": "Error validating access token"}}
    monkeypatch.setattr(fetch.requests, "get", lambda *a, **kw: FakeResp(payload))
    with pytest.raises(fetch.TokenExpiredError):
        fetch.fetch_graph(["acc"], 12, "ig123", "tok")


def test_unavailable_account_collected(monkeypatch):
    payload = {"error": {"code": 110, "message": "Cannot find the IG user"}}
    monkeypatch.setattr(fetch.requests, "get", lambda *a, **kw: FakeResp(payload))
    records, errors = fetch.fetch_graph(["ghost"], 12, "ig123", "tok")
    assert records == [] and "ghost" in errors


def test_run_fetch_missing_apify_token_raises_config_error(con):
    cfg = dict(common.DEFAULTS, accounts=["acc"], source="apify")
    with pytest.raises(fetch.ConfigError) as excinfo:
        fetch.run_fetch(12, cfg=cfg, env={}, con=con)
    assert "APIFY_TOKEN" in str(excinfo.value)


def test_run_fetch_missing_graph_env_raises_config_error(con):
    cfg = dict(common.DEFAULTS, accounts=["acc"], source="metagraph")
    with pytest.raises(fetch.ConfigError) as excinfo:
        fetch.run_fetch(12, cfg=cfg, env={}, con=con)
    msg = str(excinfo.value)
    assert "IG_ACCESS_TOKEN" in msg and "IG_BUSINESS_ID" in msg


def test_run_fetch_persists_and_sets_status(monkeypatch, con, tmp_path):
    monkeypatch.setattr(fetch, "fetch_apify",
                        lambda accounts, limit, token:
                        ([fetch.normalize_apify({
                            "shortCode": "C1", "ownerUsername": "acc",
                            "caption": "x", "timestamp": "2026-07-19T10:00:00.000Z",
                            "likesCount": 10, "commentsCount": 1,
                            "url": "https://www.instagram.com/p/C1/"})],
                         {"ghost": "нет данных"}))
    cfg = dict(common.DEFAULTS, accounts=["acc", "ghost"], source="apify")
    records, errors = fetch.run_fetch(12, cfg=cfg, env={"APIFY_TOKEN": "t"}, con=con)
    assert len(common.latest_metrics(con, "acc")) == 1
    row = con.execute("SELECT last_error FROM account_status WHERE account='ghost'").fetchone()
    assert row["last_error"]
