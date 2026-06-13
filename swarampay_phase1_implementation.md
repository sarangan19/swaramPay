# SwaramPay — Phase 1 Implementation Plan

**Base Repo:** https://github.com/kisnaXD/acm-manipal-vaanipay — clone this, all existing routes and services are the starting point  
**Stack:** Flask · Twilio · Sarvam AI (STT + TTS + LLM) · Groq or OpenAI (Mentor LLM) · resemblyzer (voice biometrics) · plain JSON (mock DB)  
**Goal:** A fully demoable end-to-end voice-first financial assistant — onboarding, auth, wallet payments, contacts, and guardian companion web.

> Each section lists: what exists in the base code, what needs to be built, and the exact implementation tasks with code structure.

---

## What to Take Directly from the Repo — Do Not Regenerate

Clone the base repo and keep the following files and features exactly as they are (or with minor renames). Claude Code should not rewrite these from scratch.

### Files — keep wholesale

| File | What it gives you |
|---|---|
| `config.py` | `LANG_CONFIG` — digit-to-language mapping for all 9 languages. Use as-is. |
| `mock_db.py` | `get_user(phone)`, `get_account(acc_id)`, `load_json()`, `save_json()` — the entire JSON-based DB layer. Use as-is. |
| `services/financial_ops.py` | `perform_upi_transaction()` (deducts balance, writes transaction record) and `calculate_behavioral_score()`. Both mocked with JSON. Use as-is — no changes needed. |
| `services/ai_mentor.py` | `process_mentor_audio()` — full STT → Groq LLM → TTS pipeline with background threading. `speech_to_text()` and `save_tts()` helper functions used across the whole app. Keep this file — you'll import `speech_to_text` and `save_tts` everywhere. |
| `download_audios.py` | Pre-generation script for static audio files. Keep and extend (add new keys), don't replace. |
| `universal_language_menu.wav` | Already generated static audio. Copy directly — do not regenerate. |

### Routes in `app.py` — keep as-is

| Route | What it does |
|---|---|
| `/prompt-lang` + `/submit-lang` | Language selection via keypad (1 digit), stores lang in `CALL_STATE`. Already works. |
| `/prompt-main-menu` + `/submit-main-menu` | Main menu (digits 1–5+), routes to balance/UPI/mentor. Keep the digit routing logic. |
| `/prompt-upi-recipient` + `/submit-upi-recipient` | Keypad-based recipient entry. Keep as the fallback path. |
| `/prompt-upi-amount` + `/submit-upi-amount` | Amount entry. Keep as-is. |
| `/submit-upi-success` | Reads back confirmation and balance after payment. Keep as-is. |
| `/mentor/start`, `/mentor/listen`, `/mentor/process`, `/mentor/check-result`, `/mentor/respond` | Full AI mentor pipeline with background thread + polling. Keep entirely — only fix the `groq` import (see Section 7). |
| `/prompt-mpin` + `/submit-mpin` | Old keypad PIN auth. Keep in code but it will be superseded by voice auth for the primary flow. |

### Data files — extend, don't replace

| File | Action |
|---|---|
| `data/users.json` | Add `voice_model`, `contacts`, `guardians` fields to the user object schema. Existing fields stay. |
| `data/accounts.json` | No changes needed — `perform_upi_transaction()` already reads/writes it correctly. |

### Patterns — reuse everywhere

- **`CALL_STATE[call_sid]`** — the in-memory call state dict already in `app.py`. All new routes read/write to this same dict.
- **`redirect_to_prompt(path)`** — the helper already in `app.py` for returning a TwiML redirect. Use it in every new route.
- **`save_tts(text, lang, path)`** — from `ai_mentor.py`. Every new route that speaks to the user calls this.
- **`speech_to_text(audio_path, lang)`** — from `ai_mentor.py`. Every new route that records the user calls this.
- **`download_twilio_recording(url, path)`** — already in `app.py`. Use in every record-then-process route.
- **`BALANCE_TEMPLATE`** dict — already has balance strings in all 9 languages. Reuse for post-payment balance readback.

### What is genuinely new (build these)

Everything marked 🆕 in the sections below: registration route chain, voice biometrics enrollment + verification, contacts + intent extraction, guardian companion web portal, outbound notification call.

---

## ⚠️ CRITICAL — Voice Profile Is Your Security Foundation

> **A voice profile is not a "nice to have" feature. It is the PIN. Without it, the system has no authentication.**

In traditional digital banking, the UPI PIN is the single irreplaceable security primitive — no PIN, no transaction. In SwaramPay, which operates entirely over voice for people who cannot use a smartphone, **the voice profile is the equivalent of that PIN.**

- Every returning caller is challenged with a random phrase and verified against their stored voice model before any action is allowed.
- Every payment authorization requires a second voice verification at transaction time, exactly like entering a PIN at a POS.
- Without a voice profile on file, there is no way to distinguish the real user from anyone else who calls from that number.

**Implementation consequences:**
1. Voice enrollment (Section 2.3) MUST complete successfully before the user reaches the main menu. It cannot be skipped or made optional. If enrollment fails midway, restart it.
2. The build order table puts voice enrollment at priority 2 — it blocks everything else downstream.
3. The similarity threshold (0.72 cosine similarity) should be treated like a PIN policy — do not lower it without reason.
4. Voice verification fires twice per payment: once at login (`/auth/verify`) and once at payment confirmation (`/voice-payment-confirm`). This is intentional — same as how a PIN is required even after you're already "logged in" to your bank app for high-value actions.

**For the demo: lead with this.** When the judges ask "but how is it secure?", the answer is: "The voice profile is the PIN. The user speaks, we verify, and only then execute. There is no keyboard, no app, no OTP the farmer needs to manage."

---

## LLM Architecture — Which Model Does What

This is important. STT and intent extraction are two separate pipeline steps — Sarvam handles the first, an LLM handles the second. They are never the same call.

```
Sarvam STT (Saaras) → transcript text → LLM → structured output or response
```

The split across tasks:

