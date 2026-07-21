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
