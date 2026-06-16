# SwaramPay 🎙️₹

**Voice-first banking assistant for every Indian.**
*No app. No screen. No literacy barrier. Just your voice.*

SwaramPay is a fully voice-driven financial assistant accessible via a **regular phone call** — feature phone or smartphone. It supports **9 Indian languages** and uses **voice biometrics** as the primary security layer, so users never need to remember a password or tap a screen.

---

## Features

- **Voice biometric authentication** — your voice is your PIN
- **UPI-style payments by voice** — "send 500 to my nephew"
- **Balance check, mini loans, insurance, savings** — all spoken
- **AI Financial Mentor** — conversational financial advice in your language
- **Guardian Companion Portal** — web dashboard for family oversight
- **SMS notifications** to recipients and guardians
- **9 Indian languages**: Hindi, English, Tamil, Telugu, Kannada, Malayalam, Marathi, Bengali, Gujarati

---

## Tech Stack

| Layer | Technology |
|---|---|
| Backend | Flask (Python 3.12) |
| Telephony / IVR | Twilio Voice + TwiML |
| Speech-to-Text | Sarvam AI — Saaras v3 (9 Indian languages) |
| Speech Translation | Sarvam AI — Saaras v2.5 (any language → English) |
| Text-to-Speech | Sarvam AI — Bulbul |
| LLM (intent + mentor) | Groq — Llama 3.1 8B Instant |
| Voice Biometrics | SpeechBrain ECAPA-TDNN (VoxCeleb pretrained) |
| Data store | JSON-based mock DB |
| Web portal | Flask + Jinja2 |

---

## How It Works

### Call Flow

```
User dials Twilio number
        │
        ▼
Language selection (1-9)
        │
        ▼
Phone number entry
        │
        ├─── New user ──→ Name → Voice Enrollment (3 phrases) → MPIN → Guardian
        │
        └─── Returning ──→ Voice Authentication Challenge
                                    │
                                    ▼
                             Main Menu
                    ┌──────────────┼──────────────┐
                    ▼              ▼               ▼
              Balance          UPI Pay         Mentor
              Loan            Insurance        Savings
```

Each route returns TwiML (XML) to Twilio, which plays audio back to the caller and records their response — a state machine driven by `CALL_STATE[call_sid]` in memory.

### Voice Biometrics — The Security Core

**Enrollment (registration):**
1. User speaks 3 different challenge phrases during registration.
2. Each recording is downloaded from Twilio and passed through **SpeechBrain ECAPA-TDNN**.
3. The model produces a **192-dimensional speaker embedding** per phrase.
4. The 3 embeddings are **averaged** into one `voice_model` stored per user.

**Authentication (every return call):**
1. User is challenged with a **random phrase** (anti-replay — can't pre-record an answer).
2. Live recording → 192-dim embedding via ECAPA-TDNN.
3. **Cosine similarity** between live and stored voiceprint.
4. Threshold = **0.45** (empirically calibrated: genuine ~0.60–0.65, impostors ~0.29–0.36).
5. 3 failed attempts → graceful fallback to spoken MPIN.
6. Voice verification fires again at **payment confirmation** — same as re-entering a PIN for high-value transactions.

**Adaptive learning:**
On every high-confidence match (similarity ≥ 0.60), the live embedding is blended into the stored voiceprint:
```
new_model = 0.9 × old_model + 0.1 × live_embedding  (re-normalized)
```
The model adapts naturally to voice changes (illness, mic, environment) over time. Borderline matches (0.45–0.60) authenticate but don't update the template, limiting poisoning risk.

---

## Setup

### Prerequisites

- Python 3.12+
- Twilio account + phone number
- Sarvam AI API key
- Groq API key
- ngrok (for local dev)

### Install

```bash
git clone https://github.com/sarangan19/swaramPay.git
cd swaramPay
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### Configure `.env`

Create a `.env` file in the project root:

```env
SARVAM_API_KEY=your_sarvam_key
TWILIO_ACCOUNT_SID=ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
TWILIO_AUTH_TOKEN=your_twilio_auth_token
TWILIO_PHONE_NUMBER=+1xxxxxxxxxx
SERVER_BASE_URL=https://your-ngrok-url.ngrok-free.app
FLASK_SECRET_KEY=your-secret-key
GROQ_API_KEY=your_groq_key
```

### Run

```bash
# Start ngrok tunnel
ngrok http 5000

# Update Twilio webhook to your ngrok URL, then start Flask
python3 -u app.py
```

The `-u` flag enables unbuffered stdout so voice auth logs (cosine similarity scores) appear in real time.

---

## Project Structure

```
swaramPay/
├── app.py                  # Main Flask app — all IVR routes + voice auth
├── config.py               # Language config + enrollment phrases
├── mock_db.py              # get_user(), get_account() helpers
├── services/
│   ├── ai_mentor.py        # STT, STT-translate, Groq LLM, TTS, recording download
│   ├── financial_ops.py    # UPI transaction, behavioral score (JSON-backed)
│   └── sarvam_tts.py       # Sarvam TTS wrapper
├── templates/companion/
│   ├── login.html          # Guardian portal login (OTP)
│   └── dashboard.html      # Guardian portal dashboard
├── static/img/logo.png     # SwaramPay logo
├── prompt_audio/           # Pre-generated static audio (9 langs × all prompts)
├── dynamic_audio/          # Runtime-generated audio (per call)
├── data/
│   ├── users.json          # User profiles + voice models
│   ├── accounts.json       # Wallet balances + transactions
│   └── transactions.json   # Transaction history
└── pretrained_models/      # SpeechBrain ECAPA-TDNN model (auto-downloaded)
```

---

## Guardian Companion Portal

Accessible at `/companion` — a web dashboard for family members/guardians.

- OTP login via SMS (Twilio)
- View dependent's wallet balance and transaction history
- Add money to the dependent's wallet
- Gives families oversight without removing the primary user's autonomy

---

## Scalability Notes

- **Voice auth is O(1) per call** — cosine similarity against a single stored vector, regardless of total users.
- Production path: swap JSON files → MongoDB, move `CALL_STATE` → Redis, run SpeechBrain as a separate inference microservice, audio files → S3.
- Telephony scales via Twilio natively; only the Flask webhook backend needs horizontal scaling.

---

## Team

Built for HackPrix Season 3.

Sarangan
Aryan Bharti 
---

## License

MIT
