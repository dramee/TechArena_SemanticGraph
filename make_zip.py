"""Собрать solution.zip: код решения + submission.json (python make_zip.py)."""
import os
import zipfile

ROOT = os.path.dirname(os.path.abspath(__file__))
FILES = ["your_solution.py", "SOLUTION.md", "submission.json"]

for dp, dns, fns in os.walk(os.path.join(ROOT, "solution")):
    dns[:] = [d for d in dns if d != "__pycache__"]
    for f in fns:
        if not f.endswith(".pyc"):
            FILES.append(os.path.relpath(os.path.join(dp, f), ROOT))

out = os.path.join(ROOT, "solution.zip")
with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
    for f in sorted(FILES):
        z.write(os.path.join(ROOT, f), f.replace(os.sep, "/"))

with zipfile.ZipFile(out) as z:
    for i in z.infolist():
        print(f"{i.file_size:8d}  {i.filename}")
print(os.path.getsize(out), "байт ->", out)
