#!/usr/bin/env python3
"""Разбор видео чужих рилсов: речь в текст + кадры.

Зачем. Инстаграм-отчёты feedwatch до 08.08.2026 видели только подпись под
постом, а у рилса подпись — это одна строка, весь смысл в самом видео. Все
разборы ниши поэтому шли с оговоркой «анализ ограничен слоем подписей».
Здесь эта дыра закрывается: у топовых рилсов недели забираем звук (Groq
Whisper) и несколько кадров, дальше их читает планёрка.

Почему сразу после сбора, а не отдельной джобой. `media_url` от Meta живёт
на CDN считанные часы: ссылка, записанная вчера, сегодня уже мертва. Значит
качать надо в том же прогоне, что и fetch, иначе разбирать будет нечего.

Наружу отдаём только текст — блоком в поток инстаграм-ниши. Сам файл живёт во
временной папке и удаляется сразу после расшифровки: хранить его незачем,
посмотреть ролик глазами всегда можно по `permalink` в инстаграме, а свежую
ссылку на файл каждый прогон приносит заново.

Кадры в автоматике НЕ режем (`--frames 0` по умолчанию) — читать их некому:
планёрка на Pi картинки не смотрит. Флаг оставлен для ручного разбора на Маке:
там кадры видит Claude и может прочитать плашки и субтитры немого ролика.
"""
import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import timedelta
from pathlib import Path

import requests

import common

GROQ_URL = "https://api.groq.com/openai/v1/audio/transcriptions"
GROQ_MODEL = "whisper-large-v3"
DOWNLOAD_TIMEOUT = 120
# Лимит Groq на файл — 25 МБ. Минута речи во flac 16 кГц моно весит ~1 МБ,
# так что для рилсов (обычно до 90 секунд) запас многократный, и резать на
# куски, как это делает groq-transcribe для часовых митингов, не нужно.
MAX_AUDIO_BYTES = 24 * 1024 * 1024


class ReelError(Exception):
    """Осечка на одном рилсе. Остальные должны досчитаться."""


# Whisper на дорожке без речи (музыка, только текст на экране) не отдаёт
# пустоту, а выдумывает титры из обучающей выборки — «Субтитры сделал…»,
# «Продолжение следует…». Поймано 08.08.2026 на рилсе @marinamogilko, где
# слов нет вовсе. Пропустить такое дальше опаснее, чем ничего не отдать:
# планёрка примет выдумку за реплику автора.
# Ловим не слово «субтитры» само по себе — про субтитры в рилсах Наташа и её
# ниша говорят регулярно, живую реплику резать нельзя. Признак выдумки в том,
# что короткая строка НАЧИНАЕТСЯ с этого слова: «Субтитры сделал…», «Субтитры
# создавал…». Перечислять глаголы бесполезно — 09.08.2026 сквозь список фраз
# прошло «создавал» при том, что «создал» в списке был.
HALLUCINATION_RE = re.compile(
    r"^\s*субтитры\b"
    r"|редактор субтитров"
    r"|^\s*продолжение следует"
    r"|спасибо за просмотр"
    r"|подписывайтесь на канал",
    re.IGNORECASE,
)
# Настоящие титры-галлюцинации короткие. Живая речь такой длины тоже бывает,
# поэтому одной длины мало — нужно ещё совпадение с шаблоном.
HALLUCINATION_MAX_LEN = 80


def clean_transcript(text):
    """Пустая строка вместо выдуманных титров. Настоящую речь не трогаем."""
    text = (text or "").strip()
    if not text:
        return ""
    if len(text) <= HALLUCINATION_MAX_LEN and HALLUCINATION_RE.search(text):
        return ""
    return text


def _ffmpeg(args):
    proc = subprocess.run(["ffmpeg", "-y", "-v", "error", *args],
                          capture_output=True, text=True)
    if proc.returncode != 0:
        raise ReelError(f"ffmpeg: {proc.stderr[-500:]}")


