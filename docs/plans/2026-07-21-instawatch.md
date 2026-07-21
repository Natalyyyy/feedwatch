# instawatch — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Скилл для Claude Code (публичный GitHub-репо), который мониторит чужие публичные Instagram-аккаунты через Apify или Meta Graph API и шлёт в Telegram еженедельный отчёт + ежедневный пульс по медианной логике.

**Architecture:** Плоский набор Python-скриптов вокруг SQLite: `fetch.py` (два адаптера → нормализованные записи → снапшоты в базу), `report.py` (пульс/еженедельный отчёт, вся медианная математика в `common.py`), `telegram.py` (доставка), `schedule.py` (launchd/cron). SKILL.md — онбординг и ручные триггеры для Claude. Спека: `ObsidianVault/projects/vibe-coding/docs/{vibe-coding} {plan} instawatch дизайн – 2026-07-21.md`.

**Tech Stack:** Python 3.9+ (стандартная библиотека + `requests`), SQLite, pytest (только dev), Telegram Bot API, Apify API, Meta Graph API `business_discovery`.

## Global Constraints

- Runtime-зависимость ровно одна: `requests`. Никакого python-dotenv (`.env` парсим руками), pandas и т.п. pytest — только для разработки, в README пользователю не нужен.
- Совместимость с Python 3.9 (маковский CLT-python): никаких `X | Y` в аннотациях, `datetime.fromisoformat` не понимает `Z` и `+0000` — таймстампы нормализуем.
- **Каждая строка-пост в любом отчёте обязана содержать permalink** — это зашито в форматтеры и покрыто тестами.
- Все оценки «залетело» — только в кратных медианы своего аккаунта (`×2.4 от медианы`), не в голых цифрах.
- Скрытые лайки = `NULL` в базе (Apify отдаёт `-1`, Graph не отдаёт поле) — везде обрабатываем `None`.
- Все пользовательские строки (отчёты, ошибки, README, SKILL.md) — по-русски.
- Секреты в `.env` (в `.gitignore`), настройки в `config.json` (в `.gitignore`), в репо — только `.env.example` и `config.example.json`.
- Пути в коде — только через `common.ROOT` (= папка скрипта), никаких хардкодов на машину Наташи.
- Разработка: `~/Projects/instawatch/`, venv `python3.11 -m venv venv`, тесты `venv/bin/pytest`.

---

### Task 1: Каркас репо + `common.py` (env/config)

**Files:**
- Create: `~/Projects/instawatch/.gitignore`, `.env.example`, `config.example.json`, `common.py`, `tests/conftest.py`, `tests/test_common.py`

**Interfaces:**
- Produces: `common.ROOT`, `common.DATA_DIR`, `common.load_env(path=None) -> dict`, `common.load_config(path=None) -> dict`, `common.DEFAULTS`

- [ ] **Step 1: Каркас**

```bash
mkdir -p ~/Projects/instawatch/{tests,prompts,docs/plans}
cd ~/Projects/instawatch && git init
/opt/homebrew/bin/python3.11 -m venv venv
venv/bin/pip install requests pytest
```

`.gitignore`:
```
.env
config.json
data/
__pycache__/
venv/
.pytest_cache/
.DS_Store
```

`.env.example`:
```
# --- Источник данных: нужен ОДИН из двух блоков ---
# Вариант 1: Apify (любые публичные аккаунты, платно)
APIFY_TOKEN=

# Вариант 2: Meta Graph API (бесплатно, только бизнес/креатор-аккаунты)
IG_ACCESS_TOKEN=
IG_BUSINESS_ID=

# --- Telegram (свой бот через @BotFather) ---
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=
```

`config.example.json`:
```json
{
  "source": "apify",
  "accounts": ["natgeo", "nasa"],
  "pulse_multiplier": 2.0,
  "median_window_days": 30,
  "median_min_posts": 12,
  "median_min_age_days": 2,
  "pulse_max_age_days": 3,
  "fetch_limit_pulse": 12,
  "fetch_limit_weekly": 25,
  "weekly_day": "sun",
  "weekly_time": "18:00",
  "pulse_time": "10:00"
}
```

- [ ] **Step 2: Failing-тест на env/config**

`tests/conftest.py`:
```python
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
```

`tests/test_common.py`:
```python
import common


def test_load_env_parses_and_ignores_junk(tmp_path):
    envfile = tmp_path / ".env"
    envfile.write_text(
        "# комментарий\nAPIFY_TOKEN=abc123\nTELEGRAM_CHAT_ID='42'\n\nмусор без равно\n",
        encoding="utf-8",
    )
    env = common.load_env(envfile)
    assert env == {"APIFY_TOKEN": "abc123", "TELEGRAM_CHAT_ID": "42"}


def test_load_env_missing_file(tmp_path):
    assert common.load_env(tmp_path / "nope") == {}


def test_load_config_merges_defaults(tmp_path):
    cfg_file = tmp_path / "config.json"
    cfg_file.write_text('{"accounts": ["someblog"], "pulse_multiplier": 3}', encoding="utf-8")
    cfg = common.load_config(cfg_file)
    assert cfg["accounts"] == ["someblog"]
    assert cfg["pulse_multiplier"] == 3
    assert cfg["median_window_days"] == 30  # дефолт
```

- [ ] **Step 3: Запустить, убедиться что падает**

Run: `venv/bin/pytest tests/test_common.py -v` → FAIL (`No module named 'common'` / нет `connect`) — conftest импортирует common, поэтому упадёт на импорте: нормально.

- [ ] **Step 4: `common.py` — первая часть**

```python
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
```

(Функции `connect`/`save_posts` появятся в Task 2 — тест на них пока не пишем, conftest их использует только внутри `make_post`, который в этом таске не вызывается. Чтобы conftest импортировался, добавь в конец `common.py` заглушки НЕ НАДО — `make_post` дергает `common.save_posts` только при вызове, импорт пройдёт.)

- [ ] **Step 5: Прогнать тесты** — `venv/bin/pytest tests/test_common.py -v` → 3 PASS

- [ ] **Step 6: Commit**

```bash
git add -A && git commit -m "feat: scaffold + env/config loading"
```

---

### Task 2: `common.py` — база данных

**Files:**
- Modify: `common.py`
- Test: `tests/test_db.py`

**Interfaces:**
- Produces: `common.connect(db_path=None) -> sqlite3.Connection` (row_factory=Row, создаёт схему), `common.save_posts(con, records, fetched_at=None)`, `common.latest_metrics(con, account) -> list[dict]`, `common.was_alerted(con, post_id) -> bool`, `common.mark_alerted(con, post_ids, at=None)`, `common.set_account_status(con, account, error=None, at=None)`
- Формат записи (единый для адаптеров и отчётов): `{"post_id": str, "account": str(lower), "caption": str, "posted_at": iso-str, "likes": int|None, "comments": int|None, "views": int|None, "permalink": str}`. `views` — публичные просмотры рилса/видео: Apify отдаёт, Graph по чужим — нет (всегда `None`); фото — `None`. Просмотры только показываем в отчётах, в медианы/сигналы v1 не входят.

- [ ] **Step 1: Failing-тесты**