| Task | Model | Reason |
|---|---|---|
| Speech → Text | Sarvam Saaras | Purpose-built for Indian languages, best accuracy |
| Intent extraction (payments, contacts) | Sarvam-2 (30B) | Trained on Indian languages, understands "bhatije ko paisa bhej do" better than English-trained models. Simple JSON task — no need for a large external model. |
| AI Financial Mentor responses | Groq llama-3.1-8b-instant OR OpenAI | Longer conversational output, speed matters. Use whichever you have credits for — Groq is faster and free tier is generous, OpenAI gives higher quality. |
| Text → Speech | Sarvam Bulbul | Purpose-built for Indian languages, all 9 supported |

**Why Sarvam-2 for intent extraction specifically:**  
Pulling `{"recipient": "bhatija", "amount": 400}` from "mere bhatije ko chaar sau rupiye bhej do" requires understanding Hindi/Tamil/Telugu relationship terms and number words natively. Sarvam-2 is trained on this. A general English LLM (LLaMA, GPT) can do it but will occasionally miss regional nuances. Keep Groq/OpenAI for the mentor where longer, richer responses are needed.

**In code — two separate clients:**

```python
from sarvamai import SarvamAI
from groq import Groq  # or: from openai import OpenAI

sarvam_client = SarvamAI(api_subscription_key=os.getenv('SARVAM_API_KEY'))
mentor_llm = Groq(api_key=os.getenv('GROQ_API_KEY'))  # swap for OpenAI if preferred

def extract_payment_intent(transcript):
    """Uses Sarvam-2 — better for Indian language understanding."""
    response = sarvam_client.chat.completions.create(
        model="sarvam-2",  # or current model name from docs
        messages=[
            {"role": "system", "content": INTENT_SYSTEM_PROMPT},
            {"role": "user", "content": transcript}
        ],
        temperature=0,
        max_tokens=80
    )
    return json.loads(response.choices[0].message.content.strip())

def generate_mentor_response(transcript, lang, user_context):
    """Uses Groq/OpenAI — faster/richer for conversational responses."""
    response = mentor_llm.chat.completions.create(
        model="llama-3.1-8b-instant",
        messages=[
            {"role": "system", "content": build_mentor_prompt(lang, user_context)},
            {"role": "user", "content": transcript}
        ],
        temperature=0.7,
        max_tokens=200
    )
    return response.choices[0].message.content.strip()
```

---

## How to Read This Plan

- ✅ Already exists in the base code — use as-is or minor tweak
- 🔧 Exists but needs modification
- 🆕 New — build from scratch

---

## Section 1 — New vs Returning Caller Detection

### What exists
✅ `app.py` has a `handle_incoming()` route at `/` that creates a blank `CALL_STATE[call_sid]` and redirects to `/prompt-lang`.  
✅ `mock_db.py` has `get_user(phone)` which returns `None` if user doesn't exist.

### What needs to change
🔧 `handle_incoming()` needs to read the caller's phone number from the `From` field Twilio sends, check if they exist, and branch:
- New user → `/register/language`
- Returning user → `/auth/voice-challenge`

### Implementation

```python
@app.route('/', methods=['GET', 'POST'])
def handle_incoming():
    call_sid = request.values.get('CallSid')
    # Twilio sends caller number as 'From', e.g. +919876543210
    raw_from = request.values.get('From', '')
    caller_phone = raw_from.replace('+91', '').replace('+', '').strip()

    user = get_user(caller_phone)

    if not user:
        # Brand new caller — go to registration
        CALL_STATE[call_sid] = {'phone': caller_phone}
        return redirect_to_prompt('/register/language')
    else:
        # Returning caller — skip registration, go to voice auth
        CALL_STATE[call_sid] = {
            'phone': caller_phone,
            'lang': user.get('lang', 'hi'),
            'user': user
        }
        return redirect_to_prompt('/auth/greet')
```

---

## Section 2 — Onboarding (New Callers)

### 2.1 Language Selection (Keypad)

### What exists
✅ `/prompt-lang` route — plays `universal_language_menu.wav`, collects 1 digit  
✅ `/submit-lang` route — validates digit, stores lang in CALL_STATE  
✅ `config.py` — LANG_CONFIG maps "1"→"hi", "2"→"en", etc.  
✅ `universal_language_menu.wav` — already generated

### What needs to change
🔧 Create new registration-specific language route so it doesn't conflict with returning user flow. Functionally identical, just different redirect target after.

```python
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
```

---

### 2.2 Name Collection (STT)

### What exists
✅ Sarvam STT already wired in `services/ai_mentor.py` — `speech_to_text()` function  
✅ Twilio `record()` verb used in mentor mode

### What needs to build
🆕 `/register/name` — play "Apna naam boliye", record, STT, store name

```python
NAME_PROMPTS = {
    'hi': 'Apna naam boliye.',
    'en': 'Please say your full name.',
    'ta': 'Ungal peyar sollunga.',
    'te': 'Meeru peru cheppandi.',
    'kn': 'Nimma hesaru heli.',
    'ml': 'Ningalude peru parayan.',
    'mr': 'Tumcha naav sanga.',
    'bn': 'Aapnar naam bolun.',
    'gu': 'Tamarun naam bolo.'
}

@app.route('/register/name', methods=['GET', 'POST'])
def register_name():
    call_sid = request.values.get('CallSid')
    lang = CALL_STATE[call_sid].get('lang', 'hi')

    prompt_text = NAME_PROMPTS[lang]
    audio_path = Path(f'dynamic_audio/reg_name_prompt_{call_sid}.wav')
    save_tts(prompt_text, lang, audio_path)

    resp = VoiceResponse()
    resp.play(f'/dynamic-audio/reg_name_prompt_{call_sid}.wav')
    resp.record(
        action='/register/name-submit',
        method='POST',
        max_length=6,
        finish_on_key='#',
        play_beep=True,
        timeout=4
    )
    resp.redirect('/register/name')  # loop if no input
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
        return redirect_to_prompt('/register/name')  # retry

    state['name'] = name.strip().title()
    CALL_STATE[call_sid] = state
    return redirect_to_prompt('/register/voice-enroll-intro')
```

---

### 2.3 Voice Biometrics Enrollment ⚠️ MUST NOT BE SKIPPED

> **This is where the user's "voice PIN" is created. If this step is incomplete, the user cannot log in or authorize any payment on any future call. Treat enrollment failure as a hard blocker — retry until 3 valid samples are captured.**

### What exists
❌ Nothing — entirely new

### Dependencies to install
```
pip install resemblyzer numpy
```

### Phrase bank (add to config.py)

