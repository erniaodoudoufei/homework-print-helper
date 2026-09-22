"""Local sample checks. Does not modify or print the source images."""
from pathlib import Path
from hashlib import sha256
import json
import time

from PIL import Image
from homework_print.processing import load_rgb, process, suggest_settings

destination = Path(__file__).parent / "qa"
destination.mkdir(exist_ok=True)
results = []
for source in Path(__file__).parent.parent.glob("*.jpg"):
    before = sha256(source.read_bytes()).hexdigest()
    start = time.perf_counter()
    rgb = load_rgb(source)
    settings, note = suggest_settings(rgb)
    result = process(rgb, settings)
    Image.fromarray(result).save(destination / f"{source.stem}_auto.png")
    from homework_print.processing import resize_preview
    Image.fromarray(resize_preview(result, 1500)).save(destination / f"{source.stem}_preview.png")
    results.append({"file": source.name, "quad": settings.quad, "angle": settings.deskew,
                    "note": note, "seconds": round(time.perf_counter() - start, 2),
                    "sha256": before, "original_unchanged": sha256(source.read_bytes()).hexdigest() == before})
(destination / "sample-checks.json").write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps(results, ensure_ascii=False, indent=2))
