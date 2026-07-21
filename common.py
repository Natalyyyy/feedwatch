"""Общие утилиты instawatch: .env, конфиг, база, медианы."""
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
DB_PATH = DATA_DIR / "instawatch.db"
CONFIG_PATH = ROOT / "config.json"
ENV_PATH = ROOT / ".env"

DEFAULTS = {
    "source": "apify",
    "accounts": [],
    "pulse_multiplier": 2.0,
    "median_window_days": 30,
    "median_min_posts": 12,
    "median_min_age_days": 2,
    "pulse_max_age_days": 3,
    "fetch_limit_pulse": 12,
    "fetch_limit_weekly": 25,
    "weekly_day": "sun",
    "weekly_time": "18:00",
    "pulse_time": "10:00",
}


def load_env(path=None):
    path = Path(path or ENV_PATH)
    env = {}
    if not path.exists():
        return env
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        value = value.strip().strip('"').strip("'")
        if value:
            env[key.strip()] = value
    return env


def load_config(path=None):
    path = Path(path or CONFIG_PATH)
    cfg = dict(DEFAULTS)
    if path.exists():
        cfg.update(json.loads(path.read_text(encoding="utf-8")))
    return cfg


def now_utc():
    return datetime.now(timezone.utc)


def parse_ts(value):
    """ISO-таймстамп → aware datetime. Терпит 'Z' и '+0000' (Python 3.9)."""
    value = value.replace("Z", "+00:00")
    if value.endswith("+0000"):
        value = value[:-5] + "+00:00"
    return datetime.fromisoformat(value)


SCHEMA = """
CREATE TABLE IF NOT EXISTS posts (
    post_id TEXT PRIMARY KEY,
    account TEXT NOT NULL,
    caption TEXT,
    posted_at TEXT NOT NULL,
    permalink TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    post_id TEXT NOT NULL,
    fetched_at TEXT NOT NULL,
    likes INTEGER,
    comments INTEGER,
    views INTEGER
);
CREATE TABLE IF NOT EXISTS alerted (
    post_id TEXT PRIMARY KEY,
    alerted_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS account_status (
    account TEXT PRIMARY KEY,
    last_ok TEXT,
    last_error TEXT
);
"""


def connect(db_path=None):
    path = Path(db_path or DB_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)
    return con


def save_posts(con, records, fetched_at=None):
    fetched = (fetched_at or now_utc()).isoformat() if not isinstance(fetched_at, str) else fetched_at
    for r in records:
        con.execute(
            "INSERT INTO posts (post_id, account, caption, posted_at, permalink) "
            "VALUES (?,?,?,?,?) "
            "ON CONFLICT(post_id) DO UPDATE SET caption=excluded.caption",
            (r["post_id"], r["account"], r["caption"], r["posted_at"], r["permalink"]),
        )
        con.execute(
            "INSERT INTO snapshots (post_id, fetched_at, likes, comments, views) "
            "VALUES (?,?,?,?,?)",
            (r["post_id"], fetched, r["likes"], r["comments"], r.get("views")),
        )
    con.commit()


def latest_metrics(con, account):
    """Последний снапшот каждого поста аккаунта, свежие посты первыми."""
    rows = con.execute(
        """
        SELECT p.post_id, p.account, p.caption, p.posted_at, p.permalink,
               s.likes, s.comments, s.views
        FROM posts p
        JOIN snapshots s ON s.post_id = p.post_id
        WHERE p.account = ?
          AND s.id = (SELECT MAX(id) FROM snapshots WHERE post_id = p.post_id)
        ORDER BY p.posted_at DESC
        """,
        (account,),
    ).fetchall()
    return [dict(r) for r in rows]


def was_alerted(con, post_id):
    return con.execute(
        "SELECT 1 FROM alerted WHERE post_id = ?", (post_id,)
    ).fetchone() is not None


def mark_alerted(con, post_ids, at=None):
    stamp = (at or now_utc()).isoformat()
    con.executemany(
        "INSERT OR IGNORE INTO alerted (post_id, alerted_at) VALUES (?,?)",
        [(pid, stamp) for pid in post_ids],
    )
    con.commit()


def set_account_status(con, account, error=None, at=None):
    stamp = (at or now_utc()).isoformat()
    if error is None:
        con.execute(
            "INSERT INTO account_status (account, last_ok, last_error) VALUES (?,?,NULL) "
            "ON CONFLICT(account) DO UPDATE SET last_ok=excluded.last_ok, last_error=NULL",
            (account, stamp),
        )
    else:
        con.execute(
            "INSERT INTO account_status (account, last_error) VALUES (?,?) "
            "ON CONFLICT(account) DO UPDATE SET last_error=excluded.last_error",
            (account, error),
        )
    con.commit()