```python
ENROLLMENT_PHRASES = {
    'hi': [
        "aaj mausam bahut accha hai",
        "mera ghar gaon mein hai",
        "mujhe chai bahut pasand hai",
        "kal main bazaar jaunga",
        "mere paas ek achha kaam hai"
    ],
    'en': [
        "the weather is nice today",
        "my home is in the village",
        "I enjoy drinking tea",
        "tomorrow I will go to the market",
        "I have a good job near here"
    ],
    'ta': [
        "indru vaanam azhagaaga irukku",
        "en veedu ooril irukku",
        "enakku tea romba pidikkum",
        "naalaiku kadaikku poven",
        "enakku nalla velai irukku"
    ],
    # ... add for te, kn, ml, mr, bn, gu using similar patterns
}
```

### Why challenge-response phrases and not free speech
The system picks 3 random phrases from the bank and asks the user to repeat them. This serves two purposes:
1. **Enrollment quality:** Known phrases produce consistent embeddings across sessions — better than random free speech.
2. **Replay attack prevention:** On verification calls, a different random phrase is chosen each time. A recording of the user saying "aaj mausam bahut accha hai" will not pass verification if today's challenge is "mere paas ek achha kaam hai."

### Enrollment flow

```python
import random
from resemblyzer import VoiceEncoder, preprocess_wav
import numpy as np

voice_encoder = VoiceEncoder()  # load once at module level — expensive, do not re-instantiate per call

@app.route('/register/voice-enroll-intro', methods=['GET', 'POST'])
def voice_enroll_intro():
    call_sid = request.values.get('CallSid')
    state = CALL_STATE[call_sid]
    lang = state.get('lang', 'hi')

    # Pick 3 random phrases for this session
    phrases = random.sample(ENROLLMENT_PHRASES.get(lang, ENROLLMENT_PHRASES['hi']), 3)
    state['enroll_phrases'] = phrases
    state['enroll_index'] = 0
    state['enroll_recordings'] = []
    CALL_STATE[call_sid] = state

    intro = {
        'hi': f"Namaste {state['name']} ji. Ab main aapki awaaz pahchan ke liye kuch waakyaansh bolunga. Unhe sunkar dohraaiye. Yeh aapka voice PIN hai.",
        'en': f"Welcome {state['name']}. I will say a few phrases. Please repeat each one — this creates your voice identity for secure payments.",
        'ta': f"Vanakkam {state['name']}. Naan சில வாக்கியங்களை சொல்வேன். Repeating them creates your voice profile.",
        # ... other languages
    }
    audio_path = Path(f'dynamic_audio/enroll_intro_{call_sid}.wav')
    save_tts(intro.get(lang, intro['en']), lang, audio_path)

    resp = VoiceResponse()
    resp.play(f'/dynamic-audio/enroll_intro_{call_sid}.wav')
    resp.redirect('/register/voice-enroll-phrase')
    return Response(str(resp), mimetype='text/xml')


@app.route('/register/voice-enroll-phrase', methods=['GET', 'POST'])
def voice_enroll_phrase():
    call_sid = request.values.get('CallSid')
    state = CALL_STATE[call_sid]
    lang = state.get('lang', 'hi')
    index = state.get('enroll_index', 0)
    phrases = state.get('enroll_phrases', [])

    if index >= len(phrases):
        return redirect_to_prompt('/register/build-voice-model')

    phrase = phrases[index]
    audio_path = Path(f'dynamic_audio/enroll_phrase_{call_sid}_{index}.wav')
    save_tts(phrase, lang, audio_path)

    resp = VoiceResponse()
    resp.play(f'/dynamic-audio/enroll_phrase_{call_sid}_{index}.wav')
    resp.record(
        action=f'/register/voice-enroll-record?index={index}',
        method='POST',
        max_length=8,
        play_beep=True,
        timeout=3
    )
    return Response(str(resp), mimetype='text/xml')


@app.route('/register/voice-enroll-record', methods=['GET', 'POST'])
def voice_enroll_record():
    call_sid = request.values.get('CallSid')
    index = int(request.args.get('index', 0))
    recording_url = request.values.get('RecordingUrl', '')
    duration = int(request.values.get('RecordingDuration', 0))

    state = CALL_STATE[call_sid]

    if duration < 1:
        # Too short — repeat the same phrase
        return redirect_to_prompt('/register/voice-enroll-phrase')

    audio_path = f'dynamic_audio/enroll_sample_{call_sid}_{index}.wav'
    download_twilio_recording(recording_url, audio_path)

    state['enroll_recordings'].append(audio_path)
    state['enroll_index'] = index + 1
    CALL_STATE[call_sid] = state

    return redirect_to_prompt('/register/voice-enroll-phrase')


@app.route('/register/build-voice-model', methods=['GET', 'POST'])
def build_voice_model():
    call_sid = request.values.get('CallSid')
    state = CALL_STATE[call_sid]

    recordings = state.get('enroll_recordings', [])
    embeddings = []

    for path in recordings:
        try:
            wav = preprocess_wav(path)
            embedding = voice_encoder.embed_utterance(wav)
            embeddings.append(embedding)
        except Exception as e:
            print(f"[ENROLL] Failed to process {path}: {e}")

    if len(embeddings) < 2:
        # Not enough clean samples — restart enrollment, do not proceed
        # This is intentional: we do not let the user skip voice enrollment
        state['enroll_index'] = 0
        state['enroll_recordings'] = []
        CALL_STATE[call_sid] = state
        return redirect_to_prompt('/register/voice-enroll-intro')

    # Average embeddings → voice model stored as list (JSON-serializable)
    voice_model = np.mean(embeddings, axis=0).tolist()
    state['voice_model'] = voice_model
    CALL_STATE[call_sid] = state

    return redirect_to_prompt('/register/guardian-prompt')
```

---

### 2.4 Guardian Setup (Optional)

### What exists
❌ Nothing — new

### Flow

