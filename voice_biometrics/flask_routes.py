"""
VaaniPay Voice Biometrics — Flask IVR Routes
=============================================
Drop-in replacement for the mPIN authentication step.
After the user enters their 10-digit phone number, the call is routed
to voice enrollment (first-time users) or voice verification (returning users).

HOW TO INTEGRATE INTO app.py
------------------------------
1. At the top of app.py, add:
       from voice_biometrics.flask_routes import voice_bp, VOICE_STATE
       app.register_blueprint(voice_bp)

2. In your /submit_phone route, replace the mPIN redirect with:
       resp.redirect(url_for("voice.verify_challenge"))
       # or for new users:
       resp.redirect(url_for("voice.enroll_start"))

3. Set these env vars (or add to your config):
       TWILIO_ACCOUNT_SID  — for downloading Twilio recordings
       TWILIO_AUTH_TOKEN   — for downloading Twilio recordings
       SARVAM_API_KEY      — for TTS of challenge phrases
       VOICE_BACKEND       — "resemblyzer" (default) or "speechbrain"

FLOW DIAGRAM
------------
New user:
  /voice/enroll/start
    → plays phrase 1, records
  /voice/enroll/sample (loop ×3)
    → saves embedding for each phrase
  /voice/enroll/complete
    → averages embeddings → stores in users.json → redirect to main menu

Returning user:
  /voice/verify/challenge
    → generates random phrase → TTS → records caller repeating it
  /voice/verify/check
    → downloads recording → STT text match + voice cosine similarity
    → pass → redirect to main menu
    → fail → allow retry (max 2) → hang up on 3rd failure
"""

import os
import json
import time
import logging
import tempfile
import threading
import requests
from functools import lru_cache
from pathlib import Path

from flask import Blueprint, request, url_for, current_app
from twilio.twiml.voice_response import VoiceResponse, Gather

from voice_biometrics.challenge_phrases import get_challenge_phrase, get_enrollment_phrases, SARVAM_LANG_CODE

logger = logging.getLogger(__name__)

voice_bp = Blueprint("voice", __name__, url_prefix="/voice")

# ─── Config ──────────────────────────────────────────────────────────────────

VOICE_BACKEND = os.getenv("VOICE_BACKEND", "resemblyzer")   # "resemblyzer" | "speechbrain"
USERS_JSON    = os.path.join("data", "users.json")
AUDIO_DIR     = "dynamic_audio"
os.makedirs(AUDIO_DIR, exist_ok=True)

SARVAM_API_KEY    = os.getenv("SARVAM_API_KEY", "")
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID", "")
TWILIO_AUTH_TOKEN  = os.getenv("TWILIO_AUTH_TOKEN", "")

# Cosine similarity thresholds (tune after running test_comparison.py)
THRESHOLDS = {
    "resemblyzer": 0.75,
    "speechbrain": 0.25,
}

# Max verification attempts before hanging up
MAX_VERIFY_ATTEMPTS = 3

# ─── Per-call state ───────────────────────────────────────────────────────────
# This merges into the existing CALL_STATE pattern in app.py.
# Keys written by this module:
#   voice_enroll_phrases   — list of phrase dicts being used for enrollment
#   voice_enroll_embeddings — list of embedding lists collected so far
#   voice_verify_phrase    — phrase dict sent to caller for verification
#   voice_verify_attempts  — int, verification attempt count
VOICE_STATE: dict = {}


# ─── Backend loader (lazy, cached per process) ────────────────────────────────

@lru_cache(maxsize=1)
def _get_backend():
    if VOICE_BACKEND == "speechbrain":
        from voice_biometrics.speechbrain_backend import SpeechBrainBackend
        return SpeechBrainBackend()
    else:
        from voice_biometrics.resemblyzer_backend import ResemblyzerBackend
        return ResemblyzerBackend()


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _load_users() -> dict:
    with open(USERS_JSON) as f:
        return json.load(f)

