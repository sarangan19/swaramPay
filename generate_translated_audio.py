"""
SwaramPay — Generate Translated Audio
=======================================
Reads translated_prompts_review.json (produced by translate_prompts.py,
ideally hand-reviewed) and generates TTS audio via Sarvam AI for each
entry, overwriting the corresponding files in prompt_audio/.

Only touches SERVICE_PROMPTS and STATIC_REGISTRATION_PROMPTS keys (the
prompts written for this build), for every language except English
(English source text is already native script).

Usage:
    python generate_translated_audio.py              # generate all
    python generate_translated_audio.py --lang te    # only Telugu
    python generate_translated_audio.py --dry-run    # show what would happen
"""

import argparse
import json
from pathlib import Path

from services.sarvam_tts import save_tts, LANG_TTS_CONFIG

REVIEW_FILE = Path(__file__).parent / "translated_prompts_review.json"
PROMPT_DIR = Path(__file__).parent / "prompt_audio"


def main():
    parser = argparse.ArgumentParser(description="Generate IVR prompt audio from reviewed translations")
    parser.add_argument("--lang", type=str, default=None, help="Only generate for one language (e.g. --lang te)")
    parser.add_argument("--dry-run", action="store_true", help="List files that would be generated without calling TTS")
    args = parser.parse_args()

    review = json.loads(REVIEW_FILE.read_text(encoding="utf-8"))
    langs = [args.lang] if args.lang else [l for l in LANG_TTS_CONFIG if l != "en"]

    total_ok = 0
    total_fail = 0

    for lang in langs:
        if lang not in review:
            print(f"WARNING: no translations for '{lang}', skipping")
            continue

        print(f"\n=== [{lang}] ===")
        for set_name, prompts in review[lang].items():
            for key, text in prompts.items():
                out_path = PROMPT_DIR / f"{lang}_{key}.wav"
                if args.dry_run:
                    print(f"  WOULD GENERATE: {out_path.name}")
                    continue
                print(f"  Generating: {out_path.name} ...", end=" ", flush=True)
                if save_tts(text, lang, out_path):
                    print("OK")
                    total_ok += 1
                else:
                    print("FAIL")
                    total_fail += 1

    if not args.dry_run:
        print(f"\n{'='*50}")
        print(f"Done: {total_ok} succeeded, {total_fail} failed")
        if total_fail > 0:
            print("Re-run to retry failed files.")


if __name__ == "__main__":
    main()
