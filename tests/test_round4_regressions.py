"""Targeted regressions from the second review, items 1 and 9."""
import re
from pathlib import Path
from types import SimpleNamespace

import pytest
import requests

import common
import fetch
import report
from conftest import make_post


@pytest.mark.parametrize("accounts", [["good", "bad"], ["good"], ["bad"]])
@pytest.mark.parametrize("has_posts", [False, True])
def test_weekly_exit_allows_reels_after_partial_collection(
        monkeypatch, con, tmp_path, capsys, accounts, has_posts):
    cfg = dict(common.DEFAULTS, median_min_posts=3,
               instagram={"source": "graph", "accounts": accounts})
    monkeypatch.setattr(common, "load_config", lambda: cfg)
    monkeypatch.setattr(common, "load_env", lambda: {
        "IG_ACCESS_TOKEN": "test-token", "IG_BUSINESS_ID": "1"})
    monkeypatch.setattr(common, "connect", lambda: con)
    monkeypatch.setattr(fetch.time, "sleep", lambda _: None)
    monkeypatch.setattr(report.subprocess, "run", lambda *a, **kw:
                        SimpleNamespace(returncode=0, stdout="", stderr=""))

    class Response:
        def raise_for_status(self):
            pass

        def json(self):
            return {}

    def get(*a, **kw):
        if "bad" in kw["params"]["fields"]:
            raise requests.Timeout("offline")
        return Response()

    monkeypatch.setattr(requests, "get", get)
    if has_posts:
        for account in accounts:
            for index in range(3):
                make_post(con, account + str(index), account, 10 + index, 10, 1)
            make_post(con, account, account, 1, 50, 5)
    target = tmp_path / "weekly.md"
    monkeypatch.setattr("sys.argv", ["report.py", "weekly", "--out", str(target)])
    status = 0
    try:
        report.main()
    except SystemExit as exc:
        status = exc.code

    if accounts == ["bad"]:
        assert status == 1
        assert not target.exists()
    else:
        assert status == 0  # nisha.sh only runs reels.py on success.
        text = target.read_text()
        assert "За неделю" in text
        if "bad" in accounts:
            assert "Частичный сбор" in text
            assert "частичный отказ" in capsys.readouterr().err
            assert "@bad" not in text
        else:
            assert "Частичный сбор" not in text
        if has_posts:
            assert "@good" in text


@pytest.mark.parametrize("name", ["7.log", "12.log"])
def test_review_logs_do_not_disclose_local_user_paths(name):
    log = Path(__file__).resolve().parents[1] / "docs" / "review-red" / name
    text = log.read_text()
    # Do not reproduce the sensitive match in pytest's own failure output.
    has_private_path = bool(re.search(
        r"/Users/[^/\s]+|/home/[^/\s]+|/private/var/folders/|pytest-of-(?!USER\b)[^/\s]+",
        text))
    assert not has_private_path, "Review log contains a local user path"
    assert "FAILED tests/" in text
    assert "failed" in text
