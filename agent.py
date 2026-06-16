"""
SwaramPay Real-Time Voice Agent
Pipecat + Sarvam STT/TTS + Groq LLM via Twilio Media Streams WebSocket
Runs on port 8001 alongside the Flask registration server (port 5000).

Setup:
  pip install "pipecat-ai[sarvam,silero]" fastapi uvicorn
  python agent.py
  ngrok http 8001  (point this ngrok URL as Twilio phone number webhook)
"""

import os
import json
import asyncio
from dotenv import load_dotenv

from fastapi import FastAPI, WebSocket, Request
from fastapi.responses import Response
import uvicorn

from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.worker import PipelineWorker
from pipecat.workers.runner import WorkerRunner
from pipecat.services.groq.llm import GroqLLMService
from pipecat.services.sarvam.stt import SarvamSTTService
from pipecat.services.sarvam.tts import SarvamTTSService
from pipecat.processors.aggregators.llm_response_universal import (
    LLMContextAggregatorPair,
)
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.adapters.schemas.function_schema import FunctionSchema
from pipecat.adapters.schemas.tools_schema import ToolsSchema
from pipecat.transports.websocket.fastapi import FastAPIWebsocketTransport, FastAPIWebsocketParams
from pipecat.serializers.twilio import TwilioFrameSerializer
from pipecat.frames.frames import LLMRunFrame, LLMMessagesUpdateFrame

from twilio.rest import Client as TwilioClient
from mock_db import get_user, get_account
from services.financial_ops import load_json, save_json, perform_upi_transaction

load_dotenv(override=True)

app = FastAPI()

LANG_TO_SARVAM = {
    'hi': 'hi-IN', 'te': 'te-IN', 'ta': 'ta-IN', 'kn': 'kn-IN',
    'ml': 'ml-IN', 'mr': 'mr-IN', 'bn': 'bn-IN', 'gu': 'gu-IN', 'en': 'en-IN',
}


@app.post("/")
async def handle_call(request: Request):
    """Twilio voice webhook — returns TwiML to open a Media Stream to this server."""
    host = request.headers.get("host", "")
    # Parse form body manually to avoid python-multipart version issues
    from urllib.parse import parse_qs
    body = await request.body()
    params = parse_qs(body.decode())
    caller = params.get("From", [""])[0]

    twiml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Connect>
        <Stream url="wss://{host}/ws">
            <Parameter name="caller" value="{caller}" />
        </Stream>
    </Connect>