`tests/test_db.py`:
```python
import common
from conftest import make_post


def test_save_and_latest_metrics(con):
    make_post(con, "p1", "acc", days_old=5, likes=100, comments=10)
    make_post(con, "p1", "acc", days_old=5, likes=150, comments=12)  # второй снапшот
    make_post(con, "p2", "acc", days_old=1, likes=50, comments=5)
    rows = common.latest_metrics(con, "acc")
    assert len(rows) == 2
    by_id = {r["post_id"]: r for r in rows}
    assert by_id["p1"]["likes"] == 150            # последний снапшот, не первый
    assert by_id["p2"]["permalink"].startswith("https://www.instagram.com/p/")
    assert rows[0]["post_id"] == "p2"             # сортировка: свежие первыми


def test_hidden_likes_stored_as_none(con):
    make_post(con, "p1", "acc", days_old=3, likes=None, comments=7)
    assert common.latest_metrics(con, "acc")[0]["likes"] is None


def test_alerted_dedup(con):
    assert not common.was_alerted(con, "p1")
    common.mark_alerted(con, ["p1", "p2"])
    common.mark_alerted(con, ["p1"])  # повторно — не падает
    assert common.was_alerted(con, "p1")
    assert not common.was_alerted(con, "p3")


def test_views_stored(con):
    make_post(con, "reel1", "acc", days_old=3, likes=10, comments=1, views=5000)
    assert common.latest_metrics(con, "acc")[0]["views"] == 5000


def test_account_status(con):
    common.set_account_status(con, "acc", error="не найден")
    row = con.execute("SELECT * FROM account_status").fetchone()
    assert "не найден" in row["last_error"]
    common.set_account_status(con, "acc")  # успех сбрасывает ошибку
    row = con.execute("SELECT * FROM account_status").fetchone()
    assert row["last_error"] is None and row["last_ok"]
```

- [ ] **Step 2: Запустить** — `venv/bin/pytest tests/test_db.py -v` → FAIL (`no attribute 'connect'`)

- [ ] **Step 3: Реализация — добавить в `common.py`**

```python
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
```

- [ ] **Step 4: Прогнать** — `venv/bin/pytest tests/ -v` → все PASS

- [ ] **Step 5: Commit** — `git add -A && git commit -m "feat: sqlite schema + snapshots + alert dedup"`

---

### Task 3: `common.py` — медианы

**Files:**
- Modify: `common.py`
- Test: `tests/test_medians.py`

**Interfaces:**
- Produces: `common.account_medians(con, account, cfg, now=None) -> {"likes": float|None, "comments": float|None, "n_posts": int}`
- Правила из спеки: окно `median_window_days`; посты моложе `median_min_age_days` не участвуют (ещё растут); если в окне < `median_min_posts` — добираем более старыми постами до минимума; скрытые лайки (`None`) в медиану лайков не входят.

- [ ] **Step 1: Failing-тесты**

`tests/test_medians.py`:
```python
import common
from conftest import make_post

CFG = dict(common.DEFAULTS, median_min_posts=3)


def test_median_basic(con):
    for i, likes in enumerate([100, 200, 300]):
        make_post(con, f"p{i}", "acc", days_old=5 + i, likes=likes, comments=10 * (i + 1))
    med = common.account_medians(con, "acc", CFG)
    assert med["likes"] == 200
    assert med["comments"] == 20
    assert med["n_posts"] == 3


def test_fresh_posts_excluded(con):
    make_post(con, "fresh", "acc", days_old=1, likes=9999, comments=999)  # моложе 2 дней
    for i, likes in enumerate([100, 200, 300]):
        make_post(con, f"p{i}", "acc", days_old=5 + i, likes=likes, comments=10)
    assert common.account_medians(con, "acc", CFG)["likes"] == 200


def test_min_posts_backfill_beyond_window(con):
    # в 30-дневном окне только 1 пост — добираем старыми до median_min_posts=3
    make_post(con, "new", "acc", days_old=10, likes=100, comments=1)
    make_post(con, "old1", "acc", days_old=40, likes=200, comments=2)
    make_post(con, "old2", "acc", days_old=50, likes=300, comments=3)
    make_post(con, "old3", "acc", days_old=60, likes=400, comments=4)
    med = common.account_medians(con, "acc", CFG)
    assert med["n_posts"] == 3
    assert med["likes"] == 200  # три самых свежих подходящих: 100, 200, 300


def test_hidden_likes_skipped_in_likes_median(con):
    make_post(con, "h1", "acc", days_old=5, likes=None, comments=10)
    make_post(con, "p1", "acc", days_old=6, likes=100, comments=20)
    make_post(con, "p2", "acc", days_old=7, likes=300, comments=30)
    med = common.account_medians(con, "acc", CFG)
    assert med["likes"] == 200      # медиана по 100 и 300
    assert med["comments"] == 20    # комменты считаются по всем трём


def test_no_posts_returns_none(con):
    med = common.account_medians(con, "acc", CFG)
    assert med["likes"] is None and med["comments"] is None and med["n_posts"] == 0
```

- [ ] **Step 2: Запустить** — FAIL (`no attribute 'account_medians'`)

- [ ] **Step 3: Реализация — добавить в `common.py`**

```python
def _median(values):
    values = sorted(values)
    n = len(values)
    if n == 0:
        return None
    mid = n // 2
    if n % 2:
        return float(values[mid])
    return (values[mid - 1] + values[mid]) / 2.0


def account_medians(con, account, cfg, now=None):
    """Медианы лайков/комментов аккаунта по окну из конфига."""
    now = now or now_utc()
    min_age = now - timedelta(days=cfg["median_min_age_days"])
    window_start = now - timedelta(days=cfg["median_window_days"])
    settled = [p for p in latest_metrics(con, account)
               if parse_ts(p["posted_at"]) <= min_age]      # свежие первыми
    in_window = [p for p in settled if parse_ts(p["posted_at"]) >= window_start]
    if len(in_window) < cfg["median_min_posts"]:
        in_window = settled[:cfg["median_min_posts"]]
    likes = [p["likes"] for p in in_window if p["likes"] is not None]
    comments = [p["comments"] for p in in_window if p["comments"] is not None]
    return {"likes": _median(likes), "comments": _median(comments),
            "n_posts": len(in_window)}
```

- [ ] **Step 4: Прогнать** — `venv/bin/pytest tests/ -v` → все PASS
- [ ] **Step 5: Commit** — `git commit -am "feat: per-account median logic (window + min-posts + hidden likes)"`

---

### Task 4: `fetch.py` — нормализация и Apify-адаптер

**Files:**
- Create: `fetch.py`
- Test: `tests/test_fetch_apify.py`

**Interfaces:**
- Consumes: `common.save_posts`, `common.set_account_status`
- Produces: `fetch.normalize_apify(item) -> record`, `fetch.fetch_apify(accounts, limit, token) -> (records, errors: dict)`, `fetch.run_fetch(limit, cfg=None, env=None, con=None) -> (records, errors)`, `fetch.TokenExpiredError`, CLI `python3 fetch.py --limit N`
- Сеть в тестах мокается через `monkeypatch` на `fetch.requests`.

- [ ] **Step 1: Failing-тесты**