```python
GUARDIAN_PROMPTS = {
    'hi': "Aapko ek SMS bheja gaya hai jisme companion portal ka link hai. Agar aap kisi guardian ko apne wallet mein paise daalne ki anumati dena chahte hain, toh unka 10 ank ka number abhi boliye. Nahi chahte toh chup rahiye.",
    'en': "We have sent you an SMS with the companion portal link. If you would like to add a guardian who can add money to your wallet, please say their 10-digit number now. Otherwise stay silent.",
    # ... other languages
}

GUARDIAN_CONFIRM_PROMPTS = {
    'hi': "Kya aapne yeh number bola hai: {}? Haan ke liye haan boliye, nahi ke liye nahi.",
    'en': "Did you say the number: {}? Say yes to confirm or no to retry.",
}

@app.route('/register/guardian-prompt', methods=['GET', 'POST'])
def register_guardian_prompt():
    call_sid = request.values.get('CallSid')
    state = CALL_STATE[call_sid]
    lang = state.get('lang', 'hi')
    phone = state.get('phone')

    # Fire SMS to user's own number with companion portal link
    try:
        twilio_client = Client(os.getenv('TWILIO_ACCOUNT_SID'), os.getenv('TWILIO_AUTH_TOKEN'))
        twilio_client.messages.create(
            body=f"SwaramPay: Aapka wallet tayaar hai! Companion portal: {os.getenv('SERVER_BASE_URL')}/companion",
            from_=os.getenv('TWILIO_PHONE_NUMBER'),
            to=f'+91{phone}'
        )
    except Exception as e:
        print(f"[SMS] Failed to send portal link: {e}")

    prompt_text = GUARDIAN_PROMPTS.get(lang, GUARDIAN_PROMPTS['en'])
    audio_path = Path(f'dynamic_audio/guardian_prompt_{call_sid}.wav')
    save_tts(prompt_text, lang, audio_path)

    resp = VoiceResponse()
    resp.play(f'/dynamic-audio/guardian_prompt_{call_sid}.wav')
    resp.record(
        action='/register/guardian-number-submit',
        method='POST',
        max_length=10,
        play_beep=False,
        timeout=6
    )
    # Silence → skip guardian, go to completion
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
    transcript = speech_to_text(audio_path, lang)

    import re
    digits_only = re.sub(r'\D', '', transcript)

    if len(digits_only) != 10:
        # Couldn't parse a valid number — skip guardian
        return redirect_to_prompt('/register/complete')

    state['pending_guardian'] = digits_only
    CALL_STATE[call_sid] = state

    # Read back for confirmation — digit by digit
    spaced = ' '.join(list(digits_only))
    confirm_text = GUARDIAN_CONFIRM_PROMPTS.get(lang, GUARDIAN_CONFIRM_PROMPTS['en']).format(spaced)
    audio_path = Path(f'dynamic_audio/guardian_confirm_{call_sid}.wav')
    save_tts(confirm_text, lang, audio_path)

    resp = VoiceResponse()
    resp.play(f'/dynamic-audio/guardian_confirm_{call_sid}.wav')
    resp.record(
        action='/register/guardian-confirm-submit',
        method='POST',
        max_length=4,
        play_beep=True,
        timeout=4
    )
    return Response(str(resp), mimetype='text/xml')


@app.route('/register/guardian-confirm-submit', methods=['GET', 'POST'])
def register_guardian_confirm_submit():
    call_sid = request.values.get('CallSid')
    recording_url = request.values.get('RecordingUrl', '')
    state = CALL_STATE[call_sid]
    lang = state.get('lang', 'hi')

    audio_path = f'dynamic_audio/guardian_yn_{call_sid}.wav'
    download_twilio_recording(recording_url, audio_path)
    answer = speech_to_text(audio_path, lang).lower().strip()

    confirmed = any(w in answer for w in ['haan', 'ha', 'yes', 'ho', 'sahi', 'correct', 'theek'])

    if confirmed:
        guardian_phone = state.get('pending_guardian')
        state['guardians'] = [guardian_phone]
        CALL_STATE[call_sid] = state

        # SMS to guardian
        try:
            twilio_client = Client(os.getenv('TWILIO_ACCOUNT_SID'), os.getenv('TWILIO_AUTH_TOKEN'))
            twilio_client.messages.create(
                body=f"{state['name']} ne aapko SwaramPay guardian banaya hai. Login karein: {os.getenv('SERVER_BASE_URL')}/companion",
                from_=os.getenv('TWILIO_PHONE_NUMBER'),
                to=f'+91{guardian_phone}'
            )
            print(f"[SMS] Guardian invite sent to {guardian_phone}")
        except Exception as e:
            print(f"[SMS] Guardian SMS failed: {e}")
    else:
        state['guardians'] = []
        CALL_STATE[call_sid] = state

    return redirect_to_prompt('/register/complete')
```

---

### 2.5 Write to DB + Completion

```python
@app.route('/register/complete', methods=['GET', 'POST'])
def register_complete():
    call_sid = request.values.get('CallSid')
    state = CALL_STATE[call_sid]
    lang = state.get('lang', 'hi')
    phone = state.get('phone')
    name = state.get('name', 'User')

    # Write new user
    users = load_json('data/users.json')
    accounts = load_json('data/accounts.json')

    acc_id = f"acc_{phone}"
    users[phone] = {
        'name': name,
        'phone': phone,
        'lang': lang,
        'voice_model': state.get('voice_model', []),  # the "voice PIN"
        'account_id': acc_id,
        'guardians': state.get('guardians', []),
        'contacts': [],
        'registered_on': str(datetime.date.today())
    }
    accounts[acc_id] = {
        'balance': 0,
        'transactions': []
    }
    save_json('data/users.json', users)
    save_json('data/accounts.json', accounts)

    completion = {
        'hi': f"Badhaai ho {name} ji! Aapka SwaramPay wallet tayaar hai. Aapka balance abhi shunya rupaye hai.",
        'en': f"Congratulations {name}! Your SwaramPay wallet is ready. Your current balance is zero rupees.",
        'ta': f"Vanakkam {name}! Ungal SwaramPay wallet tayaar. Balance: poojaaram.",
        # ... other languages
    }
    audio_path = Path(f'dynamic_audio/reg_complete_{call_sid}.wav')
    save_tts(completion.get(lang, completion['en']), lang, audio_path)

    resp = VoiceResponse()
    resp.play(f'/dynamic-audio/reg_complete_{call_sid}.wav')
    resp.redirect('/prompt-main-menu')
    return Response(str(resp), mimetype='text/xml')
```

---

## Section 3 — Voice Authentication (Returning Callers)

### What exists
✅ `/prompt-mpin` + `/submit-mpin` — keypad PIN auth  
❌ Voice biometrics verification — new

