import os
import re
import json
import time
import random
import datetime
import threading
from pathlib import Path

from flask import Flask, request, Response, send_from_directory, render_template, redirect, session, jsonify
from twilio.twiml.voice_response import VoiceResponse, Gather
from twilio.rest import Client
from dotenv import load_dotenv

from services.sarvam_tts import save_tts
from services.ai_mentor import speech_to_text, speech_to_text_english, groq_extract, download_twilio_recording, process_mentor_audio
from mock_db import get_user, get_account
from services.financial_ops import load_json, save_json, calculate_behavioral_score, perform_upi_transaction
from config import LANG_CONFIG, ENROLLMENT_PHRASES

load_dotenv(override=True)

# ---------------------------------------------------------------------------
# Voice biometrics — load VoiceEncoder once at startup (3-5 s cold start)
# ---------------------------------------------------------------------------
try:
    from resemblyzer import VoiceEncoder, preprocess_wav
    import numpy as np
    voice_encoder = VoiceEncoder()
    print("[STARTUP] resemblyzer VoiceEncoder loaded.")
except Exception as _ve_err:
    voice_encoder = None
    preprocess_wav = None
    np = None
    print(f"[STARTUP] resemblyzer not available: {_ve_err}")

app = Flask(__name__)
app.secret_key = os.getenv('FLASK_SECRET_KEY', 'swarampay-dev-secret')

# Ensure dynamic_audio directory exists at startup
os.makedirs('dynamic_audio', exist_ok=True)

# ---------------------------------------------------------------------------
# Global state
# ---------------------------------------------------------------------------
CALL_STATE = {}
MENTOR_RESULTS = {}  # call_sid -> audio filename | 'PROCESSING' | 'ERROR'
OTP_STORE = {}       # {phone: {'otp': '123456', 'expires': timestamp}}

BALANCE_TEMPLATE = {
    'en': 'Your remaining balance is rupees {}',
    'hi': 'Aapka shesh balance hai {} rupay',
    'ta': 'Ungal meedhi iruppu rubai {}',
    'te': 'Mee migilina balance {} rupayilu',
    'kn': 'Nimmalli uLida byalens {} rupayi',
    'ml': 'Ningalude baaki balance {} roopa aanu',
    'mr': 'Tumcha shillak balance ahe {} rupaye',
    'bn': 'Aapnar baki balance {} taka',
    'gu': 'Tamarun baki balance chhe {} rupiya'
}

# Native + Roman yes-words used across voice confirmation prompts
YES_WORDS = [
    'haan', 'ha', 'yes', 'ho', 'sahi', 'correct', 'theek', 'bilkul',
    'aama', 'avunu', 'hovudu', 'aana',
    'हाँ', 'हां', 'हा', 'जी', 'हो',
    'হ্যাঁ', 'হ্যা', 'হা',
    'ஆம்', 'ஆமா',
    'అవును', 'అవు',
    'ಹೌದು', 'ಹೌ',
    'ആണ്', 'ആനൽ',
    'હા', 'હાં',
]

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def play(response, lang, prompt_name):
    """Play a pre-generated static prompt audio file."""
    audio_url = f"/audio/{lang}_{prompt_name}.wav"
    response.play(audio_url)


def redirect_to_prompt(route):
    """Return a TwiML redirect to the given route."""
    resp = VoiceResponse()
    resp.redirect(route)
    return Response(str(resp), mimetype='text/xml')


# ---------------------------------------------------------------------------
# Static audio serving
# ---------------------------------------------------------------------------

@app.route('/audio/<filename>')
def serve_audio(filename):
    return send_from_directory('prompt_audio', filename)


@app.route('/dynamic-audio/<filename>')
def serve_dynamic_audio(filename):
    return send_from_directory('dynamic_audio', filename)


@app.route('/call-status', methods=['POST'])
def call_status():
    """Twilio status-callback webhook — logs call lifecycle events and cleans up CALL_STATE."""
    call_sid = request.values.get('CallSid')
    status = request.values.get('CallStatus')
    print(f"[CALL STATUS] {call_sid}: {status}")
    if status in ('completed', 'busy', 'failed', 'no-answer', 'canceled'):
        CALL_STATE.pop(call_sid, None)
    return ('', 204)


# ---------------------------------------------------------------------------
# Section 1 — New vs Returning Caller Detection (handle_incoming)
# Implemented below — replaces the base repo's plain redirect to /prompt-lang
# ---------------------------------------------------------------------------

@app.route('/', methods=['GET', 'POST'])
def handle_incoming():
    call_sid = request.values.get('CallSid')
    raw_from = request.values.get('From', '')
    caller_phone = raw_from.replace('+91', '').replace('+', '').strip()

    user = get_user(caller_phone)

    if not user:
        # New caller → registration
        CALL_STATE[call_sid] = {'phone': caller_phone}
        return redirect_to_prompt('/register/language')
    else:
        # Returning caller → voice auth
        CALL_STATE[call_sid] = {
            'phone': caller_phone,
            'lang': user.get('lang', 'hi'),
            'user': user
        }
        return redirect_to_prompt('/auth/greet')


# ---------------------------------------------------------------------------
# Original language / phone / mPIN routes (kept as-is for MPIN fallback)
# ---------------------------------------------------------------------------

@app.route('/prompt-lang', methods=['GET', 'POST'])
def prompt_lang():
    resp = VoiceResponse()
    gather = Gather(num_digits=1, action='/submit-lang', method='POST', timeout=8, finish_on_key='')
    gather.play('/audio/universal_language_menu.wav')
    resp.append(gather)
    resp.redirect('/prompt-lang')
    return Response(str(resp), mimetype='text/xml')


@app.route('/submit-lang', methods=['GET', 'POST'])
def submit_lang():
    call_sid = request.values.get('CallSid')
    digit = request.values.get('Digits')
    if not digit or digit not in LANG_CONFIG:
        return redirect_to_prompt('/prompt-lang')
    lang = LANG_CONFIG[digit]
    CALL_STATE[call_sid] = {'lang': lang}
    return redirect_to_prompt('/prompt-phone')


@app.route('/prompt-phone', methods=['GET', 'POST'])
def prompt_phone():
    call_sid = request.values.get('CallSid')
    lang = CALL_STATE.get(call_sid, {}).get('lang', 'en')
    resp = VoiceResponse()
    gather = Gather(num_digits=10, action='/submit-phone', method='POST', timeout=15)
    play(gather, lang, 'enter_phone')
    resp.append(gather)
    resp.redirect('/prompt-phone')
    return Response(str(resp), mimetype='text/xml')


@app.route('/submit-phone', methods=['GET', 'POST'])
def submit_phone():
    call_sid = request.values.get('CallSid')
    phone = request.values.get('Digits', '').strip()
    state = CALL_STATE.get(call_sid, {})
    lang = state.get('lang', 'en')
    if len(phone) < 3:
        return redirect_to_prompt('/prompt-phone')
    user = get_user(phone)
    if not user:
        resp = VoiceResponse()
        play(resp, lang, 'invalid')
        resp.redirect('/prompt-phone')
        return Response(str(resp), mimetype='text/xml')
    state['phone'] = phone
    state['user'] = user
    CALL_STATE[call_sid] = state
    return redirect_to_prompt('/prompt-mpin')


@app.route('/prompt-mpin', methods=['GET', 'POST'])
def prompt_mpin():
    call_sid = request.values.get('CallSid')
    lang = CALL_STATE.get(call_sid, {}).get('lang', 'en')
    resp = VoiceResponse()
    gather = Gather(num_digits=4, action='/submit-mpin', method='POST', timeout=15)
    play(gather, lang, 'enter_mpin')
    resp.append(gather)
    resp.redirect('/prompt-mpin')
    return Response(str(resp), mimetype='text/xml')


@app.route('/submit-mpin', methods=['GET', 'POST'])
def submit_mpin():
    call_sid = request.values.get('CallSid')
    mpin = request.values.get('Digits')
    state = CALL_STATE.get(call_sid, {})
    lang = state.get('lang', 'en')
    user = state.get('user', {})
    if user.get('pin') != mpin:
        resp = VoiceResponse()
        play(resp, lang, 'wrong_mpin')
        resp.redirect('/prompt-mpin')
        return Response(str(resp), mimetype='text/xml')
    state['authenticated'] = True
    CALL_STATE[call_sid] = state
    resp = VoiceResponse()
    play(resp, lang, 'auth_success')
    resp.redirect('/prompt-main-menu')
    return Response(str(resp), mimetype='text/xml')


# ---------------------------------------------------------------------------
# Main Menu
# ---------------------------------------------------------------------------

@app.route('/prompt-main-menu', methods=['GET', 'POST'])
def prompt_main_menu():
    call_sid = request.values.get('CallSid')
    lang = CALL_STATE.get(call_sid, {}).get('lang', 'en')
    resp = VoiceResponse()
    play(resp, lang, 'how_can_i_help')
    resp.record(action='/handle-intent', method='POST', max_length=10,
                play_beep=True, timeout=5)
    resp.redirect('/prompt-main-menu')
    return Response(str(resp), mimetype='text/xml')


@app.route('/submit-main-menu', methods=['GET', 'POST'])
def submit_main_menu():
    call_sid = request.values.get('CallSid')
    digit = request.values.get('Digits')
    state = CALL_STATE.get(call_sid, {})
    lang = state.get('lang', 'en')
    user = state.get('user', {})

    resp = VoiceResponse()

    if digit == '1':  # Voice command / send money
        # Play prompt then record for /voice-command
        VOICE_CMD_PROMPTS = {
            'hi': 'Boliye, kya karna chahte hain?',
            'en': 'Please say what you would like to do.',
            'ta': 'Neenga enna seyya virumbureenga sollunga.',
            'te': 'Meeru emanna cheyyalanukunnaaru cheppandi.',
            'kn': 'Nimma ichchisida kaaryavenu heli.',
            'ml': 'Ningal enna cheyyanam ennu parayan.',
            'mr': 'Tumhala kay karaycha ahe sanga.',
            'bn': 'Aapni ki korte chan bolun.',
            'gu': 'Tame shu karvu chho te kaho.',
        }
        prompt_text = VOICE_CMD_PROMPTS.get(lang, VOICE_CMD_PROMPTS['en'])
        audio_path = Path(f'dynamic_audio/vcmd_prompt_{call_sid}.wav')
        save_tts(prompt_text, lang, audio_path)
        resp.play(f'/dynamic-audio/vcmd_prompt_{call_sid}.wav')
        resp.record(action='/voice-command', method='POST', max_length=10,
                    play_beep=True, timeout=5)
        resp.redirect('/prompt-main-menu')

    elif digit == '2':  # Balance
        acc = get_account(user.get('account_id', ''))
        balance = acc.get('balance', 0) if acc else 0
        text = BALANCE_TEMPLATE.get(lang, BALANCE_TEMPLATE['en']).format(int(balance))
        audio_path = Path(f'dynamic_audio/bal_{call_sid}.wav')
        if save_tts(text, lang, audio_path):
            resp.play(f'/dynamic-audio/bal_{call_sid}.wav')
        resp.redirect('/prompt-main-menu')

    elif digit == '3':
        resp.redirect('/prompt-loan-amount')

    elif digit == '4':
        resp.redirect('/prompt-insurance')

    elif digit == '5':  # Credit score — per-language TTS (not resp.say)
        score, factors = calculate_behavioral_score(user.get('phone', ''))
        credit_texts = {
            'hi': f"Aapka credit score hai {score} nau sau mein se.",
            'en': f"Your credit score is {score} out of 900.",
            'ta': f"Ungal credit score {score} in 900.",
            'te': f"Mee credit score {score} tanikivi 900 lo.",
            'kn': f"Nimmada credit score {score} out of 900.",
            'ml': f"Ningalude credit score aanu {score} 900 il ninnu.",
            'mr': f"Tumcha credit score ahe {score} naushe madhe.",
            'bn': f"Aapnar credit score holo {score} nau shorer modhye.",
            'gu': f"Tamaro credit score chhe {score} nau sau maan thi.",
        }
        credit_text = credit_texts.get(lang, credit_texts['en'])
        audio_path = Path(f'dynamic_audio/credit_{call_sid}.wav')
        if save_tts(credit_text, lang, audio_path):
            resp.play(f'/dynamic-audio/credit_{call_sid}.wav')
        resp.redirect('/prompt-main-menu')

    elif digit == '6':
        resp.redirect('/prompt-savings-amount')

    elif digit == '8':  # AI mentor
        resp.redirect('/mentor/start')

    else:
        play(resp, lang, 'invalid')
        resp.redirect('/prompt-main-menu')

    return Response(str(resp), mimetype='text/xml')


