"""
AI Financial Mentor Service
- Sarvam AI for STT (Speech-to-Text)  
- Groq LLM (llama3-8b-8192) for financial advice
- Sarvam AI for TTS (Text-to-Speech)
"""
import os
import time
import requests
from pathlib import Path
from groq import Groq
from services.sarvam_tts import save_tts
from dotenv import load_dotenv

load_dotenv()

SARVAM_STT_URL = "https://api.sarvam.ai/speech-to-text"

# Map our internal lang keys to Sarvam language codes
LANG_STT_CONFIG = {
    "en": "en-IN",
    "hi": "hi-IN",
    "ta": "ta-IN",
    "te": "te-IN",
    "kn": "kn-IN",
    "ml": "ml-IN",
    "mr": "mr-IN",
    "bn": "bn-IN",
    "gu": "gu-IN",
}

LANG_NAMES = {
    "en": "English",
    "hi": "Hindi",
    "ta": "Tamil",
    "te": "Telugu",
    "kn": "Kannada",
    "ml": "Malayalam",
    "mr": "Marathi",
    "bn": "Bengali",
    "gu": "Gujarati",
}

# Groq client
groq_client = Groq(api_key=os.getenv("GROQ_API_KEY"))


def speech_to_text(audio_file_path: str, lang_key: str) -> str:
    """
    Send audio file to Sarvam STT API and return transcribed text.
    Returns empty string on failure.
    """
    api_key = os.getenv("SARVAM_API_KEY", "")
    language_code = LANG_STT_CONFIG.get(lang_key, "hi-IN")

    try:
        with open(audio_file_path, "rb") as audio_file:
            response = requests.post(
                SARVAM_STT_URL,
                headers={"api-subscription-key": api_key},
                data={"language_code": language_code, "model": "saaras:v3"},
                files={"file": ("audio.wav", audio_file, "audio/wav")},
                timeout=15,
            )

        if response.ok:
            data = response.json()
            transcript = data.get("transcript", "").strip()
            print(f"   [STT] Transcribed ({lang_key}): '{transcript}'")
            return transcript
        else:
            print(f"   [STT ERROR] {response.status_code}: {response.text[:200]}")
            return ""

    except Exception as e:
        print(f"   [STT EXCEPTION] {e}")
        return ""


def generate_financial_response(user_text: str, lang_key: str, user_context: dict) -> str:
    """
    Call Groq LLM with user's financial question and context.
    Returns the AI response string.
    """
    lang_name = LANG_NAMES.get(lang_key, "English")
    balance = user_context.get("balance", "unknown")
    credit_score = user_context.get("credit_score", "unknown")

    system_prompt = f"""You are VaaniPay, a helpful and friendly financial advisor for rural Indian users.
- ALWAYS respond ONLY in {lang_name}. Do NOT mix languages.
- Keep responses SHORT: 2-3 simple sentences maximum.
- Use simple, everyday words. No financial jargon.
- Give practical, actionable advice.
- Relate to Indian financial context (UPI, Jan Dhan, PMJBY, SIP, etc.).
- User's current balance: Rs {balance}
- User's credit score: {credit_score}/900
- Be encouraging, warm, and empathetic — you are helping someone who may be new to finance."""

    try:
        response = groq_client.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_text},
            ],
            temperature=0.7,
            max_tokens=200,
        )
        answer = response.choices[0].message.content.strip()
        print(f"   [LLM] Response: {answer[:100]}...")
        return answer

    except Exception as e:
        print(f"   [LLM EXCEPTION] {e}")
        fallback = {
            "en": "I'm sorry, I could not process that. Please try again.",
            "hi": "Maafi chahta hoon, mujhe samajh nahi aaya. Kripya phir se bolein.",
            "ta": "Mannikavum, puriyavillai. Meedum sollungal.",
            "te": "Nenu artham chesukoledu. Malli cheppandi.",
            "kn": "Kshamissi, artha aagalilla. Dayavittu matte heli.",
            "ml": "Manasilaayilla, onnu koodi parayan.",
            "mr": "Maaf kara, samajale nahi. Parat sanga.",
            "bn": "Dukkhit, bujhte parini. Abar bolun.",
            "gu": "Maafi manghu chu, samajhyu nahi. Pharthi bolo.",
        }
        return fallback.get(lang_key, fallback["en"])


def download_twilio_recording(recording_url: str, output_path: str) -> bool:
    """
    Download a Twilio recording using Twilio credentials.
    Twilio recordings need Basic Auth.
    """
    account_sid = os.getenv("TWILIO_ACCOUNT_SID")
    auth_token = os.getenv("TWILIO_AUTH_TOKEN")

    try:
        # Twilio recording URL needs .wav appended
        wav_url = recording_url + ".wav" if not recording_url.endswith(".wav") else recording_url
        
        # Wait briefly for recording to be ready on Twilio's servers
        time.sleep(0.5)
        
        resp = requests.get(wav_url, auth=(account_sid, auth_token), timeout=15)
        if resp.ok:
            Path(output_path).parent.mkdir(parents=True, exist_ok=True)
            with open(output_path, "wb") as f:
                f.write(resp.content)
            print(f"   [RECORDING] Downloaded to {output_path} ({len(resp.content)} bytes)")
            return True
        else:
            print(f"   [RECORDING ERROR] {resp.status_code}: {resp.text[:100]}")
            return False

    except Exception as e:
        print(f"   [RECORDING EXCEPTION] {e}")
        return False


def process_mentor_audio(recording_url: str, call_sid: str, user_session: dict) -> str | None:
    """
    Full pipeline: Download → STT → LLM → TTS → return audio filename.
    Returns the dynamic audio filename (relative to prompt_audio/) or None on error.
    """
    lang = user_session.get("lang", "en")
    
    # 1. Download the recording
    audio_path = f"dynamic_audio/recording_{call_sid}.wav"
    if not download_twilio_recording(recording_url, audio_path):
        return None

    # 2. Speech to Text
    text = speech_to_text(audio_path, lang)
    if not text:
        return None

    # 3. Get financial context
    user_context = {
        "balance": user_session.get("balance", "unknown"),
        "credit_score": user_session.get("credit_score", "unknown"),
        "phone": user_session.get("phone", "unknown"),
    }

    # 4. Generate LLM response
    response_text = generate_financial_response(text, lang, user_context)

    # 5. Convert to speech
    audio_filename = f"mentor_response_{call_sid}_{int(time.time())}.wav"
    audio_out_path = Path("dynamic_audio") / audio_filename

    try:
        if save_tts(response_text, lang, audio_out_path):
            print(f"   [MENTOR] Audio saved: {audio_filename}")
            return audio_filename
        return None
    except Exception as e:
        print(f"   [TTS EXCEPTION] {e}")
        return None
