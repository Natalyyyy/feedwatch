"""Публикация отчётов ниши идёт точными именами файлов, а не каталогом.

Протокол `vault_git` каталог отбивает намеренно: коммит каталогом забрал бы и
чужие правки под тем же путём, а в `projects/channel/trendwatching` рядом лежат
потоки других джоб. Каталог здесь работал до 20.09.2026, пока эталон не доехал
до копии этого репозитория; после этого джоба падала с «exact vault-relative
file paths required».

`vault_publish_safe` подменён заглушкой, пишущей свои аргументы, — тот же приём,
что в tgstat-puller/tests/test_pull_sh.py.
"""
import os
import subprocess
from pathlib import Path

import pytest

РЕПО = Path(__file__).resolve().parent.parent
# Сам nisha.sh в .gitignore: репозиторий публичный, а в скрипте пути и логика
# наблюдения за чужими аккаунтами. Канон копии — projects/vibe-coding/configs
# в волте. В чистом клоне файла нет, и тесту нечего проверять.
pytestmark = pytest.mark.skipif(not (РЕПО / "nisha.sh").exists(),
                                reason="nisha.sh не публикуется (см. .gitignore)")
ПОТОК = "projects/channel/trendwatching/{channel} {source} инстаграм-ниша биз.md"
ЧУЖОЙ_ПОТОК = "projects/channel/trendwatching/{channel} {source} трендвотч тг.md"


def git(*args, cwd):
    return subprocess.run(["git", *args], cwd=cwd, check=True,
                          capture_output=True, text=True)


@pytest.fixture()
def стенд(tmp_path):
    script_dir = tmp_path / "feedwatch"
    (script_dir / "data").mkdir(parents=True)
    (script_dir / "nisha.sh").write_text((РЕПО / "nisha.sh").read_text(encoding="utf-8"),
                                         encoding="utf-8")

    vault = tmp_path / "vault"
    (vault / "projects/channel/trendwatching").mkdir(parents=True)
    (vault / "projects/vibe-coding/configs").mkdir(parents=True)
    git("init", "-q", "-b", "main", ".", cwd=vault)
    git("config", "user.email", "t@t", cwd=vault)
    git("config", "user.name", "t", cwd=vault)
    (vault / "projects/vibe-coding/configs/config.nisha-biz.json").write_text(
        '{"accounts": []}\n', encoding="utf-8")
    # Чужой поток в том же каталоге: он не наш и в публикацию попасть не должен.
    (vault / ЧУЖОЙ_ПОТОК).write_text("# трендвотч тг\n", encoding="utf-8")
    git("add", "-A", cwd=vault)
    git("commit", "-qm", "seed", cwd=vault)

    (script_dir / ".env").write_text(
        f"FEEDWATCH_VAULT_ROOT={vault}\nFEEDWATCH_DATA_DIR={tmp_path / 'data'}\n"
        "FEEDWATCH_GIT_SYNC=1\nTELEGRAM_BOT_TOKEN=x\nTELEGRAM_CHAT_ID=42\n",
        encoding="utf-8")
    (script_dir / "vault_git.sh").write_text(
        "vault_begin(){ :; }\n"
        "vault_publish_safe(){ printf '%s\\n' \"$@\" > \"$VAULT_PUBLISH_ARGS\"; }\n",
        encoding="utf-8")

    # Один питон за report.py, reels.py, stream.py и вычисление запаса токена.
    (script_dir / "venv" / "bin").mkdir(parents=True)
    питон = script_dir / "venv" / "bin" / "python"
    питон.write_text(f"""#!/usr/bin/env bash
case "$1" in
  -c) echo 30; exit 0 ;;                       # запас токена Meta в днях
  *report.py) out=""; while [ $# -gt 0 ]; do [ "$1" = "--out" ] && out="$2"; shift; done
              printf 'отчёт\\n' > "$out"; exit 0 ;;
  *reels.py)  exit 1 ;;                        # расшифровка осекается — штатно
  *stream.py) printf '## блок\\nотчёт\\n' > "{vault}/{ПОТОК}"; exit 0 ;;
esac
exit 0
""", encoding="utf-8")
    питон.chmod(0o755)
    return script_dir, vault, tmp_path


def _прогон(стенд):
    script_dir, vault, tmp_path = стенд
    args_file = tmp_path / "publish-args.txt"
    res = subprocess.run(["bash", str(script_dir / "nisha.sh")],
                         capture_output=True, text=True, timeout=60,
                         env={**os.environ, "VAULT_PUBLISH_ARGS": str(args_file)})
    return res, args_file


def test_публикация_идёт_файлами_а_не_каталогом(стенд):
    res, args_file = _прогон(стенд)
    assert res.returncode == 0, res.stdout + res.stderr

    args = args_file.read_text(encoding="utf-8").splitlines()
    assert "projects/channel/trendwatching" not in args, (
        "передан каталог — протокол такой вызов отбивает")
    assert ПОТОК in args, f"свой поток не попал в публикацию: {args}"
    assert ЧУЖОЙ_ПОТОК not in args, (
        f"захвачен чужой поток, который джоба не меняла: {args}")


def test_нечего_публиковать_протокол_не_зовётся(стенд):
    """Край: поток уже закоммичен и не изменился. Пустой список публиковать
    нельзя — протокол отбивает вызов без путей."""
    script_dir, vault, tmp_path = стенд
    (vault / ПОТОК).write_text("## блок\nотчёт\n", encoding="utf-8")
    git("add", "-A", cwd=vault)
    git("commit", "-qm", "поток уже в истории", cwd=vault)

    res, args_file = _прогон((script_dir, vault, tmp_path))

    assert res.returncode == 0, res.stdout + res.stderr
    assert not args_file.exists(), "протокол позвали, хотя публиковать нечего"