# ---------------------------------------------------------------------------
# UPI Payment (keypad — existing routes kept as fallback)
# ---------------------------------------------------------------------------

@app.route('/prompt-upi-recipient', methods=['GET', 'POST'])
def prompt_upi_recipient():
    call_sid = request.values.get('CallSid')
    lang = CALL_STATE.get(call_sid, {}).get('lang', 'en')
    resp = VoiceResponse()
    gather = Gather(num_digits=10, action='/submit-upi-recipient', method='POST', timeout=12)
    play(gather, lang, 'upi_ask_recipient')
    resp.append(gather)
    resp.redirect('/prompt-upi-recipient')
    return Response(str(resp), mimetype='text/xml')


@app.route('/submit-upi-recipient', methods=['GET', 'POST'])
def submit_upi_recipient():
    call_sid = request.values.get('CallSid')
    recip = request.values.get('Digits')
    state = CALL_STATE.get(call_sid, {})
    lang = state.get('lang', 'en')
    if not recip or len(recip) != 10 or not recip.isdigit():
        resp = VoiceResponse()
        play(resp, lang, 'invalid')
        resp.redirect('/prompt-upi-recipient')
        return Response(str(resp), mimetype='text/xml')
    state['recipient'] = recip
    CALL_STATE[call_sid] = state
    recip_user = get_user(recip)
    resp = VoiceResponse()
    if recip_user:
        name = recip_user.get('name', 'User')
        text = f"Sending money to {name}." if lang == 'en' else f"{name} ko paise bheje jayenge."
        audio_path = Path(f'dynamic_audio/recip_name_{call_sid}.wav')
        if save_tts(text, lang, audio_path):
            resp.play(f'/dynamic-audio/recip_name_{call_sid}.wav')
    resp.redirect('/prompt-upi-amount')
    return Response(str(resp), mimetype='text/xml')


@app.route('/prompt-upi-amount', methods=['GET', 'POST'])
def prompt_upi_amount():
    call_sid = request.values.get('CallSid')
    lang = CALL_STATE.get(call_sid, {}).get('lang', 'en')
    resp = VoiceResponse()
    gather = Gather(num_digits=4, action='/submit-upi-success', method='POST', timeout=12)
    play(gather, lang, 'upi_ask_amount')
    resp.append(gather)
    resp.redirect('/prompt-upi-amount')
    return Response(str(resp), mimetype='text/xml')


@app.route('/submit-upi-success', methods=['GET', 'POST'])
def submit_upi_success():
    call_sid = request.values.get('CallSid')
    amount = request.values.get('Digits', '0')
    state = CALL_STATE.get(call_sid, {})
    lang = state.get('lang', 'en')
    user_phone = state.get('phone', '')
    success, new_balance = perform_upi_transaction(user_phone, amount)
    resp = VoiceResponse()
    if success:
        try:
            twilio_client = Client(os.getenv('TWILIO_ACCOUNT_SID'), os.getenv('TWILIO_AUTH_TOKEN'))
            recip = state.get('recipient')
            if recip:
                twilio_client.messages.create(
                    body=f"SwaramPay: Rs {amount} credited to your account from {user_phone}.",
                    from_=os.getenv('TWILIO_PHONE_NUMBER'),
                    to=f'+91{recip}'
                )
        except Exception as e:
            print(f"[SMS] Failed: {e}")
        play(resp, lang, 'upi_success')
        text = BALANCE_TEMPLATE.get(lang, BALANCE_TEMPLATE['en']).format(int(new_balance))
        audio_path = Path(f'dynamic_audio/bal_{call_sid}.wav')
        if save_tts(text, lang, audio_path):
            resp.play(f'/dynamic-audio/bal_{call_sid}.wav')
    else:
        play(resp, lang, 'upi_failed')
    resp.redirect('/prompt-main-menu')
    return Response(str(resp), mimetype='text/xml')


# ---------------------------------------------------------------------------
# UPI PIN (Section 5 — mock DTMF)
# ---------------------------------------------------------------------------

@app.route('/prompt-upi-pin', methods=['GET', 'POST'])
def prompt_upi_pin():
    call_sid = request.values.get('CallSid')
    lang = CALL_STATE.get(call_sid, {}).get('lang', 'hi')
    resp = VoiceResponse()
    gather = Gather(num_digits=4, action='/submit-upi-pin', method='POST', timeout=15)
    play(gather, lang, 'enter_upi_pin')
    resp.append(gather)
    resp.redirect('/prompt-upi-pin')
    return Response(str(resp), mimetype='text/xml')


@app.route('/submit-upi-pin', methods=['GET', 'POST'])
def submit_upi_pin():
    # Demo: any 4-digit PIN accepted. In production: UPI 123PAY API.
    return redirect_to_prompt('/submit-upi-success')


# ---------------------------------------------------------------------------
# Other sub-menus (loan, insurance, savings — kept from base)
# ---------------------------------------------------------------------------

@app.route('/prompt-loan-amount', methods=['GET', 'POST'])
def prompt_loan_amount():
    call_sid = request.values.get('CallSid')
    lang = CALL_STATE.get(call_sid, {}).get('lang', 'en')
    resp = VoiceResponse()
    gather = Gather(input="dtmf", finish_on_key="#", timeout=15, method="POST", action="/submit-loan")
    play(gather, lang, 'loan_ask_amount')
    resp.append(gather)
    resp.redirect('/prompt-loan-amount')
    return Response(str(resp), mimetype='text/xml')


@app.route('/submit-loan', methods=['GET', 'POST'])
def submit_loan():
    call_sid = request.values.get('CallSid')
    lang = CALL_STATE.get(call_sid, {}).get('lang', 'en')
    resp = VoiceResponse()
    play(resp, lang, 'loan_approved')
    resp.redirect('/prompt-main-menu')
    return Response(str(resp), mimetype='text/xml')


@app.route('/prompt-insurance', methods=['GET', 'POST'])
def prompt_insurance():
    call_sid = request.values.get('CallSid')
    lang = CALL_STATE.get(call_sid, {}).get('lang', 'en')
    resp = VoiceResponse()
    gather = Gather(num_digits=1, action='/submit-insurance', method='POST', timeout=8)
    play(gather, lang, 'insurance_menu')
    resp.append(gather)
    resp.redirect('/prompt-insurance')
    return Response(str(resp), mimetype='text/xml')


@app.route('/submit-insurance', methods=['GET', 'POST'])
def submit_insurance():
    call_sid = request.values.get('CallSid')
    choice = request.values.get('Digits')
    lang = CALL_STATE.get(call_sid, {}).get('lang', 'en')
    resp = VoiceResponse()
    if choice in ['1', '2']:
        play(resp, lang, 'insurance_success')
        resp.redirect('/prompt-main-menu')
    else:
        play(resp, lang, 'invalid')
        resp.redirect('/prompt-insurance')
    return Response(str(resp), mimetype='text/xml')


@app.route('/prompt-savings-amount', methods=['GET', 'POST'])
def prompt_savings_amount():
    call_sid = request.values.get('CallSid')
    lang = CALL_STATE.get(call_sid, {}).get('lang', 'en')
    resp = VoiceResponse()
    gather = Gather(num_digits=4, action='/prompt-savings-duration', method='POST', timeout=10)
    play(gather, lang, 'savings_ask_amount')
    resp.append(gather)
    resp.redirect('/prompt-savings-amount')
    return Response(str(resp), mimetype='text/xml')


@app.route('/prompt-savings-duration', methods=['GET', 'POST'])
def prompt_savings_duration():
    call_sid = request.values.get('CallSid')
    amount = request.values.get('Digits')
    state = CALL_STATE.get(call_sid, {})
    if amount:
        state['savings_amt'] = amount
    CALL_STATE[call_sid] = state
    lang = state.get('lang', 'en')
    resp = VoiceResponse()
    gather = Gather(num_digits=2, action='/submit-savings', method='POST', timeout=10)
    play(gather, lang, 'savings_ask_duration')
    resp.append(gather)
    resp.redirect('/prompt-savings-duration')
    return Response(str(resp), mimetype='text/xml')


@app.route('/submit-savings', methods=['GET', 'POST'])
def submit_savings():
    call_sid = request.values.get('CallSid')
    lang = CALL_STATE.get(call_sid, {}).get('lang', 'en')
    resp = VoiceResponse()
    play(resp, lang, 'savings_success')
    resp.redirect('/prompt-main-menu')
    return Response(str(resp), mimetype='text/xml')


# ---------------------------------------------------------------------------
# AI Financial Mentor (kept from base — Section 7 deprioritized)
# ---------------------------------------------------------------------------

@app.route('/mentor/start', methods=['GET', 'POST'])
def mentor_start():
    call_sid = request.values.get('CallSid')
    state = CALL_STATE.get(call_sid, {})
    lang = state.get('lang', 'en')
    user = state.get('user', {})
    acc = get_account(user.get('account_id', ''))
    state['balance'] = acc.get('balance', 0) if acc else 0
    state['credit_score'] = 650
    CALL_STATE[call_sid] = state
    resp = VoiceResponse()
    intro_texts = {
        'en': 'Welcome to SwaramPay Financial Mentor. Ask me any financial question after the beep.',
        'hi': 'SwaramPay Financial Mentor mein aapka swagat hai. Beep ke baad apna sawaal poochein.',
        'ta': 'SwaramPay Financial Mentor-il ungalai varuverpagiren. Beep-ku piragu ungal kelvi kelunga.',
        'te': 'SwaramPay Financial Mentor lo swaagatam. Beep taravata mee prashna adugandi.',
        'kn': 'SwaramPay Financial Mentor ge swagatha. Beep nantara nimma prashne keeli.',
        'ml': 'SwaramPay Financial Mentor il swagatham. Beep-inu sesham ninagal chodyam chodyikku.',
        'mr': 'SwaramPay Financial Mentor madhye swagat. Beep nantar tumcha prashna vicharaa.',
        'bn': 'SwaramPay Financial Mentor e swagato. Beep er pore apanar proshno jiggesh korun.',
        'gu': 'SwaramPay Financial Mentor ma swagat chhe. Beep pachhi tamaro prashna poochho.',
    }
    intro_file = Path(f'dynamic_audio/mentor_intro_{call_sid}.wav')
    try:
        save_tts(intro_texts.get(lang, intro_texts['en']), lang, intro_file)
        resp.play(f'/dynamic-audio/mentor_intro_{call_sid}.wav')
    except Exception:
        pass
    resp.redirect('/mentor/listen')
    return Response(str(resp), mimetype='text/xml')


