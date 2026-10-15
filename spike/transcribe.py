"""THROWAWAY spike: test local Whisper on a real talk clip (Apple Silicon Mac).

Answers two questions:
  1. Is the transcript good enough for Cantonese / Mandarin / English / mixed talks?
  2. Is it fast enough? (real-time factor < 1.0 means faster than the talk itself)

Usage:
  python transcribe.py clip.m4a
  python transcribe.py clip.m4a --language yue
  python transcribe.py clip.m4a --models turbo large --language auto
"""
import argparse
import time
from pathlib import Path

import mlx_whisper

MODELS = {
    "turbo": "mlx-community/whisper-large-v3-turbo",
    "large": "mlx-community/whisper-large-v3-mlx",
}

# Nudges the output script. Whisper has no "Traditional Chinese" switch,
# so a prompt written in the wanted style is the usual trick.
PROMPTS = {
    "yue": "以下係廣東話內容，可能夾雜English。請用繁體中文。",
    "zh": "以下是普通話內容，可能夾雜English。請使用繁體中文。",
    "en": "",
    "auto": "以下內容可能係廣東話、普通話或English，請用繁體中文。",
}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("audio", help="audio file (m4a, mp3, wav, ...)")
    ap.add_argument("--models", nargs="+", default=["turbo", "large"], choices=MODELS)
    ap.add_argument("--language", default="auto", choices=PROMPTS)
    ap.add_argument("--out", default="out")
    args = ap.parse_args()

    out_dir = Path(args.out)
    out_dir.mkdir(exist_ok=True)
    audio = Path(args.audio)
    lang = None if args.language == "auto" else args.language

    for name in args.models:
        print(f"\n=== model={name} language={args.language} ===")
        start = time.time()
        result = mlx_whisper.transcribe(
            str(audio),
            path_or_hf_repo=MODELS[name],
            language=lang,
            initial_prompt=PROMPTS[args.language] or None,
            verbose=False,
        )
        elapsed = time.time() - start

        segments = result.get("segments", [])
        duration = segments[-1]["end"] if segments else 0.0
        rtf = elapsed / duration if duration else float("nan")

        lines = [
            f"[{int(s['start'] // 60):02d}:{int(s['start'] % 60):02d}] {s['text'].strip()}"
            for s in segments
        ]
        out_file = out_dir / f"{audio.stem}.{name}.{args.language}.txt"
        out_file.write_text("\n".join(lines), encoding="utf-8")

        print(f"detected language : {result.get('language')}")
        print(f"audio length      : {duration / 60:.1f} min")
        print(f"time taken        : {elapsed / 60:.1f} min")
        print(f"real-time factor  : {rtf:.2f}  (below 1.0 = faster than the talk)")
        print(f"saved             : {out_file}")
        print("--- first lines ---")
        print("\n".join(lines[:8]))

    print(
        "\nNote: the first run of each model includes the model download. "
        "Run again to get the true speed."
    )


if __name__ == "__main__":
    main()