> **Voice auth replaces the keypad PIN entirely. The stored voice model IS the PIN. A caller who cannot pass voice verification is denied access — same as entering the wrong PIN three times.**

### New auth flow

Returning callers are greeted by name, then given a random challenge phrase to repeat. The system compares their live voice embedding against the stored model using cosine similarity.

```python
from numpy import dot
from numpy.linalg import norm

VOICE_AUTH_THRESHOLD = 0.72  # cosine similarity — tune with real test data

def verify_voice(stored_model_list, audio_path):
    """
    Compare a live recording against the stored voice model.
    Returns (authenticated: bool, score: float).
    Treat the score like a PIN match — True/False, no partial credit.
    """
    try:
        stored = np.array(stored_model_list)
        wav = preprocess_wav(audio_path)
        live = voice_encoder.embed_utterance(wav)
        similarity = dot(stored, live) / (norm(stored) * norm(live))
        print(f"[VOICE AUTH] Similarity score: {similarity:.3f}")
        return similarity >= VOICE_AUTH_THRESHOLD, float(similarity)
    except Exception as e:
        print(f"[VOICE AUTH] Error: {e}")
        return False, 0.0


@app.route('/auth/greet', methods=['GET', 'POST'])
def auth_greet():
    call_sid = request.values.get('CallSid')
    state = CALL_STATE[call_sid]
    lang = state.get('lang', 'hi')
    name = state['user'].get('name', '')

    greet = {
        'hi': f"Namaste {name} ji! Apni awaaz se login karne ke liye neeche diya phrase dohraaiye.",
        'en': f"Welcome back {name}! Please repeat the following phrase to log in with your voice.",
    }

    # Pick a random challenge phrase — different every call (anti-replay)
    phrase = random.choice(ENROLLMENT_PHRASES.get(lang, ENROLLMENT_PHRASES['hi']))
    state['auth_phrase'] = phrase
    state['auth_attempts'] = 0
    CALL_STATE[call_sid] = state

    full_text = greet.get(lang, greet['en']) + ' ' + phrase
    audio_path = Path(f'dynamic_audio/auth_challenge_{call_sid}.wav')
    save_tts(full_text, lang, audio_path)

    resp = VoiceResponse()
    resp.play(f'/dynamic-audio/auth_challenge_{call_sid}.wav')
    resp.record(
        action='/auth/verify',
        method='POST',
        max_length=8,
        play_beep=True,
        timeout=4
    )
    resp.redirect('/auth/greet')
    return Response(str(resp), mimetype='text/xml')


@app.route('/auth/verify', methods=['GET', 'POST'])
def auth_verify():
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

    voice_model = user.get('voice_model', [])
    authenticated, score = verify_voice(voice_model, audio_path)

    attempts = state.get('auth_attempts', 0) + 1
    state['auth_attempts'] = attempts

    if authenticated:
        print(f"[AUTH] ✅ {user['phone']} authenticated (score={score:.3f})")
        state['authenticated'] = True
        CALL_STATE[call_sid] = state
        return redirect_to_prompt('/prompt-main-menu')
    elif attempts >= 3:
        # 3 failed attempts — lock out this call, same as PIN lockout
        print(f"[AUTH] ❌ {user['phone']} LOCKED after 3 failed voice attempts")
        fail_text = {
            'hi': 'Awaaz pehchaan mein nakaam. Baad mein dobara try karein.',
            'en': 'Voice authentication failed. Please try again later.'
        }
        audio_path_fail = Path(f'dynamic_audio/auth_fail_{call_sid}.wav')
        save_tts(fail_text.get(lang, fail_text['en']), lang, audio_path_fail)
        resp = VoiceResponse()
        resp.play(f'/dynamic-audio/auth_fail_{call_sid}.wav')
        resp.hangup()
        return Response(str(resp), mimetype='text/xml')
    else:
        state['auth_attempts'] = attempts
        CALL_STATE[call_sid] = state
        return redirect_to_prompt('/auth/greet')
```

---

## Section 4 — Wallet Balance Check

### What exists
✅ Digit 2 in `submit_main_menu` — reads balance via dynamic TTS  
✅ `BALANCE_TEMPLATE` dict for all 9 languages  
✅ `save_tts()` call already implemented

### Status
✅ No changes needed. This feature is complete.

---

## Section 5 — First Payment (Wallet-to-Wallet)

### What exists
✅ UPI payment routes: `/prompt-upi-recipient`, `/submit-upi-recipient`, `/prompt-upi-amount`, `/submit-upi-success`  
✅ `perform_upi_transaction()` in `financial_ops.py` — deducts balance, writes transaction  
✅ Twilio SMS to recipient already implemented  
🔧 Needs contacts integration (see Section 6)  
🔧 Needs voice input for recipient (instead of keypad only)

### Regulatory note on UPI PIN
For the hackathon demo this is mocked. In production, NPCI mandates DTMF (keypad) for UPI PIN entry — this is the ONE keyboard moment in the entire product, and it is a regulatory requirement, not a design choice. The rest of the flow is 100% voice.

```python
@app.route('/prompt-upi-pin', methods=['GET', 'POST'])
def prompt_upi_pin():
    call_sid = request.values.get('CallSid')
    lang = CALL_STATE.get(call_sid, {}).get('lang', 'hi')
    resp = VoiceResponse()
    gather = Gather(num_digits=4, action='/submit-upi-pin', method='POST', timeout=15)
    play(gather, lang, 'enter_upi_pin')  # pre-generate this audio file
    resp.append(gather)
    resp.redirect('/prompt-upi-pin')
    return Response(str(resp), mimetype='text/xml')

@app.route('/submit-upi-pin', methods=['GET', 'POST'])
def submit_upi_pin():
    # For demo: any 4-digit PIN is accepted
    # In production: this is where UPI 123PAY API call happens
    return redirect_to_prompt('/submit-upi-success')
```

### Pre-generate audio files needed
Add to `download_audios.py`:
- `{lang}_enter_upi_pin.wav` — "Apna UPI PIN daalen"
- `{lang}_upi_pin_wrong.wav` — "PIN galat hai. Dobara try karein."

---

## Section 6 — Contacts ("Mere Bhatije Ko Paise Bhejo")

### What exists
❌ Entirely new feature

### Data structure (add to users.json schema)