`tests/test_fetch_apify.py`:
```python
import fetch

APIFY_ITEM = {
    "shortCode": "Cxyz1",
    "ownerUsername": "SomeBlog",
    "caption": "Запустили новый продукт!",
    "timestamp": "2026-07-19T10:00:00.000Z",
    "likesCount": 500,
    "commentsCount": 40,
    "url": "https://www.instagram.com/p/Cxyz1/",
}


def test_normalize_apify():
    r = fetch.normalize_apify(APIFY_ITEM)
    assert r["post_id"] == "Cxyz1"
    assert r["account"] == "someblog"           # lower
    assert r["posted_at"] == "2026-07-19T10:00:00.000+00:00"
    assert r["likes"] == 500 and r["comments"] == 40
    assert r["views"] is None                    # фото — просмотров нет
    assert r["permalink"] == "https://www.instagram.com/p/Cxyz1/"


def test_normalize_apify_hidden_likes():
    assert fetch.normalize_apify({**APIFY_ITEM, "likesCount": -1})["likes"] is None


def test_normalize_apify_reel_views():
    r = fetch.normalize_apify({**APIFY_ITEM, "videoPlayCount": 10000})
    assert r["views"] == 10000
    # фолбэк на videoViewCount, если play-счётчика нет
    r2 = fetch.normalize_apify({**APIFY_ITEM, "videoViewCount": 7000})
    assert r2["views"] == 7000


class FakeResp:
    status_code = 200
    def __init__(self, payload): self._payload = payload
    def raise_for_status(self): pass
    def json(self): return self._payload


def test_fetch_apify_missing_account_is_error(monkeypatch):
    monkeypatch.setattr(fetch.requests, "post", lambda *a, **kw: FakeResp([APIFY_ITEM]))
    records, errors = fetch.fetch_apify(["someblog", "ghost"], limit=12, token="t")
    assert len(records) == 1
    assert "ghost" in errors
```

- [ ] **Step 2: Запустить** — FAIL (`No module named 'fetch'`)

- [ ] **Step 3: Реализация `fetch.py`**

```python
"""Сбор постов Instagram (Apify или Meta Graph API) → SQLite."""
import argparse
import sys

import requests

import common

APIFY_URL = ("https://api.apify.com/v2/acts/apify~instagram-scraper/"
             "run-sync-get-dataset-items")
GRAPH_URL = "https://graph.facebook.com/v21.0/{ig_id}"


class TokenExpiredError(Exception):
    """Meta Graph API вернул код 190 — long-lived токен протух."""


def normalize_apify(item):
    likes = item.get("likesCount")
    if likes is not None and likes < 0:  # -1 = лайки скрыты
        likes = None
    return {
        "post_id": item["shortCode"],
        "account": item["ownerUsername"].lower(),
        "caption": item.get("caption") or "",
        "posted_at": item["timestamp"].replace("Z", "+00:00"),
        "likes": likes,
        "comments": item.get("commentsCount"),
        "views": item.get("videoPlayCount") or item.get("videoViewCount"),
        "permalink": item.get("url")
                     or "https://www.instagram.com/p/{}/".format(item["shortCode"]),
    }


def fetch_apify(accounts, limit, token):
    payload = {
        "directUrls": ["https://www.instagram.com/{}/".format(a) for a in accounts],
        "resultsType": "posts",
        "resultsLimit": limit,
    }
    resp = requests.post(APIFY_URL, params={"token": token}, json=payload, timeout=600)
    resp.raise_for_status()
    records, errors = [], {}
    for item in resp.json():
        if item.get("error"):
            errors[str(item.get("username", "?")).lower()] = str(item["error"])
            continue
        if "shortCode" not in item:
            continue
        records.append(normalize_apify(item))
    got = {r["account"] for r in records}
    for a in accounts:
        if a.lower() not in got and a.lower() not in errors:
            errors[a.lower()] = "нет данных (закрыт / переименован / не найден?)"
    return records, errors
```

- [ ] **Step 4: Прогнать** — тесты Task 4 PASS
- [ ] **Step 5: Commit** — `git add -A && git commit -m "feat: apify adapter + normalization"`

---

### Task 5: `fetch.py` — Graph-адаптер, run_fetch, CLI

**Files:**
- Modify: `fetch.py`
- Test: `tests/test_fetch_graph.py`

**Interfaces:**
- Produces: `fetch.normalize_graph(account, media) -> record`, `fetch.fetch_graph(accounts, limit, ig_id, token) -> (records, errors)`; `run_fetch` роутит по `cfg["source"]` (`"apify"` / `"metagraph"`), пишет в базу и `account_status`, пробрасывает `TokenExpiredError` наверх.

- [ ] **Step 1: Failing-тесты**

`tests/test_fetch_graph.py`:
```python
import pytest

import common
import fetch

MEDIA = {
    "id": "1789_222",
    "caption": "Пост про запуск",
    "timestamp": "2026-07-19T10:00:00+0000",
    "like_count": 300,
    "comments_count": 25,
    "permalink": "https://www.instagram.com/p/Cabc/",
}


class FakeResp:
    def __init__(self, payload): self._payload = payload
    def json(self): return self._payload


def test_normalize_graph_and_ts():
    r = fetch.normalize_graph("SomeBlog", MEDIA)
    assert r["account"] == "someblog"
    assert common.parse_ts(r["posted_at"]).year == 2026  # '+0000' переварен
    assert r["permalink"] == MEDIA["permalink"]
    assert r["views"] is None  # business_discovery не отдаёт просмотры чужих


def test_normalize_graph_hidden_likes():
    media = {k: v for k, v in MEDIA.items() if k != "like_count"}
    assert fetch.normalize_graph("acc", media)["likes"] is None


def test_token_expired_raises(monkeypatch):
    payload = {"error": {"code": 190, "message": "Error validating access token"}}
    monkeypatch.setattr(fetch.requests, "get", lambda *a, **kw: FakeResp(payload))
    with pytest.raises(fetch.TokenExpiredError):
        fetch.fetch_graph(["acc"], 12, "ig123", "tok")


def test_unavailable_account_collected(monkeypatch):
    payload = {"error": {"code": 110, "message": "Cannot find the IG user"}}
    monkeypatch.setattr(fetch.requests, "get", lambda *a, **kw: FakeResp(payload))
    records, errors = fetch.fetch_graph(["ghost"], 12, "ig123", "tok")
    assert records == [] and "ghost" in errors


def test_run_fetch_persists_and_sets_status(monkeypatch, con, tmp_path):
    monkeypatch.setattr(fetch, "fetch_apify",
                        lambda accounts, limit, token:
                        ([fetch.normalize_apify({
                            "shortCode": "C1", "ownerUsername": "acc",
                            "caption": "x", "timestamp": "2026-07-19T10:00:00.000Z",
                            "likesCount": 10, "commentsCount": 1,
                            "url": "https://www.instagram.com/p/C1/"})],
                         {"ghost": "нет данных"}))
    cfg = dict(common.DEFAULTS, accounts=["acc", "ghost"], source="apify")
    records, errors = fetch.run_fetch(12, cfg=cfg, env={"APIFY_TOKEN": "t"}, con=con)
    assert len(common.latest_metrics(con, "acc")) == 1
    row = con.execute("SELECT last_error FROM account_status WHERE account='ghost'").fetchone()
    assert row["last_error"]
```

- [ ] **Step 2: Запустить** — FAIL (`no attribute 'normalize_graph'`)

- [ ] **Step 3: Реализация — добавить в `fetch.py`**

