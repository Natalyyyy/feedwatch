import telegram


def test_split_short():
    assert telegram.split_message("привет") == ["привет"]


def test_split_on_line_boundaries():
    text = "\n".join("строка {}".format(i) for i in range(1000))
    chunks = telegram.split_message(text, max_len=200)
    assert all(len(c) <= 200 for c in chunks)
    assert "\n".join(chunks) == text  # ничего не потеряли


def test_split_giant_line():
    chunks = telegram.split_message("х" * 500, max_len=200)
    assert all(len(c) <= 200 for c in chunks)
    assert "".join(chunks) == "х" * 500


def test_send_posts_each_chunk(monkeypatch):
    sent = []
    class FakeResp:
        def raise_for_status(self): pass
    def fake_post(url, json=None, timeout=None):
        sent.append(json["text"])
        return FakeResp()
    monkeypatch.setattr(telegram.requests, "post", fake_post)
    telegram.send("a\n" * 3000, "tok", "42")
    assert len(sent) > 1