def candidates(con, cfg, days=7, limit=5, now=None):
    """Топ рилсов за окно: сильнее своей медианы, с живой ссылкой, без транскрипта.

    Считаем в кратных медианы аккаунта, а не в абсолютных лайках, — иначе
    крупный аккаунт всегда забирал бы все слоты у маленького.
    """
    now = now or common.now_utc()
    window_start = now - timedelta(days=days)
    rows = con.execute(
        "SELECT p.post_id, p.account, p.caption, p.posted_at, p.permalink, p.media_url,"
        "       (SELECT likes FROM snapshots s WHERE s.post_id = p.post_id"
        "        ORDER BY s.fetched_at DESC LIMIT 1) AS likes"
        " FROM posts p"
        # Пустая строка — это «разобрали, речи не было»: такой рилс повторно
        # не качаем, иначе немые ролики съедали бы все слоты каждый прогон.
        " WHERE p.media_type = 'VIDEO' AND p.media_url IS NOT NULL"
        "   AND p.transcript IS NULL"
    ).fetchall()

    medians, out = {}, []
    for r in rows:
        if common.parse_ts(r["posted_at"]) < window_start:
            continue
        acc = r["account"]
        if acc not in medians:
            medians[acc] = common.account_medians(con, acc, cfg)
        med = (medians[acc] or {}).get("likes")
        likes = r["likes"]
        if not med or likes is None:
            continue
        out.append({**dict(r), "ratio": likes / med})
    out.sort(key=lambda x: -x["ratio"])
    return out[:limit]


def download(url, dst):
    with requests.get(url, stream=True, timeout=DOWNLOAD_TIMEOUT) as resp:
        if resp.status_code != 200:
            # Самый частый случай — протухшая ссылка: её уже не воскресить.
            raise ReelError(f"скачивание не удалось, HTTP {resp.status_code}")
        with open(dst, "wb") as fh:
            shutil.copyfileobj(resp.raw, fh)
    if dst.stat().st_size == 0:
        raise ReelError("пустой файл")


def transcribe(video, api_key, language="ru"):
    with tempfile.TemporaryDirectory() as tmp:
        audio = Path(tmp) / "audio.flac"
        _ffmpeg(["-i", str(video), "-vn", "-ac", "1", "-ar", "16000", str(audio)])
        if audio.stat().st_size > MAX_AUDIO_BYTES:
            raise ReelError("аудио длиннее, чем влезает в один запрос Groq")
        with open(audio, "rb") as fh:
            resp = requests.post(
                GROQ_URL,
                headers={"Authorization": f"Bearer {api_key}"},
                files={"file": (audio.name, fh, "audio/flac")},
                data={"model": GROQ_MODEL, "language": language},
                timeout=180,
            )
    if resp.status_code != 200:
        raise ReelError(f"Groq вернул {resp.status_code}: {resp.text[:200]}")
    return clean_transcript(resp.json().get("text"))


def grab_frames(video, out_dir, count=6, width=480):
    """Равномерные кадры по всей длине — видно плашки, субтитры и что в кадре."""
    out_dir.mkdir(parents=True, exist_ok=True)
    duration = probe_duration(video)
    step = max(duration / count, 1.0) if duration else 9.0
    _ffmpeg(["-i", str(video), "-vf", f"fps=1/{step:.2f},scale={width}:-1",
             "-frames:v", str(count), str(out_dir / "frame_%02d.jpg")])
    return sorted(out_dir.glob("frame_*.jpg"))


def probe_duration(video):
    proc = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", str(video)], capture_output=True, text=True)
    try:
        return float(proc.stdout.strip())
    except ValueError:
        return 0.0


def rotate(root, keep_days=14, now=None):
    """Старые папки с кадрами удаляем — это кэш ручного разбора, а не архив."""
    now = now or common.now_utc()
    cutoff = (now - timedelta(days=keep_days)).strftime("%Y-%m-%d")
    for child in sorted(root.glob("20*")):
        if child.is_dir() and child.name < cutoff:
            shutil.rmtree(child, ignore_errors=True)