```python
def normalize_graph(account, media):
    return {
        "post_id": media["id"],
        "account": account.lower(),
        "caption": media.get("caption") or "",
        "posted_at": media["timestamp"],  # parse_ts переварит '+0000' при чтении
        "likes": media.get("like_count"),  # нет поля = лайки скрыты
        "comments": media.get("comments_count"),
        "views": None,  # business_discovery не отдаёт просмотры по чужим аккаунтам
        "permalink": media["permalink"],
    }


def fetch_graph(accounts, limit, ig_id, token):
    records, errors = [], {}
    for account in accounts:
        fields = ("business_discovery.username({}){{media.limit({})"
                  "{{id,caption,like_count,comments_count,permalink,timestamp}}}}"
                  ).format(account, limit)
        resp = requests.get(GRAPH_URL.format(ig_id=ig_id),
                            params={"fields": fields, "access_token": token},
                            timeout=60)
        data = resp.json()
        if "error" in data:
            err = data["error"]
            if err.get("code") == 190:
                raise TokenExpiredError(err.get("message", "token expired"))
            errors[account.lower()] = err.get("message", "неизвестная ошибка")
            continue
        media = data.get("business_discovery", {}).get("media", {}).get("data", [])
        records.extend(normalize_graph(account, m) for m in media)
    return records, errors


def run_fetch(limit, cfg=None, env=None, con=None):
    cfg = cfg or common.load_config()
    env = env or common.load_env()
    con = con or common.connect()
    accounts = cfg["accounts"]
    if cfg["source"] == "apify":
        records, errors = fetch_apify(accounts, limit, env["APIFY_TOKEN"])
    else:
        records, errors = fetch_graph(accounts, limit,
                                      env["IG_BUSINESS_ID"], env["IG_ACCESS_TOKEN"])
    common.save_posts(con, records)
    for a in accounts:
        a = a.lower()
        common.set_account_status(con, a, error=errors.get(a))
    return records, errors


def main():
    ap = argparse.ArgumentParser(description="Сбор постов в базу instawatch")
    ap.add_argument("--limit", type=int, default=12,
                    help="постов на аккаунт (30 для холодного старта)")
    args = ap.parse_args()
    records, errors = run_fetch(args.limit)
    print("Сохранено постов: {}".format(len(records)))
    for a, e in errors.items():
        print("⚠️ @{}: {}".format(a, e), file=sys.stderr)


if __name__ == "__main__":
    main()
```

**Внимание:** `posted_at` из Graph хранится как `'...+0000'` — все места чтения дат обязаны идти через `common.parse_ts` (в Task 2–3 это уже так).

- [ ] **Step 4: Прогнать всё** — `venv/bin/pytest tests/ -v` → PASS
- [ ] **Step 5: Commit** — `git commit -am "feat: graph adapter + run_fetch + CLI"`

---

### Task 6: `telegram.py`

**Files:**
- Create: `telegram.py`
- Test: `tests/test_telegram.py`

**Interfaces:**
- Produces: `telegram.split_message(text, max_len=4000) -> list[str]`, `telegram.send(text, token, chat_id)` (режет на куски, шлёт sendMessage, plain text, `disable_web_page_preview=True`)

- [ ] **Step 1: Failing-тесты**

`tests/test_telegram.py`:
```python
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
```

- [ ] **Step 2: Запустить** — FAIL

- [ ] **Step 3: Реализация `telegram.py`**

```python
"""Отправка отчётов в Telegram ботом пользователя."""
import requests

MAX_LEN = 4000  # лимит API 4096, оставляем запас


def split_message(text, max_len=MAX_LEN):
    if len(text) <= max_len:
        return [text]
    chunks, current = [], ""
    for line in text.split("\n"):
        candidate = current + "\n" + line if current else line
        if len(candidate) > max_len:
            if current:
                chunks.append(current)
            while len(line) > max_len:  # сверхдлинная строка — режем жёстко
                chunks.append(line[:max_len])
                line = line[max_len:]
            current = line
        else:
            current = candidate
    if current:
        chunks.append(current)
    return chunks


def send(text, token, chat_id):
    for chunk in split_message(text):
        resp = requests.post(
            "https://api.telegram.org/bot{}/sendMessage".format(token),
            json={"chat_id": chat_id, "text": chunk,
                  "disable_web_page_preview": True},
            timeout=30,
        )
        resp.raise_for_status()
```

- [ ] **Step 4: Прогнать** — PASS
- [ ] **Step 5: Commit** — `git add -A && git commit -m "feat: telegram delivery with chunking"`

---

### Task 7: `report.py` — ежедневный пульс

**Files:**
- Create: `report.py`
- Test: `tests/test_pulse.py`

**Interfaces:**
- Consumes: `common.account_medians`, `common.latest_metrics`, `common.was_alerted`, `common.mark_alerted`, `fetch.run_fetch`, `fetch.TokenExpiredError`, `telegram.send`
- Produces: `report.pulse_signals(con, cfg, now=None) -> list[dict]` (сигнал = пост + `ratio`, `metric` ("likes"/"comments"), `likes_hidden`), `report.format_pulse(signals) -> str`, вспомогательные `report.format_ratio(value, median) -> float|None`, `report.post_age_days(post, now) -> float`, `report.preview(caption, limit=120) -> str`. CLI: `python3 report.py pulse [--send] [--no-fetch]`.

- [ ] **Step 1: Failing-тесты**

`tests/test_pulse.py`:
```python
import common
import report
from conftest import make_post

CFG = dict(common.DEFAULTS, accounts=["acc"], median_min_posts=3, pulse_multiplier=2.0)


def seed_baseline(con):
    for i, likes in enumerate([100, 100, 100]):
        make_post(con, "base{}".format(i), "acc", days_old=5 + i, likes=likes, comments=10)


def test_signal_above_median(con):
    seed_baseline(con)
    make_post(con, "hit", "acc", days_old=1, likes=250, comments=15)  # ×2.5
    signals = report.pulse_signals(con, CFG)
    assert len(signals) == 1
    s = signals[0]
    assert s["post_id"] == "hit" and s["metric"] == "likes"
    assert abs(s["ratio"] - 2.5) < 0.01


def test_no_signal_below_threshold(con):
    seed_baseline(con)
    make_post(con, "meh", "acc", days_old=1, likes=150, comments=15)  # ×1.5 < 2
    assert report.pulse_signals(con, CFG) == []


def test_old_posts_ignored(con):
    seed_baseline(con)
    make_post(con, "oldhit", "acc", days_old=10, likes=999, comments=99)
    assert report.pulse_signals(con, CFG) == []


def test_dedup_after_mark(con):
    seed_baseline(con)
    make_post(con, "hit", "acc", days_old=1, likes=250, comments=15)
    common.mark_alerted(con, ["hit"])
    assert report.pulse_signals(con, CFG) == []


def test_hidden_likes_falls_back_to_comments(con):
    seed_baseline(con)
    make_post(con, "hid", "acc", days_old=1, likes=None, comments=30)  # комменты ×3
    signals = report.pulse_signals(con, CFG)
    assert len(signals) == 1 and signals[0]["metric"] == "comments"
    assert signals[0]["likes_hidden"]


def test_format_pulse_has_permalink_every_signal(con):
    seed_baseline(con)
    make_post(con, "hit", "acc", days_old=1, likes=250, comments=15)
    text = report.format_pulse(report.pulse_signals(con, CFG))
    assert "https://www.instagram.com/p/hit/" in text
    assert "×2.5" in text
```

- [ ] **Step 2: Запустить** — FAIL (`No module named 'report'`)

- [ ] **Step 3: Реализация `report.py` (пульс + CLI-каркас)**

