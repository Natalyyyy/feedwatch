"""Накопительные файлы-потоки: один файл на поток, новый прогон сверху.

До 08.08.2026 каждый прогон клал в волт отдельный файл с датой в имени, и
за три недели в trendwatching накопилось 100 файлов при темпе 5 в день.
Здесь — фолдинг прогона в один живой файл.
"""
from pathlib import Path

import pytest

from stream import prepend_block


TITLE = "Инстаграм-ниша: ai"


def test_creates_file_with_title_and_block(tmp_path: Path):
    """Первый прогон: файла ещё нет, он должен появиться с заголовком и блоком."""
    path = tmp_path / "поток.md"

    prepend_block(path, TITLE, "2026-08-09", "топ-3 за неделю\n")

    text = path.read_text(encoding="utf-8")
    assert text.startswith("# " + TITLE + "\n")
    assert "## 2026-08-09" in text
    assert "топ-3 за неделю" in text


def test_newer_block_goes_above_older(tmp_path: Path):
    """Свежее сверху: иначе за свежим отчётом придётся мотать в конец файла."""
    path = tmp_path / "поток.md"

    prepend_block(path, TITLE, "2026-08-08", "вчерашнее\n")
    prepend_block(path, TITLE, "2026-08-09", "сегодняшнее\n")

    text = path.read_text(encoding="utf-8")
    assert text.index("## 2026-08-09") < text.index("## 2026-08-08")
    assert "вчерашнее" in text


def test_same_date_twice_replaces_not_duplicates(tmp_path: Path):
    """Повторный прогон за тот же день — обычное дело: ручной перезапуск после
    сбоя. Дублирующийся блок развалил бы и чтение планёркой, и глазами."""
    path = tmp_path / "поток.md"

    prepend_block(path, TITLE, "2026-08-09", "первая версия\n")
    prepend_block(path, TITLE, "2026-08-09", "исправленная версия\n")

    text = path.read_text(encoding="utf-8")
    assert text.count("## 2026-08-09") == 1
    assert "исправленная версия" in text
    assert "первая версия" not in text


def test_older_block_does_not_clobber_history(tmp_path: Path):
    """Догоняющий прогон за прошлую дату встаёт на своё место по порядку,
    а не сверху и не вместо свежего."""
    path = tmp_path / "поток.md"

    prepend_block(path, TITLE, "2026-08-09", "свежее\n")
    prepend_block(path, TITLE, "2026-08-07", "догоняющее\n")

    text = path.read_text(encoding="utf-8")
    assert text.index("## 2026-08-09") < text.index("## 2026-08-07")
    assert "свежее" in text and "догоняющее" in text


def test_cli_folds_report_file_into_stream(tmp_path: Path):
    """nisha.sh зовёт стрим как процесс: report.py пишет отчёт во временный
    файл, стрим складывает его в поток. Без CLI шелл звал бы python -c с
    экранированием кириллицы — источник тихих поломок."""
    import stream

    report = tmp_path / "отчёт.md"
    report.write_text("# заголовок отчёта\n\nтело\n", encoding="utf-8")
    out = tmp_path / "поток.md"

    rc = stream.main([str(out), TITLE, "2026-08-09", str(report)])

    assert rc == 0
    text = out.read_text(encoding="utf-8")
    assert "## 2026-08-09" in text
    assert "тело" in text


def test_cli_fails_loudly_when_report_missing(tmp_path: Path):
    """Отчёт не собрался — поток трогать нельзя: пустой блок планёрка
    прочтёт как «в нише тихо», а это тихая потеря данных."""
    import stream

    out = tmp_path / "поток.md"
    rc = stream.main([str(out), TITLE, "2026-08-09", str(tmp_path / "нет.md")])

    assert rc != 0
    assert not out.exists()


def test_старые_блоки_уезжают_в_архив(tmp_path: Path):
    """8 КБ на прогон — за год живой файл раздуется до 3 МБ, а планёрка смотрит
    максимум на три дня назад. Лишнее уезжает в архив по годам, не пропадая."""
    path = tmp_path / "поток.md"
    for день in range(1, 6):
        prepend_block(path, TITLE, "2026-08-0%d" % день, "прогон %d\n" % день,
                      keep=2)

    живой = path.read_text(encoding="utf-8")
    архив = (tmp_path / "поток – 2026.md").read_text(encoding="utf-8")

    assert живой.count("## ") == 2
    assert "## 2026-08-05" in живой and "## 2026-08-04" in живой
    assert "прогон 1" in архив and "прогон 3" in архив


def test_архив_не_теряет_ранее_сложенное(tmp_path: Path):
    """Второй перелив не должен затирать первый."""
    path = tmp_path / "поток.md"
    for день in range(1, 8):
        prepend_block(path, TITLE, "2026-08-0%d" % день, "прогон %d\n" % день,
                      keep=2)

    архив = (tmp_path / "поток – 2026.md").read_text(encoding="utf-8")

    assert архив.count("## ") == 5
    assert "прогон 1" in архив


def test_без_keep_ничего_не_обрезается(tmp_path: Path):
    """Обрезка — осознанный вызов, а не поведение по умолчанию."""
    path = tmp_path / "поток.md"
    for день in range(1, 6):
        prepend_block(path, TITLE, "2026-08-0%d" % день, "прогон %d\n" % день)

    assert path.read_text(encoding="utf-8").count("## ") == 5
    assert not (tmp_path / "поток – 2026.md").exists()


def test_cli_принимает_keep(tmp_path: Path):
    """nisha.sh задаёт глубину живого файла — иначе обрезка недостижима из шелла."""
    import stream

    out = tmp_path / "поток.md"
    for день in (7, 8, 9):
        report = tmp_path / "r.md"
        report.write_text("тело %d\n" % день, encoding="utf-8")
        assert stream.main([str(out), TITLE, "2026-08-0%d" % день,
                            str(report), "--keep", "2"]) == 0

    assert out.read_text(encoding="utf-8").count("## ") == 2
    assert (tmp_path / "поток – 2026.md").exists()
