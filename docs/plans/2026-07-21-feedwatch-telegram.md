# feedwatch (rename + Telegram monitoring) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Переименовать instawatch в feedwatch и добавить мониторинг Telegram-каналов (источники: веб-превью t.me/s и TGStat API) с единым отчётом и пульсом.

**Architecture:** Существующая схема (SQLite: posts/snapshots/alerted/account_status; медианы по аккаунту; pulse + weekly) расширяется колонкой `platform`. Новый модуль `fetch_tg.py` даёт два ТГ-фетчера, `fetch.run_fetch` оркестрирует платформы по секциям конфига `instagram`/`telegram`. Пульс для ТГ триггерится по просмотрам; weekly получает платформенные секции.

**Tech Stack:** Python 3.9+ (стиль модулей — `.format()`, без f-строк в продукт-коде), только `requests` из внешних зависимостей, pytest.

**Spec:** `docs/specs/2026-07-21-feedwatch-telegram-design.md` — читать перед началом.

## Global Constraints

- Python 3.9 совместимость: никаких `X | Y` в аннотациях, продукт-код — `.format()` как в существующих модулях (в тестах f-строки допустимы).
- Внешняя зависимость только `requests` (+ pytest в dev). Никаких bs4/lxml — HTML парсим регулярками.
- Все пользовательские сообщения — по-русски, как существующие.
- Рабочая папка: `~/Projects/instawatch` (физически переименовывается только в Task 10).
- Тесты гоняются так: `./venv/bin/python -m pytest tests/ -q` — после каждого таска весь набор зелёный.
- Коммиты: английские subject в стиле репо (`feat:`, `test:`, `docs:`, `refactor:`).
- `post_id` для ТГ: `tg:<канал>:<номер>`. Значение `platform`: строго `instagram` | `telegram`.
- При смене источника ТГ (web ↔ tgstat) post_id не совпадут (у TGStat свои внутренние id) — известное ограничение, в коде не решаем.

---

### Task 1: Конфиг — платформенные секции + legacy-миграция

**Files:**
- Modify: `common.py` (DEFAULTS, load_config, + normalize_config, + active_accounts)
- Modify: `config.example.json`
- Test: `tests/test_common.py`

**Interfaces:**
- Produces: `common.normalize_config(cfg) -> dict`; `common.active_accounts(cfg) -> list[tuple[str, str]]` (пары `(platform, account)`, аккаунты в lower). `cfg["instagram"]` / `cfg["telegram"]` — dict или None; IG-dict: `{"source": "apify"|"graph", "accounts": [...]}`; TG-dict: `{"source": "web"|"tgstat", "channels": [...]}`.
- Consumes: —

- [ ] **Step 1: Написать падающие тесты** — в `tests/test_common.py` добавить:

```python
def test_load_config_legacy_flat_becomes_instagram_section(tmp_path):
    cfg_file = tmp_path / "config.json"
    cfg_file.write_text('{"accounts": ["someblog"], "source": "apify"}', encoding="utf-8")
    cfg = common.load_config(cfg_file)
    assert cfg["instagram"] == {"source": "apify", "accounts": ["someblog"]}
    assert cfg["telegram"] is None


def test_load_config_new_format_sections(tmp_path):
    cfg_file = tmp_path / "config.json"
    cfg_file.write_text(
        '{"instagram": {"source": "apify", "accounts": ["a"]},'
        ' "telegram": {"source": "web", "channels": ["ch"]}}', encoding="utf-8")
    cfg = common.load_config(cfg_file)
    assert cfg["instagram"]["accounts"] == ["a"]
    assert cfg["telegram"]["channels"] == ["ch"]


def test_active_accounts_pairs_and_lowercase():
    cfg = dict(common.DEFAULTS,
               instagram={"source": "apify", "accounts": ["NatGeo"]},
               telegram={"source": "web", "channels": ["SoloKumi"]})
    assert common.active_accounts(cfg) == [
        ("instagram", "natgeo"), ("telegram", "solokumi")]


def test_active_accounts_empty_platforms():
    assert common.active_accounts(dict(common.DEFAULTS)) == []
```

- [ ] **Step 2: Убедиться, что падают**

Run: `./venv/bin/python -m pytest tests/test_common.py -q`
Expected: FAIL (`KeyError: 'instagram'` / `AttributeError: active_accounts`)

- [ ] **Step 3: Реализация в `common.py`** — в DEFAULTS убрать `"source"` и `"accounts"`, добавить `"instagram": None, "telegram": None` (остальные ключи без изменений). После merge в `load_config` звать `normalize_config`:

```python
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
```

`config.example.json` — новый формат (общие ключи не трогать):

```json
{
  "instagram": { "source": "apify", "accounts": ["natgeo", "nasa"] },
  "telegram":  { "source": "web",   "channels": ["telegram"] },
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

- [ ] **Step 4: Весь набор зелёный** — старые тесты добавляют `accounts=`/`source=` поверх DEFAULTS явно, потому не ломаются.

Run: `./venv/bin/python -m pytest tests/ -q`
Expected: PASS (52 passed)

- [ ] **Step 5: Commit**

```bash
git add common.py config.example.json tests/test_common.py
git commit -m "feat: platform sections in config (instagram/telegram) with legacy fallback"
```

---

### Task 2: База — колонка platform, feedwatch.db, subscribers в account_status

**Files:**
- Modify: `common.py` (DB_PATH, SCHEMA, connect, save_posts, latest_metrics, set_account_status)
- Test: `tests/test_db.py`

**Interfaces:**
- Produces: `connect()` мигрирует старые базы (rename `instawatch.db` → `feedwatch.db`, ALTER posts, пересборка account_status). `save_posts` пишет `r.get("platform", "instagram")`. `latest_metrics(con, account, platform="instagram")` — фильтр по платформе, в строках появляется ключ `platform`. `set_account_status(con, account, error=None, at=None, platform="instagram", subscribers=None)` — subscribers обновляется только не-None значением.
- Consumes: —

- [ ] **Step 1: Падающие тесты** — в `tests/test_db.py`:

```python
def test_platform_saved_and_filtered(con):
    make_post(con, "p1", "acc", 3, 10, 1)                       # instagram по умолчанию
    common.save_posts(con, [{
        "post_id": "tg:acc:1", "account": "acc", "platform": "telegram",
        "caption": "тг", "posted_at": common.now_utc().isoformat(),
        "likes": 5, "comments": None, "views": 100,
        "permalink": "https://t.me/acc/1",
    }])
    ig = common.latest_metrics(con, "acc")
    tg = common.latest_metrics(con, "acc", platform="telegram")
    assert [p["post_id"] for p in ig] == ["p1"]
    assert [p["post_id"] for p in tg] == ["tg:acc:1"]
    assert tg[0]["platform"] == "telegram"


