"""Общие утилиты instawatch: .env, конфиг, база, медианы."""
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
DB_PATH = DATA_DIR / "feedwatch.db"
CONFIG_PATH = ROOT / "config.json"
ENV_PATH = ROOT / ".env"

DEFAULTS = {
    "instagram": None,
    "telegram": None,
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


def normalize_config(cfg):
    """Плоский legacy-формат (source/accounts в корне) → секция instagram.

    Корневые legacy-ключи не удаляем — их никто больше не читает."""
    if not cfg.get("instagram") and (cfg.get("accounts") or cfg.get("source")):
        cfg["instagram"] = {"source": cfg.get("source") or "apify",
                            "accounts": cfg.get("accounts") or []}
    cfg.setdefault("instagram", None)
    cfg.setdefault("telegram", None)
    return cfg


def load_config(path=None):
    path = Path(path or CONFIG_PATH)
    cfg = dict(DEFAULTS)
    if path.exists():
        cfg.update(json.loads(path.read_text(encoding="utf-8")))
    return normalize_config(cfg)


def active_accounts(cfg):
    """[(platform, account), ...] по конфигу, аккаунты в lower."""
    out = []
    ig = cfg.get("instagram") or {}
    for a in ig.get("accounts", []):
        out.append(("instagram", a.lower()))
    tg = cfg.get("telegram") or {}
    for c in tg.get("channels", []):
        out.append(("telegram", c.lower()))
    return out


def now_utc():
    return datetime.now(timezone.utc)


def parse_ts(value):
    """ISO-таймстамп → aware datetime. Терпит 'Z' и '+0000' (Python 3.9)."""
    value = value.replace("Z", "+00:00")
    if value.endswith("+0000"):
        value = value[:-5] + "+00:00"
    return datetime.fromisoformat(value)


ACCOUNT_STATUS_SCHEMA = """
CREATE TABLE IF NOT EXISTS account_status (
    platform TEXT NOT NULL DEFAULT 'instagram',
    account TEXT NOT NULL,
    last_ok TEXT,
    last_error TEXT,
    subscribers INTEGER,
    PRIMARY KEY (platform, account)
);
"""

SCHEMA = """
CREATE TABLE IF NOT EXISTS posts (
    post_id TEXT PRIMARY KEY,
    account TEXT NOT NULL,
    platform TEXT NOT NULL DEFAULT 'instagram',
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
""" + ACCOUNT_STATUS_SCHEMA


def connect(db_path=None):
    path = Path(db_path or DB_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    legacy = path.parent / "instawatch.db"
    if path.name == "feedwatch.db" and not path.exists() and legacy.exists():
        legacy.rename(path)
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)
    _migrate(con)
    return con


def _migrate(con):
    cols = {r["name"] for r in con.execute("PRAGMA table_info(posts)")}
    if "platform" not in cols:
        con.execute("ALTER TABLE posts ADD COLUMN platform TEXT NOT NULL DEFAULT 'instagram'")
    cols = {r["name"] for r in con.execute("PRAGMA table_info(account_status)")}
    if "platform" not in cols:
        con.execute("ALTER TABLE account_status RENAME TO account_status_legacy")
        con.executescript(ACCOUNT_STATUS_SCHEMA)
        con.execute("INSERT INTO account_status (platform, account, last_ok, last_error) "
                    "SELECT 'instagram', account, last_ok, last_error FROM account_status_legacy")
        con.execute("DROP TABLE account_status_legacy")
    con.commit()


def save_posts(con, records, fetched_at=None):
    fetched = (fetched_at or now_utc()).isoformat() if not isinstance(fetched_at, str) else fetched_at
    for r in records:
        con.execute(
            "INSERT INTO posts (post_id, account, platform, caption, posted_at, permalink) "
            "VALUES (?,?,?,?,?,?) "
            "ON CONFLICT(post_id) DO UPDATE SET caption=excluded.caption",
            (r["post_id"], r["account"], r.get("platform", "instagram"), r["caption"],
             r["posted_at"], r["permalink"]),
        )
        con.execute(
            "INSERT INTO snapshots (post_id, fetched_at, likes, comments, views) "
            "VALUES (?,?,?,?,?)",
            (r["post_id"], fetched, r["likes"], r["comments"], r.get("views")),
        )
    con.commit()


def latest_metrics(con, account, platform="instagram"):
    """Последний снапшот каждого поста аккаунта, свежие посты первыми."""
    rows = con.execute(
        """
        SELECT p.post_id, p.account, p.platform, p.caption, p.posted_at, p.permalink,
               s.likes, s.comments, s.views
        FROM posts p
        JOIN snapshots s ON s.post_id = p.post_id
        WHERE p.account = ?
          AND p.platform = ?
          AND s.id = (SELECT MAX(id) FROM snapshots WHERE post_id = p.post_id)
        ORDER BY p.posted_at DESC
        """,
        (account, platform),
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


def _median(values):
    values = sorted(values)
    n = len(values)
    if n == 0:
        return None
    mid = n // 2
    if n % 2:
        return float(values[mid])
    return (values[mid - 1] + values[mid]) / 2.0


def account_medians(con, account, cfg, now=None, platform="instagram"):
    """Медианы лайков/комментов/просмотров аккаунта по окну из конфига."""
    now = now or now_utc()
    min_age = now - timedelta(days=cfg["median_min_age_days"])
    window_start = now - timedelta(days=cfg["median_window_days"])
    settled = [p for p in latest_metrics(con, account, platform=platform)
               if parse_ts(p["posted_at"]) <= min_age]      # свежие первыми
    in_window = [p for p in settled if parse_ts(p["posted_at"]) >= window_start]
    if len(in_window) < cfg["median_min_posts"]:
        in_window = settled[:cfg["median_min_posts"]]
    likes = [p["likes"] for p in in_window if p["likes"] is not None]
    comments = [p["comments"] for p in in_window if p["comments"] is not None]
    views = [p["views"] for p in in_window if p["views"] is not None]
    return {"likes": _median(likes), "comments": _median(comments),
            "views": _median(views), "n_posts": len(in_window)}


def set_account_status(con, account, error=None, at=None, platform="instagram",
                       subscribers=None):
    stamp = (at or now_utc()).isoformat()
    if error is None:
        con.execute(
            "INSERT INTO account_status (platform, account, last_ok, last_error, subscribers) "
            "VALUES (?,?,?,NULL,?) "
            "ON CONFLICT(platform, account) DO UPDATE SET last_ok=excluded.last_ok, "
            "last_error=NULL, "
            "subscribers=COALESCE(excluded.subscribers, account_status.subscribers)",
            (platform, account, stamp, subscribers),
        )
    else:
        con.execute(
            "INSERT INTO account_status (platform, account, last_error) VALUES (?,?,?) "
            "ON CONFLICT(platform, account) DO UPDATE SET last_error=excluded.last_error",
            (platform, account, error),
        )
    con.commit()
