"""
Sarvam AI TTS client.
API docs: https://docs.sarvam.ai/api-reference/text-to-speech

The API returns base64-encoded WAV audio (PCM, 8000 Hz mono)
suitable for Twilio telephony playback.
"""
import base64
import os
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv()

SARVAM_TTS_URL = "https://api.sarvam.ai/text-to-speech"

# Sarvam AI language codes + speaker per language (bulbul:v3 voices)
LANG_TTS_CONFIG = {
    "hi": {"target_language_code": "hi-IN", "speaker": "anand"},
    "en": {"target_language_code": "en-IN", "speaker": "ritu"},
    "ta": {"target_language_code": "ta-IN", "speaker": "kavitha"},
    "te": {"target_language_code": "te-IN", "speaker": "ritu"},
    "kn": {"target_language_code": "kn-IN", "speaker": "ritu"},
    "ml": {"target_language_code": "ml-IN", "speaker": "ritu"},
    "mr": {"target_language_code": "mr-IN", "speaker": "ritu"},
    "bn": {"target_language_code": "bn-IN", "speaker": "ritu"},
    "gu": {"target_language_code": "gu-IN", "speaker": "ritu"},
}


def generate_tts(text: str, lang_key: str) -> bytes:
    """
    Call Sarvam AI TTS and return raw audio bytes (WAV format).
    Raises requests.HTTPError on API failure.
    """
    api_key = os.getenv("SARVAM_API_KEY", "")
    if not api_key or api_key == "your_sarvam_api_key_here":
        raise RuntimeError("SARVAM_API_KEY not set in .env")

    cfg = LANG_TTS_CONFIG.get(lang_key, LANG_TTS_CONFIG["en"])

    payload = {
        "inputs": [text],
        "target_language_code": cfg["target_language_code"],
        "speaker": cfg["speaker"],
        "pace": 0.95,
        "speech_sample_rate": 8000,
        "enable_preprocessing": True,
        "model": "bulbul:v3",
    }

    headers = {
        "Content-Type": "application/json",
        "api-subscription-key": api_key,
    }

    resp = requests.post(SARVAM_TTS_URL, json=payload, headers=headers, timeout=20)
    if not resp.ok:
        raise RuntimeError(f"HTTP {resp.status_code}: {resp.json()}")

    data = resp.json()
    audio_b64 = data["audios"][0]
    return base64.b64decode(audio_b64)


def save_tts(text: str, lang_key: str, output_path: Path) -> bool:
    """
    Generate TTS audio and save to output_path.
    Returns True on success, False on failure.
    """
    try:
        audio_bytes = generate_tts(text, lang_key)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "wb") as f:
            f.write(audio_bytes)
        return True
    except Exception as e:
        print(f"    TTS ERROR [{lang_key}]: {e}")
        return False