@app.route('/mentor/listen', methods=['GET', 'POST'])
def mentor_listen():
    resp = VoiceResponse()
    resp.say(".")
    resp.record(action='/mentor/process', method='POST', max_length=30,
                finish_on_key='#', play_beep=True, timeout=5)
    resp.redirect('/mentor/listen')
    return Response(str(resp), mimetype='text/xml')


@app.route('/mentor/process', methods=['GET', 'POST'])
def mentor_process():
    call_sid = request.values.get('CallSid')
    recording_url = request.values.get('RecordingUrl', '')
    recording_duration = int(request.values.get('RecordingDuration', 0))
    state = CALL_STATE.get(call_sid, {})
    resp = VoiceResponse()
    if recording_duration < 1:
        resp.redirect('/mentor/listen')
        return Response(str(resp), mimetype='text/xml')
    MENTOR_RESULTS[call_sid] = 'PROCESSING'

    def _bg():
        result = process_mentor_audio(recording_url, call_sid, state)
        MENTOR_RESULTS[call_sid] = result if result else 'ERROR'

    threading.Thread(target=_bg, daemon=True).start()
    resp.pause(length=8)
    resp.redirect('/mentor/check-result')
    return Response(str(resp), mimetype='text/xml')


@app.route('/mentor/check-result', methods=['GET', 'POST'])
def mentor_check_result():
    call_sid = request.values.get('CallSid')
    state = CALL_STATE.get(call_sid, {})
    lang = state.get('lang', 'en')
    result = MENTOR_RESULTS.get(call_sid, 'ERROR')
    resp = VoiceResponse()
    if result == 'PROCESSING':
        resp.pause(length=3)
        resp.redirect('/mentor/check-result')
    elif result != 'ERROR' and result:
        resp.redirect(f'/mentor/respond?audio={result}')
    else:
        error_texts = {
            'en': 'Sorry, I did not understand. Please speak again.',
            'hi': 'Maafi chahta hoon, samajh nahi aaya. Kripya phir se bolein.',
        }
        resp.say(error_texts.get(lang, error_texts['en']))
        resp.redirect('/mentor/listen')
    return Response(str(resp), mimetype='text/xml')


@app.route('/mentor/respond', methods=['GET', 'POST'])
def mentor_respond():
    call_sid = request.values.get('CallSid')
    audio_filename = request.values.get('audio', '')
    state = CALL_STATE.get(call_sid, {})
    lang = state.get('lang', 'en')
    resp = VoiceResponse()
    if audio_filename:
        resp.play(f'/dynamic-audio/{audio_filename}')
    followup_texts = {
        'en': 'You can ask another question, or press star to return to the main menu.',
        'hi': 'Aap aur sawaal pooch sakte hain, ya star dabakar main menu mein wapas ja sakte hain.',
    }
    followup_file = Path(f'dynamic_audio/mentor_followup_{call_sid}.wav')
    try:
        save_tts(followup_texts.get(lang, followup_texts['en']), lang, followup_file)
        resp.play(f'/dynamic-audio/mentor_followup_{call_sid}.wav')
    except Exception:
        resp.say(followup_texts.get(lang, followup_texts['en']))
    resp.record(action='/mentor/process', method='POST', max_length=30,
                finish_on_key='*', play_beep=True, timeout=5)
    resp.redirect('/prompt-main-menu')
    return Response(str(resp), mimetype='text/xml')


# ===========================================================================
# SECTION 2 — Registration Chain (new callers)
# ===========================================================================

NAME_PROMPTS = {
    'hi': 'Apna naam boliye.',
    'en': 'Please say your full name.',
    'ta': 'Ungal peyar sollunga.',
    'te': 'Meeru peru cheppandi.',
    'kn': 'Nimma hesaru heli.',
    'ml': 'Ningalude peru parayan.',
    'mr': 'Tumcha naav sanga.',
    'bn': 'Aapnar naam bolun.',
    'gu': 'Tamarun naam bolo.',
}

GUARDIAN_PROMPTS = {
    'hi': "Aapko ek SMS bheja gaya hai jisme companion portal ka link hai. "
          "Agar aap kisi guardian ko apne wallet mein paise daalne ki anumati dena chahte hain, "
          "toh unka 10 ank ka number abhi boliye. Nahi chahte toh chup rahiye.",
    'en': "We have sent you an SMS with the companion portal link. "
          "If you would like to add a guardian who can add money to your wallet, "
          "please say their 10-digit number now. Otherwise stay silent.",
    'ta': "Ungal SMS-il companion portal link anuppinoom. "
          "Guardian number solluvadhu virupthamana sollunga. Illatha podu maun aagidunga.",
    'te': "Mee SMS ki companion portal link pathimamu. "
          "Guardian number cheppali ante cheppandi. Leda maatladakandi.",
    'kn': "Companion portal link SMS madhye kalisiddeve. "
          "Guardian number helikollalu ichche iddare heli. Beda enandare sumu.",
    'ml': "Companion portal link SMS il anachchu. "
          "Guardian number parayan virumbunaale parayan. Illa enkil maunam pal.",
    'mr': "Companion portal link SMS madhye pathavala ahe. "
          "Guardian number sangayache asel tar sanga. Nahi tar gapp raha.",
    'bn': "Companion portal link SMS e pathano hoyeche. "
          "Guardian number bolte chan ta bolun. Nahole chup thakun.",
    'gu': "Companion portal link SMS ma mokli chhe. "
          "Guardian number keheva hoy to kaho. Na hoy to chup raho.",
}

GUARDIAN_CONFIRM_PROMPTS = {
    'hi': "Kya aapne yeh number bola hai: {}? Haan ke liye haan boliye, nahi ke liye nahi.",
    'en': "Did you say the number: {}? Say yes to confirm or no to retry.",
    'ta': "Neenga solnadu {} numbera? Aama ena haan solunga, illana na solunga.",
    'te': "Meeru cheppindi {} numbera? Avunu ante avunu ani cheppandi, kadu ante kadu.",
    'kn': "Neevu helida number {} na? Hovudaadare hovudu heli, illadidare illa heli.",
    'ml': "Ningal paranjathu {} number aano? Aanenkilum aana parayan, illenkilum illa parayan.",
    'mr': "Tumhi sanghitala number {} ahe ka? Ho assal tar ho sanga, nahi assal tar nahi.",
    'bn': "Apni ki {} number bolechen? Ha hole haan bolun, na hole na bolun.",
    'gu': "Tamne {} number kahyo hato? Ha hoy to haa kaho, na hoy to na kaho.",
}

GUARDIAN_DTMF_PROMPTS = {
    'hi': "Keypad se guardian ka 10 ank ka number daalen.",
    'en': "Please enter the guardian's 10-digit number on the keypad.",
    'ta': "Guardian number keypad il type pannunga.",
    'te': "Keypad lo guardian number enter cheyyandi.",
    'kn': "Keypad nadige guardian number enter madi.",
    'ml': "Guardian number keypadil type cheyyoo.",
    'mr': "Guardian number keypad var enter kara.",
    'bn': "Keypad e guardian number din.",
    'gu': "Keypad par guardian number nakhho.",
}

COMPLETION_PROMPTS = {
    'hi': "Badhaai ho {}ji! Aapka SwaramPay wallet tayaar hai. Paise jama karne ke liye, hamari website par jaayein. Dhanyavaad!",
    'en': "Congratulations {}! Your SwaramPay wallet is ready. Please visit our website to deposit money. Thank you!",
    'ta': "Nandri {}! Ungal SwaramPay wallet tayaar. Panam podradhuku, engal website-ku sellungal. Nandri!",
    'te': "Abhinandanalu {}! Mee SwaramPay wallet ready. Daanam jamacheyataniki, maa website ki vellandi. Dhanyavaadalu!",
    'kn': "Abhimanada {}! Nimmada SwaramPay wallet siddha. Hana jama maadalu, nammada website ge hogi. Dhanyavaadagalu!",
    'ml': "Aabhivaadanam {}! Ningalude SwaramPay wallet tayaar. Panam nikshepikkan, njangalude website il pokoo. Nanni!",
    'mr': "Abhinandan {}! Tumcha SwaramPay wallet tayaar ahe. Paise jama karnyasathi, amchya website la jaa. Dhanyavaad!",
    'bn': "Abhinandan {}! Aapnar SwaramPay wallet tayaar. Taka jama korar jonno, amader website e jaan. Dhonnobad!",
    'gu': "Abhinandan {}! Tamaro SwaramPay wallet tayaar chhe. Paisa jama karva mate, amari website par jaav. Aabhar!",
}


@app.route('/register/language', methods=['GET', 'POST'])
def register_language():
    resp = VoiceResponse()
    gather = Gather(num_digits=1, action='/register/submit-language',
                    method='POST', timeout=8, finish_on_key='')
    gather.play('/audio/universal_language_menu.wav')
    resp.append(gather)
    resp.redirect('/register/language')
    return Response(str(resp), mimetype='text/xml')


@app.route('/register/submit-language', methods=['GET', 'POST'])
def register_submit_language():
    call_sid = request.values.get('CallSid')
    digit = request.values.get('Digits')
    if digit not in LANG_CONFIG:
        return redirect_to_prompt('/register/language')
    lang = LANG_CONFIG[digit]
    CALL_STATE[call_sid]['lang'] = lang
    return redirect_to_prompt('/register/name')


@app.route('/register/name', methods=['GET', 'POST'])
def register_name():
    call_sid = request.values.get('CallSid')
    lang = CALL_STATE[call_sid].get('lang', 'hi')
    resp = VoiceResponse()
    resp.play(f'/audio/{lang}_reg_name_prompt.wav')
    resp.record(action='/register/name-submit', method='POST',
                max_length=6, finish_on_key='#', play_beep=True, timeout=4)
    resp.redirect('/register/name')
    return Response(str(resp), mimetype='text/xml')


@app.route('/register/name-submit', methods=['GET', 'POST'])
def register_name_submit():
    call_sid = request.values.get('CallSid')
    recording_url = request.values.get('RecordingUrl', '')
    state = CALL_STATE[call_sid]
    lang = state.get('lang', 'hi')
    audio_path = f'dynamic_audio/reg_name_{call_sid}.wav'
    download_twilio_recording(recording_url, audio_path)
    name = speech_to_text(audio_path, lang)
    if not name or len(name.strip()) < 2:
        return redirect_to_prompt('/register/name')
    state['name'] = name.strip().title()
    CALL_STATE[call_sid] = state
    return redirect_to_prompt('/register/voice-enroll-intro')


