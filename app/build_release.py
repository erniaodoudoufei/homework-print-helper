from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import sys
import json
import zipfile
from importlib.metadata import distribution
from homework_print import __version__

ROOT = Path(__file__).resolve().parent
WORKSPACE = ROOT.parent.resolve()
BUILD = (ROOT / "build").resolve()
DELIVERY = (WORKSPACE / "交付").resolve()
NAME = "作业图片打印助手"
RELEASE = DELIVERY / NAME
# PyInstaller --noconfirm may replace its output; limit all such paths to workspace.
assert BUILD.is_relative_to(ROOT) and DELIVERY.is_relative_to(WORKSPACE)
assert RELEASE.resolve().is_relative_to(DELIVERY)
BUILD.mkdir(parents=True, exist_ok=True)
DELIVERY.mkdir(parents=True, exist_ok=True)

os.environ["QT_QPA_PLATFORM"] = "offscreen"
from PySide6.QtWidgets import QApplication
from PIL import Image
from main import make_icon

app = QApplication.instance() or QApplication([])
make_icon().pixmap(256, 256).save(str(BUILD / "icon.png"))
Image.open(BUILD / "icon.png").save(BUILD / "icon.ico", sizes=[(16, 16), (32, 32), (48, 48), (128, 128), (256, 256)])

# Exclude unrelated native-tool DLLs from the host's PATH during dependency
# discovery. In particular, Poppler's ICU has incompatible suffixed exports.
build_environment = dict(os.environ)
for name in ["PYTHONPATH", "PYTHONHOME", "QT_PLUGIN_PATH", "QML2_IMPORT_PATH"]:
    build_environment.pop(name, None)
windows = Path(os.environ.get("WINDIR", "C:/Windows"))
build_environment["PATH"] = os.pathsep.join(map(str, [
    Path(sys.executable).parent, Path(sys.base_prefix), Path(sys.base_prefix) / "DLLs",
    windows / "System32", windows,
]))

subprocess.run([sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--onedir", "--windowed",
                "--name", NAME, "--icon", str(BUILD / "icon.ico"),
                "--distpath", str(DELIVERY), "--workpath", str(BUILD / "pyinstaller"),
                "--specpath", str(BUILD), "--add-data", f"{ROOT / 'homework_print' / 'assets'}:homework_print/assets",
                "--exclude-module", "pytest", "--exclude-module", "pypdf",
                "--exclude-module", "tkinter", "--exclude-module", "matplotlib",
                str(ROOT / "main.py")], cwd=ROOT, env=build_environment, check=True)

for name in ("使用说明.txt", "THIRD_PARTY_NOTICES.md"):
    shutil.copy2(ROOT / name, RELEASE / name)
licenses = RELEASE / "licenses"
licenses.mkdir(exist_ok=True)
for name in ["PySide6", "PySide6_Essentials", "PySide6_Addons", "shiboken6", "numpy", "opencv-python-headless", "Pillow", "pyinstaller"]:
    dist = distribution(name)
    for file in dist.files or []:
        lower = str(file).lower()
        if ("license" in lower or "copying" in lower) and not lower.endswith((".xml", ".py", ".pyc", ".pyd")):
            source = Path(dist.locate_file(file))
            if source.is_file():
                target = licenses / name / Path(str(file))
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)
python_license = Path(sys.base_prefix) / "LICENSE.txt"
if python_license.exists():
    shutil.copy2(python_license, licenses / "Python-LICENSE.txt")
if (ROOT / "third_party").exists():
    shutil.copytree(ROOT / "third_party", licenses / "Qt-open-source", dirs_exist_ok=True)

# Exercise the packaged executable with no Python installation or development PATH.
environment = dict(os.environ)
for name in ["PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV", "QT_PLUGIN_PATH", "QML2_IMPORT_PATH"]:
    environment.pop(name, None)
environment["PATH"] = str(Path(os.environ.get("WINDIR", "C:/Windows")) / "System32")
environment["QT_QPA_PLATFORM"] = "offscreen"
qa = ROOT / "qa" / "packaged"
subprocess.run([str(RELEASE / f"{NAME}.exe"), "--smoke-test", str(qa)], cwd=RELEASE,
               env=environment, check=True, timeout=120)
report = json.loads((qa / "smoke-result.json").read_text(encoding="utf-8"))
assert report["status"] == "passed"

archive = DELIVERY / f"{NAME}-{__version__}-Windows便携版.zip"
with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
    for path in RELEASE.rglob("*"):
        if path.is_file():
            z.write(path, path.relative_to(DELIVERY))
print(f"Release complete: {archive}")
print("Packaged smoke test passed; no physical print job submitted.")