def _save_users(users: dict):
    with open(USERS_JSON, "w") as f:
        json.dump(users, f, indent=2)

def _get_call_state(call_sid: str) -> dict:
    """Returns the caller's CALL_STATE dict (from main app) merged with VOICE_STATE."""
    # Try to grab from the main app's CALL_STATE first
    try:
        from app import CALL_STATE
        state = CALL_STATE.get(call_sid, {})
    except ImportError:
        state = {}
    state.update(VOICE_STATE.get(call_sid, {}))
    return state

def _set_voice_state(call_sid: str, **kwargs):
    if call_sid not in VOICE_STATE:
        VOICE_STATE[call_sid] = {}
    VOICE_STATE[call_sid].update(kwargs)

def _download_twilio_recording(recording_url: str, dest_path: str) -> bool:
    """Download a Twilio recording WAV to dest_path using Basic Auth."""
    try:
        # Twilio recording URLs serve MP3 by default; append .wav for WAV
        wav_url = recording_url if recording_url.endswith(".wav") else recording_url + ".wav"
        r = requests.get(wav_url, auth=(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN), timeout=15)
        r.raise_for_status()
        with open(dest_path, "wb") as f:
            f.write(r.content)
        return True
    except Exception as e:
        logger.error(f"Failed to download recording {recording_url}: {e}")
        return False

def _generate_tts(text: str, lang: str, filename: str) -> str:
    """
    Generate a WAV file via Sarvam TTS.
    Returns the path to the generated file.
    Uses the same pattern as the existing app.
    """
    path = os.path.join(AUDIO_DIR, filename)
    if os.path.exists(path):
        return path

    sarvam_lang = SARVAM_LANG_CODE.get(lang, "hi-IN")
    try:
        r = requests.post(
            "https://api.sarvam.ai/text-to-speech",
            headers={
                "api-subscription-key": SARVAM_API_KEY,
                "Content-Type": "application/json",
            },
            json={
                "inputs": [text],
                "target_language_code": sarvam_lang,
                "speaker": "meera",
                "model": "bulbul:v1",
            },
            timeout=10,
        )
        r.raise_for_status()
        data = r.json()
        import base64
        audio_b64 = data["audios"][0]
        with open(path, "wb") as f:
            f.write(base64.b64decode(audio_b64))
        return path
    except Exception as e:
        logger.error(f"Sarvam TTS failed: {e}")
        return None

def _transcribe_audio(audio_path: str, lang: str) -> str:
    """
    Transcribe audio via Sarvam STT (saarika:v2.5).
    Returns the transcript string, or "" on failure.
    """
    sarvam_lang = SARVAM_LANG_CODE.get(lang, "hi-IN")
    try:
        with open(audio_path, "rb") as f:
            r = requests.post(
                "https://api.sarvam.ai/speech-to-text",
                headers={"api-subscription-key": SARVAM_API_KEY},
                files={"file": (os.path.basename(audio_path), f, "audio/wav")},
                data={"model": "saarika:v2.5", "language_code": sarvam_lang},
                timeout=20,
            )
        r.raise_for_status()
        return r.json().get("transcript", "").strip().lower()
    except Exception as e:
        logger.error(f"Sarvam STT failed: {e}")
        return ""

def _text_matches(spoken: str, expected: str, threshold: float = 0.5) -> bool:
    """
    Check if the spoken transcript roughly matches the expected phrase.
    Uses character-level overlap ratio rather than exact match,
    since STT transcripts may have minor differences.
    """
    spoken = spoken.lower().strip()
    expected = expected.lower().strip()

    # Exact match
    if spoken == expected:
        return True

    # Word-level overlap (Jaccard similarity)
    spoken_words = set(spoken.split())
    expected_words = set(expected.split())
    if not expected_words:
        return False

    overlap = spoken_words & expected_words
    jaccard = len(overlap) / len(expected_words)
    return jaccard >= threshold

def _audio_url(filename: str) -> str:
    """Return the public URL for a dynamic audio file."""
    return url_for("serve_dynamic_audio", filename=filename, _external=True)


