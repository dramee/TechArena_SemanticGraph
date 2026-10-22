"""Собирает solution.zip: код решения, тесты и submission.json.

Запуск::

    python make_zip.py
"""

import os
import zipfile

ROOT = os.path.dirname(os.path.abspath(__file__))
TOP_FILES = (
    "your_solution.py",
    "SOLUTION.md",
    "submission.json",
    "pyproject.toml",
    ".flake8",
    "requirements-dev.txt",
)
PACKAGES = ("solution", "tests")


def collect_files():
    """Возвращает пути файлов архива относительно корня проекта."""
    files = [f for f in TOP_FILES if os.path.exists(os.path.join(ROOT, f))]
    for package in PACKAGES:
        for dirpath, dirnames, filenames in os.walk(
            os.path.join(ROOT, package)
        ):
            dirnames[:] = [d for d in dirnames if d != "__pycache__"]
            for name in filenames:
                if not name.endswith(".pyc"):
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