def test_legacy_db_renamed_and_migrated(tmp_path):
    legacy = tmp_path / "instawatch.db"
    import sqlite3
    old = sqlite3.connect(legacy)
    old.executescript("""
        CREATE TABLE posts (post_id TEXT PRIMARY KEY, account TEXT NOT NULL,
            caption TEXT, posted_at TEXT NOT NULL, permalink TEXT NOT NULL);
        CREATE TABLE snapshots (id INTEGER PRIMARY KEY AUTOINCREMENT, post_id TEXT NOT NULL,
            fetched_at TEXT NOT NULL, likes INTEGER, comments INTEGER, views INTEGER);
        CREATE TABLE alerted (post_id TEXT PRIMARY KEY, alerted_at TEXT NOT NULL);
        CREATE TABLE account_status (account TEXT PRIMARY KEY, last_ok TEXT, last_error TEXT);
        INSERT INTO posts VALUES ('old1', 'acc', 'старый', '2026-07-01T00:00:00+00:00', 'u');
        INSERT INTO account_status (account, last_error) VALUES ('acc', 'ошибка');
    """)
    old.commit(); old.close()
    con = common.connect(tmp_path / "feedwatch.db")
    assert not legacy.exists()
    row = con.execute("SELECT platform FROM posts WHERE post_id='old1'").fetchone()
    assert row["platform"] == "instagram"
    st = con.execute("SELECT platform, account, last_error, subscribers "
                     "FROM account_status").fetchone()
    assert (st["platform"], st["account"], st["last_error"]) == ("instagram", "acc", "ошибка")


def test_account_status_platform_and_subscribers(con):
    common.set_account_status(con, "ch", platform="telegram", subscribers=36300)
    common.set_account_status(con, "ch", platform="telegram")   # без subscribers — не затирает
    st = con.execute("SELECT subscribers, last_ok FROM account_status "
                     "WHERE platform='telegram' AND account='ch'").fetchone()
    assert st["subscribers"] == 36300 and st["last_ok"] is not None
```

- [ ] **Step 2: Убедиться, что падают**

Run: `./venv/bin/python -m pytest tests/test_db.py -q`
Expected: FAIL

- [ ] **Step 3: Реализация в `common.py`**

```python
DB_PATH = DATA_DIR / "feedwatch.db"

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
```

В SCHEMA: в `posts` добавить `platform TEXT NOT NULL DEFAULT 'instagram'` (после account), блок `account_status` заменить на `ACCOUNT_STATUS_SCHEMA` (SCHEMA — конкатенация строк). `connect`:

```python
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
```

`save_posts`: в INSERT posts добавить колонку `platform`, значение `r.get("platform", "instagram")`. `latest_metrics`: параметр `platform="instagram"`, в SELECT добавить `p.platform`, в WHERE — `AND p.platform = ?`. `set_account_status`:

```python
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
```

- [ ] **Step 4: Весь набор зелёный**

Run: `./venv/bin/python -m pytest tests/ -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add common.py tests/test_db.py
git commit -m "feat: platform column, feedwatch.db migration, subscribers in account_status"
```

---

### Task 3: Медиана просмотров

**Files:**
- Modify: `common.py` (account_medians)
- Test: `tests/test_medians.py`

**Interfaces:**
- Produces: `account_medians(con, account, cfg, now=None, platform="instagram")` → `{"likes", "comments", "views", "n_posts"}`.
- Consumes: `latest_metrics(..., platform=...)` из Task 2.

- [ ] **Step 1: Падающий тест** — в `tests/test_medians.py` (использовать `make_post` из conftest с `views=`):

```python
def test_views_median_and_platform(con):
    now = common.now_utc()
    for i, v in enumerate([100, 200, 300]):
        make_post(con, f"tg{i}", "ch", 5 + i, None, None, views=v, now=now)
        con.execute("UPDATE posts SET platform='telegram' WHERE post_id=?", (f"tg{i}",))
    con.commit()
    med = common.account_medians(con, "ch", CFG, now=now, platform="telegram")
    assert med["views"] == 200
    assert med["likes"] is None
```

- [ ] **Step 2: Убедиться, что падает**

Run: `./venv/bin/python -m pytest tests/test_medians.py -q`
Expected: FAIL (`TypeError: unexpected keyword argument 'platform'`)

- [ ] **Step 3: Реализация** — `account_medians` получает параметр `platform="instagram"`, пробрасывает в `latest_metrics`, добавляет `views = [p["views"] for p in in_window if p["views"] is not None]` и ключ `"views": _median(views)` в результат.

- [ ] **Step 4: Весь набор зелёный**

Run: `./venv/bin/python -m pytest tests/ -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add common.py tests/test_medians.py
git commit -m "feat: views median + platform-aware account_medians"
```

---

### Task 4: fetch_tg.py — веб-источник t.me/s

**Files:**
- Create: `fetch_tg.py`
- Create: `tests/fixtures/tg_web_sample.html`
- Test: `tests/test_fetch_tg_web.py`

**Interfaces:**
- Produces: `fetch_tg.fetch_web(channels, limit, session=None) -> (records, errors, subs)` — records в формате `save_posts` (с `platform="telegram"`, `comments=None`), `errors: {channel: msg}`, `subs: {channel: int}`. Также `parse_count(text)`, `parse_page(page_html, channel) -> (records, min_id)`, `parse_subscribers(page_html)`, константа `PREVIEW_UNAVAILABLE`.
- Consumes: —

- [ ] **Step 1: Собрать фикстуру с живой страницы** (первые 6 сообщений + шапка канала достаточны):

```bash
curl -s -A "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36" \
  "https://t.me/s/telegram" -o /tmp/tg_full.html
python3 - <<'EOF'
html = open("/tmp/tg_full.html", encoding="utf-8").read()
marker = 'class="tgme_widget_message_wrap'
parts = html.split(marker)
open("tests/fixtures/tg_web_sample.html", "w", encoding="utf-8").write(
    parts[0] + "".join(marker + p for p in parts[1:7]))
