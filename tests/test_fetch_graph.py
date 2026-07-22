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


class NonJsonResp:
    """Task 4: resp.json() падает голым ValueError на не-JSON ответе
    (например HTML страница ошибки от Graph API)."""
    def json(self):
        raise ValueError("Expecting value: line 1 column 1 (char 0)")


def test_fetch_graph_non_json_response_is_collected_as_error(monkeypatch):
    monkeypatch.setattr(fetch.requests, "get", lambda *a, **kw: NonJsonResp())
    records, errors = fetch.fetch_graph(["acc"], 12, "ig123", "tok")
    assert records == []
    assert "acc" in errors and "JSON" in errors["acc"]


def test_fetch_graph_non_json_does_not_block_other_accounts(monkeypatch):
    calls = {"n": 0}

    def fake_get(*a, **kw):
        calls["n"] += 1
        if calls["n"] == 1:
            return NonJsonResp()
        return FakeResp({"business_discovery": {"media": {"data": [
            {"id": "1", "caption": "ok", "timestamp": "2026-07-19T10:00:00+0000",
             "like_count": 1, "comments_count": 1, "permalink": "https://x/"},
        ]}}})

    monkeypatch.setattr(fetch.requests, "get", fake_get)
    records, errors = fetch.fetch_graph(["broken", "acc"], 12, "ig123", "tok")
    assert "broken" in errors
    assert len(records) == 1 and records[0]["account"] == "acc"


def test_run_fetch_missing_apify_token_raises_config_error(monkeypatch, con):
    # run_fetch делает `env = env or common.load_env()` — пустой env={} falsy,
    # поэтому без подмены load_env тест читал бы реальный .env с диска и мог
    # улететь в живой запрос к Apify. Глушим load_env, чтобы тест был герметичным.
    monkeypatch.setattr(fetch.common, "load_env", lambda *a, **k: {})
    cfg = dict(common.DEFAULTS, instagram={"source": "apify", "accounts": ["acc"]})
    with pytest.raises(fetch.ConfigError) as excinfo:
        fetch.run_fetch(12, cfg=cfg, env={}, con=con)
    assert "APIFY_TOKEN" in str(excinfo.value)


def test_run_fetch_missing_graph_env_raises_config_error(monkeypatch, con):
    # См. комментарий выше: пустой env={} — falsy, run_fetch иначе подхватил бы
    # реальный .env с диска и обратился бы к живому Meta Graph API.
    monkeypatch.setattr(fetch.common, "load_env", lambda *a, **k: {})
    cfg = dict(common.DEFAULTS, instagram={"source": "metagraph", "accounts": ["acc"]})
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
    cfg = dict(common.DEFAULTS, instagram={"source": "apify", "accounts": ["acc", "ghost"]})
    records, errors = fetch.run_fetch(12, cfg=cfg, env={"APIFY_TOKEN": "t"}, con=con)
    assert len(common.latest_metrics(con, "acc")) == 1
    row = con.execute("SELECT last_error FROM account_status WHERE account='ghost'").fetchone()
    assert row["last_error"]
    assert errors == {("instagram", "ghost"): "нет данных"}


def test_run_fetch_telegram_web(monkeypatch, con):
    monkeypatch.setattr(fetch.fetch_tg, "fetch_web",
                        lambda channels, limit, session=None: (
                            [{"post_id": "tg:ch:1", "account": "ch", "platform": "telegram",
                              "caption": "x", "posted_at": common.now_utc().isoformat(),
                              "likes": 3, "comments": None, "views": 50,
                              "permalink": "https://t.me/ch/1"}],
                            {}, {"ch": 1000}))
    cfg = dict(common.DEFAULTS, telegram={"source": "web", "channels": ["ch"]})
    records, errors = fetch.run_fetch(5, cfg=cfg, env={}, con=con)
    assert len(records) == 1 and errors == {}
    row = con.execute("SELECT subscribers FROM account_status "
                      "WHERE platform='telegram' AND account='ch'").fetchone()
    assert row["subscribers"] == 1000


def test_run_fetch_tgstat_requires_token(con):
    cfg = dict(common.DEFAULTS, telegram={"source": "tgstat", "channels": ["ch"]})
    with pytest.raises(fetch.ConfigError):
        fetch.run_fetch(5, cfg=cfg, env={}, con=con)


def test_run_fetch_no_platforms(con):
    with pytest.raises(fetch.ConfigError):
        fetch.run_fetch(5, cfg=dict(common.DEFAULTS), env={}, con=con)


def test_run_fetch_ig_network_error_does_not_block_telegram(monkeypatch, con):
    """Task 3: RequestException из Apify/Graph раньше ронял весь run_fetch,
    включая TG-каналы. Платформы должны падать независимо."""
    import requests

    def boom(*a, **kw):
        raise requests.HTTPError("402 Payment Required")

    monkeypatch.setattr(fetch, "fetch_apify", boom)
    monkeypatch.setattr(fetch.fetch_tg, "fetch_web",
                        lambda channels, limit, session=None: (
                            [{"post_id": "tg:ch:1", "account": "ch", "platform": "telegram",
                              "caption": "x", "posted_at": common.now_utc().isoformat(),
                              "likes": 3, "comments": None, "views": 50,
                              "permalink": "https://t.me/ch/1"}],
                            {}, {}))
    cfg = dict(common.DEFAULTS,
              instagram={"source": "apify", "accounts": ["acc"]},
              telegram={"source": "web", "channels": ["ch"]})

    records, errors = fetch.run_fetch(12, cfg=cfg, env={"APIFY_TOKEN": "t"}, con=con)

    # TG собрался несмотря на упавший IG
    assert len(common.latest_metrics(con, "ch", platform="telegram")) == 1
    assert any(r["platform"] == "telegram" for r in records)
    # IG-ошибка попала в отчёт человекочитаемым сообщением, не traceback'ом
    assert ("instagram", "acc") in errors
    assert "Instagram" in errors[("instagram", "acc")]
    row = con.execute(
        "SELECT last_error FROM account_status WHERE platform='instagram' AND account='acc'"
    ).fetchone()
    assert row["last_error"]


def test_run_fetch_ig_token_expired_still_propagates(monkeypatch, con):
    """Изоляция ловит только requests.RequestException — TokenExpiredError
    должен по-прежнему всплывать наверх (report.py его обрабатывает отдельной
    веткой с другим сообщением)."""
    def boom(*a, **kw):
        raise fetch.TokenExpiredError("Error validating access token")

    monkeypatch.setattr(fetch, "fetch_graph", boom)
    cfg = dict(common.DEFAULTS, instagram={"source": "graph", "accounts": ["acc"]})

    with pytest.raises(fetch.TokenExpiredError):
        fetch.run_fetch(12, cfg=cfg,
                        env={"IG_ACCESS_TOKEN": "t", "IG_BUSINESS_ID": "1"}, con=con)
