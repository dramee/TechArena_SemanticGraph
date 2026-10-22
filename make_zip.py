"""Собирает solution.zip для сдачи: код решения, описание и ответ.

В архив не попадают тесты, отладочные инструменты и настройки разработки.

Запуск::

    python make_zip.py
"""

import os
import zipfile

ROOT = os.path.dirname(os.path.abspath(__file__))
TOP_FILES = ("your_solution.py", "SOLUTION.md", "submission.json")
PACKAGE = "solution"
EXCLUDED_DIRS = ("__pycache__", "tools")


def collect_files():
    """Возвращает пути файлов архива относительно корня проекта."""
    files = list(TOP_FILES)
    for dirpath, dirnames, filenames in os.walk(os.path.join(ROOT, PACKAGE)):
        dirnames[:] = [d for d in dirnames if d not in EXCLUDED_DIRS]
        for name in filenames:
            if name.endswith(".py"):
                rel = os.path.relpath(os.path.join(dirpath, name), ROOT)
                files.append(rel.replace(os.sep, "/"))
    return sorted(files)


def main():
    """Пишет архив и печатает его содержимое."""
    out = os.path.join(ROOT, "solution.zip")
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for rel in collect_files():
            z.write(os.path.join(ROOT, rel), rel)
    with zipfile.ZipFile(out) as z:
        for info in z.infolist():
            print(f"{info.file_size:8d}  {info.filename}")
    print(os.path.getsize(out), "байт ->", out)


if __name__ == "__main__":
    main()
