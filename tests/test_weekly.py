import common
import report
from conftest import make_post

CFG = dict(common.DEFAULTS,
           instagram={"source": "apify", "accounts": ["acc", "quietacc"]},
           median_min_posts=3)


def seed(con):
    for i, likes in enumerate([100, 100, 100]):
        make_post(con, "base{}".format(i), "acc", days_old=8 + i, likes=likes, comments=10)
    make_post(con, "wk1", "acc", days_old=3, likes=300, comments=5, caption="залетевший пост")
    make_post(con, "wk2", "acc", days_old=1, likes=50, comments=40, caption="свежий пост")


def test_weekly_data_split(con):
    seed(con)
    # "ghost" больше не в cfg["accounts"] — удалённый аккаунт не должен
    # засорять отчёт вечным "не удалось получить"
    common.set_account_status(con, "ghost", error="не найден")
    per_account, quiet, unavailable = report.weekly_data(
        con, CFG, "instagram", CFG["instagram"]["accounts"])
    assert set(per_account) == {"acc"}
    assert len(per_account["acc"]) == 2          # только посты за 7 дней
    assert quiet == ["quietacc"]
    assert unavailable == []


def test_ratios_and_fresh_flag(con):
    seed(con)
    per_account, _, _ = report.weekly_data(
        con, CFG, "instagram", CFG["instagram"]["accounts"])
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
    assert report.claude_summary({("instagram", "acc"): [{"caption": "x"}]}, prompt) is None


def test_claude_summary_returns_stripped_output_on_success(monkeypatch, tmp_path):
    prompt = tmp_path / "weekly.md"
    prompt.write_text("промпт", encoding="utf-8")

    class FakeResult:
        returncode = 0
        stdout = "— все писали про AI\n"

    def fake_run(*a, **kw):
        return FakeResult()

    monkeypatch.setattr(report.subprocess, "run", fake_run)
    result = report.claude_summary({("instagram", "acc"): [{"caption": "x"}]}, prompt)
    assert result == "— все писали про AI"


def test_unavailable_account_excluded_from_quiet(con):
    seed(con)
    common.set_account_status(con, "quietacc", error="нет данных")
    per_account, quiet, unavailable = report.weekly_data(
        con, CFG, "instagram", CFG["instagram"]["accounts"])
    assert "quietacc" not in quiet
    unavailable_accounts = {u["account"] for u in unavailable}
    assert "quietacc" in unavailable_accounts


def test_weekly_tg_section_with_views_top_and_subscribers(con, monkeypatch):
    monkeypatch.setattr(report, "claude_summary", lambda *a, **k: None)
    cfg = dict(common.DEFAULTS,
               telegram={"source": "web", "channels": ["ch"]}, median_min_posts=3)
    now = common.now_utc()
    for i, v in enumerate([100, 100, 100]):
        make_post(con, f"tgo{i}", "ch", 8 + i, 4, None, views=v, now=now)
    make_post(con, "tgtop", "ch", 3, 20, None, views=500, now=now)
    con.execute("UPDATE posts SET platform='telegram' WHERE account='ch'")
    con.commit()
    common.set_account_status(con, "ch", platform="telegram", subscribers=36300)
    text = report.build_weekly(con, cfg, now=now)
    assert "📊 За неделю" in text
    assert "✈️ Telegram" not in text          # одна платформа — без подзаголовка
    assert "Топ по просмотрам" in text and "×5.0" in text
    assert "Топ по реакциям" in text          # реакции есть (likes=4/20)
    assert "36 300" in text or "36300" in text


def test_weekly_two_platforms_two_sections(con, monkeypatch):
    monkeypatch.setattr(report, "claude_summary", lambda *a, **k: None)
    cfg = dict(common.DEFAULTS,
               instagram={"source": "apify", "accounts": ["acc"]},
               telegram={"source": "web", "channels": ["ch"]}, median_min_posts=3)
    now = common.now_utc()
    make_post(con, "ig1", "acc", 3, 10, 1, now=now)
    make_post(con, "tg1", "ch", 3, None, None, views=100, now=now)
    con.execute("UPDATE posts SET platform='telegram' WHERE account='ch'")
    con.commit()
    text = report.build_weekly(con, cfg, now=now)
    assert "📸 Instagram" in text and "✈️ Telegram" in text
