import io

import common
import reels
import pytest
from test_reels import CFG, _post


def test_report_includes_saved_transcripts_on_repeat_run(tmp_path, monkeypatch):
    con = common.connect(tmp_path / "t.db")
    now = common.now_utc()
    for i in range(3):
        _post(con, f"base{i}", "acc", 10 + i, 10, now=now)
    _post(con, "saved", "acc", 1, 100, transcript="сохранённая речь", now=now)
    _post(con, "fresh", "acc", 2, 90, now=now)
    class VideoResponse:
        status_code = 200
        def __enter__(self): return self
        def __exit__(self, *_): pass
        @property
        def raw(self): return io.BytesIO(b"video")
        def iter_content(self, chunk_size): return iter((b"video",))
    class GroqResponse:
        status_code = 200
        def json(self): return {"text": "новая речь"}
    def post(*args, **kwargs): return GroqResponse()
    def run(args, **kwargs):
        if args[0] == "ffmpeg":
            from pathlib import Path
            Path(args[-1]).write_bytes(b"flac")
        return type("Proc", (), {"returncode": 0, "stderr": "", "stdout": ""})()
    get_calls = []
    def get(*a, **kw):
        get_calls.append(a[0])
        return VideoResponse()
    monkeypatch.setattr(reels.requests, "get", get)
    monkeypatch.setattr(reels.requests, "post", post)
    monkeypatch.setattr(reels.subprocess, "run", run)

    done, failed = reels.process(con, CFG, {"GROQ_API_KEY": "x"}, data_dir=tmp_path)
    report = reels.render(done, failed)
    second_done, second_failed = reels.process(
        con, CFG, {"GROQ_API_KEY": "x"}, data_dir=tmp_path)
    second_report = reels.render(second_done, second_failed)

    assert "сохранённая речь" in report
    assert "новая речь" in report
    assert "сохранённая речь" in second_report and "новая речь" in second_report
    assert get_calls == ["https://cdn/x.mp4"]
    assert [item["post_id"] for item in reels.candidates(con, CFG)] == []


def test_download_rejects_body_above_limit(tmp_path, monkeypatch):
    class Response:
        status_code = 200
        headers = {}
        raw = io.BytesIO(b"1234")
        def __enter__(self): return self
        def __exit__(self, *_): pass
        def iter_content(self, chunk_size): return iter((b"1234",))

    monkeypatch.setattr(reels, "MAX_DOWNLOAD_BYTES", 3, raising=False)
    monkeypatch.setattr(reels.requests, "get", lambda *a, **kw: Response())
    try:
        reels.download("https://cdn/video", tmp_path / "video.mp4")
    except reels.ReelError as exc:
        assert "размер" in str(exc)
    else:
        assert False, "oversized download accepted"
    assert not (tmp_path / "video.mp4").exists()


def test_ffmpeg_timeout_is_bounded_and_reported(monkeypatch):
    calls = []
    def run(*args, **kwargs):
        calls.append(kwargs)
        raise reels.subprocess.TimeoutExpired("ffmpeg", kwargs["timeout"])
    monkeypatch.setattr(reels.subprocess, "run", run)
    try:
        reels._ffmpeg(["-i", "video.mp4", "audio.flac"])
    except reels.ReelError as exc:
        assert "время" in str(exc).lower()
    else:
        assert False, "ffmpeg timeout was swallowed"
    assert calls[0]["timeout"] == reels.FFMPEG_TIMEOUT


def test_ffprobe_timeout_is_bounded(monkeypatch):
    calls = []
    def run(*args, **kwargs):
        calls.append(kwargs)
        raise reels.subprocess.TimeoutExpired("ffprobe", kwargs["timeout"])
    monkeypatch.setattr(reels.subprocess, "run", run)
    assert reels.probe_duration("video.mp4") == 0.0
    assert calls[0]["timeout"] == reels.FFPROBE_TIMEOUT


class StreamResponse:
    def __init__(self, status=200, chunks=()):
        self.status_code, self.chunks = status, chunks
    def __enter__(self): return self
    def __exit__(self, *_): pass
    def iter_content(self, chunk_size): return iter(self.chunks)


def test_download_happy_exact_limit_and_empty_body(tmp_path, monkeypatch):
    monkeypatch.setattr(reels, "MAX_DOWNLOAD_BYTES", 4)
    responses = iter((StreamResponse(chunks=(b"12", b"34")),
                      StreamResponse(chunks=())))
    monkeypatch.setattr(reels.requests, "get", lambda *a, **kw: next(responses))
    exact = tmp_path / "exact.mp4"
    reels.download("https://cdn/x", exact)
    assert exact.read_bytes() == b"1234"
    with pytest.raises(reels.ReelError, match="пустой файл"):
        reels.download("https://cdn/empty", tmp_path / "empty.mp4")