```python
"""Отчёты instawatch: ежедневный пульс и еженедельный разбор."""
import argparse
import subprocess
import sys
from datetime import timedelta
from pathlib import Path

import common
import fetch
import telegram


def format_ratio(value, median):
    if value is None or median is None or median == 0:
        return None
    return value / median


def post_age_days(post, now):
    return (now - common.parse_ts(post["posted_at"])).total_seconds() / 86400


def preview(caption, limit=120):
    text = " ".join((caption or "").split())
    return text[:limit] + ("…" if len(text) > limit else "")


def pulse_signals(con, cfg, now=None):
    now = now or common.now_utc()
    k = cfg["pulse_multiplier"]
    signals = []
    for account in cfg["accounts"]:
        account = account.lower()
        med = common.account_medians(con, account, cfg, now=now)
        for post in common.latest_metrics(con, account):
            if post_age_days(post, now) > cfg["pulse_max_age_days"]:
                continue
            if common.was_alerted(con, post["post_id"]):
                continue
            likes_hidden = post["likes"] is None
            if likes_hidden:
                ratio, metric = format_ratio(post["comments"], med["comments"]), "comments"
            else:
                ratio, metric = format_ratio(post["likes"], med["likes"]), "likes"
            if ratio is not None and ratio >= k:
                signals.append({**post, "ratio": ratio, "metric": metric,
                                "likes_hidden": likes_hidden})
    return signals


def format_pulse(signals):
    lines = ["🔥 Инстаграм-пульс: залетает выше медианы", ""]
    for s in signals:
        metric_ru = "комментам" if s["metric"] == "comments" else "лайкам"
        hidden = " (лайки скрыты)" if s["likes_hidden"] else ""
        likes = "—" if s["likes"] is None else s["likes"]
        lines.append("@{}{} — ×{:.1f} от медианы по {}".format(
            s["account"], hidden, s["ratio"], metric_ru))
        stats = "❤️ {} 💬 {}".format(likes, s["comments"])
        if s.get("views"):
            stats += " ▶️ {}".format(s["views"])
        lines.append(stats)
        if preview(s["caption"]):
            lines.append(preview(s["caption"]))
        lines.append(s["permalink"])
        lines.append("")
    return "\n".join(lines).strip()


TOKEN_EXPIRED_MSG = (
    "⚠️ instawatch: токен Meta Graph API протух (он живёт 60 дней).\n"
    "Скажи Claude: «обнови токен инстаграма» — он проведёт по шагам."
)


def main():
    ap = argparse.ArgumentParser(description="Отчёты instawatch")
    ap.add_argument("mode", choices=["pulse", "weekly"])
    ap.add_argument("--send", action="store_true", help="отправить в Telegram")
    ap.add_argument("--no-fetch", action="store_true", help="только по данным из базы")
    args = ap.parse_args()

    cfg, env, con = common.load_config(), common.load_env(), common.connect()

    if not args.no_fetch:
        limit = cfg["fetch_limit_pulse"] if args.mode == "pulse" else cfg["fetch_limit_weekly"]
        try:
            fetch.run_fetch(limit, cfg=cfg, env=env, con=con)
        except fetch.TokenExpiredError:
            if args.send and env.get("TELEGRAM_BOT_TOKEN"):
                telegram.send(TOKEN_EXPIRED_MSG, env["TELEGRAM_BOT_TOKEN"],
                              env["TELEGRAM_CHAT_ID"])
            print(TOKEN_EXPIRED_MSG, file=sys.stderr)
            sys.exit(1)

    if args.mode == "pulse":
        signals = pulse_signals(con, cfg)
        if not signals:
            print("Тихо: сигналов нет.")
            return
        text = format_pulse(signals)
        common.mark_alerted(con, [s["post_id"] for s in signals])
    else:
        text = build_weekly(con, cfg)  # Task 8

    print(text)
    if args.send and env.get("TELEGRAM_BOT_TOKEN"):
        telegram.send(text, env["TELEGRAM_BOT_TOKEN"], env["TELEGRAM_CHAT_ID"])


if __name__ == "__main__":
    main()
```

(Функция `build_weekly` появится в Task 8; до тех пор `report.py weekly` упадёт — тесты пульса это не трогают.)

- [ ] **Step 4: Прогнать** — тесты пульса PASS
- [ ] **Step 5: Commit** — `git add -A && git commit -m "feat: daily pulse with median logic + dedup"`

---

### Task 8: `report.py` — еженедельный отчёт

**Files:**
- Modify: `report.py`
- Create: `prompts/weekly.md`
- Test: `tests/test_weekly.py`

**Interfaces:**
- Produces: `report.weekly_data(con, cfg, now=None) -> (per_account: dict, quiet: list, unavailable: list)`, `report.format_top(all_posts, key, title, emoji, n=10) -> list[str]`, `report.claude_summary(per_account, prompt_path) -> str|None`, `report.build_weekly(con, cfg, now=None) -> str`
- Посты недели получают поля `like_ratio`, `comment_ratio` (float|None), `fresh` (bool, моложе `median_min_age_days` — пометка «⏳ ещё растёт»).

- [ ] **Step 1: Failing-тесты**

`tests/test_weekly.py`:
```python
import common
import report
from conftest import make_post

CFG = dict(common.DEFAULTS, accounts=["acc", "quietacc"], median_min_posts=3)


def seed(con):
    for i, likes in enumerate([100, 100, 100]):
        make_post(con, "base{}".format(i), "acc", days_old=8 + i, likes=likes, comments=10)
    make_post(con, "wk1", "acc", days_old=3, likes=300, comments=5, caption="залетевший пост")
    make_post(con, "wk2", "acc", days_old=1, likes=50, comments=40, caption="свежий пост")


def test_weekly_data_split(con):
    seed(con)
    common.set_account_status(con, "ghost", error="не найден")
    per_account, quiet, unavailable = report.weekly_data(con, CFG)
    assert set(per_account) == {"acc"}
    assert len(per_account["acc"]) == 2          # только посты за 7 дней
    assert quiet == ["quietacc"]
    assert unavailable[0]["account"] == "ghost"


def test_ratios_and_fresh_flag(con):
    seed(con)
    per_account, _, _ = report.weekly_data(con, CFG)
    by_id = {p["post_id"]: p for p in per_account["acc"]}
    assert abs(by_id["wk1"]["like_ratio"] - 3.0) < 0.01
    assert by_id["wk2"]["fresh"] is True
    assert by_id["wk1"]["fresh"] is False


def test_build_weekly_sections_and_permalinks(con, monkeypatch):
    monkeypatch.setattr(report, "claude_summary", lambda *a, **kw: None)
    seed(con)
    text = report.build_weekly(con, CFG)
    assert "Топ по лайкам" in text and "Топ по комментам" in text
    assert "😴" in text and "@quietacc" in text
    assert "⏳ ещё растёт" in text
    # каждый пост со ссылкой
    assert text.count("https://www.instagram.com/p/wk1/") >= 1
    assert text.count("https://www.instagram.com/p/wk2/") >= 1


def test_claude_summary_fallback_on_failure(monkeypatch, tmp_path):
    prompt = tmp_path / "weekly.md"
    prompt.write_text("промпт", encoding="utf-8")
    def boom(*a, **kw):
        raise OSError("claude not found")
    monkeypatch.setattr(report.subprocess, "run", boom)
    assert report.claude_summary({"acc": [{"caption": "x"}]}, prompt) is None
```