```json
{
  "9876543210": {
    "name": "Ramesh Kumar",
    "contacts": [
      {
        "nickname": "bhatija",
        "real_name": "Rahul Kumar",
        "phone": "8765432109"
      },
      {
        "nickname": "beti",
        "real_name": "Sunita Devi",
        "phone": "7654321098"
      }
    ]
  }
}
```

### Intent extraction via Sarvam-2

Uses Sarvam's own LLM — better understanding of Indian language relationship terms and number words than English-trained models. Simple JSON task, low token count, fast. See "LLM Architecture" section at the top for the full rationale.

```python
INTENT_SYSTEM_PROMPT = """You are a payment intent extractor for an Indian voice banking app.
Extract payment intent from the user's spoken sentence.
Return ONLY valid JSON: {"recipient": "<name/relationship or null>", "amount": <number or null>, "reason": "<string or null>"}
If no payment intent, return {"recipient": null, "amount": null, "reason": null}
The user speaks in Indian languages. Common relationship terms:
bhatija/bhanja=nephew, beti/ladki=daughter, beta/ladka=son, bhai=brother,
behen/didi=sister, dost/yaar=friend, papa/pita=father, mama/chacha=uncle,
nana/dada=grandfather, nani/dadi=grandmother, chacha/mama=uncle, chachi/mami=aunt"""

def extract_payment_intent(transcript):
    """
    Uses Sarvam-2 LLM — purpose-trained on Indian languages.
    Returns {recipient, amount, reason} or all None if no payment intent.
    NOTE: Do NOT use Groq/OpenAI here — Sarvam-2 has better Indian language
    understanding for relationship terms and spoken number words.
    """
    try:
        response = sarvam_client.chat.completions.create(
            model="sarvam-2",
            messages=[
                {"role": "system", "content": INTENT_SYSTEM_PROMPT},
                {"role": "user", "content": transcript}
            ],
            temperature=0,
            max_tokens=100
        )
        result = json.loads(response.choices[0].message.content.strip())
        return result
    except Exception as e:
        print(f"[INTENT] Sarvam-2 extraction failed: {e}")
        return {"recipient": None, "amount": None, "reason": None}


def find_contact(user_phone, nickname):
    """Look up a contact by nickname. Handles Hindi oblique case (bhatije → bhatija)."""
    oblique_map = {
        'bhatije': 'bhatija', 'bete': 'beta', 'bhai ko': 'bhai',
        'behan ko': 'behan', 'didi ko': 'didi', 'dost ko': 'dost'
    }
    users = load_json('data/users.json')
    user = users.get(user_phone, {})
    contacts = user.get('contacts', [])
    nickname_lower = nickname.lower().strip()
    normalized = oblique_map.get(nickname_lower, nickname_lower)
    for contact in contacts:
        if normalized in contact.get('nickname', '').lower():
            return contact
    return None
```

### Routing based on intent

```python
@app.route('/voice-command', methods=['GET', 'POST'])
def voice_command():
    """User speaks freely — extract intent and route accordingly."""
    call_sid = request.values.get('CallSid')
    recording_url = request.values.get('RecordingUrl', '')
    state = CALL_STATE.get(call_sid, {})
    lang = state.get('lang', 'hi')
    user = state.get('user', {})

    audio_path = f'dynamic_audio/cmd_{call_sid}.wav'
    download_twilio_recording(recording_url, audio_path)
    transcript = speech_to_text(audio_path, lang)

    intent = extract_payment_intent(transcript)
    recipient_name = intent.get('recipient')
    amount = intent.get('amount')
    reason = intent.get('reason')

    resp = VoiceResponse()

    if recipient_name and amount:
        contact = find_contact(user['phone'], recipient_name)
        if contact:
            state['recipient'] = contact['phone']
            state['upi_amount'] = str(int(amount))
            state['payment_reason'] = reason
            CALL_STATE[call_sid] = state

            confirm_text = build_confirm_text(contact['real_name'], amount, lang)
            audio_path_confirm = Path(f'dynamic_audio/pay_confirm_{call_sid}.wav')
            save_tts(confirm_text, lang, audio_path_confirm)
            resp.play(f'/dynamic-audio/pay_confirm_{call_sid}.wav')
            resp.record(action='/voice-payment-confirm', method='POST',
                       max_length=4, play_beep=True, timeout=4)
        else:
            not_found_text = {
                'hi': f"{recipient_name} aapke contacts mein nahi mila. Kya aap number keypad se dalna chahenge?",
                'en': f"I couldn't find {recipient_name} in your contacts. Would you like to enter a number?"
            }
            audio_path_nf = Path(f'dynamic_audio/contact_nf_{call_sid}.wav')
            save_tts(not_found_text.get(lang, not_found_text['en']), lang, audio_path_nf)
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

    confirmed = any(w in answer for w in ['haan', 'ha', 'yes', 'ho', 'sahi', 'bilkul', 'correct'])

    if confirmed:
        user_phone = state.get('phone')
        amount = state.get('upi_amount', '0')
        recipient = state.get('recipient')
        reason = state.get('payment_reason', '')

        success, new_balance = perform_upi_transaction(user_phone, amount)

        resp = VoiceResponse()
        if success:
            try:
                twilio_client = Client(os.getenv('TWILIO_ACCOUNT_SID'), os.getenv('TWILIO_AUTH_TOKEN'))
                msg = f"SwaramPay: Aapke paas Rs {amount} aaye hain {state.get('user', {}).get('name', '')} ki taraf se."
                if reason:
                    msg += f" {reason.capitalize()} ke liye!"
                twilio_client.messages.create(
                    body=msg,
                    from_=os.getenv('TWILIO_PHONE_NUMBER'),
                    to=f'+91{recipient}'
                )
            except Exception as e:
                print(f"[SMS] Failed: {e}")

            play(resp, lang, 'upi_success')
            bal_text = BALANCE_TEMPLATE.get(lang, BALANCE_TEMPLATE['en']).format(int(new_balance))
            bal_audio = Path(f'dynamic_audio/bal_{call_sid}.wav')
            save_tts(bal_text, lang, bal_audio)
            resp.play(f'/dynamic-audio/bal_{call_sid}.wav')
        else:
            play(resp, lang, 'upi_failed')

        resp.redirect('/prompt-main-menu')
        return Response(str(resp), mimetype='text/xml')
    else:
        return redirect_to_prompt('/prompt-main-menu')
```