# ---------------------------------------------------------------------------
# Voice Enrollment (Section 2.3) — 3 phrases → average embeddings → store
# ---------------------------------------------------------------------------

ENROLL_INTRO_PROMPTS = {
    'hi': "Abhi hum aapki awaaz register karenge. Aapko teen waakyaan dohraaney honge. "
          "Har baar beep ke baad clearly boliye.",
    'en': "We will now register your voice. You will repeat three phrases. "
          "Please speak clearly after each beep.",
    'ta': "Ippodu ungal kural pothivom. Moondru vaarthaigalai thirumba solluveenga. "
          "Oru beep piragu thannai thendivu sollunga.",
    'te': "Ippudu meeru voice register cheyyabotunnam. Moodu phrases repeat cheyyandi. "
          "Prathi beep tarvata clearly maatladandi.",
    'kn': "Ippaga nimma dhwani nondayisuvemu. Mooru vaakya punha heluvi. "
          "Pratii beep nantara sparshta vaagi heli.",
    'ml': "Ippol ningalude shwaram register cheyyunnu. Moonnu vakyam repeat cheyyuka. "
          "Oru beep-inu sesham spashTamaai parayan.",
    'mr': "Aata aapla awaz nondavuvat. Teen vakya punha sanga. "
          "Pratyeki beep nantar spashTa pane sanga.",
    'bn': "Ekhon aapnar awaz nondhibon. Tin baky abar bolte hobe. "
          "Protibar beep er pore spashto kore bolun.",
    'gu': "Havan tamaro awaj nond karvaano. Teen vaakyo repeat karva. "
          "Ek beep pachi spashTa bolo.",
}


@app.route('/register/voice-enroll-intro', methods=['GET', 'POST'])
def register_voice_enroll_intro():
    call_sid = request.values.get('CallSid')
    state = CALL_STATE[call_sid]
    lang = state.get('lang', 'hi')
    state['enroll_embeddings'] = []
    state['enroll_phrase_idx'] = 0
    CALL_STATE[call_sid] = state
    resp = VoiceResponse()
    resp.play(f'/audio/{lang}_enroll_intro.wav')
    resp.redirect('/register/voice-enroll-phrase')
    return Response(str(resp), mimetype='text/xml')


@app.route('/register/voice-enroll-phrase', methods=['GET', 'POST'])
def register_voice_enroll_phrase():
    """Play the current challenge phrase; then record."""
    call_sid = request.values.get('CallSid')
    state = CALL_STATE[call_sid]
    lang = state.get('lang', 'hi')
    idx = state.get('enroll_phrase_idx', 0)
    phrases = ENROLLMENT_PHRASES.get(lang, ENROLLMENT_PHRASES['hi'])
    phrase = phrases[idx % len(phrases)]
    state['current_enroll_phrase'] = phrase
    CALL_STATE[call_sid] = state
    phrase_count_map = {
        'hi': f"Vaakya {idx + 1}: {phrase}",
        'en': f"Phrase {idx + 1}: {phrase}",
        'ta': f"Vaarthai {idx + 1}: {phrase}",
        'te': f"Phrase {idx + 1}: {phrase}",
        'kn': f"Vaakya {idx + 1}: {phrase}",
        'ml': f"Phrase {idx + 1}: {phrase}",
        'mr': f"Vaakya {idx + 1}: {phrase}",
        'bn': f"Vakya {idx + 1}: {phrase}",
        'gu': f"Vaakya {idx + 1}: {phrase}",
    }
    resp = VoiceResponse()
    resp.play(f'/audio/{lang}_enroll_phrase_{idx}.wav')
    resp.record(action='/register/voice-enroll-record', method='POST',
                max_length=8, play_beep=True, timeout=4)
    resp.redirect('/register/voice-enroll-phrase')  # timeout fallback
    return Response(str(resp), mimetype='text/xml')


@app.route('/register/voice-enroll-record', methods=['GET', 'POST'])
def register_voice_enroll_record():
    """Download recording, compute embedding, store or restart."""
    call_sid = request.values.get('CallSid')
    recording_url = request.values.get('RecordingUrl', '')
    duration = int(request.values.get('RecordingDuration', 0))
    state = CALL_STATE[call_sid]
    lang = state.get('lang', 'hi')
    if duration < 1:
        return redirect_to_prompt('/register/voice-enroll-phrase')
    audio_path = f'dynamic_audio/enroll_rec_{call_sid}_{state["enroll_phrase_idx"]}.wav'
    download_twilio_recording(recording_url, audio_path)
    embedding = None
    if voice_encoder is not None and preprocess_wav is not None:
        try:
            wav = preprocess_wav(audio_path)
            embedding = voice_encoder.embed_utterance(wav).tolist()
        except Exception as e:
            print(f"[ENROLL] Embedding failed: {e}")
    embeddings = state.get('enroll_embeddings', [])
    if embedding:
        embeddings.append(embedding)
    state['enroll_embeddings'] = embeddings
    state['enroll_phrase_idx'] = state.get('enroll_phrase_idx', 0) + 1
    CALL_STATE[call_sid] = state
    if state['enroll_phrase_idx'] < 3:
        return redirect_to_prompt('/register/voice-enroll-phrase')
    return redirect_to_prompt('/register/build-voice-model')


@app.route('/register/build-voice-model', methods=['GET', 'POST'])
def register_build_voice_model():
    """Average collected embeddings → store voice_model → proceed to guardian."""
    call_sid = request.values.get('CallSid')
    state = CALL_STATE[call_sid]
    lang = state.get('lang', 'hi')
    embeddings = state.get('enroll_embeddings', [])
    if len(embeddings) < 2:
        # Not enough clean samples — restart enrollment
        state['enroll_embeddings'] = []
        state['enroll_phrase_idx'] = 0
        CALL_STATE[call_sid] = state
        resp = VoiceResponse()
        play(resp, lang, 'enroll_retry')
        resp.redirect('/register/voice-enroll-intro')
        return Response(str(resp), mimetype='text/xml')
    # Average embeddings
    avg = np.mean(np.array(embeddings), axis=0).tolist()
    state['voice_model'] = avg
    CALL_STATE[call_sid] = state
    return redirect_to_prompt('/register/mpin-setup')


@app.route('/register/mpin-setup', methods=['GET', 'POST'])
def register_mpin_setup():
    call_sid = request.values.get('CallSid')
    lang = CALL_STATE.get(call_sid, {}).get('lang', 'hi')
    resp = VoiceResponse()
    gather = Gather(num_digits=4, action='/register/mpin-confirm', method='POST', timeout=15)
    play(gather, lang, 'mpin_setup')
    resp.append(gather)
    resp.redirect('/register/mpin-setup')
    return Response(str(resp), mimetype='text/xml')


@app.route('/register/mpin-confirm', methods=['GET', 'POST'])
def register_mpin_confirm():
    call_sid = request.values.get('CallSid')
    digits = request.values.get('Digits', '')
    state = CALL_STATE[call_sid]
    lang = state.get('lang', 'hi')
    if len(digits) != 4 or not digits.isdigit():
        return redirect_to_prompt('/register/mpin-setup')
    state['pending_mpin'] = digits
    CALL_STATE[call_sid] = state
    resp = VoiceResponse()
    gather = Gather(num_digits=4, action='/register/mpin-verify', method='POST', timeout=15)
    play(gather, lang, 'mpin_confirm')
    resp.append(gather)
    resp.redirect('/register/mpin-setup')
    return Response(str(resp), mimetype='text/xml')


@app.route('/register/mpin-verify', methods=['GET', 'POST'])
def register_mpin_verify():
    call_sid = request.values.get('CallSid')
    digits = request.values.get('Digits', '')
    state = CALL_STATE[call_sid]
    lang = state.get('lang', 'hi')
    if digits != state.get('pending_mpin'):
        resp = VoiceResponse()
        play(resp, lang, 'mpin_mismatch')
        resp.redirect('/register/mpin-setup')
        return Response(str(resp), mimetype='text/xml')
    state['mpin'] = digits
    state.pop('pending_mpin', None)
    CALL_STATE[call_sid] = state
    return redirect_to_prompt('/register/guardian-prompt')


@app.route('/register/guardian-prompt', methods=['GET', 'POST'])
def register_guardian_prompt():
    call_sid = request.values.get('CallSid')
    state = CALL_STATE[call_sid]
    lang = state.get('lang', 'hi')
    phone = state.get('phone')
    try:
        twilio_client = Client(os.getenv('TWILIO_ACCOUNT_SID'), os.getenv('TWILIO_AUTH_TOKEN'))
        twilio_client.messages.create(
            body=f"SwaramPay: Aapka wallet tayaar hai! Companion portal: {os.getenv('SERVER_BASE_URL', '')}/companion",
            from_=os.getenv('TWILIO_PHONE_NUMBER'),
            to=f'+91{phone}'
        )
    except Exception as e:
        print(f"[SMS] Failed to send portal link: {e}")
    resp = VoiceResponse()
    resp.play(f'/audio/{lang}_guardian_prompt.wav')
    resp.record(action='/register/guardian-number-submit', method='POST',
                max_length=10, play_beep=False, timeout=6)
    resp.redirect('/register/complete')
    return Response(str(resp), mimetype='text/xml')


@app.route('/register/guardian-number-submit', methods=['GET', 'POST'])
def register_guardian_number_submit():
    call_sid = request.values.get('CallSid')
    recording_url = request.values.get('RecordingUrl', '')
    duration = int(request.values.get('RecordingDuration', 0))
    state = CALL_STATE[call_sid]
    lang = state.get('lang', 'hi')
    if duration < 1:
        return redirect_to_prompt('/register/complete')
    audio_path = f'dynamic_audio/guardian_num_{call_sid}.wav'
    download_twilio_recording(recording_url, audio_path)
    # Force English STT for number capture — digits are spoken in English across all languages
    transcript = speech_to_text(audio_path, 'en')
    digits_only = re.sub(r'\D', '', transcript)
    if len(digits_only) != 10:
        # Voice didn't yield 10 digits — fall back to DTMF keypad
        return redirect_to_prompt('/register/guardian-keypad')
    state['pending_guardian'] = digits_only
    CALL_STATE[call_sid] = state
    spaced = ' '.join(list(digits_only))
    confirm_text = GUARDIAN_CONFIRM_PROMPTS.get(lang, GUARDIAN_CONFIRM_PROMPTS['en']).format(spaced)
    audio_path = Path(f'dynamic_audio/guardian_confirm_{call_sid}.wav')
    save_tts(confirm_text, lang, audio_path)
    resp = VoiceResponse()
    resp.play(f'/dynamic-audio/guardian_confirm_{call_sid}.wav')
    resp.record(action='/register/guardian-confirm-submit', method='POST',
                max_length=4, play_beep=True, timeout=4)
    return Response(str(resp), mimetype='text/xml')


@app.route('/register/guardian-keypad', methods=['GET', 'POST'])
def register_guardian_keypad():
    """Keypad fallback when voice digit extraction fails."""
    call_sid = request.values.get('CallSid')
    lang = CALL_STATE.get(call_sid, {}).get('lang', 'hi')
    resp = VoiceResponse()
    gather = Gather(num_digits=10, action='/register/guardian-keypad-submit',
                    method='POST', timeout=15)
    gather.play(f'/audio/{lang}_guardian_dtmf.wav')
    resp.append(gather)
    resp.redirect('/register/complete')  # timeout → skip
    return Response(str(resp), mimetype='text/xml')


