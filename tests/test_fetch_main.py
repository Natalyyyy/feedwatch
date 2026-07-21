import pytest
import requests

import common
import fetch


def _stub_env(monkeypatch, con, cfg=None):
    """main() читает конфиг/env/базу напрямую из common — подменяем на тестовые."""
    monkeypatch.setattr(fetch.common, "load_config", lambda: cfg or dict(common.DEFAULTS))
    monkeypatch.setattr(fetch.common, "load_env", lambda: {})
    monkeypatch.setattr(fetch.common, "connect", lambda: con)


def test_main_exits_on_config_error_no_platform(monkeypatch, con, capsys):
    """Холодный старт с пустым config.json — дружелюбное сообщение, не traceback."""
    _stub_env(monkeypatch, con)
    monkeypatch.setattr("sys.argv", ["fetch.py", "--limit", "30"])

    with pytest.raises(SystemExit) as excinfo:
        fetch.main()

    assert excinfo.value.code == 1
    captured = capsys.readouterr()
    assert "не настроена ни одна платформа" in captured.err


def test_main_exits_on_request_exception(monkeypatch, con, capsys):
    _stub_env(monkeypatch, con,
              cfg=dict(common.DEFAULTS, instagram={"source": "apify", "accounts": ["acc"]}))
    monkeypatch.setattr("sys.argv", ["fetch.py", "--limit", "30"])

    def boom(*a, **kw):
        raise requests.ConnectionError("network down")

    monkeypatch.setattr(fetch, "run_fetch", boom)

    with pytest.raises(SystemExit) as excinfo:
        fetch.main()

    assert excinfo.value.code == 1
    captured = capsys.readouterr()
    assert "Не удалось собрать данные" in captured.err


def test_main_exits_on_token_expired(monkeypatch, con, capsys):
    _stub_env(monkeypatch, con,
              cfg=dict(common.DEFAULTS, instagram={"source": "graph", "accounts": ["acc"]}))
    monkeypatch.setattr("sys.argv", ["fetch.py", "--limit", "30"])

    def boom(*a, **kw):
        raise fetch.TokenExpiredError("Error validating access token")

    monkeypatch.setattr(fetch, "run_fetch", boom)

    with pytest.raises(SystemExit) as excinfo:
        fetch.main()

    assert excinfo.value.code == 1
    captured = capsys.readouterr()
    assert "обнови токен инстаграма" in captured.err