EOF
grep -c 'data-post=' tests/fixtures/tg_web_sample.html   # ожидаем 6
```

Проверить глазами, что в фикстуре есть `tgme_widget_message_views`, `<time datetime=`, `counter_value` + `subscriber`; блоки `tgme_reaction` могут отсутствовать у конкретного канала — тогда взять канал с реакциями (проверено 2026-07-21 на `solokumi`: `<span class="tgme_reaction"><i class="emoji"...><b>🔥</b></i>127</span>`, платные — `<span class="tgme_reaction tgme_reaction_paid">`). Если реакций нет и на запасном канале — добавить в конец фикстуры руками один такой блок внутрь последнего сообщения, пометив комментарием `<!-- synthetic reactions for test -->`.

- [ ] **Step 2: Падающие тесты** — `tests/test_fetch_tg_web.py`:

```python
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
```

- [ ] **Step 3: Убедиться, что падают**

Run: `./venv/bin/python -m pytest tests/test_fetch_tg_web.py -q`
Expected: FAIL (`ModuleNotFoundError: fetch_tg`)

- [ ] **Step 4: Реализация `fetch_tg.py`**

```python
"""Сбор постов Telegram-каналов: веб-превью t.me/s (без ключей) или TGStat API."""
import html as html_module
import re

import requests

TG_WEB_URL = "https://t.me/s/{}"
HEADERS = {"User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                          "AppleWebKit/537.36 (KHTML, like Gecko) "
                          "Chrome/120.0 Safari/537.36")}
PREVIEW_UNAVAILABLE = ("веб-превью недоступно (канал скрытый, приватный или "
                       "не существует) — попробуй источник tgstat")


def parse_count(text):
    """'13K' → 13000, '1.2M' → 1200000, '419' → 419. Мусор → None."""
    if text is None:
        return None
    t = text.strip().replace("\xa0", "").replace(" ", "").replace(",", ".")
    try:
        if t[-1:].lower() == "k":
            return int(float(t[:-1]) * 1000)
        if t[-1:].lower() == "m":
            return int(float(t[:-1]) * 1000000)
        return int(float(t))
    except ValueError:
        return None


def _strip_html(fragment):
    text = re.sub(r"<br\s*/?>", "\n", fragment)
    text = re.sub(r"<[^>]+>", "", text)
    return html_module.unescape(text).strip()


def parse_page(page_html, channel):
    """Одна страница t.me/s → (records, min_post_id). Платные реакции (звёзды) не считаем."""
    records, min_id = [], None
    for block in page_html.split('class="tgme_widget_message_wrap')[1:]:
        m = re.search(r'data-post="[^"/]+/(\d+)"', block)
        time_m = re.search(r'<time datetime="([^"]+)"', block)
        if not m or not time_m:
            continue
        post_id = int(m.group(1))
        min_id = post_id if min_id is None else min(min_id, post_id)
        text_m = re.search(r'tgme_widget_message_text[^>]*>(.*?)</div>', block, re.S)
        views_m = re.search(r'tgme_widget_message_views">([^<]+)<', block)
        reactions = re.findall(
            r'<span class="tgme_reaction">.*?</i>\s*([\d.,KMkm\xa0 ]+)</span>',
            block, re.S)
        likes = None
        if reactions:
            parsed = [parse_count(r) for r in reactions]
            likes = sum(v for v in parsed if v is not None)
        records.append({
            "post_id": "tg:{}:{}".format(channel, post_id),
            "account": channel,
            "platform": "telegram",
            "caption": _strip_html(text_m.group(1)) if text_m else "",
            "posted_at": time_m.group(1),
            "likes": likes,
            "comments": None,   # веб-превью счётчик комментов не отдаёт
            "views": parse_count(views_m.group(1)) if views_m else None,
            "permalink": "https://t.me/{}/{}".format(channel, post_id),
        })
    return records, min_id


def parse_subscribers(page_html):
    m = re.search(
        r'counter_value">([^<]+)</span>\s*<span class="counter_type">subscriber',
        page_html)
    return parse_count(m.group(1)) if m else None


def _fetch_channel_web(http, channel, limit):
    resp = http.get(TG_WEB_URL.format(channel), headers=HEADERS, timeout=30)
    resp.raise_for_status()
    records, min_id = parse_page(resp.text, channel)
    subs = parse_subscribers(resp.text)
    while records and len(records) < limit and min_id and min_id > 1:
        resp = http.get(TG_WEB_URL.format(channel), params={"before": min_id},
                        headers=HEADERS, timeout=30)
        resp.raise_for_status()
        more, new_min = parse_page(resp.text, channel)
        known = {r["post_id"] for r in records}
        more = [r for r in more if r["post_id"] not in known]
        if not more:
            break
        records += more
        min_id = new_min
    return records, subs


def fetch_web(channels, limit, session=None):
    """Посты каналов из веб-превью. → (records, errors, subs)."""
    http = session or requests
    records, errors, subs = [], {}, {}
    for channel in channels:
        channel = channel.lower()
        try:
            chan_records, chan_subs = _fetch_channel_web(http, channel, limit)
        except requests.RequestException as exc:
            errors[channel] = "сеть/HTTP: {}".format(exc)
            continue
        if not chan_records:
            errors[channel] = PREVIEW_UNAVAILABLE
            continue
        records += chan_records[:limit]
        if chan_subs is not None:
            subs[channel] = chan_subs
    return records, errors, subs
```

- [ ] **Step 5: Тесты зелёные** — если конкретный regex не совпал с фикстурой, чинить regex по реальному HTML фикстуры (не подгонять фикстуру под regex).

Run: `./venv/bin/python -m pytest tests/ -q`
Expected: PASS

- [ ] **Step 6: Дымовой прогон на живом канале**

Run: `./venv/bin/python -c "import fetch_tg, json; r, e, s = fetch_tg.fetch_web(['telegram'], 25); print(len(r), e, s); print(json.dumps(r[0], ensure_ascii=False)[:300])"`
Expected: ~25 постов (сработала пагинация `before`), errors `{}`, subs с числом.

- [ ] **Step 7: Commit**

```bash
git add fetch_tg.py tests/fixtures/tg_web_sample.html tests/test_fetch_tg_web.py
git commit -m "feat: telegram web-preview fetcher (t.me/s parser, pagination, subscribers)"
```

---

### Task 5: fetch_tg.py — источник TGStat

**Files:**
- Modify: `fetch_tg.py`
- Modify: `.env.example` (строка `TGSTAT_TOKEN=`)
- Test: `tests/test_fetch_tg_tgstat.py`

**Interfaces:**
- Produces: `fetch_tg.fetch_tgstat(channels, limit, token, subscribers=False) -> (records, errors, subs)` — тот же формат, что fetch_web; likes/comments всегда None. `fetch_tg.TGStatError(Exception)`.
- Consumes: —

- [ ] **Step 1: Падающие тесты** — `tests/test_fetch_tg_tgstat.py`:

```python
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import fetch_tg