# ─── Enrollment Routes ────────────────────────────────────────────────────────

@voice_bp.route("/enroll/start", methods=["POST"])
def enroll_start():
    """
    Entry point for new user voice enrollment.
    Picks 3 challenge phrases and starts recording the first one.
    """
    call_sid = request.form.get("CallSid")
    state = _get_call_state(call_sid)
    lang = state.get("language", "hi")

    # Pick 3 distinct phrases for enrollment
    phrases = get_enrollment_phrases(lang, count=3)
    _set_voice_state(call_sid,
        voice_enroll_phrases=phrases,
        voice_enroll_embeddings=[],
    )

    resp = VoiceResponse()

    # Intro message
    intro_texts = {
        "hi": "Aapki awaaz pahchaan ke liye register karna hoga. Main aapko teen waakyaansh bolunga. Unhe dohraaiye.",
        "en": "To register your voice, I will say three phrases. Please repeat each one clearly.",
    }
    intro = intro_texts.get(lang, intro_texts["hi"])

    # Generate TTS for intro
    intro_path = _generate_tts(intro, lang, f"voice_enroll_intro_{lang}.wav")
    if intro_path:
        resp.play(url_for("serve_dynamic_audio", filename=os.path.basename(intro_path), _external=True))

    # Play phrase 1 and record
    phrase = phrases[0]
    phrase_path = _generate_tts(phrase["display"], lang, f"voice_enroll_phrase_0_{lang}.wav")
    if phrase_path:
        resp.play(url_for("serve_dynamic_audio", filename=os.path.basename(phrase_path), _external=True))

    resp.record(
        action=url_for("voice.enroll_sample", n=0, _external=True),
        method="POST",
        max_length=8,
        finish_on_key="#",
        play_beep=True,
    )
    return str(resp)


@voice_bp.route("/enroll/sample/<int:n>", methods=["POST"])
def enroll_sample(n: int):
    """
    Receives recording n (0-indexed), extracts embedding, moves to next phrase.
    After phrase 2 (n=2), calls enroll_complete.
    """
    call_sid = request.form.get("CallSid")
    recording_url = request.form.get("RecordingUrl", "")
    state = _get_call_state(call_sid)
    lang = state.get("language", "hi")
    phrases = VOICE_STATE.get(call_sid, {}).get("voice_enroll_phrases", [])
    embeddings = VOICE_STATE.get(call_sid, {}).get("voice_enroll_embeddings", [])

    resp = VoiceResponse()

    # Download the recording
    audio_path = os.path.join(AUDIO_DIR, f"enroll_{call_sid}_{n}.wav")
    if recording_url and _download_twilio_recording(recording_url, audio_path):
        try:
            backend = _get_backend()
            emb = backend.get_embedding(audio_path)
            embeddings.append(emb)
            _set_voice_state(call_sid, voice_enroll_embeddings=embeddings)
        except Exception as e:
            logger.error(f"Embedding extraction failed on sample {n}: {e}")

    next_n = n + 1

    if next_n >= 3 or next_n >= len(phrases):
        # All samples collected — finalise
        resp.redirect(url_for("voice.enroll_complete", _external=True), method="POST")
        return str(resp)

    # Play next phrase and record
    phrase = phrases[next_n]
    phrase_path = _generate_tts(phrase["display"], lang, f"voice_enroll_phrase_{next_n}_{lang}.wav")
    if phrase_path:
        resp.play(url_for("serve_dynamic_audio", filename=os.path.basename(phrase_path), _external=True))

    resp.record(
        action=url_for("voice.enroll_sample", n=next_n, _external=True),
        method="POST",
        max_length=8,
        finish_on_key="#",
        play_beep=True,
    )
    return str(resp)


