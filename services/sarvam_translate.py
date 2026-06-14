"""
Sarvam AI text-to-text translation client.
API docs: https://docs.sarvam.ai/api-reference/translate

Used to turn the hand-written English IVR prompt text into proper
native-script translations before handing them to sarvam_tts, instead
of TTS-ing hand-rolled Romanized transliterations.
"""
import os
import time

import requests
from dotenv import load_dotenv

load_dotenv(override=True)

SARVAM_TRANSLATE_URL = "https://api.sarvam.ai/translate"


def translate_text(text: str, target_language_code: str, source_language_code: str = "en-IN") -> str:
    """
    Translate text via Sarvam AI. Returns the translated text.
    Raises RuntimeError on API failure.
    """
    api_key = os.getenv("SARVAM_API_KEY", "")
    if not api_key or api_key == "your_sarvam_api_key_here":
        raise RuntimeError("SARVAM_API_KEY not set in .env")

    payload = {
        "input": text,
        "source_language_code": source_language_code,
        "target_language_code": target_language_code,
        "mode": "formal",
        "model": "sarvam-translate:v1",
    }

    headers = {
        "Content-Type": "application/json",
        "api-subscription-key": api_key,
    }

    t0 = time.perf_counter()
    try:
        resp = requests.post(SARVAM_TRANSLATE_URL, json=payload, headers=headers, timeout=30)
        if not resp.ok:
            raise RuntimeError(f"HTTP {resp.status_code}: {resp.text}")
        data = resp.json()
        return data["translated_text"]
    finally:
        print(f"   [TIMING] translate_text({target_language_code}) took {time.perf_counter() - t0:.2f}s")
