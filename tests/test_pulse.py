import common
import report
from conftest import make_post

CFG = dict(common.DEFAULTS, accounts=["acc"], median_min_posts=3, pulse_multiplier=2.0)


def seed_baseline(con):
    for i, likes in enumerate([100, 100, 100]):
        make_post(con, "base{}".format(i), "acc", days_old=5 + i, likes=likes, comments=10)


def test_signal_above_median(con):
    seed_baseline(con)
    make_post(con, "hit", "acc", days_old=1, likes=250, comments=15)  # ×2.5
    signals = report.pulse_signals(con, CFG)
    assert len(signals) == 1
    s = signals[0]
    assert s["post_id"] == "hit" and s["metric"] == "likes"
    assert abs(s["ratio"] - 2.5) < 0.01


def test_no_signal_below_threshold(con):
    seed_baseline(con)
    make_post(con, "meh", "acc", days_old=1, likes=150, comments=15)  # ×1.5 < 2
    assert report.pulse_signals(con, CFG) == []


def test_old_posts_ignored(con):
    seed_baseline(con)
    make_post(con, "oldhit", "acc", days_old=10, likes=999, comments=99)
    assert report.pulse_signals(con, CFG) == []


def test_dedup_after_mark(con):
    seed_baseline(con)
    make_post(con, "hit", "acc", days_old=1, likes=250, comments=15)
    common.mark_alerted(con, ["hit"])
    assert report.pulse_signals(con, CFG) == []


def test_hidden_likes_falls_back_to_comments(con):
    seed_baseline(con)
    make_post(con, "hid", "acc", days_old=1, likes=None, comments=30)  # комменты ×3
    signals = report.pulse_signals(con, CFG)
    assert len(signals) == 1 and signals[0]["metric"] == "comments"
    assert signals[0]["likes_hidden"]


def test_format_pulse_has_permalink_every_signal(con):
    seed_baseline(con)
    make_post(con, "hit", "acc", days_old=1, likes=250, comments=15)
    text = report.format_pulse(report.pulse_signals(con, CFG))
    assert "https://www.instagram.com/p/hit/" in text
    assert "×2.5" in text
