"""Smoke test for the duplex back-side prompt.

Runs `build_back_prompt` against a handful of pre-rendered back-side PNGs and
prints the raw model response. Intended for prompt iteration, not for the
production pipeline.

Usage:
    python scripts/back_prompt_smoke.py [--ollama URL] [--model NAME]
"""
import argparse
import base64
import json
import sys
from pathlib import Path

import requests

# Project root on sys.path so we can import rag_prompt without installing.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from rag_prompt import build_back_prompt  # noqa: E402


# A SmokeSample is a tuple (label, image_path, front_context_dict).
# label   : short tag for log output ("table" | "narrative" | "blank")
# image   : path to a rendered back-side PNG
# context : minimal front-context dict — botanical_name, family,
#           accession_number, propagation_tail. None of these need to be
#           accurate for the smoke test; they exist to exercise the
#           prompt's front-context block.
SAMPLES = [
    (
        "table",
        "/tmp/duplex_peek/sample_amso_back1-11.png",
        {
            "botanical_name": "Amsonia tabernaemontana",
            "family": "Apocynaceae",
            "accession_number": "31436-167-93",
            "propagation_tail": "Feb 1-95 sown PSH; Mar 28-95 germ 11",
        },
    ),
    (
        "narrative",
        "/tmp/duplex_peek/sample_celm_back4-14.png",
        {
            "botanical_name": "Cestrum nocturnum",
            "family": "Solanaceae",
            "accession_number": "37060-657-2004",
            "propagation_tail": "Feb 1-01 sown 35; PSH",
        },
    ),
    (
        "blank",
        "/tmp/duplex_peek/back2-12.png",
        {
            "botanical_name": "Abies lasiocarpa",
            "family": "Pinaceae",
            "accession_number": "32865-167-94",
            "propagation_tail": "May 4-97 DEAD",
        },
    ),
]


def run_one(ollama_url: str, model: str, image_path: str, front_ctx: dict) -> str:
    with open(image_path, "rb") as f:
        img_b64 = base64.b64encode(f.read()).decode()
    prompt = build_back_prompt(front_ctx)
    # Match the production pipeline: /api/chat is required for vision models in
    # Ollama >=0.23.4 (rag_worker.call_ollama_with_prompt uses the same shape).
    r = requests.post(
        f"{ollama_url.rstrip('/')}/api/chat",
        json={
            "model": model,
            "messages": [
                {"role": "user", "content": prompt, "images": [img_b64]}
            ],
            "stream": False,
            "options": {"num_predict": 1024, "temperature": 0.1},
        },
        timeout=300,
    )
    r.raise_for_status()
    return r.json().get("message", {}).get("content", "").strip()


def main() -> int:
    ap = argparse.ArgumentParser()
    # Base URL only (no path). Defaults to TUF + 3B for a quick free gate;
    # on the Mac run with: --ollama http://localhost:11434 --model qwen2.5vl:7b
    ap.add_argument("--ollama", default="http://192.168.1.120:11434")
    ap.add_argument("--model", default="qwen2.5vl:3b")
    args = ap.parse_args()

    for label, path, ctx in SAMPLES:
        if not Path(path).exists():
            print(f"\n=== {label.upper()}: {path} ===\n[MISSING — re-render sample]")
            continue
        print(f"\n=== {label.upper()}: {Path(path).name} ===")
        try:
            out = run_one(args.ollama, args.model, path, ctx)
        except Exception as e:
            print(f"[ERROR] {type(e).__name__}: {e}")
            continue
        print(out[:2000])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
