import common
import report
from conftest import make_post

CFG = dict(common.DEFAULTS, accounts=["acc", "quietacc"], median_min_posts=3)


def seed(con):
    for i, likes in enumerate([100, 100, 100]):
        make_post(con, "base{}".format(i), "acc", days_old=8 + i, likes=likes, comments=10)
    make_post(con, "wk1", "acc", days_old=3, likes=300, comments=5, caption="залетевший пост")
    make_post(con, "wk2", "acc", days_old=1, likes=50, comments=40, caption="свежий пост")


def test_weekly_data_split(con):
    seed(con)
    common.set_account_status(con, "ghost", error="не найден")
    per_account, quiet, unavailable = report.weekly_data(con, CFG)
    assert set(per_account) == {"acc"}
    assert len(per_account["acc"]) == 2          # только посты за 7 дней
    assert quiet == ["quietacc"]
    assert unavailable[0]["account"] == "ghost"


def test_ratios_and_fresh_flag(con):
    seed(con)
    per_account, _, _ = report.weekly_data(con, CFG)
    by_id = {p["post_id"]: p for p in per_account["acc"]}
    assert abs(by_id["wk1"]["like_ratio"] - 3.0) < 0.01
    assert by_id["wk2"]["fresh"] is True
    assert by_id["wk1"]["fresh"] is False


def test_build_weekly_sections_and_permalinks(con, monkeypatch):
    monkeypatch.setattr(report, "claude_summary", lambda *a, **kw: None)
    seed(con)
    text = report.build_weekly(con, CFG)
    assert "Топ по лайкам" in text and "Топ по комментам" in text
    assert "😴" in text and "@quietacc" in text
    assert "⏳ ещё растёт" in text
    # каждый пост со ссылкой
    assert text.count("https://www.instagram.com/p/wk1/") >= 1
    assert text.count("https://www.instagram.com/p/wk2/") >= 1


def test_claude_summary_fallback_on_failure(monkeypatch, tmp_path):
    prompt = tmp_path / "weekly.md"
    prompt.write_text("промпт", encoding="utf-8")
    def boom(*a, **kw):
        raise OSError("claude not found")
    monkeypatch.setattr(report.subprocess, "run", boom)
    assert report.claude_summary({"acc": [{"caption": "x"}]}, prompt) is None
