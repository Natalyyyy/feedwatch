import pytest
import requests

import common
import fetch
import report
from conftest import make_post


def _stub_env(monkeypatch, con, env=None):
    """main() читает конфиг/env/базу напрямую из common — подменяем на тестовые."""
    monkeypatch.setattr(report.common, "load_config",
                        lambda: dict(common.DEFAULTS,
                                     instagram={"source": "apify", "accounts": ["acc"]}))
    monkeypatch.setattr(report.common, "load_env", lambda: env if env is not None else {})
    monkeypatch.setattr(report.common, "connect", lambda: con)


def test_main_exits_on_http_error_without_send(monkeypatch, con):
    _stub_env(monkeypatch, con)

    def boom(*a, **kw):
        raise requests.HTTPError("402 Payment Required")

    monkeypatch.setattr(report.fetch, "run_fetch", boom)
    monkeypatch.setattr("sys.argv", ["report.py", "pulse"])

    with pytest.raises(SystemExit) as excinfo:
        report.main()
    assert excinfo.value.code == 1


def test_main_exits_on_config_error_without_send(monkeypatch, con):
    _stub_env(monkeypatch, con)

    def boom(*a, **kw):
        raise fetch.ConfigError(
            "Не найден APIFY_TOKEN в .env — заполни его по образцу .env.example")

    monkeypatch.setattr(report.fetch, "run_fetch", boom)
    monkeypatch.setattr("sys.argv", ["report.py", "pulse"])

    with pytest.raises(SystemExit) as excinfo:
        report.main()
    assert excinfo.value.code == 1


def test_main_exits_on_token_expired_via_original_path(monkeypatch, con, capsys):
    """TokenExpiredError должен уходить в свою ветку (TOKEN_EXPIRED_MSG),
    а не путаться с общим обработчиком ConfigError/RequestException."""
    _stub_env(monkeypatch, con)

    def boom(*a, **kw):
        raise fetch.TokenExpiredError("Error validating access token")

    monkeypatch.setattr(report.fetch, "run_fetch", boom)
    monkeypatch.setattr("sys.argv", ["report.py", "pulse"])

    with pytest.raises(SystemExit) as excinfo:
        report.main()
    assert excinfo.value.code == 1
    err = capsys.readouterr().err
    assert report.TOKEN_EXPIRED_MSG in err
    assert report.FETCH_ERROR_MSG not in err


def _pulse_cfg():
    return dict(common.DEFAULTS, instagram={"source": "apify", "accounts": ["acc"]},
                median_min_posts=3, pulse_multiplier=2.0)


def _seed_signal(con):
    for i, likes in enumerate([100, 100, 100]):
        make_post(con, "base{}".format(i), "acc", days_old=5 + i, likes=likes, comments=10)
    make_post(con, "hit", "acc", days_old=1, likes=250, comments=15)  # ×2.5 от медианы


def test_missing_telegram_env_reports_both_keys():
    assert report.missing_telegram_env({}) == ["TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID"]
    assert report.missing_telegram_env({"TELEGRAM_BOT_TOKEN": "t"}) == ["TELEGRAM_CHAT_ID"]
    assert report.missing_telegram_env(
        {"TELEGRAM_BOT_TOKEN": "t", "TELEGRAM_CHAT_ID": "c"}) == []


def test_main_marks_alerted_only_after_successful_send(monkeypatch, con):
    """Task 2: mark_alerted теперь идёт после telegram.send, не до него."""
    _stub_env(monkeypatch, con, env={"TELEGRAM_BOT_TOKEN": "t", "TELEGRAM_CHAT_ID": "c"})
    monkeypatch.setattr(report.common, "load_config", lambda: _pulse_cfg())
    _seed_signal(con)

    sent = []
    monkeypatch.setattr(report.telegram, "send", lambda text, token, chat_id: sent.append(text))
    monkeypatch.setattr("sys.argv", ["report.py", "pulse", "--send", "--no-fetch"])

    report.main()

    assert len(sent) == 1
    assert common.was_alerted(con, "hit")


def test_main_does_not_mark_alerted_when_send_fails(monkeypatch, con):
    """Task 2 (критично): сбой telegram.send не должен терять сигнал навсегда —
    пост остаётся неотмеченным и всплывёт в следующем прогоне пульса."""
    _stub_env(monkeypatch, con, env={"TELEGRAM_BOT_TOKEN": "t", "TELEGRAM_CHAT_ID": "c"})
    monkeypatch.setattr(report.common, "load_config", lambda: _pulse_cfg())
    _seed_signal(con)

    def boom(*a, **kw):
        raise requests.ConnectionError("telegram down")

    monkeypatch.setattr(report.telegram, "send", boom)
    monkeypatch.setattr("sys.argv", ["report.py", "pulse", "--send", "--no-fetch"])

    with pytest.raises(requests.ConnectionError):
        report.main()

    assert not common.was_alerted(con, "hit")


def test_main_send_requires_chat_id_before_anything_else(monkeypatch, con):
    """Task 5: --send с TOKEN, но без CHAT_ID — внятная ошибка и выход ДО
    fetch/mark_alerted, а не голый KeyError на телеграм-отправке."""
    _stub_env(monkeypatch, con, env={"TELEGRAM_BOT_TOKEN": "t"})
    monkeypatch.setattr(report.common, "load_config", lambda: _pulse_cfg())
    _seed_signal(con)

    sent = []
    monkeypatch.setattr(report.telegram, "send", lambda text, token, chat_id: sent.append(text))
    monkeypatch.setattr("sys.argv", ["report.py", "pulse", "--send", "--no-fetch"])

    with pytest.raises(SystemExit) as excinfo:
        report.main()

    assert excinfo.value.code == 1
    assert not sent
    assert not common.was_alerted(con, "hit")