</Response>"""
    return Response(content=twiml, media_type="text/xml")


@app.post("/call-status")
async def call_status():
    """Twilio call status callback — acknowledge and ignore."""
    return Response(content="", status_code=204)


async def run_bot(websocket: WebSocket, stream_sid: str, call_sid: str, caller: str):
    """Build and run the Pipecat pipeline for one call."""
    phone = caller.replace("+91", "").lstrip("+")
    user = get_user(phone)

    lang = user.get("lang", "hi") if user else "hi"
    sarvam_lang = LANG_TO_SARVAM.get(lang, "hi-IN")

    if user:
        account = get_account(user.get("account_id", ""))
        balance = account.get("balance", 0) if account else 0
        contacts = user.get("contacts", [])
        contacts_str = (
            ", ".join(f"{c['nickname']} ({c['phone']})" for c in contacts) or "none"
        )
        name = user.get("name", "User")
        system_msg = (
            f"You are SwaramPay, a friendly voice banking assistant.\n"
            f"User's name: {name} | Contacts: {contacts_str}\n"
            f"Language: respond ONLY in {lang} (Hindi=hi, Telugu=te, Tamil=ta, etc.).\n"
            f"Keep every reply under 2 sentences — this is a phone call, be concise.\n"
            f"Tools:\n"
            f"- check_balance: call when user asks for balance. Speak the result out loud.\n"
            f"- confirm_payment: call this once you have recipient AND amount. It will ask the user to confirm. "
            f"Wait for their response.\n"
            f"- send_payment: ONLY call this after confirm_payment returned and user said YES/haan. "
            f"If user said no, cancel completely.\n"
            f"- add_contact: call only when user gives you a name AND phone number.\n"
            f"- end_call: call this AFTER saying your goodbye sentence to hang up.\n"
            f"After every tool result, speak it and ask if they need anything else.\n"
            f"NEVER call any tool during greeting.\n"
            f"When the user is done: say ONLY a goodbye sentence in {lang}, nothing else. Then call end_call as a tool. NEVER write '<function=end_call>' as text."
        )
    else:
        system_msg = (
            "You are SwaramPay. This phone number is not registered with us. "
            "Politely tell the caller to register by calling our registration line. "
            "Keep it brief — one sentence."
        )

    # --- Transport ---
    serializer = TwilioFrameSerializer(
        stream_sid=stream_sid,
        call_sid=call_sid,
        account_sid=os.getenv("TWILIO_ACCOUNT_SID", ""),
        auth_token=os.getenv("TWILIO_AUTH_TOKEN", ""),
    )

    transport = FastAPIWebsocketTransport(
        websocket=websocket,
        params=FastAPIWebsocketParams(
            audio_in_enabled=True,
            audio_out_enabled=True,
            audio_in_sample_rate=16000,   # resample Twilio's 8kHz → 16kHz for STT
            audio_out_sample_rate=8000,   # TTS output downsampled to 8kHz for Twilio
            add_wav_header=False,
            serializer=serializer,
        ),
    )

    # --- STT (Sarvam saaras:v3, 16kHz after resampling) ---
    stt = SarvamSTTService(
        api_key=os.getenv("SARVAM_API_KEY"),
        sample_rate=16000,
        settings=SarvamSTTService.Settings(
            language=sarvam_lang,
            vad_signals=True,
            high_vad_sensitivity=False,
            positive_speech_threshold=0.6,
            negative_speech_threshold=0.85,
            min_speech_frames=4,
        ),
    )

    # --- TTS (Sarvam bulbul:v2, 8kHz output for Twilio) ---
    tts = SarvamTTSService(
        api_key=os.getenv("SARVAM_API_KEY"),
        sample_rate=8000,
        settings=SarvamTTSService.Settings(
            language=sarvam_lang,
            voice="simran",
            model="bulbul:v3",
            pace=1.0,
        ),
    )

    # --- LLM (Groq llama-3.3-70b) ---
    llm = GroqLLMService(
        api_key=os.getenv("GROQ_API_KEY"),
        settings=GroqLLMService.Settings(model="llama-3.3-70b-versatile"),
    )

    # --- Tools ---
    tools = ToolsSchema(standard_tools=[
        FunctionSchema(
            name="check_balance",
            description="Get the user's current wallet balance",
            properties={},
            required=[],
        ),
        FunctionSchema(
            name="confirm_payment",
            description="Ask the user to confirm payment details before sending. Call this FIRST with recipient and amount, then only call send_payment if user says yes.",
            properties={
                "recipient": {"type": "string", "description": "Contact nickname or 10-digit phone number"},
                "amount": {"anyOf": [{"type": "number"}, {"type": "string"}], "description": "Amount in rupees"},
            },
            required=["recipient", "amount"],
        ),
        FunctionSchema(
            name="send_payment",
            description="Send money. ONLY call this after confirm_payment was called and user said YES.",
            properties={
                "recipient": {"type": "string", "description": "Contact nickname or 10-digit phone number"},
                "amount": {"anyOf": [{"type": "number"}, {"type": "string"}], "description": "Amount in rupees"},
            },
            required=["recipient", "amount"],
        ),
        FunctionSchema(
            name="add_contact",
            description="Save a new contact. ONLY call when user has explicitly stated BOTH a name AND a 10-digit phone number. If phone number is missing, ask the user for it before calling this tool.",
            properties={
                "name": {"type": "string", "description": "Contact nickname"},
                "phone": {"type": "string", "description": "10-digit phone number — must be provided by user, never invent one"},
            },
            required=["name", "phone"],
        ),
        FunctionSchema(
            name="end_call",
            description="Call this immediately AFTER saying goodbye to hang up the call. Use whenever the user is done and you have said your farewell.",
            properties={},
            required=[],
        ),
    ])

    # --- Tool handlers (Pipecat 1.x: must call params.result_callback, not return) ---
    async def check_balance_handler(params):
        acc = get_account(user.get("account_id", "")) if user else None
        bal = int(acc.get("balance", 0)) if acc else 0
        await params.result_callback(f"Your balance is Rs {bal}.")

    async def confirm_payment_handler(params):
        args = params.arguments or {}
        recipient_input = str(args.get("recipient", "")).strip()
        amount = args.get("amount", 0)
        digits_only = ''.join(filter(str.isdigit, recipient_input))
        if digits_only and len(digits_only) != 10:
            await params.result_callback(f"Invalid number. '{recipient_input}' is not 10 digits. Ask the user for the full 10-digit phone number.")
            return
        await params.result_callback(f"Ask the user in {lang} to confirm: 'Kya aap {recipient_input} ko Rs {amount} bhejna chahte hain? Haan ya naa?' Then wait for their answer.")

    async def send_payment_handler(params):
        if not user:
            await params.result_callback("You are not registered.")
            return
        args = params.arguments or {}
        recipient_input = str(args.get("recipient", ""))
        amount = float(args.get("amount", 0))

        users_data = load_json("data/users.json")
        saved_contacts = users_data.get(phone, {}).get("contacts", [])
        recipient_phone = None
        recipient_name = recipient_input

        for c in saved_contacts:
            nick = c.get("nickname", "").lower()
            real = c.get("real_name", "").lower()
            if recipient_input.lower() in nick or recipient_input.lower() in real:
                recipient_phone = c["phone"]
                recipient_name = c["nickname"]
                break

        if not recipient_phone and recipient_input.isdigit() and len(recipient_input) == 10:
            recipient_phone = recipient_input

        if not recipient_phone:
            await params.result_callback(f"I couldn't find a contact named {recipient_input}. Please give me their phone number.")
            return

        success, new_bal = perform_upi_transaction(phone, amount, desc=f"Sent to {recipient_name} ({recipient_phone})")
        if success:
            twilio = TwilioClient(os.getenv("TWILIO_ACCOUNT_SID"), os.getenv("TWILIO_AUTH_TOKEN"))
            from_num = os.getenv("TWILIO_PHONE_NUMBER")
            try:
                twilio.messages.create(
                    body=f"SwaramPay: You received Rs {int(amount)} from {name}.",
                    from_=from_num,
                    to=f"+91{recipient_phone}",
                )
            except Exception as e:
                print(f"[SMS] recipient failed: {e}")
            try:
                twilio.messages.create(
                    body=f"SwaramPay: Rs {int(amount)} sent to {recipient_name}. New balance: Rs {int(new_bal)}.",
                    from_=from_num,
                    to=f"+91{phone}",
                )
            except Exception as e:
                print(f"[SMS] sender failed: {e}")
            await params.result_callback(f"Payment of Rs {int(amount)} to {recipient_name} was successful. Your new balance is Rs {int(new_bal)}.")
        else:
            await params.result_callback(f"Payment failed. Your balance is Rs {int(new_bal)}.")

    async def add_contact_handler(params):
        if not user:
            await params.result_callback("You are not registered.")
            return
        args = params.arguments or {}
        contact_name = str(args.get("name", ""))
        contact_phone = str(args.get("phone", ""))
        digits_only = ''.join(filter(str.isdigit, contact_phone))
        if len(digits_only) != 10:
            await params.result_callback(f"Phone number '{contact_phone}' is not valid. Ask the user for a 10-digit phone number for {contact_name}.")
            return
        users_data = load_json("data/users.json")
        if phone in users_data:
            users_data[phone]["contacts"].append(
                {"nickname": contact_name, "real_name": contact_name, "phone": contact_phone}
            )
            save_json("data/users.json", users_data)
            await params.result_callback(f"Saved {contact_name} with number {contact_phone}.")
        else:
            await params.result_callback("Could not save contact.")

    # end_call uses worker which is created below — store ref in a mutable container
    worker_ref = []

    async def end_call_handler(params):
        from pipecat.frames.frames import EndFrame
        if worker_ref:
            await worker_ref[0].queue_frames([EndFrame()])
        await params.result_callback("")

    llm.register_function("check_balance", check_balance_handler)
    llm.register_function("confirm_payment", confirm_payment_handler)
    llm.register_function("send_payment", send_payment_handler)
    llm.register_function("add_contact", add_contact_handler)
    llm.register_function("end_call", end_call_handler)

    # --- Context + aggregators ---
    messages = [{"role": "system", "content": system_msg}]
    context = LLMContext(messages=messages, tools=tools)
    aggregators = LLMContextAggregatorPair(context)

    # --- Pipeline ---
    pipeline = Pipeline(
        [
            transport.input(),
            stt,
            aggregators.user(),
            llm,
            tts,
            transport.output(),
            aggregators.assistant(),
        ]
    )

    worker = PipelineWorker(pipeline)
    worker_ref.append(worker)

    @transport.event_handler("on_client_connected")
    async def on_connected(transport, client):
        greeting_messages = messages + [{"role": "user", "content": "greet the user warmly by name and ask how you can help them today"}]
        await worker.queue_frames([
            LLMMessagesUpdateFrame(messages=greeting_messages),
            LLMRunFrame(),
        ])

    runner = WorkerRunner()
    await runner.add_workers(worker)
    await runner.run()


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """Receives Twilio Media Stream, extracts stream_sid, runs the bot."""
    await websocket.accept()

    stream_sid = ""
    caller = ""

    # Consume Twilio's initial handshake messages to extract stream_sid/caller.
    # Audio ("media") events come after "start", so nothing useful is lost.
    async for raw in websocket.iter_text():
        data = json.loads(raw)
        event = data.get("event")
        if event == "connected":
            continue
        if event == "start":
            stream_sid = data.get("streamSid", "")
            start_data = data.get("start", {})
            call_sid = start_data.get("callSid", "")
            custom = start_data.get("customParameters", {})
            caller = custom.get("caller", "")
            print(f"[WS] stream_sid={stream_sid} call_sid={call_sid} caller='{caller}' custom={custom}")
            break

    await run_bot(websocket, stream_sid, call_sid, caller)


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8001, log_level="info", timeout_graceful_shutdown=1)
