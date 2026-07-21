import pytest
import requests

import common
import fetch
import report


def _stub_env(monkeypatch, con):
    """main() читает конфиг/env/базу напрямую из common — подменяем на тестовые."""
    monkeypatch.setattr(report.common, "load_config",
                        lambda: dict(common.DEFAULTS, accounts=["acc"], source="apify"))
    monkeypatch.setattr(report.common, "load_env", lambda: {})
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
