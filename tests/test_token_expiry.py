"""Срок жизни токена Meta.

Токен живёт 60 дней и не продлевается сам. Молча протухнув, он не ломает
прогон с грохотом — просто чужие аккаунты перестают собираться, и узнаёшь
об этом по пустому разделу в сводке. Предупреждать надо заранее.
"""
import fetch

NOW = 1_784_000_000  # произвольная точка отсчёта в тестах


class FakeResp:
    def __init__(self, payload): self._payload = payload
    def json(self): return self._payload


def test_days_left_counted_from_expiry(monkeypatch):
    monkeypatch.setattr(fetch.requests, "get",
                        lambda *a, **kw: FakeResp(
                            {"data": {"expires_at": NOW + 5 * 86400}}))

    assert fetch.token_days_left("EAA-токен", now=NOW) == 5


def test_never_expiring_token_is_not_a_worry(monkeypatch):
    """expires_at=0 у Meta значит «бессрочный» — тревожить не о чем."""
    monkeypatch.setattr(fetch.requests, "get",
                        lambda *a, **kw: FakeResp({"data": {"expires_at": 0}}))

    assert fetch.token_days_left("EAA-токен", now=NOW) is None


def test_unreadable_answer_does_not_break_the_run(monkeypatch):
    """Проверка срока — сервисная: её сбой не повод ронять сбор данных."""
    def boom(*a, **kw):
        raise fetch.requests.ConnectionError("meta недоступна")

    monkeypatch.setattr(fetch.requests, "get", boom)

    assert fetch.token_days_left("EAA-токен", now=NOW) is None


def test_expired_token_gives_negative_days(monkeypatch):
    monkeypatch.setattr(fetch.requests, "get",
                        lambda *a, **kw: FakeResp(
                            {"data": {"expires_at": NOW - 3 * 86400}}))

    assert fetch.token_days_left("EAA-токен", now=NOW) == -3


def test_now_defaults_to_current_time(monkeypatch):
    """Боевой вызов идёт без now — в нём и жила бы забытая зависимость."""
    monkeypatch.setattr(fetch.requests, "get",
                        lambda *a, **kw: FakeResp({"data": {"expires_at": 0}}))

    assert fetch.token_days_left("EAA-токен") is None