POSTS_OK = {"status": "ok", "response": {"items": [
    {"id": 4174011852, "date": 1784476800, "views": 1500,
     "text": "<b>жирный</b> пост", "link": "https://t.me/ch/419"},
]}}
INFO_OK = {"status": "ok", "response": {"participants_count": 36300}}
ERR = {"status": "error", "error": "channel_not_found"}


class FakeResp:
    def __init__(self, payload):
        self._payload = payload
    def json(self):
        return self._payload


def test_fetch_tgstat_ok(monkeypatch):
    calls = []
    def fake_get(url, params=None, timeout=None):
        calls.append((url, params))
        return FakeResp(INFO_OK if url.endswith("channels/get") else POSTS_OK)
    monkeypatch.setattr(fetch_tg.requests, "get", fake_get)
    records, errors, subs = fetch_tg.fetch_tgstat(["Ch"], 25, "tok", subscribers=True)
    assert errors == {} and subs == {"ch": 36300}
    r = records[0]
    assert r["post_id"] == "tg:ch:4174011852"
    assert r["platform"] == "telegram" and r["views"] == 1500
    assert r["likes"] is None and r["comments"] is None
    assert r["caption"] == "жирный пост"
    assert r["permalink"] == "https://t.me/ch/419"
    assert r["posted_at"].startswith("2026-07-19")
    assert calls[0][1]["channelId"] == "@Ch" and calls[0][1]["token"] == "tok"


def test_fetch_tgstat_error_per_channel(monkeypatch):
    monkeypatch.setattr(fetch_tg.requests, "get",
                        lambda url, params=None, timeout=None: FakeResp(ERR))
    records, errors, subs = fetch_tg.fetch_tgstat(["ghost"], 25, "tok")
    assert records == [] and "channel_not_found" in errors["ghost"]


def test_fetch_tgstat_no_subscribers_no_extra_request(monkeypatch):
    calls = []
    def fake_get(url, params=None, timeout=None):
        calls.append(url)
        return FakeResp(POSTS_OK)
    monkeypatch.setattr(fetch_tg.requests, "get", fake_get)
    fetch_tg.fetch_tgstat(["ch"], 25, "tok", subscribers=False)
    assert len(calls) == 1 and calls[0].endswith("channels/posts")
```

- [ ] **Step 2: Убедиться, что падают**

Run: `./venv/bin/python -m pytest tests/test_fetch_tg_tgstat.py -q`
Expected: FAIL (`AttributeError: fetch_tgstat`)

- [ ] **Step 3: Реализация** — добавить в `fetch_tg.py` (вверху `from datetime import datetime, timezone`):

```python
TGSTAT_BASE = "https://api.tgstat.ru"


class TGStatError(Exception):
    """TGStat вернул status=error или не-JSON."""


def _tgstat_request(method, params, token):
    resp = requests.get("{}/{}".format(TGSTAT_BASE, method),
                        params=dict(params, token=token), timeout=60)
    try:
        data = resp.json()
    except ValueError:
        raise TGStatError("не-JSON ответ от TGStat /{}".format(method))
    if data.get("status") == "ok":
        return data.get("response") or {}
    raise TGStatError(str(data.get("error") or data))


def normalize_tgstat(channel, item):
    return {
        "post_id": "tg:{}:{}".format(channel, item["id"]),
        "account": channel,
        "platform": "telegram",
        "caption": _strip_html(item.get("text") or ""),
        "posted_at": datetime.fromtimestamp(item["date"], tz=timezone.utc).isoformat(),
        "likes": None,      # лёгкий режим TGStat реакции не отдаёт
        "comments": None,
        "views": item.get("views"),
        "permalink": item.get("link") or "https://t.me/{}".format(channel),
    }


def fetch_tgstat(channels, limit, token, subscribers=False):
    """Посты каналов из TGStat API (лёгкий режим: только channels/posts
    [+ channels/get при subscribers=True]). → (records, errors, subs)."""
    records, errors, subs = [], {}, {}
    for channel in channels:
        key = channel.lower()
        try:
            resp = _tgstat_request(
                "channels/posts",
                {"channelId": "@" + channel, "limit": limit, "hideDeleted": 1},
                token)
        except (TGStatError, requests.RequestException) as exc:
            errors[key] = str(exc)
            continue
        for item in resp.get("items", []):
            records.append(normalize_tgstat(key, item))
        if subscribers:
            try:
                info = _tgstat_request("channels/get", {"channelId": "@" + channel}, token)
                if info.get("participants_count") is not None:
                    subs[key] = info["participants_count"]
            except (TGStatError, requests.RequestException):
                pass    # подписчики — некритичное украшение
    return records, errors, subs
```

- [ ] **Step 4: Весь набор зелёный**

Run: `./venv/bin/python -m pytest tests/ -q`
Expected: PASS

- [ ] **Step 5: `.env.example`** — добавить в конец:

```
# Telegram через TGStat (только для telegram.source = "tgstat")
TGSTAT_TOKEN=
```

- [ ] **Step 6: Commit**

```bash
git add fetch_tg.py tests/test_fetch_tg_tgstat.py .env.example
git commit -m "feat: TGStat fetcher (light mode: channels/posts + optional channels/get)"
```

---

### Task 6: run_fetch — оркестрация двух платформ

**Files:**
- Modify: `fetch.py` (run_fetch, main; import fetch_tg)
- Modify: `report.py:main` (одна строка — параметр subscribers)
- Test: `tests/test_fetch_graph.py` (обновить формат cfg), `tests/test_report_main.py` (обновить стаб cfg)

**Interfaces:**
- Produces: `fetch.run_fetch(limit, cfg=None, env=None, con=None, subscribers=False) -> (records, errors)`, errors keyed `(platform, account)`, только непустые. Пустые обе платформы → `ConfigError`.
- Consumes: `fetch_tg.fetch_web` / `fetch_tg.fetch_tgstat` (Tasks 4–5), `common.set_account_status(..., platform=, subscribers=)` (Task 2), секции конфига (Task 1).

- [ ] **Step 1: Падающие тесты** — в `tests/test_fetch_graph.py` убедиться, что вверху есть `import pytest` и `import common` (добавить при отсутствии), перевести существующие cfg на `dict(common.DEFAULTS, instagram={"source": "apify", "accounts": ["acc"]})` (и аналог для metagraph/ghost-кейсов; ожидания errors — на ключи `("instagram", "acc")`), добавить:

```python
def test_run_fetch_telegram_web(monkeypatch, con):
    monkeypatch.setattr(fetch.fetch_tg, "fetch_web",
                        lambda channels, limit, session=None: (
                            [{"post_id": "tg:ch:1", "account": "ch", "platform": "telegram",
                              "caption": "x", "posted_at": common.now_utc().isoformat(),
                              "likes": 3, "comments": None, "views": 50,
                              "permalink": "https://t.me/ch/1"}],
                            {}, {"ch": 1000}))
    cfg = dict(common.DEFAULTS, telegram={"source": "web", "channels": ["ch"]})
    records, errors = fetch.run_fetch(5, cfg=cfg, env={}, con=con)
    assert len(records) == 1 and errors == {}
    row = con.execute("SELECT subscribers FROM account_status "
                      "WHERE platform='telegram' AND account='ch'").fetchone()
    assert row["subscribers"] == 1000