- [ ] **Step 2: Запустить** — FAIL (`no attribute 'weekly_data'`)

- [ ] **Step 3: Реализация — добавить в `report.py`**

```python
def weekly_data(con, cfg, now=None):
    now = now or common.now_utc()
    week_ago = now - timedelta(days=7)
    per_account, quiet = {}, []
    for account in cfg["accounts"]:
        account = account.lower()
        med = common.account_medians(con, account, cfg, now=now)
        posts = [p for p in common.latest_metrics(con, account)
                 if common.parse_ts(p["posted_at"]) >= week_ago]
        for p in posts:
            p["like_ratio"] = format_ratio(p["likes"], med["likes"])
            p["comment_ratio"] = format_ratio(p["comments"], med["comments"])
            p["fresh"] = post_age_days(p, now) < cfg["median_min_age_days"]
        if posts:
            per_account[account] = posts
        else:
            quiet.append(account)
    unavailable = [dict(r) for r in con.execute(
        "SELECT account, last_error FROM account_status WHERE last_error IS NOT NULL")]
    return per_account, quiet, unavailable


def format_top(all_posts, key, title, emoji, n=10):
    ranked = sorted((p for p in all_posts if p[key] is not None),
                    key=lambda p: p[key], reverse=True)
    lines = ["{} {}".format(emoji, title), ""]
    for p in ranked[:n]:
        growing = " ⏳ ещё растёт" if p["fresh"] else ""
        likes = "—" if p["likes"] is None else p["likes"]
        lines.append("@{} — ×{:.1f} от медианы{}".format(p["account"], p[key], growing))
        stats = "❤️ {} 💬 {}".format(likes, p["comments"])
        if p.get("views"):
            stats += " ▶️ {}".format(p["views"])
        lines.append(stats)
        if preview(p["caption"]):
            lines.append(preview(p["caption"]))
        lines.append(p["permalink"])
        lines.append("")
    return lines


def claude_summary(per_account, prompt_path):
    """Тематическая выжимка недели через headless Claude. Любой сбой → None."""
    digest = []
    for account, posts in per_account.items():
        digest.append("## @{}".format(account))
        digest.extend("- " + preview(p["caption"], 500) for p in posts)
    prompt = Path(prompt_path).read_text(encoding="utf-8") + "\n\n" + "\n".join(digest)
    try:
        result = subprocess.run(
            ["claude", "-p", "--output-format", "text"],
            input=prompt, capture_output=True, text=True, timeout=300,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        pass
    return None


def build_weekly(con, cfg, now=None):
    per_account, quiet, unavailable = weekly_data(con, cfg, now=now)
    all_posts = [p for posts in per_account.values() for p in posts]
    lines = ["📊 Инстаграм за неделю", ""]
    if per_account:
        summary = claude_summary(per_account, common.ROOT / "prompts" / "weekly.md")
        if summary:
            lines += ["🧠 О чём писали", "", summary, ""]
    if all_posts:
        lines += format_top(all_posts, "like_ratio", "Топ по лайкам (×N от медианы аккаунта)", "❤️")
        lines += format_top(all_posts, "comment_ratio", "Топ по комментам (×N от медианы аккаунта)", "💬")
    else:
        lines.append("За неделю ни одного нового поста.")
    if quiet:
        lines.append("😴 Молчали: " + ", ".join("@{}".format(a) for a in quiet))
    if unavailable:
        lines.append("⚠️ Не удалось получить: " + "; ".join(
            "@{} ({})".format(u["account"], u["last_error"]) for u in unavailable))
    return "\n".join(lines).strip()
```

`prompts/weekly.md`:
```markdown
Ты — аналитик соцсетей. Ниже подписи к постам Instagram-аккаунтов за неделю,
сгруппированные по аккаунтам.

Напиши секцию «О чём писали» для отчёта в Telegram:
- 3–6 пунктов о главных темах недели: кто про что писал, какие темы
  повторялись у нескольких аккаунтов, какие форматы/заходы заметны.
- Пиши по-русски, коротко и конкретно, без воды и без вводных фраз.
- Опирайся ТОЛЬКО на тексты ниже, ничего не выдумывай. Если по текстам
  тема неясна — пропусти, не догадывайся.
- Формат: простые строки-пункты с «— », без markdown-заголовков
  (отчёт уходит в Telegram плоским текстом).

Тексты постов:
```

- [ ] **Step 4: Прогнать всё** — `venv/bin/pytest tests/ -v` → PASS
- [ ] **Step 5: Commit** — `git add -A && git commit -m "feat: weekly report (claude summary + tops + quiet/unavailable)"`

---

### Task 9: `schedule.py` — launchd/cron

**Files:**
- Create: `schedule.py`
- Test: `tests/test_schedule.py`

**Interfaces:**
- Consumes: `common.load_config`, `common.ROOT`, `common.DATA_DIR`
- Produces: `schedule.plist_xml(label, mode, hour, minute, weekday=None) -> str`, `schedule.cron_lines(cfg) -> list[str]`, `schedule.parse_time("18:00") -> (18, 0)`; CLI `python3 schedule.py install|remove|status`
- launchd Weekday и cron: воскресенье = 0.

- [ ] **Step 1: Failing-тесты**

`tests/test_schedule.py`:
```python
import common
import schedule


def test_parse_time():
    assert schedule.parse_time("18:05") == (18, 5)


def test_plist_weekly_has_weekday():
    xml = schedule.plist_xml("com.instawatch.weekly", "weekly", 18, 0, weekday=0)
    assert "<string>weekly</string>" in xml
    assert "<key>Weekday</key><integer>0</integer>" in xml
    assert "<string>--send</string>" in xml
    assert "report.py" in xml


def test_plist_pulse_no_weekday():
    xml = schedule.plist_xml("com.instawatch.pulse", "pulse", 10, 0)
    assert "Weekday" not in xml


def test_cron_lines():
    cfg = dict(common.DEFAULTS, weekly_day="sun", weekly_time="18:00", pulse_time="10:30")
    pulse, weekly = schedule.cron_lines(cfg)
    assert pulse.startswith("30 10 * * * ")
    assert weekly.startswith("0 18 * * 0 ")
    assert pulse.endswith("# instawatch") and weekly.endswith("# instawatch")
```

- [ ] **Step 2: Запустить** — FAIL

- [ ] **Step 3: Реализация `schedule.py`**

