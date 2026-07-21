import sys
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

import common


@pytest.fixture
def con(tmp_path):
    return common.connect(tmp_path / "test.db")


def make_post(con, post_id, account, days_old, likes, comments,
              caption="тестовый пост", views=None, now=None):
    """Сидирование: пост возрастом days_old дней + один снапшот метрик."""
    now = now or common.now_utc()
    posted = (now - timedelta(days=days_old)).isoformat()
    common.save_posts(con, [{
        "post_id": post_id, "account": account, "caption": caption,
        "posted_at": posted, "likes": likes, "comments": comments, "views": views,
        "permalink": f"https://www.instagram.com/p/{post_id}/",
    }], fetched_at=now)