@voice_bp.route("/enroll/complete", methods=["POST"])
def enroll_complete():
    """
    Average all collected embeddings, store in users.json, proceed to main menu.
    """
    call_sid = request.form.get("CallSid")
    state = _get_call_state(call_sid)
    lang = state.get("language", "hi")
    phone = state.get("phone_number", "")
    embeddings = VOICE_STATE.get(call_sid, {}).get("voice_enroll_embeddings", [])

    resp = VoiceResponse()

    if embeddings:
        import numpy as np
        voice_model = np.mean(embeddings, axis=0).tolist()

        # Store in users.json
        users = _load_users()
        if phone in users:
            users[phone]["voice_embedding"] = voice_model
            users[phone]["voice_enrolled"] = True
            users[phone]["voice_backend"] = VOICE_BACKEND
            _save_users(users)

        success_texts = {
            "hi": "Aapki awaaz register ho gayi. Aage se call karne par sirf ek waakyaansh dohraaiye.",
            "en": "Your voice has been registered. From now on, just repeat one phrase to log in.",
        }
        msg = success_texts.get(lang, success_texts["hi"])
        success_path = _generate_tts(msg, lang, f"voice_enroll_success_{lang}.wav")
        if success_path:
            resp.play(url_for("serve_dynamic_audio", filename=os.path.basename(success_path), _external=True))
    else:
        # Enrollment failed — fall back to mPIN
        logger.warning(f"Enrollment failed for {phone} — no embeddings collected")
        resp.redirect(url_for("get_mpin", _external=True), method="POST")
        return str(resp)

    # Redirect to main menu (adjust route name to match your app.py)
    resp.redirect(url_for("main_menu", _external=True), method="POST")
    return str(resp)


# ─── Verification Routes ──────────────────────────────────────────────────────

@voice_bp.route("/verify/challenge", methods=["POST"])
def verify_challenge():
    """
    Generate a random challenge phrase, play it via TTS, record the caller repeating it.
    This replaces the mPIN step for users who have enrolled.
    """
    call_sid = request.form.get("CallSid")
    state = _get_call_state(call_sid)
    lang = state.get("language", "hi")
    phone = state.get("phone_number", "")

    # Check if user is enrolled; fall back to mPIN if not
    users = _load_users()
    user = users.get(phone, {})
    if not user.get("voice_enrolled"):
        resp = VoiceResponse()
        resp.redirect(url_for("enroll_start", _external=True), method="POST")
        return str(resp)

    # Pick a random challenge phrase (not one recently used, if we track that)
    phrase = get_challenge_phrase(lang)
    _set_voice_state(call_sid,
        voice_verify_phrase=phrase,
        voice_verify_attempts=VOICE_STATE.get(call_sid, {}).get("voice_verify_attempts", 0),
    )

    resp = VoiceResponse()

    # Prompt
    prompt_texts = {
        "hi": "Awaaz pahchaan ke liye, yeh waakyaansh dohraaiye:",
        "en": "To verify your voice, please repeat this phrase:",
    }
    prompt = prompt_texts.get(lang, prompt_texts["hi"])
    prompt_path = _generate_tts(prompt, lang, f"voice_verify_prompt_{lang}.wav")
    if prompt_path:
        resp.play(url_for("serve_dynamic_audio", filename=os.path.basename(prompt_path), _external=True))

    # Play the challenge phrase
    phrase_path = _generate_tts(
        phrase["display"], lang,
        f"voice_challenge_{phrase['text'][:20].replace(' ', '_')}_{lang}.wav"
    )
    if phrase_path:
        resp.play(url_for("serve_dynamic_audio", filename=os.path.basename(phrase_path), _external=True))

    # Record the caller's response
    resp.record(
        action=url_for("voice.verify_check", _external=True),
        method="POST",
        max_length=10,
        finish_on_key="#",
        play_beep=True,
    )
    return str(resp)