### Adding contacts by voice

```python
@app.route('/contacts/add-name', methods=['GET', 'POST'])
def contacts_add_name():
    # Ask: "Unka naam ya rishta batayein" → record → STT → store as nickname
    pass

@app.route('/contacts/add-number', methods=['GET', 'POST'])
def contacts_add_number():
    # Ask: "Unka 10 ank ka number boliye" → record → STT → extract digits → confirm
    pass

@app.route('/contacts/add-complete', methods=['GET', 'POST'])
def contacts_add_complete():
    # Write to users.json contacts array → confirm to user
    pass
```

---

## Section 7 — AI Financial Mentor

### What exists
✅ Full mentor pipeline in `app.py`: `/mentor/start`, `/mentor/listen`, `/mentor/process`, `/mentor/check-result`, `/mentor/respond`  
✅ `services/ai_mentor.py`: `process_mentor_audio()` — full STT → LLM → TTS pipeline  
✅ Background threading + polling loop

### Status
⏸ Deprioritized — implement only if time allows after Sections 1–8 are working.

### Quick fixes still needed (even if mentor is deprioritized)

**Fix `requirements.txt`** — `groq` is imported in `ai_mentor.py` but missing from the file:

```
flask
twilio
requests
python-dotenv
pytest
groq
resemblyzer
numpy
sarvamai
```

**Fix credit score language bug** — currently uses `resp.say()` (English only). Replace:

```python
elif digit == '5':
    score, factors = calculate_behavioral_score(user.get('phone'))
    lang = state.get('lang', 'en')
    credit_texts = {
        'hi': f"Aapka credit score hai {score} nau sau mein se.",
        'en': f"Your credit score is {score} out of 900.",
        'ta': f"Ungal credit score {score} mara.",
        # ... other languages
    }
    credit_text = credit_texts.get(lang, credit_texts['en'])
    audio_path = Path(f'dynamic_audio/credit_{call_sid}.wav')
    save_tts(credit_text, lang, audio_path)
    resp.play(f'/dynamic-audio/credit_{call_sid}.wav')
    resp.redirect('/prompt-main-menu')
```

---

## Section 8 — Guardian Companion Web Portal

### What exists
❌ Entirely new — Flask web routes + simple HTML

### Routes needed

```python
OTP_STORE = {}  # {phone: {'otp': '123456', 'expires': timestamp}}

@app.route('/companion', methods=['GET'])
def companion_home():
    return render_template('companion/login.html')

@app.route('/companion/send-otp', methods=['POST'])
def companion_send_otp():
    phone = request.form.get('phone', '').strip()
    otp = str(random.randint(100000, 999999))
    OTP_STORE[phone] = {'otp': otp, 'expires': time.time() + 300}

    twilio_client = Client(os.getenv('TWILIO_ACCOUNT_SID'), os.getenv('TWILIO_AUTH_TOKEN'))
    twilio_client.messages.create(
        body=f"SwaramPay Guardian OTP: {otp}. Valid for 5 minutes.",
        from_=os.getenv('TWILIO_PHONE_NUMBER'),
        to=f'+91{phone}'
    )
    return jsonify({'status': 'sent'})

@app.route('/companion/verify-otp', methods=['POST'])
def companion_verify_otp():
    phone = request.form.get('phone')
    otp = request.form.get('otp')
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
        if guardian_phone in user.get('guardians', []):
            acc = accounts.get(user['account_id'], {})
            linked_wallets.append({
                'name': user['name'],
                'phone': phone,
                'balance': acc.get('balance', 0),
                'recent': acc.get('transactions', [])[-3:]
            })

    return render_template('companion/dashboard.html', wallets=linked_wallets)

@app.route('/companion/add-money', methods=['POST'])
def companion_add_money():
    guardian_phone = session.get('guardian_phone')
    if not guardian_phone:
        return jsonify({'error': 'Unauthorized'}), 401

    target_phone = request.form.get('target_phone')
    amount = float(request.form.get('amount', 0))

    if amount <= 0 or amount > 50000:
        return jsonify({'error': 'Invalid amount'}), 400

    users = load_json('data/users.json')
    target_user = users.get(target_phone, {})
    if guardian_phone not in target_user.get('guardians', []):
        return jsonify({'error': 'Unauthorized'}), 403

    accounts = load_json('data/accounts.json')
    acc_id = target_user.get('account_id')
    accounts[acc_id]['balance'] += amount
    if 'transactions' not in accounts[acc_id]:
        accounts[acc_id]['transactions'] = []
    accounts[acc_id]['transactions'].append({
        'type': 'credit',
        'amount': amount,
        'from': guardian_phone,
        'desc': 'Guardian top-up',
        'timestamp': str(datetime.datetime.now())
    })
    save_json('data/accounts.json', accounts)

    notify_deposit_by_call(
        farmer_phone=target_phone,
        amount=amount,
        guardian_name=guardian_phone,
        farmer_lang=target_user.get('lang', 'hi')
    )

    return jsonify({'status': 'success', 'new_balance': accounts[acc_id]['balance']})
```

### Outbound notification call

```python
def notify_deposit_by_call(farmer_phone, amount, guardian_name, farmer_lang):
    notify_texts = {
        'hi': f"Namaste! Aapke SwaramPay wallet mein {int(amount)} rupiye aaye hain. Aapka naya balance check karne ke liye dobara call karein.",
        'en': f"Hello! {int(amount)} rupees have been added to your SwaramPay wallet. Call back to check your new balance.",
        'ta': f"Vanakkam! Ungal SwaramPay wallet-il {int(amount)} rubai vandhirukku.",
        # ... other languages
    }
    text = notify_texts.get(farmer_lang, notify_texts['en'])
    audio_path = Path(f'dynamic_audio/deposit_notify_{farmer_phone}.wav')
    save_tts(text, farmer_lang, audio_path)

    try:
        twilio_client = Client(os.getenv('TWILIO_ACCOUNT_SID'), os.getenv('TWILIO_AUTH_TOKEN'))
        twilio_client.calls.create(
            twiml=f'<Response><Play>{os.getenv("SERVER_BASE_URL")}/dynamic-audio/deposit_notify_{farmer_phone}.wav</Play></Response>',
            to=f'+91{farmer_phone}',
            from_=os.getenv('TWILIO_PHONE_NUMBER')
        )
        print(f"[NOTIFY] Outbound call fired to {farmer_phone}")
    except Exception as e:
        print(f"[NOTIFY] Call failed: {e}")
```