def process(con, cfg, env, days=7, limit=5, frames=0, data_dir=None, keep_days=14):
    api_key = env.get("GROQ_API_KEY")
    if not api_key:
        raise ReelError("в .env нет GROQ_API_KEY — расшифровывать нечем")
    data_dir = Path(data_dir or env.get("FEEDWATCH_DATA_DIR")
                    or Path.home() / "feedwatch-data") / "reels"

    done, failed = [], []
    for item in candidates(con, cfg, days=days, limit=limit):
        slug = f"{item['account']}-{item['post_id']}"
        try:
            # Видео нужно ровно на время расшифровки: качаем во временную
            # папку, она сама убирается на выходе из блока.
            with tempfile.TemporaryDirectory(prefix="reel-") as tmp:
                video = Path(tmp) / f"{slug}.mp4"
                download(item["media_url"], video)
                text = transcribe(video, api_key)
                shots = ([str(p) for p in grab_frames(
                    video, data_dir / common.now_utc().strftime("%Y-%m-%d") / slug,
                    count=frames)] if frames else [])
            con.execute("UPDATE posts SET transcript=? WHERE post_id=?",
                        (text, item["post_id"]))
            con.commit()
            done.append({**item, "transcript": text, "frames": shots})
        except (ReelError, requests.RequestException, OSError) as exc:
            # Один мёртвый рилс не повод терять остальные.
            failed.append({**item, "error": str(exc)})
    if data_dir.exists():
        rotate(data_dir, keep_days=keep_days)
    return done, failed


def render(done, failed):
    if not done and not failed:
        return "🎬 Рилсы: нечего разбирать (нет свежих видео с живой ссылкой)\n"
    out = ["🎬 Расшифровка топовых рилсов недели\n"]
    for item in done:
        cap = " ".join((item["caption"] or "").split())[:120]
        out.append(f"\n@{item['account']} — ×{item['ratio']:.1f} от медианы"
                   f" · {item['posted_at'][:10]}\n{item['permalink']}")
        if cap:
            out.append(f"подпись: {cap}")
        if item["transcript"]:
            out.append(f"речь: {item['transcript']}")
        else:
            # Немой ролик держится на тексте в кадре и монтаже — расшифровка
            # тут бессильна. Смотреть его надо по ссылке выше.
            out.append("речь: без слов — смысл в кадре, смотреть сам ролик")
        if item["frames"]:
            out.append(f"кадры ({len(item['frames'])}): {Path(item['frames'][0]).parent}")
    for item in failed:
        out.append(f"\n@{item['account']} {item['permalink']} — не разобрал: {item['error']}")
    return "\n".join(out) + "\n"


def main():
    ap = argparse.ArgumentParser(description="Расшифровка чужих рилсов: речь + кадры")
    ap.add_argument("--config", help="конфиг вместо config.json")
    ap.add_argument("--db", help="файл базы")
    ap.add_argument("--out", help="записать отчёт в файл")
    ap.add_argument("--days", type=int, default=7, help="окно отбора, дней")
    ap.add_argument("--limit", type=int, default=5, help="сколько рилсов разбирать")
    ap.add_argument("--frames", type=int, default=0,
                    help="нарезать N кадров на рилс (для ручного разбора; в автоматике не нужно)")
    ap.add_argument("--keep-days", type=int, default=14, help="сколько дней держать видео")
    args = ap.parse_args()

    cfg = common.load_config(args.config)
    env = common.load_env()
    con = common.connect(args.db)
    try:
        done, failed = process(con, cfg, env, days=args.days, limit=args.limit,
                               frames=args.frames, keep_days=args.keep_days)
    except ReelError as exc:
        print(f"reels: {exc}", file=sys.stderr)
        return 1
    text = render(done, failed)
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
    else:
        print(text)
    print(f"reels: разобрано {len(done)}, не вышло {len(failed)}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