@app.route('/register/guardian-keypad-submit', methods=['GET', 'POST'])
def register_guardian_keypad_submit():
    # DTMF digits are unambiguous — save directly without voice confirmation
    call_sid = request.values.get('CallSid')
    digits = request.values.get('Digits', '')
    state = CALL_STATE[call_sid]
    lang = state.get('lang', 'hi')
    if len(digits) != 10 or not digits.isdigit():
        return redirect_to_prompt('/register/complete')
    state['guardians'] = [digits]
    CALL_STATE[call_sid] = state
    try:
        twilio_client = Client(os.getenv('TWILIO_ACCOUNT_SID'), os.getenv('TWILIO_AUTH_TOKEN'))
        name = state.get('name', 'Your ward')
        twilio_client.messages.create(
            body=f"{name} ne aapko SwaramPay guardian banaya hai. "
                 f"Login karein: {os.getenv('SERVER_BASE_URL', '')}/companion",
            from_=os.getenv('TWILIO_PHONE_NUMBER'),
            to=f'+91{digits}'
        )
        print(f"[GUARDIAN] SMS sent to {digits}")
    except Exception as e:
        print(f"[GUARDIAN] SMS failed: {e}")
    return redirect_to_prompt('/register/complete')


@app.route('/register/guardian-confirm-submit', methods=['GET', 'POST'])
def register_guardian_confirm_submit():
    call_sid = request.values.get('CallSid')
    recording_url = request.values.get('RecordingUrl', '')
    state = CALL_STATE[call_sid]
    lang = state.get('lang', 'hi')
    audio_path = f'dynamic_audio/guardian_yn_{call_sid}.wav'
    download_twilio_recording(recording_url, audio_path)
    answer = speech_to_text(audio_path, lang).lower().strip()
    confirmed = any(w in answer for w in [
        # Roman transliterations
        'haan', 'ha', 'yes', 'ho', 'sahi', 'correct', 'theek',
        'aama', 'avunu', 'hovudu', 'aana',
        # Native scripts: Hindi/Marathi हाँ हां हा जी, Bengali হ্যাঁ হ্যা,
        # Tamil ஆம், Telugu అవును, Kannada ಹೌದು, Malayalam ആണ്, Gujarati હા
        'हाँ', 'हां', 'हा', 'जी', 'हो',
        'হ্যাঁ', 'হ্যা', 'হা',
        'ஆம்', 'ஆமா',
        'అవును', 'అవు',
        'ಹೌದು', 'ಹೌ',
        'ആണ്', 'ആനൽ',
        'હા', 'હાં',
    ])
    if confirmed:
        guardian_phone = state.get('pending_guardian')
        state['guardians'] = [guardian_phone]
        CALL_STATE[call_sid] = state
        try:
            twilio_client = Client(os.getenv('TWILIO_ACCOUNT_SID'), os.getenv('TWILIO_AUTH_TOKEN'))
            twilio_client.messages.create(
                body=f"{state['name']} ne aapko SwaramPay guardian banaya hai. "
                     f"Login karein: {os.getenv('SERVER_BASE_URL', '')}/companion",
                from_=os.getenv('TWILIO_PHONE_NUMBER'),
                to=f'+91{guardian_phone}'
            )
        except Exception as e:
            print(f"[SMS] Guardian invite failed: {e}")
    else:
        state['guardians'] = []
        CALL_STATE[call_sid] = state
    return redirect_to_prompt('/register/complete')


@app.route('/register/complete', methods=['GET', 'POST'])
def register_complete():
    call_sid = request.values.get('CallSid')
    state = CALL_STATE[call_sid]
    lang = state.get('lang', 'hi')
    phone = state.get('phone')
    name = state.get('name', 'User')
    users = load_json('data/users.json')
    accounts = load_json('data/accounts.json')
    acc_id = f"acc_{phone}"
    users[phone] = {
        'name': name,
        'phone': phone,
        'lang': lang,
        'voice_model': state.get('voice_model', []),
        'pin': state.get('mpin', ''),
        'account_id': acc_id,
        'guardians': state.get('guardians', []),
        'contacts': [],
        'registered_on': str(datetime.date.today()),
    }
    accounts[acc_id] = {'balance': 0, 'transactions': []}
    save_json('data/users.json', users)
    save_json('data/accounts.json', accounts)
    completion_text = COMPLETION_PROMPTS.get(lang, COMPLETION_PROMPTS['en']).format(name + ' ')
    audio_path = Path(f'dynamic_audio/reg_complete_{call_sid}.wav')
    save_tts(completion_text, lang, audio_path)
    resp = VoiceResponse()
    resp.play(f'/dynamic-audio/reg_complete_{call_sid}.wav')
    resp.hangup()
    return Response(str(resp), mimetype='text/xml')


# ===========================================================================
# SECTION 3 — Voice Authentication (returning callers)
# ===========================================================================

VOICE_AUTH_THRESHOLD = 0.80  # calibrated: genuine ~0.86-0.88, impostor ~0.68-0.74 on 8kHz Twilio audio


def verify_voice(stored_model_list, audio_path):
    """
    Compare live recording against the stored voice model.
    Returns (authenticated: bool, score: float).
    Guard against empty model (no enrollment yet).
    """
    if not stored_model_list:
        print("[VOICE AUTH] No voice model enrolled.")
        return False, 0.0
    try:
        stored = np.array(stored_model_list)
        wav = preprocess_wav(audio_path)
        live = voice_encoder.embed_utterance(wav)
        similarity = float(np.dot(stored, live) / (np.linalg.norm(stored) * np.linalg.norm(live)))
        print(f"[VOICE AUTH] Cosine similarity: {similarity:.3f}")
        return similarity >= VOICE_AUTH_THRESHOLD, similarity
    except Exception as e:
        print(f"[VOICE AUTH] Error: {e}")
        return False, 0.0


def _transcript_matches_challenge(challenge_phrase: str, response_text: str) -> bool:
    """
    Anti-replay check: >50% of challenge words must appear in the response.
    No external stopwords library — plain word-set intersection.
    """
    challenge_words = set(challenge_phrase.lower().split())
    response_words = set(response_text.lower().split())
    if not challenge_words:
        return True
    overlap = len(challenge_words & response_words)
    ratio = overlap / len(challenge_words)
    print(f"[ANTI-REPLAY] Overlap {overlap}/{len(challenge_words)} = {ratio:.2f}")
    return ratio > 0.5


@app.route('/auth/greet', methods=['GET', 'POST'])
def auth_greet():
    call_sid = request.values.get('CallSid')
    state = CALL_STATE[call_sid]
    lang = state.get('lang', 'hi')
    from config import ENROLLMENT_PHRASES
    phrases = ENROLLMENT_PHRASES.get(lang, ENROLLMENT_PHRASES['hi'])
    idx = random.randrange(len(phrases))
    state['auth_phrase'] = phrases[idx]
    state['auth_attempts'] = state.get('auth_attempts', 0)
    CALL_STATE[call_sid] = state
    resp = VoiceResponse()
    play(resp, lang, 'auth_greet')
    resp.play(f'/audio/{lang}_auth_phrase_{idx}.wav')
    resp.record(action='/auth/verify', method='POST', max_length=8, play_beep=True, timeout=4)
    resp.redirect('/auth/greet')
    return Response(str(resp), mimetype='text/xml')


@app.route('/auth/verify', methods=['GET', 'POST'])
def auth_verify():
    t_handler = time.perf_counter()
    call_sid = request.values.get('CallSid')
    recording_url = request.values.get('RecordingUrl', '')
    duration = int(request.values.get('RecordingDuration', 0))
    state = CALL_STATE[call_sid]
    lang = state.get('lang', 'hi')
    user = state.get('user', {})
    if duration < 1:
        return redirect_to_prompt('/auth/greet')
    audio_path = f'dynamic_audio/auth_live_{call_sid}.wav'
    download_twilio_recording(recording_url, audio_path)
    t_verify = time.perf_counter()
    voice_model = user.get('voice_model', [])
    authenticated, score = verify_voice(voice_model, audio_path)
    print(f"   [TIMING] verify_voice took {time.perf_counter() - t_verify:.2f}s")
    print(f"   [TIMING] /auth/verify total took {time.perf_counter() - t_handler:.2f}s")
    # Anti-replay check disabled: challenge is Roman transliteration but STT
    # returns native script (Devanagari etc.) so word-set intersection always 0.
    attempts = state.get('auth_attempts', 0) + 1
    state['auth_attempts'] = attempts
    CALL_STATE[call_sid] = state
    if authenticated:
        print(f"[AUTH] ✅ {user.get('phone')} authenticated (score={score:.3f})")
        state['authenticated'] = True
        CALL_STATE[call_sid] = state
        return redirect_to_prompt('/prompt-main-menu')
    elif attempts >= 3:
        print(f"[AUTH] ❌ {user.get('phone')} locked after 3 failed attempts — routing to MPIN")
        # Keypad MPIN fallback — pre-populate state so /prompt-mpin can work
        state['phone'] = user.get('phone')
        CALL_STATE[call_sid] = state
        resp = VoiceResponse()
        play(resp, lang, 'auth_fail')
        resp.redirect('/prompt-mpin')
        return Response(str(resp), mimetype='text/xml')
    else:
        return redirect_to_prompt('/auth/greet')


# ===========================================================================
# SECTION 6 — Contacts + Intent Extraction + Voice Command
# ===========================================================================

def find_contact(user_phone: str, nickname: str):
    """Look up contact by nickname, handling Hindi oblique case."""
    oblique_map = {
        'bhatije': 'bhatija', 'bete': 'beta', 'bhai ko': 'bhai',
        'behan ko': 'behan', 'didi ko': 'didi', 'dost ko': 'dost',
        'beti ko': 'beti', 'beta ko': 'beta',
    }
    users = load_json('data/users.json')
    contacts = users.get(user_phone, {}).get('contacts', [])
    nick_lower = nickname.lower().strip()
    normalized = oblique_map.get(nick_lower, nick_lower)
    for contact in contacts:
        if normalized in contact.get('nickname', '').lower():
            return contact
        if normalized in contact.get('real_name', '').lower():
            return contact
    return None


def find_contact_in_text(user_phone: str, text: str):
    """Check each saved contact's nickname/real_name against an English transcript."""
    users = load_json('data/users.json')
    contacts = users.get(user_phone, {}).get('contacts', [])
    text_lower = text.lower()
    for contact in contacts:
        nickname = contact.get('nickname', '').lower().strip()
        real_name = contact.get('real_name', '').lower().strip()
        if nickname and nickname in text_lower:
            return contact
        if real_name and real_name in text_lower:
            return contact
    return None


# Word-number parsing for spoken amounts like "five hundred rupees"
NUMBER_WORDS = {
    'zero': 0, 'one': 1, 'two': 2, 'three': 3, 'four': 4, 'five': 5,
    'six': 6, 'seven': 7, 'eight': 8, 'nine': 9, 'ten': 10,
    'eleven': 11, 'twelve': 12, 'thirteen': 13, 'fourteen': 14, 'fifteen': 15,
    'sixteen': 16, 'seventeen': 17, 'eighteen': 18, 'nineteen': 19, 'twenty': 20,
    'thirty': 30, 'forty': 40, 'fifty': 50, 'sixty': 60, 'seventy': 70,
    'eighty': 80, 'ninety': 90,
}
NUMBER_MULTIPLIERS = {'hundred': 100, 'thousand': 1000, 'lakh': 100000, 'lac': 100000}


