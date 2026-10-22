"""Собирает диагностическую сдачу: ответ с изменёнными рёбрами сценария.

Платформа показывает балл каждого сценария отдельно, поэтому изменение
одного сценария проверяет гипотезу разметки: рост балла подтверждает её,
падение — опровергает. Файл правок — JSON вида::

    {"S5": {"add": [["источник", "calls", "цель"]], "remove": [...]}}

Запуск::

    python -m solution.tools.make_probe submission.json edits.json probe.zip
"""

import json
import os
import sys
import zipfile

from .common import ROOT

CODE_FILES = ("your_solution.py", "SOLUTION.md")


def apply_edits(answer, edits):
    """Возвращает копию ответа с добавленными и удалёнными рёбрами."""
    out = json.loads(json.dumps(answer))
    for sid, change in edits.items():
        block = out["scenarios"][sid]["edges"]
        remove = {tuple(e) for e in change.get("remove", ())}
        kept = [
            e
            for e in block
            if (e["source"], e["relation"], e["target"]) not in remove
        ]
        present = {(e["source"], e["relation"], e["target"]) for e in kept}
        for source, relation, target in change.get("add", ()):
            if (source, relation, target) not in present:
                kept.append(
                    {"source": source, "relation": relation, "target": target}
                )
        out["scenarios"][sid]["edges"] = kept
    return out


def code_files():
    """Возвращает пути файлов кода решения относительно корня."""
    files = list(CODE_FILES)
    for dirpath, dirnames, filenames in os.walk(
        os.path.join(ROOT, "solution")
    ):
        dirnames[:] = [d for d in dirnames if d != "__pycache__"]
        for name in filenames:
            if name.endswith(".py"):
                rel = os.path.relpath(os.path.join(dirpath, name), ROOT)
                files.append(rel.replace(os.sep, "/"))
    return sorted(files)


def main(argv):
    """Пишет архив с кодом и изменённым ``submission.json``."""
    answer_path, edits_path, zip_path = argv
    with open(answer_path, encoding="utf-8") as f:
        answer = json.load(f)
    with open(edits_path, encoding="utf-8") as f:
        edits = json.load(f)
    probe = apply_edits(answer, edits)
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
        for rel in code_files():
            z.write(os.path.join(ROOT, rel), rel)
        z.writestr("submission.json", json.dumps(probe, ensure_ascii=False))
    print("->", os.path.normpath(zip_path))


if __name__ == "__main__":
    main(sys.argv[1:])
