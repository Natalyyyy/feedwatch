import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import fetch_tg

FIXTURE = (Path(__file__).parent / "fixtures" / "tg_web_sample.html").read_text(encoding="utf-8")
CHANNEL = FIXTURE.split('data-post="')[1].split("/")[0].lower()


def test_parse_count():
    assert fetch_tg.parse_count("13K") == 13000
    assert fetch_tg.parse_count("10.7K") == 10700
    assert fetch_tg.parse_count("1.2M") == 1200000
    assert fetch_tg.parse_count("419") == 419
    assert fetch_tg.parse_count("мусор") is None


def test_parse_page_extracts_posts():
    records, min_id = fetch_tg.parse_page(FIXTURE, CHANNEL)
    assert len(records) == 6
    assert min_id == min(int(r["post_id"].rsplit(":", 1)[1]) for r in records)
    r = records[0]
    assert r["platform"] == "telegram" and r["account"] == CHANNEL
    assert r["post_id"].startswith("tg:" + CHANNEL + ":")
    assert r["permalink"].startswith("https://t.me/" + CHANNEL + "/")
    assert r["comments"] is None
    assert isinstance(r["views"], int)
    assert "T" in r["posted_at"]          # ISO с датой и временем


def test_parse_subscribers():
    assert isinstance(fetch_tg.parse_subscribers(FIXTURE), int)


class FakeResp:
    def __init__(self, text):
        self.text = text
    def raise_for_status(self):
        pass


class FakeHttp:
    def __init__(self, pages):
        self.pages, self.calls = pages, []
    def get(self, url, **kwargs):
        self.calls.append((url, kwargs.get("params")))
        return FakeResp(self.pages.pop(0))


def test_fetch_web_single_page_enough():
    http = FakeHttp([FIXTURE])
    records, errors, subs = fetch_tg.fetch_web([CHANNEL], 3, session=http)
    assert len(records) == 3 and errors == {}
    assert subs[CHANNEL] == fetch_tg.parse_subscribers(FIXTURE)
    assert len(http.calls) == 1


def test_fetch_web_preview_unavailable():
    http = FakeHttp(["<html><body>Preview is unavailable</body></html>"])
    records, errors, subs = fetch_tg.fetch_web(["hidden"], 5, session=http)
    assert records == [] and errors == {"hidden": fetch_tg.PREVIEW_UNAVAILABLE}


def test_fetch_web_network_error():
    import requests

    class BrokenHttp:
        def get(self, url, **kwargs):
            raise requests.ConnectionError("boom")

    records, errors, subs = fetch_tg.fetch_web(["ch"], 5, session=BrokenHttp())
    assert records == [] and "ch" in errors