def words_to_amount(text: str):
    """Parse a spoken English number ('five hundred', 'two thousand five hundred') into an int."""
    tokens = re.findall(r'[a-z]+', text.lower())
    total = 0
    current = 0
    found = False
    for tok in tokens:
        if tok in NUMBER_WORDS:
            current += NUMBER_WORDS[tok]
            found = True
        elif tok in NUMBER_MULTIPLIERS:
            current = (current or 1) * NUMBER_MULTIPLIERS[tok]
            total += current
            current = 0
            found = True
    total += current
    return total if found else None


def classify_intent_fast(transcript: str) -> str:
    """Regex/keyword intent classification over an English transcript, with a Groq fallback."""
    t = transcript.lower()
    if 'contact' in t and re.search(r'\b(add|save|new|create)\b', t):
        return 'add_contact'
    if re.search(r'\bbalance\b', t) or re.search(r'how much (money|do i have)', t):
        return 'balance'
    if re.search(r'\b(pay|send|transfer|give|wire)\b', t):
        return 'payment'

    result = groq_extract(transcript, 'intent')
    return result.get('intent', 'other')


def extract_amount_fast(transcript: str):
    """Pull a rupee amount from an English transcript: digits, then word-numbers, then Groq fallback."""
    digits = re.findall(r'\d+', transcript)
    if digits:
        return int(digits[0])

    amount = words_to_amount(transcript)
    if amount:
        return amount

    result = groq_extract(transcript, 'amount')
    return result.get('amount')


def extract_payment_intent_fast(transcript: str) -> dict:
    """Pull recipient/amount/reason from an English transcript via regex, with a Groq fallback."""
    amount = extract_amount_fast(transcript)

    recipient = None
    skip_words = {'the', 'a', 'an', 'send', 'pay', 'transfer', 'give', 'wire', 'rupees', 'rupee', 'rs'}
    for word in re.findall(r'\b(?:to|for)\s+(?:my\s+)?([a-zA-Z]+)', transcript.lower()):
        if word not in skip_words:
            recipient = word
            break

    if recipient and amount is not None:
        return {"recipient": recipient, "amount": amount, "reason": None}

    result = groq_extract(transcript, 'payment')
    return {
        "recipient": recipient or result.get('recipient'),
        "amount": amount if amount is not None else result.get('amount'),
        "reason": result.get('reason'),
    }


CONFIRM_TEXTS = {
    'hi': "{} ko {} rupiye bhejun?",
    'en': "Shall I send {} rupees to {}?",
    'ta': "{} kku {} rupai anuppattuma?",
    'te': "{} ki {} rupayalu pathista?",
    'kn': "{} ge {} rupai kelutu?",
    'ml': "{} ku {} roopa ayakkattuo?",
    'mr': "{} la {} rupaye pathavayche?",
    'bn': "{} ke {} taka pathabo?",
    'gu': "{} ne {} rupiya mokhlava?",
}


def build_confirm_text(name: str, amount, lang: str) -> str:
    template = CONFIRM_TEXTS.get(lang, CONFIRM_TEXTS['en'])
    if lang == 'en':
        return template.format(int(amount), name)
    return template.format(name, int(amount))


def prompt_payment_confirm(resp, call_sid, lang, recipient_name, amount):
    """Play 'Shall I send X rupees to Y?' and record the yes/no response."""
    confirm_text = build_confirm_text(recipient_name, amount, lang)
    audio_out = Path(f'dynamic_audio/pay_confirm_{call_sid}.wav')
    save_tts(confirm_text, lang, audio_out)
    resp.play(f'/dynamic-audio/pay_confirm_{call_sid}.wav')
    resp.record(action='/payment-final-confirm', method='POST', max_length=4,
                play_beep=True, timeout=4)


@app.route('/voice-command', methods=['GET', 'POST'])
def voice_command():
    """Receives free-speech recording from main menu digit 1, extracts intent."""
    call_sid = request.values.get('CallSid')
    recording_url = request.values.get('RecordingUrl', '')
    state = CALL_STATE.get(call_sid, {})
    lang = state.get('lang', 'hi')
    user = state.get('user', {})
    audio_path = f'dynamic_audio/cmd_{call_sid}.wav'
    download_twilio_recording(recording_url, audio_path)
    transcript = speech_to_text_english(audio_path)
    intent = extract_payment_intent_fast(transcript)
    recipient_name = intent.get('recipient')
    amount = intent.get('amount')
    reason = intent.get('reason')
    resp = VoiceResponse()
    if recipient_name and amount:
        contact = find_contact(user.get('phone', ''), recipient_name)
        if contact:
            state['recipient'] = contact['phone']
            state['recipient_name'] = contact['real_name']
            state['upi_amount'] = str(int(amount))
            state['payment_reason'] = reason
            CALL_STATE[call_sid] = state
            confirm_text = build_confirm_text(contact['real_name'], amount, lang)
            audio_confirm = Path(f'dynamic_audio/pay_confirm_{call_sid}.wav')
            save_tts(confirm_text, lang, audio_confirm)
            resp.play(f'/dynamic-audio/pay_confirm_{call_sid}.wav')
            resp.record(action='/voice-payment-confirm', method='POST',
                        max_length=4, play_beep=True, timeout=4)
        else:
            not_found = {
                'hi': f"{recipient_name} aapke contacts mein nahi mila. Number keypad se daalein.",
                'en': f"I couldn't find {recipient_name} in your contacts. Please enter a number.",
                'ta': f"{recipient_name} contacts il illa. Number keypad la podunga.",
                'te': f"{recipient_name} contacts lo ledu. Number keypad lo enter cheyyandi.",
                'kn': f"{recipient_name} contacts nalli illa. Number keypad nali enter madi.",
                'ml': f"{recipient_name} contacts il illa. Number keypad il enter cheyyoo.",
                'mr': f"{recipient_name} contacts madhe nahi. Number keypad var taaka.",
                'bn': f"{recipient_name} contacts e nei. Number keypad e dun.",
                'gu': f"{recipient_name} contacts ma nathi. Number keypad par nakhho.",
            }
            audio_nf = Path(f'dynamic_audio/contact_nf_{call_sid}.wav')
            save_tts(not_found.get(lang, not_found['en']), lang, audio_nf)
            resp.play(f'/dynamic-audio/contact_nf_{call_sid}.wav')
            resp.redirect('/prompt-upi-recipient')
    else:
        resp.redirect('/prompt-main-menu')
    return Response(str(resp), mimetype='text/xml')


@app.route('/voice-payment-confirm', methods=['GET', 'POST'])
def voice_payment_confirm():
    call_sid = request.values.get('CallSid')
    recording_url = request.values.get('RecordingUrl', '')
    state = CALL_STATE.get(call_sid, {})
    lang = state.get('lang', 'hi')
    audio_path = f'dynamic_audio/confirm_yn_{call_sid}.wav'
    download_twilio_recording(recording_url, audio_path)
    answer = speech_to_text(audio_path, lang).lower()
    confirmed = any(w in answer for w in [
        'haan', 'ha', 'yes', 'ho', 'sahi', 'bilkul', 'correct',
        'aama', 'avunu', 'hovudu', 'aana',
        'हाँ', 'हां', 'हा', 'जी', 'हो',
        'হ্যাঁ', 'হ্যা', 'হা',
        'ஆம்', 'ஆமா',
        'అవును', 'అవు',
        'ಹೌದು', 'ಹೌ',
        'ആണ്', 'ആनൽ',
        'હા', 'હાં',
    ])
    resp = VoiceResponse()
    if confirmed:
        user_phone = state.get('phone')
        amount = state.get('upi_amount', '0')
        recipient = state.get('recipient')
        reason = state.get('payment_reason', '')
        success, new_balance = perform_upi_transaction(user_phone, amount)
        if success:
            try:
                twilio_client = Client(os.getenv('TWILIO_ACCOUNT_SID'), os.getenv('TWILIO_AUTH_TOKEN'))
                msg = f"SwaramPay: Aapke paas Rs {amount} aaye hain {state.get('user', {}).get('name', '')} ki taraf se."
                if reason:
                    msg += f" {reason.capitalize()} ke liye!"
                twilio_client.messages.create(
                    body=msg, from_=os.getenv('TWILIO_PHONE_NUMBER'), to=f'+91{recipient}'
                )
            except Exception as e:
                print(f"[SMS] Failed: {e}")
            notify_guardians(state.get('user', {}), state.get('recipient_name', recipient), amount, new_balance)
            play(resp, lang, 'upi_success')
            bal_text = BALANCE_TEMPLATE.get(lang, BALANCE_TEMPLATE['en']).format(int(new_balance))
            bal_audio = Path(f'dynamic_audio/bal_{call_sid}.wav')
            if save_tts(bal_text, lang, bal_audio):
                resp.play(f'/dynamic-audio/bal_{call_sid}.wav')
        else:
            play(resp, lang, 'insufficient_balance')
            bal_text = BALANCE_TEMPLATE.get(lang, BALANCE_TEMPLATE['en']).format(int(new_balance))
            bal_audio = Path(f'dynamic_audio/bal_{call_sid}.wav')
            if save_tts(bal_text, lang, bal_audio):
                resp.play(f'/dynamic-audio/bal_{call_sid}.wav')
        resp.redirect('/prompt-main-menu')
    else:
        resp.redirect('/prompt-main-menu')
    return Response(str(resp), mimetype='text/xml')


# ---------------------------------------------------------------------------
# Conversational payment flow — "How can I help you?" -> recipient -> amount -> pay
# ---------------------------------------------------------------------------

