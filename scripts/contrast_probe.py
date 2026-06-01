"""Probe: does contrast enhancement help the 3B read faint pencil backs?

For each problem image, OCR the raw render and a contrast-enhanced version,
using a repetition penalty to suppress the degenerate '0000...' spiral seen
on faint cards. Saves enhanced PNGs so they can be eyeballed too.

Usage:
    python3 scripts/contrast_probe.py [--ollama URL] [--model NAME]
"""
import argparse
import base64
import sys
from pathlib import Path

import requests
from PIL import Image, ImageOps, ImageEnhance

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
from rag_prompt import build_back_prompt  # noqa: E402

OUT = Path("/tmp/duplex_smoke")
OUT.mkdir(parents=True, exist_ok=True)

# Two faint-pencil failures from the last smoke run.
IMAGES = [
    ("amso_table", "/tmp/duplex_peek/sample_amso_back1-11.png"),
    ("back2-12", "/tmp/duplex_peek/back2-12.png"),
]


def enhance(path: str, out_path: Path) -> Path:
    """Grayscale -> autocontrast -> strong contrast boost. Pencil-friendly."""
    img = Image.open(path).convert("L")
    img = ImageOps.autocontrast(img, cutoff=1)
    img = ImageEnhance.Contrast(img).enhance(2.2)
    img = ImageEnhance.Sharpness(img).enhance(1.5)
    img.save(out_path)
    return out_path


def ocr(ollama_url: str, model: str, image_path: str) -> str:
    with open(image_path, "rb") as f:
        img_b64 = base64.b64encode(f.read()).decode()
    r = requests.post(
        ollama_url,
        json={
            "model": model,
            "prompt": build_back_prompt(None),  # no front context for the probe
            "images": [img_b64],
            "stream": False,
            # repeat_penalty/last_n tame the degenerate '0000...' spiral;
            # tighter num_predict caps the damage if it still happens.
            "options": {
                "num_predict": 768,
                "temperature": 0.1,
                "repeat_penalty": 1.3,
                "repeat_last_n": 64,
            },
        },
        timeout=300,
    )
    r.raise_for_status()
    return r.json().get("response", "").strip()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ollama", default="http://192.168.1.120:11434/api/generate")
    ap.add_argument("--model", default="qwen2.5vl:3b")
    args = ap.parse_args()

    for label, path in IMAGES:
        if not Path(path).exists():
            print(f"\n##### {label}: MISSING {path}")
            continue
        enh = enhance(path, OUT / f"enh_{label}.png")
        for variant, p in (("RAW", path), ("ENHANCED", str(enh))):
            print(f"\n##### {label} / {variant} ({Path(p).name}) #####")
            try:
                print(ocr(args.ollama, args.model, p)[:1500])
            except Exception as e:
                print(f"[ERROR] {type(e).__name__}: {e}")
    print(f"\nEnhanced PNGs saved under {OUT}/ for eyeballing.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