```python
"""Расписание instawatch: launchd (Mac) или cron (Linux)."""
import argparse
import platform
import subprocess
import sys
from pathlib import Path

import common

LABEL_PULSE = "com.instawatch.pulse"
LABEL_WEEKLY = "com.instawatch.weekly"
CRON_MARK = "# instawatch"
WEEKDAYS = {"sun": 0, "mon": 1, "tue": 2, "wed": 3, "thu": 4, "fri": 5, "sat": 6}


def parse_time(value):
    hour, minute = value.split(":")
    return int(hour), int(minute)


def _python():
    return sys.executable or "python3"


def plist_xml(label, mode, hour, minute, weekday=None):
    weekday_xml = ("<key>Weekday</key><integer>{}</integer>".format(weekday)
                   if weekday is not None else "")
    return """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>{label}</string>
  <key>ProgramArguments</key><array>
    <string>{python}</string>
    <string>{report}</string>
    <string>{mode}</string>
    <string>--send</string>
  </array>
  <key>StartCalendarInterval</key><dict>
    <key>Hour</key><integer>{hour}</integer>
    <key>Minute</key><integer>{minute}</integer>
    {weekday_xml}
  </dict>
  <key>StandardOutPath</key><string>{log}</string>
  <key>StandardErrorPath</key><string>{errlog}</string>
</dict></plist>
""".format(label=label, python=_python(), report=common.ROOT / "report.py",
           mode=mode, hour=hour, minute=minute, weekday_xml=weekday_xml,
           log=common.DATA_DIR / (mode + ".log"),
           errlog=common.DATA_DIR / (mode + ".err.log"))


def cron_lines(cfg):
    ph, pm = parse_time(cfg["pulse_time"])
    wh, wm = parse_time(cfg["weekly_time"])
    wd = WEEKDAYS[cfg["weekly_day"]]
    report = common.ROOT / "report.py"
    return [
        "{} {} * * * {} {} pulse --send {}".format(pm, ph, _python(), report, CRON_MARK),
        "{} {} * * {} {} {} weekly --send {}".format(wm, wh, wd, _python(), report, CRON_MARK),
    ]


def install(cfg):
    common.DATA_DIR.mkdir(parents=True, exist_ok=True)
    if platform.system() == "Darwin":
        agents = Path.home() / "Library" / "LaunchAgents"
        agents.mkdir(parents=True, exist_ok=True)
        ph, pm = parse_time(cfg["pulse_time"])
        wh, wm = parse_time(cfg["weekly_time"])
        jobs = [(LABEL_PULSE, "pulse", ph, pm, None),
                (LABEL_WEEKLY, "weekly", wh, wm, WEEKDAYS[cfg["weekly_day"]])]
        for label, mode, h, m, wd in jobs:
            path = agents / (label + ".plist")
            path.write_text(plist_xml(label, mode, h, m, wd), encoding="utf-8")
            subprocess.run(["launchctl", "unload", str(path)], capture_output=True)
            subprocess.run(["launchctl", "load", str(path)], check=True)
        print("Готово (launchd): пульс ежедневно в {}, отчёт по {} в {}.".format(
            cfg["pulse_time"], cfg["weekly_day"], cfg["weekly_time"]))
    else:
        current = subprocess.run(["crontab", "-l"], capture_output=True, text=True)
        lines = [l for l in (current.stdout or "").splitlines() if CRON_MARK not in l]
        lines += cron_lines(cfg)
        subprocess.run(["crontab", "-"], input="\n".join(lines) + "\n",
                       text=True, check=True)
        print("Готово (cron): пульс ежедневно, отчёт еженедельно.")


def remove():
    if platform.system() == "Darwin":
        agents = Path.home() / "Library" / "LaunchAgents"
        for label in (LABEL_PULSE, LABEL_WEEKLY):
            path = agents / (label + ".plist")
            if path.exists():
                subprocess.run(["launchctl", "unload", str(path)], capture_output=True)
                path.unlink()
        print("Расписание снято (launchd).")
    else:
        current = subprocess.run(["crontab", "-l"], capture_output=True, text=True)
        lines = [l for l in (current.stdout or "").splitlines() if CRON_MARK not in l]
        subprocess.run(["crontab", "-"], input="\n".join(lines) + "\n",
                       text=True, check=True)
        print("Расписание снято (cron).")


def status():
    if platform.system() == "Darwin":
        out = subprocess.run(["launchctl", "list"], capture_output=True, text=True).stdout
        found = [l for l in out.splitlines() if "instawatch" in l]
    else:
        out = subprocess.run(["crontab", "-l"], capture_output=True, text=True).stdout
        found = [l for l in out.splitlines() if CRON_MARK in l]
    print("\n".join(found) if found else "Расписание не установлено.")


def main():
    ap = argparse.ArgumentParser(description="Расписание instawatch")
    ap.add_argument("action", choices=["install", "remove", "status"])
    args = ap.parse_args()
    if args.action == "install":
        install(common.load_config())
    elif args.action == "remove":
        remove()
    else:
        status()


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Прогнать** — PASS
- [ ] **Step 5: Commit** — `git add -A && git commit -m "feat: schedule install/remove (launchd + cron)"`

---

### Task 10: SKILL.md + README.md

**Files:**
- Create: `SKILL.md`, `README.md`

Полный текст обоих файлов — ниже; писать как есть, адаптируя только если интерфейсы предыдущих тасков разошлись с планом.

- [ ] **Step 1: `SKILL.md`**

```markdown
---
name: instawatch
description: Мониторинг чужих публичных Instagram-аккаунтов с отчётами в Telegram. Триггеры — «настрой инстаграм-мониторинг», «отчёт по инстаграму», «что залетело в инстаграме», «проверь пульс инстаграма», «добавь/убери аккаунт из мониторинга», «обнови токен инстаграма».
---

# instawatch — мониторинг Instagram-аккаунтов

Все команды выполняются из папки скилла (`cd` в папку, где лежит этот файл).
Python-скрипты: `fetch.py` (сбор), `report.py` (отчёты), `schedule.py` (расписание).

## Онбординг (первый запуск: нет `config.json` или `.env`)

Веди пользователя по шагам, по одному вопросу за раз, на русском:

1. **Python.** Проверь `python3 --version` (нужен 3.9+). Нет — на Маке
   предложи `xcode-select --install`, на Linux — пакетный менеджер.
   Затем `python3 -c "import requests"` — если нет, `python3 -m pip install requests`.
2. **Источник данных.** Объясни выбор:
   - **Apify** — любые публичные аккаунты; платно (~$2.5–3 за 1000 постов,
     при 10 аккаунтах с ежедневным пульсом ≈ $8–10/мес; бесплатного кредита
     $5/мес хватит попробовать). Нужен токен: apify.com → Sign up →
     Settings → Integrations → Personal API token.
   - **Meta Graph API** — бесплатно, но мониторить можно только
     бизнес/креатор-аккаунты, и нужен свой Instagram Business/Creator аккаунт,
     привязанный к странице Facebook. Шаги: developers.facebook.com →
     Create App (Business) → добавить продукт Instagram Graph API →
     Graph API Explorer → выдать права `instagram_basic`,
     `business_management`, `pages_show_list` → сгенерировать токен →
     обменять на long-lived (живёт 60 дней). `IG_BUSINESS_ID` — id своего
     IG-аккаунта: запрос `me/accounts` → `?fields=instagram_business_account`.
3. **Telegram.** Бот: @BotFather → /newbot → токен. chat_id: пользователь пишет
   боту любое сообщение, затем `curl https://api.telegram.org/bot<TOKEN>/getUpdates`
   → `message.chat.id`.
4. **Аккаунты.** Список username без @. Запиши всё в `.env` (по образцу
   `.env.example`) и `config.json` (по образцу `config.example.json`).
5. **Холодный старт.** `python3 fetch.py --limit 30` — база наполняется,
   медианы считаются с первого дня. Покажи пользователю, сколько постов
   собралось и какие аккаунты недоступны.
6. **Режим.** Спроси: ручной запуск или автоматика?
   - Ручной — ничего не делать, объясни триггеры («отчёт по инстаграму»,
     «проверь пульс»).
   - Автоматика — уточни времена (дефолты в config.json), затем
     `python3 schedule.py install`. Предупреди: еженедельный отчёт
     запускает headless Claude и тратит лимиты подписки пользователя.

