"""Накопительный файл-поток: один файл на поток, прогоны блоками сверху.

Раньше каждый прогон писал в волт отдельный файл с датой в имени. За три
недели в projects/channel/trendwatching скопилось 100 файлов при темпе 5 в
день, и папка перестала читаться глазами. Здесь прогон складывается в один
живой файл блоком `## ГГГГ-ММ-ДД`.

Файл — «живой архив» из конвенции волта (CLAUDE.md → «Формула нейминга»):
имя без даты, дата живёт внутри в заголовках блоков.
"""
from __future__ import annotations

import os
import re
import tempfile
from pathlib import Path

# Заголовок блока — «## ГГГГ-ММ-ДД» в начале строки и ничего больше: любой
# другой «## ...» внутри отчёта не должен приниматься за границу блока.
_BLOCK_RE = re.compile(r"^## (\d{4}-\d{2}-\d{2})\s*$", re.MULTILINE)


def _split_blocks(text: str) -> list[tuple[str, str]]:
    """Разбирает файл на [(дата, тело)], сохраняя порядок. Шапку отбрасывает."""
    marks = list(_BLOCK_RE.finditer(text))
    blocks = []
    for i, m in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(text)
        blocks.append((m.group(1), text[m.end():end].strip("\n")))
    return blocks


def render(title: str, blocks: list[tuple[str, str]]) -> str:
    parts = ["# " + title, ""]
    for date, body in blocks:
        parts.append("## " + date)
        parts.append(body.strip("\n"))
        parts.append("")
    return "\n".join(parts).rstrip("\n") + "\n"


def _write_atomic(path: Path, text: str) -> None:
    """Через временный файл и os.replace: обрыв на полуслове иначе затёр бы всю
    накопленную историю, а не один день, как было при подневных файлах."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def _archive_path(path: Path, date: str) -> Path:
    """Архив по годам рядом с живым файлом: «поток.md» → «поток – 2026.md»."""
    return path.with_name("{} – {}{}".format(path.stem, date[:4], path.suffix))


def prepend_block(path, title: str, date: str, body: str, keep: int = 0) -> Path:
    """Кладёт прогон за `date` в файл-поток, свежие блоки выше старых.

    Повторный прогон за ту же дату заменяет блок, а не добавляет второй:
    ручной перезапуск после сбоя — штатная ситуация, а дубль сломал бы и
    чтение планёркой, и чтение глазами.
    """
    path = Path(path)
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    blocks = [b for b in _split_blocks(text) if b[0] != date]
    blocks.append((date, body))
    # По дате убывающе: догоняющий прогон за прошлое число встаёт на своё
    # место, а не сверху и не вместо свежего.
    blocks.sort(key=lambda b: b[0], reverse=True)

    # Прогон весит ~8 КБ, а планёрка смотрит максимум на три дня назад: без
    # обрезки живой файл за год вырастает до нескольких мегабайт и становится
    # неоткрываемым. Лишнее уезжает в архив по годам, а не удаляется.
    if keep and len(blocks) > keep:
        blocks, устаревшие = blocks[:keep], blocks[keep:]
        for год in sorted({b[0][:4] for b in устаревшие}):
            arc = _archive_path(path, год)
            прежние = _split_blocks(arc.read_text(encoding="utf-8")) if arc.exists() else []
            свежие = [b for b in устаревшие if b[0][:4] == год]
            слитые = {b[0]: b[1] for b in прежние}
            слитые.update({b[0]: b[1] for b in свежие})
            _write_atomic(arc, render("{} — архив {}".format(title, год),
                                      sorted(слитые.items(), reverse=True)))

    _write_atomic(path, render(title, blocks))
    return path


def main(argv=None) -> int:
    """CLI: stream.py <поток.md> <заголовок> <ГГГГ-ММ-ДД> <отчёт.md> [--keep N]"""
    import sys

    argv = list(sys.argv[1:] if argv is None else argv)
    keep = 0
    if "--keep" in argv:
        i = argv.index("--keep")
        try:
            keep = int(argv[i + 1])
        except (IndexError, ValueError):
            print("--keep требует число", file=sys.stderr)
            return 2
        del argv[i:i + 2]

    if len(argv) != 4:
        print("usage: stream.py <поток.md> <заголовок> <ГГГГ-ММ-ДД> <отчёт.md> "
              "[--keep N]", file=sys.stderr)
        return 2

    out, title, date, report = argv
    src = Path(report)
    if not src.exists():
        # Молча положить пустой блок нельзя: планёрка прочтёт его как
        # «в нише тихо» — тихая потеря данных вместо громкой ошибки.
        print("нет файла отчёта: {}".format(report), file=sys.stderr)
        return 1

    body = src.read_text(encoding="utf-8")
    # Шапка отчёта («# ...») внутри блока лишняя: её роль играет «## дата».
    body = re.sub(r"\A#\s+[^\n]*\n+", "", body)
    prepend_block(out, title, date, body, keep=keep)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