@pytest.mark.parametrize("status", [500, 429])
def test_download_http_errors(tmp_path, monkeypatch, status):
    monkeypatch.setattr(reels.requests, "get",
                        lambda *a, **kw: StreamResponse(status=status))
    with pytest.raises(reels.ReelError, match=str(status)):
        reels.download("https://cdn/x", tmp_path / "x.mp4")


def test_download_network_timeout_propagates(tmp_path, monkeypatch):
    def get(*args, **kwargs):
        assert kwargs["timeout"] == reels.DOWNLOAD_TIMEOUT
        raise reels.requests.Timeout("slow")
    monkeypatch.setattr(reels.requests, "get", get)
    with pytest.raises(reels.requests.Timeout):
        reels.download("https://cdn/x", tmp_path / "x.mp4")


def test_download_network_error_removes_partial_file(tmp_path, monkeypatch):
    class BrokenResponse(StreamResponse):
        def iter_content(self, chunk_size):
            yield b"partial"
            raise reels.requests.ConnectionError("disconnected")
    target = tmp_path / "partial.mp4"
    monkeypatch.setattr(reels.requests, "get", lambda *a, **kw: BrokenResponse())
    with pytest.raises(reels.requests.ConnectionError):
        reels.download("https://cdn/x", target)
    assert not target.exists()


def test_ffmpeg_success_and_nonzero(monkeypatch):
    monkeypatch.setattr(reels.subprocess, "run", lambda *a, **kw:
                        type("Proc", (), {"returncode": 0, "stderr": ""})())
    reels._ffmpeg(["-i", "video.mp4", "audio.flac"])
    monkeypatch.setattr(reels.subprocess, "run", lambda *a, **kw:
                        type("Proc", (), {"returncode": 1, "stderr": "bad input"})())
    with pytest.raises(reels.ReelError, match="bad input"):
        reels._ffmpeg(["-i", "video.mp4", "audio.flac"])


def test_ffprobe_success_and_malformed(monkeypatch):
    monkeypatch.setattr(reels.subprocess, "run", lambda *a, **kw:
                        type("Proc", (), {"stdout": "12.5"})())
    assert reels.probe_duration("video.mp4") == 12.5
    monkeypatch.setattr(reels.subprocess, "run", lambda *a, **kw:
                        type("Proc", (), {"stdout": "unknown"})())
    assert reels.probe_duration("video.mp4") == 0.0


def test_empty_database_and_saved_edge_cases(tmp_path, monkeypatch):
    con = common.connect(tmp_path / "empty.db")
    monkeypatch.setattr(reels.requests, "get",
                        lambda *a, **kw: pytest.fail("no video should be fetched"))
    done, failed = reels.process(con, CFG, {"GROQ_API_KEY": "x"}, data_dir=tmp_path)
    assert done == failed == []
    now = common.now_utc()
    for i in range(3):
        _post(con, f"base{i}", "acc", 10 + i, 10, now=now)
    _post(con, "silent", "acc", 1, 100, transcript="", now=now)
    _post(con, "old", "acc", 20, 100, transcript="старая речь", now=now)
    done, failed = reels.process(con, CFG, {"GROQ_API_KEY": "x"}, data_dir=tmp_path)
    assert not failed
    report = reels.render(done, failed)
    assert "без слов" in report
    assert "старая речь" not in report


def test_failed_new_download_keeps_saved_transcript_in_report(tmp_path, monkeypatch):
    con = common.connect(tmp_path / "t.db")
    now = common.now_utc()
    for i in range(3):
        _post(con, f"base{i}", "acc", 10 + i, 10, now=now)
    _post(con, "saved", "acc", 1, 100, transcript="прошлая речь", now=now)
    _post(con, "new", "acc", 1, 90, now=now)
    monkeypatch.setattr(reels.requests, "get",
                        lambda *a, **kw: (_ for _ in ()).throw(reels.requests.ConnectionError("offline")))
    done, failed = reels.process(con, CFG, {"GROQ_API_KEY": "x"}, data_dir=tmp_path)
    assert "прошлая речь" in reels.render(done, failed)
    assert len(failed) == 1 and failed[0]["post_id"] == "new"
