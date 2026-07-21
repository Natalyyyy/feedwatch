import common
from conftest import make_post


def test_save_and_latest_metrics(con):
    make_post(con, "p1", "acc", days_old=5, likes=100, comments=10)
    make_post(con, "p1", "acc", days_old=5, likes=150, comments=12)  # второй снапшот
    make_post(con, "p2", "acc", days_old=1, likes=50, comments=5)
    rows = common.latest_metrics(con, "acc")
    assert len(rows) == 2
    by_id = {r["post_id"]: r for r in rows}
    assert by_id["p1"]["likes"] == 150            # последний снапшот, не первый
    assert by_id["p2"]["permalink"].startswith("https://www.instagram.com/p/")
    assert rows[0]["post_id"] == "p2"             # сортировка: свежие первыми


def test_hidden_likes_stored_as_none(con):
    make_post(con, "p1", "acc", days_old=3, likes=None, comments=7)
    assert common.latest_metrics(con, "acc")[0]["likes"] is None


def test_alerted_dedup(con):
    assert not common.was_alerted(con, "p1")
    common.mark_alerted(con, ["p1", "p2"])
    common.mark_alerted(con, ["p1"])  # повторно — не падает
    assert common.was_alerted(con, "p1")
    assert not common.was_alerted(con, "p3")


def test_views_stored(con):
    make_post(con, "reel1", "acc", days_old=3, likes=10, comments=1, views=5000)
    assert common.latest_metrics(con, "acc")[0]["views"] == 5000


def test_account_status(con):
    common.set_account_status(con, "acc", error="не найден")
    row = con.execute("SELECT * FROM account_status").fetchone()
    assert "не найден" in row["last_error"]
    common.set_account_status(con, "acc")  # успех сбрасывает ошибку
    row = con.execute("SELECT * FROM account_status").fetchone()
    assert row["last_error"] is None and row["last_ok"]


def test_platform_saved_and_filtered(con):
    make_post(con, "p1", "acc", 3, 10, 1)                       # instagram по умолчанию
    common.save_posts(con, [{
        "post_id": "tg:acc:1", "account": "acc", "platform": "telegram",
        "caption": "тг", "posted_at": common.now_utc().isoformat(),
        "likes": 5, "comments": None, "views": 100,
        "permalink": "https://t.me/acc/1",
    }])
    ig = common.latest_metrics(con, "acc")
    tg = common.latest_metrics(con, "acc", platform="telegram")
    assert [p["post_id"] for p in ig] == ["p1"]
    assert [p["post_id"] for p in tg] == ["tg:acc:1"]
    assert tg[0]["platform"] == "telegram"


def test_legacy_db_renamed_and_migrated(tmp_path):
    legacy = tmp_path / "instawatch.db"
    import sqlite3
    old = sqlite3.connect(legacy)
    old.executescript("""
        CREATE TABLE posts (post_id TEXT PRIMARY KEY, account TEXT NOT NULL,
            caption TEXT, posted_at TEXT NOT NULL, permalink TEXT NOT NULL);
        CREATE TABLE snapshots (id INTEGER PRIMARY KEY AUTOINCREMENT, post_id TEXT NOT NULL,
            fetched_at TEXT NOT NULL, likes INTEGER, comments INTEGER, views INTEGER);
        CREATE TABLE alerted (post_id TEXT PRIMARY KEY, alerted_at TEXT NOT NULL);
        CREATE TABLE account_status (account TEXT PRIMARY KEY, last_ok TEXT, last_error TEXT);
        INSERT INTO posts VALUES ('old1', 'acc', 'старый', '2026-07-01T00:00:00+00:00', 'u');
        INSERT INTO account_status (account, last_error) VALUES ('acc', 'ошибка');
    """)
    old.commit(); old.close()
    con = common.connect(tmp_path / "feedwatch.db")
    assert not legacy.exists()
    row = con.execute("SELECT platform FROM posts WHERE post_id='old1'").fetchone()
    assert row["platform"] == "instagram"
    st = con.execute("SELECT platform, account, last_error, subscribers "
                     "FROM account_status").fetchone()
    assert (st["platform"], st["account"], st["last_error"]) == ("instagram", "acc", "ошибка")


def test_account_status_platform_and_subscribers(con):
    common.set_account_status(con, "ch", platform="telegram", subscribers=36300)
    common.set_account_status(con, "ch", platform="telegram")   # без subscribers — не затирает
    st = con.execute("SELECT subscribers, last_ok FROM account_status "
                     "WHERE platform='telegram' AND account='ch'").fetchone()
    assert st["subscribers"] == 36300 and st["last_ok"] is not None
