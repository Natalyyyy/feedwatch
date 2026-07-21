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