def test_run_fetch_tgstat_requires_token(con):
    cfg = dict(common.DEFAULTS, telegram={"source": "tgstat", "channels": ["ch"]})
    with pytest.raises(fetch.ConfigError):
        fetch.run_fetch(5, cfg=cfg, env={}, con=con)


def test_run_fetch_no_platforms(con):
    with pytest.raises(fetch.ConfigError):
        fetch.run_fetch(5, cfg=dict(common.DEFAULTS), env={}, con=con)
```

- [ ] **Step 2: Убедиться, что падают**

Run: `./venv/bin/python -m pytest tests/test_fetch_graph.py -q`
Expected: FAIL

- [ ] **Step 3: Реализация `run_fetch`** (в `fetch.py` добавить `import fetch_tg`):

```python
def run_fetch(limit, cfg=None, env=None, con=None, subscribers=False):
    cfg = cfg or common.load_config()
    env = env or common.load_env()
    con = con or common.connect()
    ig = cfg.get("instagram") or {}
    tg = cfg.get("telegram") or {}
    if not ig.get("accounts") and not tg.get("channels"):
        raise ConfigError("В config.json не настроена ни одна платформа — "
                          "заполни секцию instagram и/или telegram "
                          "по образцу config.example.json")
    records, errors = [], {}
    if ig.get("accounts"):
        accounts = ig["accounts"]
        if ig.get("source", "apify") == "apify":
            _require_env(env, ["APIFY_TOKEN"])
            recs, errs = fetch_apify(accounts, limit, env["APIFY_TOKEN"])
        else:
            _require_env(env, ["IG_ACCESS_TOKEN", "IG_BUSINESS_ID"])
            recs, errs = fetch_graph(accounts, limit,
                                     env["IG_BUSINESS_ID"], env["IG_ACCESS_TOKEN"])
        records += recs
        common.save_posts(con, recs)
        for a in accounts:
            a = a.lower()
            errors[("instagram", a)] = errs.get(a)
            common.set_account_status(con, a, error=errs.get(a))
    if tg.get("channels"):
        channels = tg["channels"]
        if tg.get("source", "web") == "web":
            recs, errs, subs = fetch_tg.fetch_web(channels, limit)
        else:
            _require_env(env, ["TGSTAT_TOKEN"])
            recs, errs, subs = fetch_tg.fetch_tgstat(channels, limit,
                                                     env["TGSTAT_TOKEN"],
                                                     subscribers=subscribers)
        records += recs
        common.save_posts(con, recs)
        for c in channels:
            c = c.lower()
            errors[("telegram", c)] = errs.get(c)
            common.set_account_status(con, c, error=errs.get(c),
                                      platform="telegram", subscribers=subs.get(c))
    return records, {k: v for k, v in errors.items() if v}
```

В `fetch.main` печать ошибок: `print("⚠️ [{}] @{}: {}".format(platform, a, e), file=sys.stderr)` по `for (platform, a), e in errors.items()`. В `report.py:main` вызов заменить на `fetch.run_fetch(limit, cfg=cfg, env=env, con=con, subscribers=(args.mode == "weekly"))`. В `tests/test_report_main.py` стаб load_config → `dict(common.DEFAULTS, instagram={"source": "apify", "accounts": ["acc"]})`.

- [ ] **Step 4: Весь набор зелёный**

Run: `./venv/bin/python -m pytest tests/ -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add fetch.py report.py tests/test_fetch_graph.py tests/test_report_main.py
git commit -m "feat: run_fetch orchestrates instagram + telegram sections"
```

---

### Task 7: Пульс — платформенная логика (ТГ по просмотрам)

**Files:**
- Modify: `report.py` (pulse_signals, format_pulse, + stats_line, + PLATFORM_TITLES, METRIC_RU)
- Test: `tests/test_pulse.py`

**Interfaces:**
- Produces: `pulse_signals` итерирует `common.active_accounts(cfg)`; сигнал получает ключи `ratio`, `metric` (`likes|comments|views`), `likes_hidden`. `stats_line(post) -> str` (ТГ: `👁 N ❤️ M`; IG: `❤️ N 💬 M [▶️ V]`). `PLATFORM_TITLES = {"instagram": "📸 Instagram", "telegram": "✈️ Telegram"}`. Заголовок пульса: `🔥 Пульс: залетает выше медианы`.
- Consumes: `active_accounts` (Task 1), `account_medians(..., platform=)` (Task 3), `latest_metrics(..., platform=)` (Task 2).

- [ ] **Step 1: Падающие тесты** — в `tests/test_pulse.py`: CFG перевести на `dict(common.DEFAULTS, instagram={"source": "apify", "accounts": ["acc"]}, median_min_posts=3, pulse_multiplier=2.0)`; существующие тесты не менять по смыслу. Добавить (сеялка ТГ-постов — как в Task 3, UPDATE platform):

```python
def seed_tg(con, n_base=3, views_base=100, now=None):
    now = now or common.now_utc()
    for i in range(n_base):
        make_post(con, f"tgb{i}", "ch", 5 + i, None, None, views=views_base, now=now)
    make_post(con, "tghot", "ch", 1, None, None, views=views_base * 3, now=now)
    con.execute("UPDATE posts SET platform='telegram' WHERE account='ch'")
    con.commit()


def test_tg_pulse_triggers_on_views(con):
    cfg = dict(common.DEFAULTS, telegram={"source": "web", "channels": ["ch"]},
               median_min_posts=3, pulse_multiplier=2.0)
    seed_tg(con)
    signals = report.pulse_signals(con, cfg)
    assert [s["post_id"] for s in signals] == ["tghot"]
    assert signals[0]["metric"] == "views" and signals[0]["ratio"] == 3.0