@voice_bp.route("/verify/check", methods=["POST"])
def verify_check():
    """
    Downloads the recording, runs:
      1. Sarvam STT → text match against challenge phrase
      2. Voice embedding → cosine similarity against stored model
    Both must pass to authenticate.
    """
    call_sid = request.form.get("CallSid")
    recording_url = request.form.get("RecordingUrl", "")
    state = _get_call_state(call_sid)
    lang = state.get("language", "hi")
    phone = state.get("phone_number", "")

    voice_state = VOICE_STATE.get(call_sid, {})
    phrase = voice_state.get("voice_verify_phrase", {})
    attempts = voice_state.get("voice_verify_attempts", 0) + 1
    _set_voice_state(call_sid, voice_verify_attempts=attempts)

    resp = VoiceResponse()

    # --- Download recording ---
    audio_path = os.path.join(AUDIO_DIR, f"verify_{call_sid}_{attempts}.wav")
    download_ok = _download_twilio_recording(recording_url, audio_path)

    text_ok = False
    voice_ok = False
    voice_score = 0.0

    if download_ok:
        # --- Check 1: Text match (did they say the right words?) ---
        transcript = _transcribe_audio(audio_path, lang)
        expected = phrase.get("text", "")
        text_ok = _text_matches(transcript, expected)
        logger.info(f"[{call_sid}] STT: '{transcript}' | expected: '{expected}' | match={text_ok}")

        # --- Check 2: Voice similarity (is this their voice?) ---
        users = _load_users()
        stored_embedding = users.get(phone, {}).get("voice_embedding")
        if stored_embedding:
            try:
                backend = _get_backend()
                threshold = THRESHOLDS.get(VOICE_BACKEND, 0.75)
                voice_ok, voice_score = backend.verify(stored_embedding, audio_path, threshold)
                logger.info(f"[{call_sid}] Voice score={voice_score:.4f} threshold={threshold} ok={voice_ok}")
            except Exception as e:
                logger.error(f"Voice verification error: {e}")
                # Fail safe: don't authenticate if verification errors
                voice_ok = False

    authenticated = text_ok and voice_ok

    if authenticated:
        # ✅ Authenticated
        success_texts = {
            "hi": "Awaaz sahi pehchaan li. Aapka swagat hai.",
            "en": "Voice verified. Welcome.",
        }
        msg = success_texts.get(lang, success_texts["hi"])
        path = _generate_tts(msg, lang, f"voice_verified_{lang}.wav")
        if path:
            resp.play(url_for("serve_dynamic_audio", filename=os.path.basename(path), _external=True))
        resp.redirect(url_for("main_menu", _external=True), method="POST")

    elif attempts >= MAX_VERIFY_ATTEMPTS:
        # ❌ Too many failed attempts — hang up
        fail_texts = {
            "hi": "Teen baar galat awaaz. Call band ho raha hai.",
            "en": "Three failed attempts. Disconnecting.",
        }
        msg = fail_texts.get(lang, fail_texts["hi"])
        path = _generate_tts(msg, lang, f"voice_failed_{lang}.wav")
        if path:
            resp.play(url_for("serve_dynamic_audio", filename=os.path.basename(path), _external=True))
        resp.hangup()

    else:
        # ❌ Failed but retries remain — tell them what went wrong
        remaining = MAX_VERIFY_ATTEMPTS - attempts
        if not text_ok:
            retry_texts = {
                "hi": f"Waakyaansh sahi nahi tha. {remaining} mauka baaqi hai. Phir koshish karein.",
                "en": f"Phrase did not match. {remaining} attempt(s) remaining. Please try again.",
            }
        else:
            retry_texts = {
                "hi": f"Awaaz match nahi hui. {remaining} mauka baaqi hai. Phir koshish karein.",
                "en": f"Voice did not match. {remaining} attempt(s) remaining. Please try again.",
            }
        msg = retry_texts.get(lang, retry_texts["hi"])
        path = _generate_tts(msg, lang, f"voice_retry_{lang}_{attempts}.wav")
        if path:
            resp.play(url_for("serve_dynamic_audio", filename=os.path.basename(path), _external=True))
        resp.redirect(url_for("voice.verify_challenge", _external=True), method="POST")

    return str(resp)