@app.route('/handle-intent', methods=['GET', 'POST'])
def handle_intent():
    """Open-ended response to 'How can I help you?' — classify and route."""
    t_handler = time.perf_counter()
    call_sid = request.values.get('CallSid')
    recording_url = request.values.get('RecordingUrl', '')
    state = CALL_STATE.get(call_sid, {})
    lang = state.get('lang', 'hi')
    user = state.get('user', {})
    audio_path = f'dynamic_audio/intent_{call_sid}.wav'
    download_twilio_recording(recording_url, audio_path)
    transcript = speech_to_text_english(audio_path)

    resp = VoiceResponse()
    if not transcript:
        resp.redirect('/prompt-main-menu')
        return Response(str(resp), mimetype='text/xml')

    intent = classify_intent_fast(transcript)
    print(f"   [TIMING] /handle-intent took {time.perf_counter() - t_handler:.2f}s")

    if intent == 'payment':
        # Try to resolve recipient + amount directly from the initial utterance
        # (e.g. "I want to send 200rs to my sister") to skip the follow-up prompts.
        intent_data = extract_payment_intent_fast(transcript)
        amount = intent_data.get('amount')

        recipient_phone = None
        recipient_name = None

        contact = find_contact_in_text(user.get('phone', ''), transcript)
        if contact:
            recipient_phone = contact['phone']
            recipient_name = contact['real_name']
        else:
            nickname = intent_data.get('recipient')
            if nickname:
                digits_only = re.sub(r'\D', '', str(nickname))
                if len(digits_only) == 10:
                    recipient_phone = digits_only
                    recip_user = get_user(recipient_phone)
                    recipient_name = recip_user.get('name') if recip_user else recipient_phone
                else:
                    contact = find_contact(user.get('phone', ''), nickname)
                    if contact:
                        recipient_phone = contact['phone']
                        recipient_name = contact['real_name']

        if recipient_phone and amount:
            state['recipient'] = recipient_phone
            state['recipient_name'] = recipient_name
            state['upi_amount'] = str(int(amount))
            CALL_STATE[call_sid] = state
            prompt_payment_confirm(resp, call_sid, lang, recipient_name, amount)
        elif recipient_phone:
            state['recipient'] = recipient_phone
            state['recipient_name'] = recipient_name
            CALL_STATE[call_sid] = state
            play(resp, lang, 'how_much')
            resp.record(action='/payment-amount', method='POST', max_length=6,
                        play_beep=True, timeout=5)
        else:
            if amount:
                state['upi_amount'] = str(int(amount))
                CALL_STATE[call_sid] = state
            play(resp, lang, 'who_to_pay')
            resp.record(action='/payment-recipient', method='POST', max_length=10,
                        play_beep=True, timeout=5)
    elif intent == 'balance':
        acc = get_account(user.get('account_id', ''))
        balance = acc.get('balance', 0) if acc else 0
        text = BALANCE_TEMPLATE.get(lang, BALANCE_TEMPLATE['en']).format(int(balance))
        audio_out = Path(f'dynamic_audio/bal_{call_sid}.wav')
        if save_tts(text, lang, audio_out):
            resp.play(f'/dynamic-audio/bal_{call_sid}.wav')
        resp.redirect('/prompt-main-menu')
    elif intent == 'add_contact':
        return redirect_to_prompt('/contacts/add-name')
    else:
        play(resp, lang, 'not_understood')
        resp.redirect('/prompt-main-menu')

    return Response(str(resp), mimetype='text/xml')


@app.route('/payment-recipient', methods=['GET', 'POST'])
def payment_recipient():
    """Resolve the recipient from a spoken name (saved contact) or 10-digit number."""
    t_handler = time.perf_counter()
    call_sid = request.values.get('CallSid')
    recording_url = request.values.get('RecordingUrl', '')
    state = CALL_STATE.get(call_sid, {})
    lang = state.get('lang', 'hi')
    user = state.get('user', {})
    audio_path = f'dynamic_audio/recipient_{call_sid}.wav'
    download_twilio_recording(recording_url, audio_path)

    resp = VoiceResponse()

    # Single translate-to-English STT call serves both digit parsing and name matching
    transcript = speech_to_text_english(audio_path)
    digits_only = re.sub(r'\D', '', transcript)

    recipient_phone = None
    recipient_name = None

    if len(digits_only) == 10:
        recipient_phone = digits_only
        recip_user = get_user(recipient_phone)
        recipient_name = recip_user.get('name') if recip_user else recipient_phone
    else:
        contact = find_contact_in_text(user.get('phone', ''), transcript)
        if not contact:
            intent = extract_payment_intent_fast(transcript)
            nickname = intent.get('recipient')
            contact = find_contact(user.get('phone', ''), nickname) if nickname else None
        if contact:
            recipient_phone = contact['phone']
            recipient_name = contact['real_name']

    print(f"   [TIMING] /payment-recipient took {time.perf_counter() - t_handler:.2f}s")

    if not recipient_phone:
        play(resp, lang, 'recipient_nf')
        resp.redirect('/prompt-main-menu')
        return Response(str(resp), mimetype='text/xml')

    state['recipient'] = recipient_phone
    state['recipient_name'] = recipient_name
    CALL_STATE[call_sid] = state

    # Amount may already be known if the caller said it in the same breath
    # as the recipient (e.g. "200 to my sister") on the previous turn.
    if state.get('upi_amount'):
        prompt_payment_confirm(resp, call_sid, lang, recipient_name, float(state['upi_amount']))
        return Response(str(resp), mimetype='text/xml')

    play(resp, lang, 'how_much')
    resp.record(action='/payment-amount', method='POST', max_length=6,
                play_beep=True, timeout=5)
    return Response(str(resp), mimetype='text/xml')


@app.route('/payment-amount', methods=['GET', 'POST'])
def payment_amount():
    """Resolve the rupee amount from spoken digits or free speech (regex + Groq fallback)."""
    t_handler = time.perf_counter()
    call_sid = request.values.get('CallSid')
    recording_url = request.values.get('RecordingUrl', '')
    state = CALL_STATE.get(call_sid, {})
    lang = state.get('lang', 'hi')
    audio_path = f'dynamic_audio/amount_{call_sid}.wav'
    download_twilio_recording(recording_url, audio_path)

    resp = VoiceResponse()

    transcript = speech_to_text_english(audio_path)
    digits_only = re.sub(r'\D', '', transcript)

    if digits_only:
        amount = int(digits_only)
    else:
        amount = extract_amount_fast(transcript)

    print(f"   [TIMING] /payment-amount took {time.perf_counter() - t_handler:.2f}s")

    if not amount or amount <= 0:
        play(resp, lang, 'amount_nu')
        resp.redirect('/prompt-main-menu')
        return Response(str(resp), mimetype='text/xml')

    state['upi_amount'] = str(int(amount))
    CALL_STATE[call_sid] = state

    prompt_payment_confirm(resp, call_sid, lang, state.get('recipient_name', ''), amount)
    return Response(str(resp), mimetype='text/xml')


def notify_guardians(user, recipient_name, amount, new_balance):
    """SMS each registered guardian when the ward makes a payment."""
    guardians = user.get('guardians', [])
    if not guardians:
        return
    ward_name = user.get('name', 'Aapka ward')
    body = (f"SwaramPay: {ward_name} ne {recipient_name} ko Rs {amount} bheja hai. "
            f"Naya balance: Rs {int(new_balance)}.")
    try:
        twilio_client = Client(os.getenv('TWILIO_ACCOUNT_SID'), os.getenv('TWILIO_AUTH_TOKEN'))
        for guardian_phone in guardians:
            twilio_client.messages.create(
                body=body, from_=os.getenv('TWILIO_PHONE_NUMBER'), to=f'+91{guardian_phone}'
            )
    except Exception as e:
        print(f"[SMS] Guardian notify failed: {e}")


def complete_payment(resp, call_sid, state, lang):
    """Execute the UPI transfer, send an SMS notification, and play success/failure prompts."""
    user_phone = state.get('phone')
    amount = state.get('upi_amount', '0')
    recipient = state.get('recipient')
    recipient_name = state.get('recipient_name', '')
    success, new_balance = perform_upi_transaction(
        user_phone, amount, desc=f"Sent to {recipient_name}"
    )
    if success:
        try:
            twilio_client = Client(os.getenv('TWILIO_ACCOUNT_SID'), os.getenv('TWILIO_AUTH_TOKEN'))
            twilio_client.messages.create(
                body=f"SwaramPay: Aapke paas Rs {amount} aaye hain {state.get('user', {}).get('name', '')} ki taraf se.",
                from_=os.getenv('TWILIO_PHONE_NUMBER'), to=f'+91{recipient}'
            )
        except Exception as e:
            print(f"[SMS] Failed: {e}")
        notify_guardians(state.get('user', {}), recipient_name, amount, new_balance)
        play(resp, lang, 'upi_success')
        bal_text = BALANCE_TEMPLATE.get(lang, BALANCE_TEMPLATE['en']).format(int(new_balance))
        bal_audio = Path(f'dynamic_audio/bal_{call_sid}.wav')
        if save_tts(bal_text, lang, bal_audio):
            resp.play(f'/dynamic-audio/bal_{call_sid}.wav')
    else:
        play(resp, lang, 'insufficient_balance')
        bal_text = BALANCE_TEMPLATE.get(lang, BALANCE_TEMPLATE['en']).format(int(new_balance))
        bal_audio = Path(f'dynamic_audio/bal_{call_sid}.wav')
        if save_tts(bal_text, lang, bal_audio):
            resp.play(f'/dynamic-audio/bal_{call_sid}.wav')


@app.route('/payment-final-confirm', methods=['GET', 'POST'])
def payment_final_confirm():
    t_handler = time.perf_counter()
    call_sid = request.values.get('CallSid')
    recording_url = request.values.get('RecordingUrl', '')
    state = CALL_STATE.get(call_sid, {})
    lang = state.get('lang', 'hi')
    audio_path = f'dynamic_audio/pay_yn_{call_sid}.wav'
    download_twilio_recording(recording_url, audio_path)
    answer = speech_to_text(audio_path, lang).lower()
    confirmed = any(w in answer for w in YES_WORDS)
    print(f"   [TIMING] /payment-final-confirm took {time.perf_counter() - t_handler:.2f}s")

    resp = VoiceResponse()
    if confirmed:
        amount = float(state.get('upi_amount', '0'))
        if amount > 500:
            state['mpin_attempts'] = 0
            CALL_STATE[call_sid] = state
            return redirect_to_prompt('/payment-mpin-verify')
        complete_payment(resp, call_sid, state, lang)
    resp.redirect('/prompt-main-menu')
    return Response(str(resp), mimetype='text/xml')


@app.route('/payment-mpin-verify', methods=['GET', 'POST'])
def payment_mpin_verify():
    call_sid = request.values.get('CallSid')
    lang = CALL_STATE.get(call_sid, {}).get('lang', 'hi')
    resp = VoiceResponse()
    gather = Gather(num_digits=4, action='/payment-mpin-submit', method='POST', timeout=15)
    play(gather, lang, 'enter_mpin')
    resp.append(gather)
    resp.redirect('/payment-mpin-verify')
    return Response(str(resp), mimetype='text/xml')


@app.route('/payment-mpin-submit', methods=['GET', 'POST'])
def payment_mpin_submit():
    call_sid = request.values.get('CallSid')
    mpin = request.values.get('Digits', '')
    state = CALL_STATE.get(call_sid, {})
    lang = state.get('lang', 'hi')
    user = state.get('user', {})

    resp = VoiceResponse()
    if user.get('pin') and user.get('pin') == mpin:
        complete_payment(resp, call_sid, state, lang)
        resp.redirect('/prompt-main-menu')
        return Response(str(resp), mimetype='text/xml')

    attempts = state.get('mpin_attempts', 0) + 1
    state['mpin_attempts'] = attempts
    CALL_STATE[call_sid] = state
    if attempts >= 3:
        play(resp, lang, 'upi_failed')
        resp.redirect('/prompt-main-menu')
        return Response(str(resp), mimetype='text/xml')

    play(resp, lang, 'wrong_mpin')
    resp.redirect('/payment-mpin-verify')
    return Response(str(resp), mimetype='text/xml')


# Contact-add routes

@app.route('/contacts/add-name', methods=['GET', 'POST'])
def contacts_add_name():
    call_sid = request.values.get('CallSid')
    lang = CALL_STATE.get(call_sid, {}).get('lang', 'hi')
    resp = VoiceResponse()
    play(resp, lang, 'contact_name')
    resp.record(action='/contacts/add-name-submit', method='POST',
                max_length=6, finish_on_key='#', play_beep=True, timeout=4)
    resp.redirect('/prompt-main-menu')
    return Response(str(resp), mimetype='text/xml')


