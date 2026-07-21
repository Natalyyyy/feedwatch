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


def test_parse_page_sums_non_paid_reactions():
    """Regression for reaction-undercount bug: custom/premium-emoji reactions
    render as <tg-emoji>...N</tg-emoji> with NO trailing </i>, so a regex
    anchored on </i> silently drops them. Ground truth hand-verified against
    the raw fixture HTML for post 419: 127 (fire) + 84 (heart) + 25 (thumbs
    up) + 3 (unicorn) + 2 (alien) + 2 (custom tg-emoji, no <i> tag) + 1
    (clap) = 244, with the paid star reaction (1) correctly excluded."""
    records, _ = fetch_tg.parse_page(FIXTURE, CHANNEL)
    likes_by_id = {r["post_id"]: r["likes"] for r in records}
    expected = {
        "tg:{}:419".format(CHANNEL): 244,
        "tg:{}:420".format(CHANNEL): 167,
        "tg:{}:421".format(CHANNEL): 258,
        "tg:{}:422".format(CHANNEL): 122,
        "tg:{}:423".format(CHANNEL): 270,
        "tg:{}:424".format(CHANNEL): 151,
    }
    assert likes_by_id == expected


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


SECOND_PAGE_HTML = (
    '<div class="tgme_channel_info">header, discarded by split</div>'
    '<div class="tgme_widget_message_wrap js-widget_message_wrap">'
    '<div class="tgme_widget_message" data-post="solokumi/418" data-view="x">'
    '<div class="tgme_widget_message_text js-message_text">Older post text</div>'
    '<span class="tgme_widget_message_views">5K</span>'
    '<a class="tgme_widget_message_date" href="https://t.me/solokumi/418">'
    '<time datetime="2026-05-15T09:00:00+00:00" class="time">09:00</time></a>'
    '</div></div>'
)


def test_fetch_web_paginates_and_dedupes_across_pages():
    """Page 1 (fixture) has 6 posts (419-424, min_id=419). With a limit of 7
    (> page-1 count), fetch_web must fetch a second, before=419-paginated
    page and merge in the older post it finds, then stop (7 >= limit) —
    exactly 2 HTTP calls, no dedup collisions, no runaway pagination."""
    http = FakeHttp([FIXTURE, SECOND_PAGE_HTML])
    records, errors, subs = fetch_tg.fetch_web([CHANNEL], 7, session=http)

    assert len(http.calls) == 2
    first_params, second_params = http.calls[0][1], http.calls[1][1]
    assert first_params is None
    assert second_params == {"before": 419}

    assert errors == {}
    assert len(records) == 7
    ids = {r["post_id"] for r in records}
    assert "tg:{}:418".format(CHANNEL) in ids


def test_fetch_web_network_error():
    import requests

    class BrokenHttp:
        def get(self, url, **kwargs):
            raise requests.ConnectionError("boom")

    records, errors, subs = fetch_tg.fetch_web(["ch"], 5, session=BrokenHttp())
    assert records == [] and "ch" in errors
