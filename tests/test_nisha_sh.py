"""Публикация отчётов ниши идёт точными именами файлов, а не каталогом.

Протокол `vault_git` каталог отбивает намеренно: коммит каталогом забрал бы и
чужие правки под тем же путём, а в `projects/channel/trendwatching` рядом лежат
потоки других джоб. Каталог здесь работал до 20.09.2026, пока эталон не доехал
до копии этого репозитория; после этого джоба падала с «exact vault-relative
file paths required».

Протокол настоящий — копия `vault_git` из репозитория и волт с origin:
проверяется то, что уехало в origin. С 21.09.2026 публикуются только свои потоки
точными именами: раскрытие общего каталога унесло бы и незакоммиченную правку
соседней джобы (тест ниже).
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

    origin = tmp_path / "origin.git"
    git("init", "-q", "--bare", "-b", "main", str(origin), cwd=tmp_path)
    vault = tmp_path / "vault"
    git("clone", "-q", str(origin), str(vault), cwd=tmp_path)
    git("config", "user.email", "t@t", cwd=vault)
    git("config", "user.name", "t", cwd=vault)
    git("checkout", "-q", "-b", "main", cwd=vault)
    (vault / "projects/channel/trendwatching").mkdir(parents=True)
    (vault / "projects/vibe-coding/configs").mkdir(parents=True)
    (vault / "projects/vibe-coding/configs/config.nisha-biz.json").write_text(
        '{"accounts": []}\n', encoding="utf-8")
    # Чужой поток в том же каталоге: он не наш и в публикацию попасть не должен.
    (vault / ЧУЖОЙ_ПОТОК).write_text("# трендвотч тг\n", encoding="utf-8")
    git("add", "-A", cwd=vault)
    git("commit", "-qm", "seed", cwd=vault)
    git("push", "-q", "-u", "origin", "main", cwd=vault)

    (script_dir / ".env").write_text(
        f"FEEDWATCH_VAULT_ROOT={vault}\nFEEDWATCH_DATA_DIR={tmp_path / 'data'}\n"
        "FEEDWATCH_GIT_SYNC=1\nTELEGRAM_BOT_TOKEN=x\nTELEGRAM_CHAT_ID=42\n",
        encoding="utf-8")
    for f in ("vault_git.sh", "vault_git.py"):
        (script_dir / f).write_bytes((РЕПО / f).read_bytes())

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
    env = {k: v for k, v in os.environ.items() if k != "VAULT_LOCK_FD"}
    env["VAULT_LOCK_PATH"] = str(tmp_path / "vault.lock")
    return subprocess.run(["bash", str(script_dir / "nisha.sh")],
                          capture_output=True, text=True, timeout=60, env=env)


def _уехало(vault):
    """Файлы последнего коммита в origin/main — то, что реально опубликовано."""
    git("fetch", "-q", "origin", cwd=vault)
    out = git("diff-tree", "--no-commit-id", "--name-only", "--no-renames", "-r", "-z",
              "origin/main~1", "origin/main", cwd=vault).stdout
    return sorted(filter(None, out.split("\0")))


def _коммитов(vault):
    git("fetch", "-q", "origin", cwd=vault)
    return int(git("rev-list", "--count", "origin/main", cwd=vault).stdout)


def test_публикация_идёт_файлами_а_не_каталогом(стенд):
    script_dir, vault, tmp_path = стенд
    res = _прогон(стенд)
    assert res.returncode == 0, res.stdout + res.stderr

    assert _уехало(vault) == [ПОТОК], "в волт уехал не свой поток"


def test_неготовая_правка_соседа_не_уезжает(стенд):
    """Край: соседняя джоба пишет свой поток в тот же каталог и ещё не
    закоммитила. Раскрытие каталога унесло бы её правку в коммит «feedwatch»."""
    script_dir, vault, tmp_path = стенд
    (vault / ЧУЖОЙ_ПОТОК).write_text("# трендвотч тг\nсосед пишет\n", encoding="utf-8")

    res = _прогон(стенд)

    assert res.returncode == 0, res.stdout + res.stderr
    assert _уехало(vault) == [ПОТОК]
    assert "трендвотч тг" in git("-c", "core.quotepath=false", "status", "--porcelain",
                                 cwd=vault).stdout, "правка соседа должна остаться в клоне"


def test_нечего_публиковать_коммита_нет(стенд):
    """Край: поток уже закоммичен и не изменился — успех без пустого коммита."""
    script_dir, vault, tmp_path = стенд
    (vault / ПОТОК).write_text("## блок\nотчёт\n", encoding="utf-8")
    git("add", "-A", cwd=vault)
    git("commit", "-qm", "поток уже в истории", cwd=vault)
    git("push", "-q", cwd=vault)
    было = _коммитов(vault)

    res = _прогон((script_dir, vault, tmp_path))

    assert res.returncode == 0, res.stdout + res.stderr
    assert _коммитов(vault) == было, "появился коммит, хотя публиковать нечего"


def test_отказ_push_роняет_джобу(стенд):
    """Ошибка: origin не принял — код выхода не 0."""
    script_dir, vault, tmp_path = стенд
    hook = tmp_path / "origin.git" / "hooks" / "pre-receive"
    hook.write_text("#!/bin/sh\nexit 1\n")
    hook.chmod(0o755)

    res = _прогон(стенд)

    assert res.returncode != 0