### Companion web templates

**`templates/companion/login.html`**
```html
<!DOCTYPE html>
<html>
<head>
  <title>SwaramPay Guardian Portal</title>
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <style>
    body { font-family: sans-serif; max-width: 400px; margin: 40px auto; padding: 20px; }
    input, button { width: 100%; padding: 12px; margin: 8px 0; font-size: 16px; box-sizing: border-box; }
    button { background: #16a34a; color: white; border: none; border-radius: 6px; cursor: pointer; }
    h2 { color: #16a34a; }
  </style>
</head>
<body>
  <h2>SwaramPay Guardian Login</h2>
  <input type="tel" id="phone" placeholder="Your 10-digit mobile number" maxlength="10">
  <button onclick="sendOTP()">Send OTP</button>
  <div id="otp-section" style="display:none">
    <input type="text" id="otp" placeholder="Enter OTP">
    <button onclick="verifyOTP()">Verify & Login</button>
  </div>
  <script>
    function sendOTP() {
      const phone = document.getElementById('phone').value;
      fetch('/companion/send-otp', {method:'POST', body: new URLSearchParams({phone})})
        .then(() => document.getElementById('otp-section').style.display = 'block');
    }
    function verifyOTP() {
      const phone = document.getElementById('phone').value;
      const otp = document.getElementById('otp').value;
      fetch('/companion/verify-otp', {method:'POST', body: new URLSearchParams({phone, otp})})
        .then(r => r.redirected ? window.location=r.url : alert('Invalid OTP'));
    }
  </script>
</body>
</html>
```

**`templates/companion/dashboard.html`**
```html
<!DOCTYPE html>
<html>
<head>
  <title>SwaramPay Guardian Dashboard</title>
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <style>
    body { font-family: sans-serif; max-width: 420px; margin: 40px auto; padding: 20px; }
    .card { border: 1px solid #e5e7eb; border-radius: 10px; padding: 20px; margin: 16px 0; }
    .balance { font-size: 28px; font-weight: bold; color: #16a34a; }
    input[type=number] { width: 100%; padding: 12px; font-size: 16px; box-sizing: border-box; margin: 8px 0; }
    button { background: #16a34a; color: white; border: none; border-radius: 6px; padding: 12px; width: 100%; font-size: 16px; cursor: pointer; }
    h2 { color: #16a34a; }
  </style>
</head>
<body>
  <h2>Guardian Dashboard</h2>
  {% for wallet in wallets %}
  <div class="card">
    <h3>{{ wallet.name }}</h3>
    <div class="balance">₹{{ wallet.balance }}</div>
    <input type="number" id="amt_{{ wallet.phone }}" placeholder="Amount to add (₹)" min="1" max="50000">
    <button onclick="addMoney('{{ wallet.phone }}')">Add Money</button>
    <p style="color:#6b7280; font-size:13px">Recent top-ups:</p>
    {% for txn in wallet.recent %}
      <p style="font-size:13px">₹{{ txn.amount }} — {{ txn.timestamp[:10] }}</p>
    {% endfor %}
  </div>
  {% endfor %}
  <script>
    function addMoney(phone) {
      const amount = document.getElementById('amt_' + phone).value;
      if (!amount || amount <= 0) return alert('Enter a valid amount');
      fetch('/companion/add-money', {
        method: 'POST',
        body: new URLSearchParams({target_phone: phone, amount})
      })
      .then(r => r.json())
      .then(d => {
        if (d.status === 'success') {
          alert('Money added! New balance: ₹' + d.new_balance);
          location.reload();
        } else {
          alert('Error: ' + d.error);
        }
      });
    }
  </script>
</body>
</html>
```

---

## Build Order for Hackathon

| Priority | Section | Est. Time | Depends On |
|---|---|---|---|
| 1 | New/returning caller detection | 20 min | Nothing |
| 2 | Registration route chain (2.1–2.5) **including voice enrollment — not skippable** | 1.5 hrs | Detection |
| 3 | Voice auth on returning calls (resemblyzer verify) | 45 min | Registration |
| 4 | Fix requirements.txt + credit score TTS bug | 10 min | Nothing |
| 5 | Guardian companion web (login + dashboard + add money) | 1.5 hrs | Nothing |
| 6 | Outbound deposit notification call | 30 min | Companion web |
| 7 | Contacts feature + Sarvam-2 intent extraction | 1.5 hrs | Nothing |
| 8 | UPI PIN prompt (mock, keypad) | 20 min | Nothing |
| **Total** | | **~6.5 hrs** | |

> **Priority 2 and 3 are the security spine of the product.** Without a voice model in the DB, every returning caller hits a dead end. Do not start the demo without successfully running a full enrollment + verification cycle.

---

## Environment Variables Needed

```
SARVAM_API_KEY=
TWILIO_ACCOUNT_SID=
TWILIO_AUTH_TOKEN=
TWILIO_PHONE_NUMBER=
SERVER_BASE_URL=           # your ngrok or deployed URL, no trailing slash
GROQ_API_KEY=
FLASK_SECRET_KEY=          # any random string, needed for Flask sessions
```

---

## File Changes Summary

| File | Change |
|---|---|
| `app.py` | Add registration routes, voice auth routes, companion web routes, voice command route, contact routes, outbound notify function |
| `config.py` | Add `ENROLLMENT_PHRASES` per language |
| `mock_db.py` | Add `get_contacts()`, `add_contact()`, `add_guardian()`, `update_balance()` helpers |
| `services/financial_ops.py` | No changes needed |
| `services/ai_mentor.py` | No changes needed |
| `requirements.txt` | Add `groq`, `resemblyzer`, `numpy`, `sarvamai` |
| `data/users.json` | Add `contacts` array, `voice_model`, `guardians` to user schema |
| `templates/companion/login.html` | New |
| `templates/companion/dashboard.html` | New |
| `download_audios.py` | Add new prompt keys: `enter_upi_pin`, `upi_pin_wrong` |

---

*Phase 1 Implementation Plan — SwaramPay*  
*Last updated: June 13, 2026*