def test_format_pulse_sections_when_both_platforms():
    ig = {"post_id": "p", "account": "acc", "platform": "instagram", "caption": "",
          "posted_at": "2026-07-20T00:00:00+00:00", "permalink": "u1",
          "likes": 10, "comments": 2, "views": None,
          "ratio": 2.5, "metric": "likes", "likes_hidden": False}
    tg = {"post_id": "tg:ch:1", "account": "ch", "platform": "telegram", "caption": "",
          "posted_at": "2026-07-20T00:00:00+00:00", "permalink": "u2",
          "likes": 5, "comments": None, "views": 300,
          "ratio": 3.0, "metric": "views", "likes_hidden": False}
    text = report.format_pulse([ig, tg])
    assert "📸 Instagram" in text and "✈️ Telegram" in text
    assert "по просмотрам" in text and "👁 300" in text
    single = report.format_pulse([tg])
    assert "✈️ Telegram" not in single      # одна платформа — без подзаголовка
```

- [ ] **Step 2: Убедиться, что падают**

Run: `./venv/bin/python -m pytest tests/test_pulse.py -q`
Expected: FAIL

- [ ] **Step 3: Реализация в `report.py`**

```python
PLATFORM_TITLES = {"instagram": "📸 Instagram", "telegram": "✈️ Telegram"}
METRIC_RU = {"likes": "лайкам", "comments": "комментам", "views": "просмотрам"}


def stats_line(p):
    if p["platform"] == "telegram":
        stats = "👁 {}".format(p["views"] if p["views"] is not None else "—")
        if p["likes"] is not None:
            stats += " ❤️ {}".format(p["likes"])
        return stats
    likes = "—" if p["likes"] is None else p["likes"]
    stats = "❤️ {} 💬 {}".format(likes, p["comments"])
    if p.get("views"):
        stats += " ▶️ {}".format(p["views"])
    return stats


def pulse_signals(con, cfg, now=None):
    now = now or common.now_utc()
    k = cfg["pulse_multiplier"]
    signals = []
    for platform, account in common.active_accounts(cfg):
        med = common.account_medians(con, account, cfg, now=now, platform=platform)
        for post in common.latest_metrics(con, account, platform=platform):
            if post_age_days(post, now) > cfg["pulse_max_age_days"]:
                continue
            if common.was_alerted(con, post["post_id"]):
                continue
            likes_hidden = False
            if platform == "telegram":
                ratio, metric = format_ratio(post["views"], med["views"]), "views"
            else:
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
    lines = ["🔥 Пульс: залетает выше медианы", ""]
    platforms = {s["platform"] for s in signals}
    for platform in ("instagram", "telegram"):
        group = [s for s in signals if s["platform"] == platform]
        if not group:
            continue
        if len(platforms) > 1:
            lines.append(PLATFORM_TITLES[platform])
            lines.append("")
        for s in group:
            hidden = " (лайки скрыты)" if s["likes_hidden"] else ""
            lines.append("@{}{} — ×{:.1f} от медианы по {}".format(
                s["account"], hidden, s["ratio"], METRIC_RU[s["metric"]]))
            lines.append(stats_line(s))
            if preview(s["caption"]):
                lines.append(preview(s["caption"]))
            lines.append(s["permalink"])
            lines.append("")
    return "\n".join(lines).strip()
```

Старый инлайн формирования stats в format_pulse удалить (заменён stats_line). Существующие пульс-тесты, завязанные на текст «Инстаграм-пульс», обновить на новый заголовок.

- [ ] **Step 4: Весь набор зелёный**

Run: `./venv/bin/python -m pytest tests/ -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add report.py tests/test_pulse.py
git commit -m "feat: platform-aware pulse (telegram triggers on views)"
```

---

### Task 8: Weekly — платформенные секции, подписчики, промпт

**Files:**
- Modify: `report.py` (weekly_data, format_top, build_weekly, claude_summary, + platform_section, tg_subscribers)
- Modify: `prompts/weekly.md`
- Test: `tests/test_weekly.py`

**Interfaces:**
- Produces: `weekly_data(con, cfg, platform, accounts, now=None) -> (per_account, quiet, unavailable)`; посты получают `like_ratio`, `comment_ratio`, `view_ratio`, `fresh`. `platform_section(platform, per_account, quiet, unavailable, subs=None) -> list[str]`. `tg_subscribers(con, accounts) -> {account: int}`. `build_weekly` — заголовок `📊 За неделю`; при одной настроенной платформе платформенный подзаголовок опускается. `claude_summary(per_account_by_platform, prompt_path)` где ключи — `(platform, account)`.
- Consumes: Task 2, 3, 7 (`PLATFORM_TITLES`, `stats_line`).

- [ ] **Step 1: Падающие тесты** — в `tests/test_weekly.py`: CFG → `dict(common.DEFAULTS, instagram={"source": "apify", "accounts": ["acc", "quietacc"]}, median_min_posts=3)`; вызовы `report.weekly_data(con, CFG)` → `report.weekly_data(con, CFG, "instagram", CFG["instagram"]["accounts"])`; ожидание заголовка «Инстаграм за неделю» → «📊 За неделю». Добавить:

```python
def test_weekly_tg_section_with_views_top_and_subscribers(con, monkeypatch):
    monkeypatch.setattr(report, "claude_summary", lambda *a, **k: None)
    cfg = dict(common.DEFAULTS,
               telegram={"source": "web", "channels": ["ch"]}, median_min_posts=3)
    now = common.now_utc()
    for i, v in enumerate([100, 100, 100]):
        make_post(con, f"tgo{i}", "ch", 8 + i, 4, None, views=v, now=now)
    make_post(con, "tgtop", "ch", 3, 20, None, views=500, now=now)
    con.execute("UPDATE posts SET platform='telegram' WHERE account='ch'")
    con.commit()
    common.set_account_status(con, "ch", platform="telegram", subscribers=36300)
    text = report.build_weekly(con, cfg, now=now)
    assert "📊 За неделю" in text
    assert "✈️ Telegram" not in text          # одна платформа — без подзаголовка
    assert "Топ по просмотрам" in text and "×5.0" in text
    assert "Топ по реакциям" in text          # реакции есть (likes=4/20)
    assert "36 300" in text or "36300" in text


