"""Модель ходит с сужённым набором инструментов и без токенов (ревью 29.08.2026).

Проверено живьём и записано в content-planner/morning.sh: `--permission-mode`
разрешает, но НЕ сужает набор — с одним белым списком модель спокойно
выполняла команды шелла. Сужает `--tools`. В промпт идут подписи чужих инстаграм-аккаунтов и телеграм-каналов.

Тест поведенческий: подменяем subprocess.run и смотрим, с чем реально позвали
CLI и что осталось в окружении процесса.
"""
import subprocess
import types

import report


def _перехват(monkeypatch, модуль):
    захват = {}

    def подделка(cmd, **kw):
        захват["cmd"] = list(cmd)
        захват["env"] = kw.get("env")
        захват["input"] = kw.get("input")
        return types.SimpleNamespace(returncode=0, stdout="ответ модели", stderr="")

    monkeypatch.setattr(модуль.subprocess, "run", подделка)
    return захват


def _промпт(tmp_path):
    p = tmp_path / "prompt.md"
    p.write_text("инструкция", encoding="utf-8")
    return str(p)


def test_вызов_идёт_через_общую_обёртку_с_кодексом(monkeypatch, tmp_path):
    захват = _перехват(monkeypatch, report)
    report.claude_summary({("instagram", "acc"): [{"caption": "текст поста"}]}, _промпт(tmp_path))
    cmd = захват["cmd"]
    assert cmd[:2] == ["bash", str(report.Path(report.__file__).resolve().parent / "llm_run.sh")]
    for option, expected in (("--engine", "codex"), ("--model", "gpt-6-sol"),
                             ("--effort", "low"), ("--access", "none"),
                             ("--timeout", "300"), ("--cwd", str(report.Path(report.__file__).resolve().parent))):
        assert cmd[cmd.index(option) + 1] == expected
    assert "--tools" not in cmd
    assert "--disallowedTools" not in cmd
    assert "текст поста" in захват["input"]


def test_токены_не_доезжают_до_модели(monkeypatch, tmp_path):
    for имя in ("APIFY_TOKEN", "IG_ACCESS_TOKEN", "GROQ_API_KEY", "TELEGRAM_BOT_TOKEN",
                "CLAUDE_CODE_OAUTH_TOKEN"):
        monkeypatch.setenv(имя, "живой-" + имя)
    захват = _перехват(monkeypatch, report)
    report.claude_summary({("instagram", "acc"): [{"caption": "текст поста"}]}, _промпт(tmp_path))
    env = захват["env"]
    if env is None:
        import os
        env = os.environ
    утекло = [имя for имя in ("APIFY_TOKEN", "IG_ACCESS_TOKEN", "GROQ_API_KEY",
                              "TELEGRAM_BOT_TOKEN", "CLAUDE_CODE_OAUTH_TOKEN") if имя in env]
    assert утекло == [], "в окружение модели утекли " + str(утекло)


def test_ненулевой_код_обёртки_сбрасывает_ответ(monkeypatch, tmp_path):
    def failed(cmd, **kw):
        return types.SimpleNamespace(returncode=124, stdout="частичный ответ", stderr="таймаут")
    monkeypatch.setattr(report.subprocess, "run", failed)
    assert report.claude_summary({("instagram", "acc"): [{"caption": "текст"}]}, _промпт(tmp_path)) is None
