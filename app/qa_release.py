"""Validate the distributed ZIP after extracting to a separate Chinese/spaced path."""
from pathlib import Path
import hashlib
import json
import os
import subprocess
import zipfile
from homework_print import __version__

ROOT = Path(__file__).resolve().parent
WORKSPACE = ROOT.parent
archive = WORKSPACE / "交付" / f"作业图片打印助手-{__version__}-Windows便携版.zip"
destination = ROOT / "qa" / f"解压独立运行 portable {__version__}"
destination.mkdir(parents=True, exist_ok=True)
with zipfile.ZipFile(archive) as package:
    for info in package.infolist():
        assert (destination / info.filename).resolve().is_relative_to(destination.resolve())
    package.extractall(destination)
executable = destination / "作业图片打印助手" / "作业图片打印助手.exe"
environment = dict(os.environ)
for key in ["PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV", "QT_PLUGIN_PATH", "QML2_IMPORT_PATH"]:
    environment.pop(key, None)
environment["PATH"] = str(Path(environment.get("WINDIR", "C:/Windows")) / "System32")
environment["QT_QPA_PLATFORM"] = "offscreen"
report_directory = destination / "验证结果"
subprocess.run([str(executable), "--smoke-test", str(report_directory)], cwd=destination,
               env=environment, check=True, timeout=120)
report = json.loads((report_directory / "smoke-result.json").read_text(encoding="utf-8"))
assert report["status"] == "passed"
# Also load the real Windows platform plugin and fonts. Only our own test
# windows are opened; the smoke entry point never submits a print job.
environment["QT_QPA_PLATFORM"] = "windows"
native_directory = destination / "Windows界面验证"
subprocess.run([str(executable), "--smoke-test", str(native_directory)], cwd=destination,
               env=environment, check=True, timeout=120,
               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
native = json.loads((native_directory / "smoke-result.json").read_text(encoding="utf-8"))
assert native["status"] == "passed"
# Local real-photo checks are optional; a fresh public checkout has no private
# school photos and can still validate the portable app with synthetic fixtures.
reference_path = ROOT / "qa" / "real" / "report.json"
hashes = {}
originals_unchanged = None
if reference_path.exists():
    reference = json.loads(reference_path.read_text(encoding="utf-8"))
    hashes = {name: hashlib.sha256((WORKSPACE / name).read_bytes()).hexdigest()
              for name in reference["source_sha256"]}
    assert hashes == reference["source_sha256"]
    originals_unchanged = True
report.update(archive_sha256=hashlib.sha256(archive.read_bytes()).hexdigest(),
              archive_bytes=archive.stat().st_size, originals_unchanged=originals_unchanged,
              source_sha256=hashes, development_path_removed=True, windows_platform_test=native["status"],
              relocation_directory=str(destination))
(ROOT / "qa" / "release-verification.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps({key: value for key, value in report.items() if key != "source_sha256"}, ensure_ascii=False, indent=2))
