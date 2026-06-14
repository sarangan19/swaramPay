"""
SwaramPay — Prompt Translation Pass
====================================
Translates the English IVR prompt text (SERVICE_PROMPTS["en"] and
STATIC_REGISTRATION_PROMPTS["en"] from download_audios.py) into native-script
text for every other configured language, using Sarvam AI's translate API.

Writes results to translated_prompts_review.json for manual review BEFORE
any TTS audio is generated/overwritten. Review and hand-edit that file, then
run generate_translated_audio.py to record the audio.

Usage:
    python translate_prompts.py              # translate all missing entries
    python translate_prompts.py --force      # re-translate everything
    python translate_prompts.py --lang te    # only translate Telugu
"""

import argparse
import json
from pathlib import Path

from download_audios import SERVICE_PROMPTS, STATIC_REGISTRATION_PROMPTS
from services.sarvam_tts import LANG_TTS_CONFIG
from services.sarvam_translate import translate_text

REVIEW_FILE = Path(__file__).parent / "translated_prompts_review.json"

TARGET_LANGS = [lang for lang in LANG_TTS_CONFIG if lang != "en"]


def load_review() -> dict:
    if REVIEW_FILE.exists():
        with open(REVIEW_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_review(data: dict) -> None:
    with open(REVIEW_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def translate_prompt_set(set_name: str, en_prompts: dict, review: dict, lang: str, force: bool) -> tuple[int, int]:
    ok = 0
    fail = 0
    target_code = LANG_TTS_CONFIG[lang]["target_language_code"]
    review.setdefault(lang, {}).setdefault(set_name, {})

    for key, en_text in en_prompts.items():
        existing = review[lang][set_name].get(key)
        if existing and not force:
            print(f"  SKIP (have): [{lang}] {set_name}.{key}")
            ok += 1
            continue

        print(f"  Translating: [{lang}] {set_name}.{key} ...", end=" ", flush=True)
        try:
            translated = translate_text(en_text, target_code)
            review[lang][set_name][key] = translated
            save_review(review)
            print("OK")
            ok += 1
        except Exception as e:
            print(f"FAIL ({e})")
            fail += 1

    return ok, fail


def main():
    parser = argparse.ArgumentParser(description="Translate SwaramPay IVR prompts via Sarvam AI")
    parser.add_argument("--force", action="store_true", help="Re-translate even if already present in review file")
    parser.add_argument("--lang", type=str, default=None, help="Only translate for one language (e.g. --lang te)")
    args = parser.parse_args()

    langs = [args.lang] if args.lang else TARGET_LANGS
    review = load_review()

    total_ok = 0
    total_fail = 0

    for lang in langs:
        if lang not in TARGET_LANGS:
            print(f"WARNING: unknown language '{lang}', skipping")
            continue

        print(f"\n=== [{lang}] Service Prompts ===")
        ok, fail = translate_prompt_set("service_prompts", SERVICE_PROMPTS["en"], review, lang, args.force)
        total_ok += ok
        total_fail += fail

        print(f"\n=== [{lang}] Static Registration Prompts ===")
        ok, fail = translate_prompt_set("static_registration_prompts", STATIC_REGISTRATION_PROMPTS["en"], review, lang, args.force)
        total_ok += ok
        total_fail += fail

    print(f"\n{'='*50}")
    print(f"Done: {total_ok} succeeded, {total_fail} failed")
    print(f"Review file: {REVIEW_FILE}")
    if total_fail > 0:
        print("Re-run to retry failed entries (skips already-translated ones automatically).")


if __name__ == "__main__":
    main()