## Ручные команды

- «отчёт по инстаграму» → `python3 report.py weekly` (показать в чате;
  спросить, отправить ли в ТГ — тогда с `--send`)
- «проверь пульс» → `python3 report.py pulse` (аналогично)
- «добавь @X в мониторинг» → дописать в `config.json` → `python3 fetch.py --limit 30`
  (холодный старт для нового аккаунта)
- «убери @X» → удалить из `config.json`
- «выключи/включи автоматику» → `python3 schedule.py remove` / `install`
- «как там мониторинг» → `python3 schedule.py status` + хвосты `data/*.log`

## Обновление токена Meta («обнови токен инстаграма»)

Токен живёт 60 дней. Веди по шагам: Graph API Explorer → сгенерировать
новый user token с теми же правами → обменять на long-lived:
`https://graph.facebook.com/v21.0/oauth/access_token?grant_type=fb_exchange_token&client_id=<APP_ID>&client_secret=<APP_SECRET>&fb_exchange_token=<КОРОТКИЙ_ТОКЕН>`
→ записать новый токен в `.env` (`IG_ACCESS_TOKEN`) → проверить:
`python3 fetch.py --limit 3`.

## Важно

- Ссылка на пост обязана быть в каждой строке отчёта — это уже зашито в код,
  не переписывай форматтеры.
- Все сравнения — в кратных медианы аккаунта, не в абсолютных цифрах.
- Секреты только в `.env`, не в config.json и не в git.
```

- [ ] **Step 2: `README.md`**

```markdown
# instawatch

Мониторинг чужих публичных Instagram-аккаунтов для Claude Code:
еженедельный отчёт в Telegram (о чём писали, что залетело по лайкам
и по комментам) + ежедневный пульс (пост резко набирает выше медианы
своего аккаунта). В каждой строке отчёта — ссылка на пост.

## Как это работает

- Данные собираются через **Apify** (любые публичные аккаунты, платно)
  или **Meta Graph API** (бесплатно, только бизнес/креатор-аккаунты) — выбор при настройке.
- Всё хранится локально в SQLite. «Залетело» считается от **медианы**
  лайков/комментов конкретного аккаунта за последние 30 дней — маленькие
  и большие аккаунты сравниваются честно, в кратных: «×2.4 от медианы».
- Отчёты приходят в Telegram через вашего собственного бота.
- Выжимку «о чём писали» пишет Claude (headless). Если вызов не сработал —
  отчёт приходит без неё, только метрики.

## Установка

1. Нужен [Claude Code](https://claude.com/claude-code) и Python 3.9+.
2. Склонируйте репо в папку скиллов:
   `git clone https://github.com/Natalyyyy/instawatch ~/.claude/skills/instawatch`
3. Откройте Claude Code и скажите: **«настрой инстаграм-мониторинг»** —
   дальше он сам: спросит про источник, поможет получить ключи, создать
   Telegram-бота, соберёт первые данные и (по желанию) поставит расписание.

## Команды после настройки

Говорите Claude: «отчёт по инстаграму», «проверь пульс», «добавь @X
в мониторинг», «выключи автоматику», «обнови токен инстаграма».

## Стоимость

- **Apify**: ~$2.5–3 за 1000 постов. 10 аккаунтов + ежедневный пульс ≈
  $8–10/мес. Бесплатного кредита ($5/мес) хватит попробовать.
- **Meta Graph API**: бесплатно, но настройка сложнее (нужны свой
  IG-бизнес-аккаунт и приложение Facebook) и токен надо обновлять раз в 60 дней.
- **Claude**: автоматический еженедельный отчёт тратит лимиты вашей подписки.

## Дисклеймер

Скрейпинг Instagram через Apify нарушает условия использования Меты —
используете на свой риск. Meta Graph API — легальный путь, но с
ограничениями (только бизнес/креатор-аккаунты, нет сторис и просмотров
чужих рилсов — их отдаёт только Apify).
Проект не аффилирован с Meta. Meta признана экстремистской организацией
и запрещена на территории РФ.
```

- [ ] **Step 3: Прогнать все тесты** — `venv/bin/pytest tests/ -v` → PASS
- [ ] **Step 4: Commit** — `git add -A && git commit -m "docs: SKILL.md onboarding + README"`

---

### Task 11: Смоук на живых данных + публикация

**Files:**
- Create: `config.json`, `.env` (локально, не в git)

- [ ] **Step 1: Реальный прогон Apify.** Нужен Apify-токен Наташи (спросить/завести на apify.com, free-кредит). `.env` + `config.json` с 2–3 реальными аккаунтами (например, референсы Марса). Затем:

```bash
python3 fetch.py --limit 30        # холодный старт: ожидаем "Сохранено постов: ~60-90"
python3 report.py weekly --no-fetch   # отчёт печатается, в каждой записи есть ссылка
python3 report.py pulse --no-fetch    # "Тихо: сигналов нет." или сигналы
```

Проверить руками: медианы адекватные (`sqlite3 data/instawatch.db 'SELECT account, COUNT(*) FROM posts GROUP BY account'`), ссылки кликаются, ×N выглядит правдоподобно.

- [ ] **Step 2: Телеграм.** Создать тестового бота (или взять существующий тестовый токен), прописать в `.env`, прогнать `python3 report.py weekly --no-fetch --send` — отчёт пришёл, длинный отчёт нарезан на куски.

- [ ] **Step 3: Расписание.** `python3 schedule.py install` → `schedule.py status` показывает два джоба → `python3 schedule.py remove` (на машине Наташи автоматика не нужна — она не пользователь продукта).

- [ ] **Step 4: Скилл.** Симлинк для локальной проверки: `ln -s ~/Projects/instawatch ~/.claude/skills/instawatch`. В новой сессии Claude Code сказать «отчёт по инстаграму» — скилл подхватывается, отчёт приходит в чат.

- [ ] **Step 5: Публикация.** `gh repo create instawatch --public --source . --push` (аккаунт Natalyyyy, ssh-алиас `github-natalyyyy`). Перед пушем проверить `git status` — `.env`, `config.json`, `data/` не в индексе.

- [ ] **Step 6: Обновить справочник.** В `ObsidianVault/projects/vibe-coding/agents.md` добавить строку про instawatch (Mac, ручной/launchd, skill instawatch) — и коммит волта уйдёт автосинком.

---

## Self-Review (выполнен при написании плана)

- Покрытие спеки: выбор источника (T4/T5 + онбординг T10), медиана с окном/минимумом/холодным стартом (T3, T10 шаг 5, T11), пульс с дедупом и фолбэком на комменты (T7), еженедельник с разделёнными топами, «⏳ ещё растёт», тихими и недоступными (T8), обязательные ссылки (тесты T7/T8), протухание токена 190 → пинг в ТГ (T5/T7), Claude-фолбэк (T8), ручной/автомат (T9/T10), ToS и стоимость (T10), python3-проверка (T10), `.env` без dotenv (T1).
- Рилсы: идут как обычные media в обоих адаптерах; просмотры (`views`) собираются и показываются, где источник отдаёт (Apify: `videoPlayCount`/`videoViewCount`; Graph по чужим — всегда None), в медианы/сигналы v1 не входят.
- Типы сведены: `record`-формат объявлен в T2 и используется в T4/T5; `cfg`-ключи объявлены в T1 и используются всюду.
```
