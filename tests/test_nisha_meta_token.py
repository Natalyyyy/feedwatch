"""nisha.sh: предупреждение «токену Meta осталось N дней».

Решение Наташи 21.09.2026: продлить токен может только она, поэтому близкий
срок (< 2 суток — 0 или 1 день) идёт срочным флагом через urgent.py, а запас
2–9 дней — обычной строкой в файл поломок (breakages.py). Когда токен
продлён (запас ≥ 10 дней — предупреждение больше не нужно — или срок вовсе
неизвестен), флаг срочного снимается через urgent.py clear, чтобы он не
остался висеть навсегда.

Порог «нужно ли вообще предупреждать» (10 дней) — старый, из уже
существующего кода, его я не придумываю; новый порог «срочно» — ровно
< 2 суток, как в задаче.

Внешнее (venv/bin/python — сборщики отчётов и сама проверка срока, urgent.py,
breakages.py) подменяется заглушками; сама nisha.sh не мокается и
запускается целиком.
"""
import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
# nisha.sh в .gitignore (репозиторий публичный) — см. test_nisha_sh.py.
pytestmark = pytest.mark.skipif(not (ROOT / "nisha.sh").exists(),
                                reason="nisha.sh не публикуется (см. .gitignore)")


def _stub(tmp_path, name, calls_name, rc_env):
    calls = tmp_path / calls_name
    stub = tmp_path / name
    stub.write_text(
        "import sys, os\n"
        f"open(r'{calls}', 'a').write('\\t'.join(sys.argv[1:]) + '\\n')\n"
        f"sys.exit(int(os.environ.get('{rc_env}', '0')))\n"
    )
    return stub, calls


@pytest.fixture()
def стенд(tmp_path):
    script_dir = tmp_path / "feedwatch"
    (script_dir / "data").mkdir(parents=True)
    (script_dir / "nisha.sh").write_text((ROOT / "nisha.sh").read_text(encoding="utf-8"),
                                         encoding="utf-8")

    vault = tmp_path / "vault"
    (vault / "projects/vibe-coding/configs").mkdir(parents=True)
    (vault / "projects/channel/trendwatching").mkdir(parents=True)
    (vault / "projects/vibe-coding/configs/config.nisha-biz.json").write_text(
        '{"accounts": []}\n', encoding="utf-8")

    urgent_stub, urgent_calls = _stub(tmp_path, "urgent_stub.py", "urgent-calls", "URGENT_RC")
    breakages_stub, breakages_calls = _stub(tmp_path, "breakages_stub.py", "breakages-calls", "RECORD_RC")

    (script_dir / ".env").write_text(
        f"FEEDWATCH_VAULT_ROOT={vault}\nFEEDWATCH_DATA_DIR={tmp_path / 'data'}\n"
        "FEEDWATCH_GIT_SYNC=0\n",
        encoding="utf-8")

    (script_dir / "venv" / "bin").mkdir(parents=True)
    python = script_dir / "venv" / "bin" / "python"
    python.write_text("""#!/usr/bin/env bash
case "$1" in
  -c) printf '%s\\n' "${FAKE_DAYS_LEFT:-}"; exit 0 ;;
  *report.py) out=""; while [ $# -gt 0 ]; do [ "$1" = "--out" ] && out="$2"; shift; done
              printf 'отчёт\\n' > "$out"; exit 0 ;;
  *reels.py)  exit 1 ;;
  *stream.py) printf '## блок\\nотчёт\\n' > "$2"; exit 0 ;;
esac
exit 0
""", encoding="utf-8")
    python.chmod(0o755)

    class Env:
        pass
    e = Env()
    e.script_dir, e.vault, e.tmp_path = script_dir, vault, tmp_path
    e.urgent_calls, e.breakages_calls = urgent_calls, breakages_calls
    e.base = {
        **os.environ,
        "URGENT_PY": str(urgent_stub),
        "BREAKAGES_PY": str(breakages_stub),
        "VAULT_LOCK_PATH": str(tmp_path / "vault.lock"),
    }
    return e


def _прогон(env, **extra):
    e = {**env.base, **extra}
    proc = subprocess.run(["bash", str(env.script_dir / "nisha.sh")],
                          capture_output=True, text=True, timeout=60, env=e)
    log = (env.tmp_path / "data" / "nisha.log")
    return proc, (log.read_text(encoding="utf-8") if log.exists() else "")


def _lines(path):
    return path.read_text().splitlines() if path.exists() else []


# --- happy: обычный запас — тишина + clear; предупредительный запас — файл --

def test_запас_большой_urgent_снимается(стенд):
    proc, log = _прогон(стенд, FAKE_DAYS_LEFT="30")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert _lines(стенд.urgent_calls) == ["clear\tmeta-token-feedwatch"]
    assert _lines(стенд.breakages_calls) == []


def test_запас_2_9_дней_идёт_в_файл_поломок(стенд):
    proc, log = _прогон(стенд, FAKE_DAYS_LEFT="5")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    [rec] = _lines(стенд.breakages_calls)
    assert rec.startswith("record\tfeedwatch-meta-token\t")
    assert "5" in rec
    assert _lines(стенд.urgent_calls) == []


# --- edge: срочная граница (0 и 1 день), срок неизвестен --------------------

def test_один_день_поднимает_urgent(стенд):
    proc, log = _прогон(стенд, FAKE_DAYS_LEFT="1")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    [call] = _lines(стенд.urgent_calls)
    assert call.startswith("raise\tmeta-token-feedwatch\t")
    assert _lines(стенд.breakages_calls) == []


def test_ноль_дней_поднимает_urgent(стенд):
    proc, log = _прогон(стенд, FAKE_DAYS_LEFT="0")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    [call] = _lines(стенд.urgent_calls)
    assert call.startswith("raise\tmeta-token-feedwatch\t")


def test_срок_неизвестен_не_поднимает_urgent(стенд):
    """Бессрочный токен или сбой самой проверки — не повод срочить."""
    proc, log = _прогон(стенд, FAKE_DAYS_LEFT="")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert _lines(стенд.urgent_calls) == ["clear\tmeta-token-feedwatch"]
    assert _lines(стенд.breakages_calls) == []


# --- error: urgent.py/breakages.py упали — видно в логе, скрипт не падает ---

def test_urgent_raise_падает_видно_в_логе(стенд):
    proc, log = _прогон(стенд, FAKE_DAYS_LEFT="1", URGENT_RC="1")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "urgent.py raise" in log and "не прошёл" in log


def test_breakages_record_падает_видно_в_логе(стенд):
    proc, log = _прогон(стенд, FAKE_DAYS_LEFT="5", RECORD_RC="1")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "breakages.py record" in log and "не прошёл" in log
