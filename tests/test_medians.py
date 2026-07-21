import common
from conftest import make_post

CFG = dict(common.DEFAULTS, median_min_posts=3)


def test_median_basic(con):
    for i, likes in enumerate([100, 200, 300]):
        make_post(con, f"p{i}", "acc", days_old=5 + i, likes=likes, comments=10 * (i + 1))
    med = common.account_medians(con, "acc", CFG)
    assert med["likes"] == 200
    assert med["comments"] == 20
    assert med["n_posts"] == 3


def test_fresh_posts_excluded(con):
    make_post(con, "fresh", "acc", days_old=1, likes=9999, comments=999)  # моложе 2 дней
    for i, likes in enumerate([100, 200, 300]):
        make_post(con, f"p{i}", "acc", days_old=5 + i, likes=likes, comments=10)
    assert common.account_medians(con, "acc", CFG)["likes"] == 200


def test_min_posts_backfill_beyond_window(con):
    # в 30-дневном окне только 1 пост — добираем старыми до median_min_posts=3
    make_post(con, "new", "acc", days_old=10, likes=100, comments=1)
    make_post(con, "old1", "acc", days_old=40, likes=200, comments=2)
    make_post(con, "old2", "acc", days_old=50, likes=300, comments=3)
    make_post(con, "old3", "acc", days_old=60, likes=400, comments=4)
    med = common.account_medians(con, "acc", CFG)
    assert med["n_posts"] == 3
    assert med["likes"] == 200  # три самых свежих подходящих: 100, 200, 300


def test_hidden_likes_skipped_in_likes_median(con):
    make_post(con, "h1", "acc", days_old=5, likes=None, comments=10)
    make_post(con, "p1", "acc", days_old=6, likes=100, comments=20)
    make_post(con, "p2", "acc", days_old=7, likes=300, comments=30)
    med = common.account_medians(con, "acc", CFG)
    assert med["likes"] == 200      # медиана по 100 и 300
    assert med["comments"] == 20    # комменты считаются по всем трём


def test_no_posts_returns_none(con):
    med = common.account_medians(con, "acc", CFG)
    assert med["likes"] is None and med["comments"] is None and med["n_posts"] == 0


def test_views_median_and_platform(con):
    now = common.now_utc()
    for i, v in enumerate([100, 200, 300]):
        make_post(con, "tg{}".format(i), "ch", 5 + i, None, None, views=v, now=now)
        con.execute("UPDATE posts SET platform='telegram' WHERE post_id=?", ("tg{}".format(i),))
    con.commit()
    med = common.account_medians(con, "ch", CFG, now=now, platform="telegram")
    assert med["views"] == 200
    assert med["likes"] is None