def test_weekly_two_platforms_two_sections(con, monkeypatch):
    monkeypatch.setattr(report, "claude_summary", lambda *a, **k: None)
    cfg = dict(common.DEFAULTS,
               instagram={"source": "apify", "accounts": ["acc"]},
               telegram={"source": "web", "channels": ["ch"]}, median_min_posts=3)
    now = common.now_utc()
    make_post(con, "ig1", "acc", 3, 10, 1, now=now)
    make_post(con, "tg1", "ch", 3, None, None, views=100, now=now)
    con.execute("UPDATE posts SET platform='telegram' WHERE account='ch'")
    con.commit()
    text = report.build_weekly(con, cfg, now=now)
    assert "📸 Instagram" in text and "✈️ Telegram" in text
```

- [ ] **Step 2: Убедиться, что падают**

Run: `./venv/bin/python -m pytest tests/test_weekly.py -q`
Expected: FAIL

- [ ] **Step 3: Реализация в `report.py`**

`weekly_data` — сигнатура `(con, cfg, platform, accounts, now=None)`: внутри `active = {a.lower() for a in accounts}`, цикл по `accounts`, `account_medians(..., platform=platform)`, `latest_metrics(..., platform=platform)`, к существующим ratio добавить `p["view_ratio"] = format_ratio(p["views"], med["views"])`, запрос unavailable — `"SELECT account, last_error FROM account_status WHERE last_error IS NOT NULL AND platform = ?", (platform,)`.

`format_top` — строку stats заменить на `stats_line(p)` (из Task 7); остальное как было.

Новые функции:

```python
def tg_subscribers(con, accounts):
    subs = {}
    for a in accounts:
        row = con.execute(
            "SELECT subscribers FROM account_status "
            "WHERE platform='telegram' AND account=?", (a.lower(),)).fetchone()
        if row and row["subscribers"]:
            subs[a.lower()] = row["subscribers"]
    return subs


def platform_section(platform, per_account, quiet, unavailable, subs=None):
    lines = [PLATFORM_TITLES[platform], ""]
    if subs:
        lines.append("👥 " + " · ".join(
            "@{} {}".format(a, "{:,}".format(n).replace(",", " "))
            for a, n in sorted(subs.items())))
        lines.append("")
    all_posts = [p for posts in per_account.values() for p in posts]
    if all_posts:
        if platform == "instagram":
            lines += format_top(all_posts, "like_ratio",
                                "Топ по лайкам (×N от медианы аккаунта)", "❤️")
            lines += format_top(all_posts, "comment_ratio",
                                "Топ по комментам (×N от медианы аккаунта)", "💬")
        else:
            lines += format_top(all_posts, "view_ratio",
                                "Топ по просмотрам (×N от медианы канала)", "👁")
            if any(p["like_ratio"] is not None for p in all_posts):
                lines += format_top(all_posts, "like_ratio",
                                    "Топ по реакциям (×N от медианы канала)", "❤️")
    else:
        lines.append("За неделю ни одного нового поста.")
        lines.append("")
    if quiet:
        lines.append("😴 Молчали: " + ", ".join("@{}".format(a) for a in quiet))
        lines.append("")
    if unavailable:
        lines.append("⚠️ Не удалось получить: " + "; ".join(
            "@{} ({})".format(u["account"], u["last_error"]) for u in unavailable))
        lines.append("")
    return lines


def build_weekly(con, cfg, now=None):
    sections, per_platform = [], {}
    ig = cfg.get("instagram") or {}
    tg = cfg.get("telegram") or {}
    if ig.get("accounts"):
        per_account, quiet, unavailable = weekly_data(
            con, cfg, "instagram", ig["accounts"], now=now)
        sections.append(platform_section("instagram", per_account, quiet, unavailable))
        per_platform.update({("instagram", a): p for a, p in per_account.items()})
    if tg.get("channels"):
        per_account, quiet, unavailable = weekly_data(
            con, cfg, "telegram", tg["channels"], now=now)
        sections.append(platform_section(
            "telegram", per_account, quiet, unavailable,
            subs=tg_subscribers(con, tg["channels"])))
        per_platform.update({("telegram", a): p for a, p in per_account.items()})
    lines = ["📊 За неделю", ""]
    if per_platform:
        summary = claude_summary(per_platform, common.ROOT / "prompts" / "weekly.md")
        if summary:
            lines += ["🧠 О чём писали", "", summary, ""]
    if len(sections) == 1:
        lines += sections[0][2:]        # платформенный подзаголовок не нужен
    else:
        for section in sections:
            lines += section
    return "\n".join(lines).strip()
```

`claude_summary` — цикл дайджеста:

```python
    for (platform, account), posts in per_account.items():
        title = "Telegram" if platform == "telegram" else "Instagram"
        digest.append("## @{} ({})".format(account, title))
        digest.extend("- " + preview(p["caption"], 500) for p in posts)
```

`prompts/weekly.md` — первую фразу заменить на: «Ты — аналитик соцсетей. Ниже тексты постов Instagram-аккаунтов и Telegram-каналов за неделю, сгруппированные по аккаунтам (платформа указана в скобках).» Остальное без изменений.

- [ ] **Step 4: Весь набор зелёный**

Run: `./venv/bin/python -m pytest tests/ -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add report.py prompts/weekly.md tests/test_weekly.py
git commit -m "feat: weekly report with platform sections, tg subscribers, views/reactions tops"
```

---

### Task 9: Rename внутренностей — schedule, тексты, SKILL.md, README

**Files:**
- Modify: `schedule.py` (лейблы + чистка legacy)
- Modify: `report.py` (TOKEN_EXPIRED_MSG, FETCH_ERROR_MSG)
- Modify: `common.py`, `fetch.py`, `telegram.py` (docstrings «instawatch» → «feedwatch»)
- Modify: `SKILL.md`, `README.md`
- Test: `tests/test_schedule.py`

**Interfaces:**
- Produces: `LABEL_PULSE = "com.feedwatch.pulse"`, `LABEL_WEEKLY = "com.feedwatch.weekly"`, `CRON_MARK = "# feedwatch"`, `LEGACY_LABELS = ["com.instawatch.pulse", "com.instawatch.weekly"]`, `LEGACY_CRON_MARK = "# instawatch"`.
- Consumes: —

- [ ] **Step 1: Падающий тест** — в `tests/test_schedule.py`:

```python
def test_labels_renamed_and_legacy_constants():
    assert schedule.LABEL_PULSE == "com.feedwatch.pulse"
    assert schedule.CRON_MARK == "# feedwatch"
    assert schedule.LEGACY_CRON_MARK == "# instawatch"


def test_cron_remove_filters_both_marks():
    existing = ["0 9 * * * old pulse # instawatch",
                "0 9 * * * new pulse # feedwatch",
                "0 8 * * * something else"]
    kept = schedule.filter_cron(existing)
    assert kept == ["0 8 * * * something else"]