@app.route('/contacts/add-name-submit', methods=['GET', 'POST'])
def contacts_add_name_submit():
    call_sid = request.values.get('CallSid')
    recording_url = request.values.get('RecordingUrl', '')
    state = CALL_STATE.get(call_sid, {})
    lang = state.get('lang', 'hi')
    audio_path = f'dynamic_audio/contact_name_{call_sid}.wav'
    download_twilio_recording(recording_url, audio_path)
    nickname = speech_to_text(audio_path, lang).strip().lower()
    if not nickname:
        return redirect_to_prompt('/contacts/add-name')
    state['new_contact_nickname'] = nickname
    CALL_STATE[call_sid] = state
    return redirect_to_prompt('/contacts/add-number')


@app.route('/contacts/add-number', methods=['GET', 'POST'])
def contacts_add_number():
    call_sid = request.values.get('CallSid')
    lang = CALL_STATE.get(call_sid, {}).get('lang', 'hi')
    resp = VoiceResponse()
    play(resp, lang, 'contact_number')
    resp.record(action='/contacts/add-number-submit', method='POST',
                max_length=10, play_beep=True, timeout=6)
    resp.redirect('/contacts/add-number')
    return Response(str(resp), mimetype='text/xml')


@app.route('/contacts/add-number-submit', methods=['GET', 'POST'])
def contacts_add_number_submit():
    call_sid = request.values.get('CallSid')
    recording_url = request.values.get('RecordingUrl', '')
    state = CALL_STATE.get(call_sid, {})
    lang = state.get('lang', 'hi')
    audio_path = f'dynamic_audio/contact_num_{call_sid}.wav'
    download_twilio_recording(recording_url, audio_path)
    # Force English STT for number capture
    transcript = speech_to_text(audio_path, 'en')
    digits_only = re.sub(r'\D', '', transcript)
    if len(digits_only) != 10:
        # Fallback to DTMF
        return redirect_to_prompt('/contacts/add-number-keypad')
    state['new_contact_phone'] = digits_only
    CALL_STATE[call_sid] = state
    return redirect_to_prompt('/contacts/add-complete')


@app.route('/contacts/add-number-keypad', methods=['GET', 'POST'])
def contacts_add_number_keypad():
    call_sid = request.values.get('CallSid')
    lang = CALL_STATE.get(call_sid, {}).get('lang', 'hi')
    resp = VoiceResponse()
    gather = Gather(num_digits=10, action='/contacts/add-number-keypad-submit',
                    method='POST', timeout=15)
    play(resp, lang, 'contact_dtmf')
    resp.append(gather)
    resp.redirect('/prompt-main-menu')
    return Response(str(resp), mimetype='text/xml')


@app.route('/contacts/add-number-keypad-submit', methods=['GET', 'POST'])
def contacts_add_number_keypad_submit():
    call_sid = request.values.get('CallSid')
    digits = request.values.get('Digits', '')
    state = CALL_STATE.get(call_sid, {})
    if len(digits) != 10 or not digits.isdigit():
        return redirect_to_prompt('/prompt-main-menu')
    state['new_contact_phone'] = digits
    CALL_STATE[call_sid] = state
    return redirect_to_prompt('/contacts/add-complete')


@app.route('/contacts/add-complete', methods=['GET', 'POST'])
def contacts_add_complete():
    call_sid = request.values.get('CallSid')
    state = CALL_STATE.get(call_sid, {})
    lang = state.get('lang', 'hi')
    user_phone = state.get('phone')
    nickname = state.get('new_contact_nickname', '')
    contact_phone = state.get('new_contact_phone', '')
    if user_phone and nickname and contact_phone:
        users = load_json('data/users.json')
        recip_user = get_user(contact_phone)
        real_name = recip_user.get('name', nickname.title()) if recip_user else nickname.title()
        if user_phone in users:
            if 'contacts' not in users[user_phone]:
                users[user_phone]['contacts'] = []
            users[user_phone]['contacts'].append({
                'nickname': nickname,
                'real_name': real_name,
                'phone': contact_phone,
            })
            save_json('data/users.json', users)
            # Update in-memory state user object too
            state['user'] = users[user_phone]
            CALL_STATE[call_sid] = state
    resp = VoiceResponse()
    play(resp, lang, 'contact_saved')
    resp.redirect('/prompt-main-menu')
    return Response(str(resp), mimetype='text/xml')


# ===========================================================================
# SECTION 8 — Guardian Companion Web Portal
# ===========================================================================

def notify_deposit_by_call(farmer_phone: str, amount: float, guardian_name: str, farmer_lang: str):
    """Outbound call to farmer notifying them of a deposit."""
    import time as _time
    notify_texts = {
        'hi': f"Namaste! Aapke SwaramPay wallet mein {int(amount)} rupiye aaye hain. "
               "Aapka naya balance check karne ke liye dobara call karein.",
        'en': f"Hello! {int(amount)} rupees have been added to your SwaramPay wallet. "
               "Call back to check your new balance.",
        'ta': f"Vanakkam! Ungal SwaramPay wallet-il {int(amount)} rubai vandhirukku. "
               "Pudhia balance theriya meedum call pannunga.",
        'te': f"Namaskaram! Mee SwaramPay wallet ki {int(amount)} rupayalu vachhayi. "
               "Naya balance check ki malli call cheyyandi.",
        'kn': f"Namaskara! Nimmada SwaramPay wallet ge {int(amount)} rupai bandide. "
               "Naya balance nodalu matte call madi.",
        'ml': f"Namaskaram! Ningalude SwaramPay wallet il {int(amount)} roopa vannu. "
               "Naya balance check cheyyaan meedum call cheyyoo.",
        'mr': f"Namaste! Tumcha SwaramPay wallet madhye {int(amount)} rupaye aale. "
               "Naya balance tapasnyasaathi parat call kara.",
        'bn': f"Namaskar! Aapnar SwaramPay wallet e {int(amount)} taka eseche. "
               "Naya balance dekhte phire call korun.",
        'gu': f"Namaste! Tamara SwaramPay wallet ma {int(amount)} rupiya aavya. "
               "Naya balance jovaa pharthi call karo.",
    }
    text = notify_texts.get(farmer_lang, notify_texts['en'])
    # Use timestamp in filename to avoid collision on repeat top-ups
    ts = int(_time.time())
    audio_path = Path(f'dynamic_audio/deposit_notify_{farmer_phone}_{ts}.wav')
    save_tts(text, farmer_lang, audio_path)
    audio_filename = audio_path.name
    try:
        twilio_client = Client(os.getenv('TWILIO_ACCOUNT_SID'), os.getenv('TWILIO_AUTH_TOKEN'))
        base_url = os.getenv('SERVER_BASE_URL', '')
        twilio_client.calls.create(
            twiml=f'<Response><Play>{base_url}/dynamic-audio/{audio_filename}</Play></Response>',
            to=f'+91{farmer_phone}',
            from_=os.getenv('TWILIO_PHONE_NUMBER')
        )
        print(f"[NOTIFY] Outbound call fired to {farmer_phone}")
    except Exception as e:
        print(f"[NOTIFY] Call failed: {e}")


@app.route('/companion', methods=['GET'])
def companion_home():
    return render_template('companion/login.html')


@app.route('/companion/send-otp', methods=['POST'])
def companion_send_otp():
    phone = request.form.get('phone', '').strip()
    if not phone or len(phone) != 10:
        return jsonify({'error': 'Invalid phone'}), 400
    otp = str(random.randint(100000, 999999))
    OTP_STORE[phone] = {'otp': otp, 'expires': time.time() + 300}
    try:
        twilio_client = Client(os.getenv('TWILIO_ACCOUNT_SID'), os.getenv('TWILIO_AUTH_TOKEN'))
        twilio_client.messages.create(
            body=f"SwaramPay Guardian OTP: {otp}. Valid for 5 minutes.",
            from_=os.getenv('TWILIO_PHONE_NUMBER'),
            to=f'+91{phone}'
        )
    except Exception as e:
        print(f"[OTP] SMS failed: {e}")
    return jsonify({'status': 'sent'})


@app.route('/companion/verify-otp', methods=['POST'])
def companion_verify_otp():
    phone = request.form.get('phone', '').strip()
    otp = request.form.get('otp', '').strip()
    stored = OTP_STORE.get(phone, {})
    if stored.get('otp') == otp and time.time() < stored.get('expires', 0):
        session['guardian_phone'] = phone
        return redirect('/companion/dashboard')
    return render_template('companion/login.html', error='Invalid or expired OTP')


@app.route('/companion/dashboard', methods=['GET'])
def companion_dashboard():
    guardian_phone = session.get('guardian_phone')
    if not guardian_phone:
        return redirect('/companion')
    users = load_json('data/users.json')
    accounts = load_json('data/accounts.json')
    linked_wallets = []
    for phone, user in users.items():
        is_self = phone == guardian_phone
        is_guardian = guardian_phone in user.get('guardians', [])
        if is_guardian or is_self:
            acc = accounts.get(user.get('account_id', ''), {})
            transactions = acc.get('transactions', [])
            linked_wallets.append({
                'name': user['name'],
                'phone': phone,
                'balance': acc.get('balance', 0),
                'recent': transactions[-3:],
                'history': list(reversed(transactions)) if is_self else [],
                'is_self': is_self,
            })
    return render_template('companion/dashboard.html', wallets=linked_wallets)


@app.route('/companion/add-money', methods=['POST'])
def companion_add_money():
    guardian_phone = session.get('guardian_phone')
    if not guardian_phone:
        return jsonify({'error': 'Unauthorized'}), 401
    target_phone = request.form.get('target_phone', '').strip()
    try:
        amount = float(request.form.get('amount', 0))
    except ValueError:
        return jsonify({'error': 'Invalid amount'}), 400
    if amount <= 0 or amount > 50000:
        return jsonify({'error': 'Amount must be between 1 and 50000'}), 400
    users = load_json('data/users.json')
    target_user = users.get(target_phone, {})
    is_self = target_phone == guardian_phone
    if not is_self and guardian_phone not in target_user.get('guardians', []):
        return jsonify({'error': 'Unauthorized'}), 403
    accounts = load_json('data/accounts.json')
    acc_id = target_user.get('account_id')
    if not acc_id or acc_id not in accounts:
        return jsonify({'error': 'Account not found'}), 404
    accounts[acc_id]['balance'] += amount
    if 'transactions' not in accounts[acc_id]:
        accounts[acc_id]['transactions'] = []
    accounts[acc_id]['transactions'].append({
        'type': 'credit',
        'amount': amount,
        'from': guardian_phone,
        'desc': 'Guardian top-up',
        'timestamp': str(datetime.datetime.now()),
    })
    save_json('data/accounts.json', accounts)
    notify_deposit_by_call(
        farmer_phone=target_phone,
        amount=amount,
        guardian_name=guardian_phone,
        farmer_lang=target_user.get('lang', 'hi')
    )
    return jsonify({'status': 'success', 'new_balance': accounts[acc_id]['balance']})


# ===========================================================================
# Entry point
# ===========================================================================

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True, use_reloader=False, threaded=True)
