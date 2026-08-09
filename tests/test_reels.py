from datetime import timedelta

import common
import reels


CFG = {"median_window_days": 30, "median_min_posts": 3, "median_min_age_days": 2}


def _post(con, post_id, account, days_ago, likes, *, media_type="VIDEO",
          media_url="https://cdn/x.mp4", transcript=None, now=None):
    now = now or common.now_utc()
    posted = (now - timedelta(days=days_ago)).isoformat()
    con.execute(
        "INSERT INTO posts (post_id, account, platform, caption, posted_at, permalink,"
        " media_type, media_url, transcript) VALUES (?,?,?,?,?,?,?,?,?)",
        (post_id, account, "instagram", "подпись", posted,
         f"https://instagram.com/reel/{post_id}", media_type, media_url, transcript))
    con.execute("INSERT INTO snapshots (post_id, fetched_at, likes, comments, views)"
                " VALUES (?,?,?,?,?)", (post_id, now.isoformat(), likes, 1, None))
    con.commit()


def test_hallucination_becomes_empty():
    assert reels.clean_transcript("Субтитры сделал DimaTorzok") == ""
    assert reels.clean_transcript("  Продолжение следует...  ") == ""
    assert reels.clean_transcript("") == ""


def test_hallucination_verb_forms():
    """09.08.2026 сквозь список фраз прошло «создавал» — ловим любую форму."""
    for text in ("Субтитры создавал DimaTorzok",
                 "Субтитры создал DimaTorzok",
                 "субтитры делала Иванова",
                 "Редактор субтитров А.Синецкая"):
        assert reels.clean_transcript(text) == "", text


def test_real_speech_survives():
    text = "Привет, меня зовут Оля, мне 39 лет и я обожаю буткэмп"
    assert reels.clean_transcript(text) == text


def test_long_text_mentioning_subtitles_survives():
    """Слово-маркер внутри длинной реплики — это речь, а не титры."""
    text = ("Я вчера час убила на то, чтобы вшить субтитры в рилс, а потом поняла, "
            "что приложение делает это само за две секунды, и мне было обидно до слёз")
    assert reels.clean_transcript(text) == text


def test_candidates_rank_by_ratio_not_likes(tmp_path):
    con = common.connect(tmp_path / "t.db")
    # Крупный аккаунт: медиана 1000, свежий пост ровно по медиане.
    for i in range(3):
        _post(con, f"big{i}", "big", 10 + i, 1000)
    _post(con, "big-new", "big", 1, 1000)
    # Маленький: медиана 10, свежий пост ×5.
    for i in range(3):
        _post(con, f"small{i}", "small", 10 + i, 10)
    _post(con, "small-new", "small", 1, 50)

    got = reels.candidates(con, CFG, days=7, limit=2)
    assert [c["post_id"] for c in got] == ["small-new", "big-new"]


def test_candidates_skip_processed_and_photos(tmp_path):
    con = common.connect(tmp_path / "t.db")
    for i in range(3):
        _post(con, f"base{i}", "acc", 10 + i, 10)
    _post(con, "done", "acc", 1, 100, transcript="уже расшифровано")
    _post(con, "silent", "acc", 1, 100, transcript="")     # немой, но разобранный
    _post(con, "photo", "acc", 1, 100, media_type="IMAGE")
    _post(con, "dead", "acc", 1, 100, media_url=None)
    _post(con, "fresh", "acc", 1, 90)

    got = reels.candidates(con, CFG, days=7, limit=10)
    assert [c["post_id"] for c in got] == ["fresh"]


def test_candidates_respect_window(tmp_path):
    con = common.connect(tmp_path / "t.db")
    for i in range(3):
        _post(con, f"base{i}", "acc", 20 + i, 10)
    _post(con, "old", "acc", 30, 100)
    got = reels.candidates(con, CFG, days=7, limit=10)
    assert got == []


def test_rotate_removes_old_dirs(tmp_path):
    now = common.now_utc()
    fresh = tmp_path / now.strftime("%Y-%m-%d")
    old = tmp_path / (now - timedelta(days=40)).strftime("%Y-%m-%d")
    for d in (fresh, old):
        d.mkdir(parents=True)
        (d / "video.mp4").write_bytes(b"x")
    reels.rotate(tmp_path, keep_days=14, now=now)
    assert fresh.exists() and not old.exists()


def test_render_marks_silent_reel():
    """У немого ролика расшифровки нет — отправляем смотреть сам ролик."""
    done = [{"account": "a", "ratio": 2.0, "posted_at": "2026-08-08T10:00:00+0000",
             "permalink": "https://instagram.com/reel/x", "caption": "подпись",
             "transcript": "", "frames": []}]
    text = reels.render(done, [])
    assert "без слов" in text and "https://instagram.com/reel/x" in text
    assert "кадры" not in text


def test_render_shows_frames_when_asked():
    done = [{"account": "a", "ratio": 2.0, "posted_at": "2026-08-08T10:00:00+0000",
             "permalink": "https://x", "caption": "подпись", "transcript": "речь",
             "frames": ["/tmp/a/frame_01.jpg"]}]
    assert "кадры (1)" in reels.render(done, [])