```

(Если в schedule.py фильтрация кронтаба инлайновая — вынести её в функцию `filter_cron(lines)`, которая убирает строки с любым из двух маркеров; install/remove пользуются ею. Аналогично для launchd: remove/install выгружают и legacy-лейблы — `for label in [LABEL_PULSE, LABEL_WEEKLY] + LEGACY_LABELS`.)

- [ ] **Step 2: Убедиться, что падает**

Run: `./venv/bin/python -m pytest tests/test_schedule.py -q`
Expected: FAIL

- [ ] **Step 3: Реализация** — константы + `filter_cron` + чистка legacy-лейблов в install/remove. В `report.py` заменить тексты:

```python
TOKEN_EXPIRED_MSG = (
    "⚠️ feedwatch: токен Meta Graph API протух (он живёт 60 дней).\n"
    "Скажи Claude: «обнови токен инстаграма» — он проведёт по шагам."
)

FETCH_ERROR_MSG = (
    "⚠️ feedwatch: не удалось собрать данные (проблема с сетью, токеном или "
    "кредитами источника). Проверь .env и баланс источника."
)
```

Docstrings модулей: «instawatch» → «feedwatch». Существующие тесты, завязанные на старые лейблы/тексты, обновить.

- [ ] **Step 4: SKILL.md** — frontmatter:

```yaml
---
name: feedwatch
description: Мониторинг чужих публичных Instagram-аккаунтов и Telegram-каналов с отчётами в Telegram. Триггеры — «настрой мониторинг соцсетей», «настрой инстаграм-мониторинг», «настрой мониторинг каналов», «отчёт по инстаграму», «отчёт по каналам», «что залетело в инстаграме/телеграме», «проверь пульс», «добавь/убери аккаунт или канал из мониторинга», «обнови токен инстаграма».
---
```

Онбординг переписать: шаг 2 становится «**Платформы.** Спроси, что мониторим: Instagram, Telegram или обе» и далее две ветки источников —

- Instagram: текущий текст про Apify / Meta Graph без изменений.
- Telegram: «**web** (по умолчанию) — веб-превью t.me, бесплатно и без ключей; не работает для каналов со скрытым превью. **tgstat** — нужен платный токен api.tgstat.ru (кабинет TGStat → API), лимиты по тарифу; в `.env` — `TGSTAT_TOKEN`».

В «Ручные команды» добавить: «добавь канал @X» → дописать в `config.json` секцию telegram → `python3 fetch.py --limit 30`; «отчёт по каналам / что залетело в телеграме» → те же `report.py weekly|pulse` (отчёт единый). Упоминания `config.json`-структуры — новый формат секций.

- [ ] **Step 5: README.md** — переписать шапку: название feedwatch, «Мониторинг чужих публичных Instagram-аккаунтов и Telegram-каналов…». Секция «Как это работает» — добавить абзац про ТГ-источники (web: бесплатно, без ключей, посты+просмотры+реакции+подписчики, комменты недоступны; tgstat: токен, лимиты, только просмотры). Установка: `git clone https://github.com/Natalyyyy/feedwatch ~/.claude/skills/feedwatch`, триггер «настрой мониторинг соцсетей». Стоимость: строка «**Telegram (web)**: бесплатно, без регистраций» + «**TGStat**: по тарифам tgstat.ru». Дисклеймер: абзац про Мету оставить, добавить: «Веб-превью t.me — публичные данные, которые Telegram отдаёт без авторизации; TGStat — официальный API по их тарифам. Каналы со скрытым превью через web-источник недоступны».

- [ ] **Step 6: Весь набор зелёный + smoke**

Run: `./venv/bin/python -m pytest tests/ -q && grep -ri instawatch --include="*.py" --include="*.md" . | grep -v docs/ | grep -v venv`
Expected: PASS; grep находит только legacy-константы в schedule.py и упоминание миграции `instawatch.db` в common.py — больше ничего.

- [ ] **Step 7: Commit**

```bash
git add schedule.py report.py common.py fetch.py telegram.py SKILL.md README.md tests/test_schedule.py
git commit -m "feat: rename product to feedwatch (labels, texts, SKILL, README)"
```

---

### Task 10: Физическое переименование — папка, GitHub, скилл, расписание

Задача ручная (без TDD), выполняется на машине Наташи после мерджа кода.

**Files:**
- Modify: `~/Projects/instawatch` → `~/Projects/feedwatch` (папка), `~/.claude/skills/instawatch`, git remote.

- [ ] **Step 1: GitHub rename** (редиректы старых URL сохраняются автоматически):

```bash
gh repo rename feedwatch -R Natalyyyy/instawatch --yes
```

- [ ] **Step 2: Папка + remote + venv** (venv пересоздаётся — в нём абсолютные пути):

```bash
cd ~/Projects && mv instawatch feedwatch && cd feedwatch
git remote set-url origin git@github-natalyyyy:Natalyyyy/feedwatch.git
rm -rf venv && python3 -m venv venv && ./venv/bin/pip install requests pytest
./venv/bin/python -m pytest tests/ -q
git push
```

Expected: тесты PASS, push ок.

- [ ] **Step 3: Скилл** — посмотреть, что лежит в `~/.claude/skills/`: если `instawatch` — симлинк, пересоздать `ln -s ~/Projects/feedwatch ~/.claude/skills/feedwatch && rm ~/.claude/skills/instawatch`; если папка-клон — `mv ~/.claude/skills/instawatch ~/.claude/skills/feedwatch && cd ~/.claude/skills/feedwatch && git remote set-url origin https://github.com/Natalyyyy/feedwatch && git pull`.

- [ ] **Step 4: Расписание** — если автоматика стояла: `cd ~/Projects/feedwatch && ./venv/bin/python schedule.py install` (install сам вычистит старые com.instawatch-лейблы — Task 9). Если не стояла — пропустить.

- [ ] **Step 5: Дымовая проверка** — `./venv/bin/python report.py pulse --no-fetch` (по данным из базы; заодно проверяет миграцию базы на живых данных: файл переименован, колонки добавлены).

---

## Порядок и зелёность

Каждый таск заканчивается полностью зелёным набором тестов; Tasks 1–3 — фундамент (конфиг/база/медианы), 4–5 — фетчеры (независимы друг от друга), 6 — оркестрация, 7–8 — отчёты, 9 — rename текстов, 10 — ручной финал. Legacy плоский config.json продолжает работать на каждом промежуточном коммите (нормализация в load_config появляется в Task 1, потребители переключаются в 6–8).
