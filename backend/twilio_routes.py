"""Signed TwiML and Media Streams routes for locally running Chanakya."""

import asyncio
import json
import logging
import os

import httpx
from fastapi import APIRouter, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import Response
from sarvamai import AsyncSarvamAI
from twilio.twiml.voice_response import VoiceResponse

from backend.twilio_security import CallRegistry, TwilioSettings, valid_signature
from backend.twilio_transport import TwilioVoiceTransport
from backend.voice_session import run_voice_session

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/telephony")
VOICE_PATH = "/api/telephony/voice"
MEDIA_PATH = "/api/telephony/media"
STREAM_STATUS_PATH = "/api/telephony/stream-status"


class TelephonyRuntime:
    def __init__(self, settings, voice_agent, sarvam_key):
        settings.validate()
        self.settings = settings
        self.voice_agent = voice_agent
        self.http_client = httpx.AsyncClient(timeout=60)
        self.sarvam = AsyncSarvamAI(api_subscription_key=sarvam_key, httpx_client=self.http_client)
        self.registry = CallRegistry(settings)
        self.sessions = set()

    async def aclose(self):
        self.registry.shutdown()
        tasks = list(self.sessions)
        for task in tasks:
            task.cancel()
        try:
            await asyncio.gather(*tasks, return_exceptions=True)
        finally:
            await self.http_client.aclose()


def get_runtime(app):
    runtime = getattr(app.state, "telephony", None)
    if runtime is None:
        raise HTTPException(status_code=503, detail="Phone calling is not configured")
    return runtime


async def signed_form(request, runtime):
    if not request.headers.get("x-twilio-signature"):
        raise HTTPException(status_code=403, detail="Twilio signature is required")
    length = request.headers.get("content-length", "0")
    if not length.isdecimal() or int(length) > 16384:
        raise HTTPException(status_code=413, detail="Webhook too large")
    body = await request.body()
    if len(body) > 16384:
        raise HTTPException(status_code=413, detail="Webhook too large")
    params = await request.form()
    if not valid_signature(
        runtime.settings, request.url.path, request.headers.get("x-twilio-signature"),
        params, query=request.url.query,
    ) or params.get("AccountSid") != runtime.settings.account_sid:
        raise HTTPException(status_code=403, detail="Invalid Twilio signature or account")
    return params


def xml_response(response):
    return Response(str(response), media_type="application/xml")


@router.post("/voice")
async def voice(request: Request):
    runtime = get_runtime(request.app)
    params = await signed_form(request, runtime)
    response = VoiceResponse()
    try:
        call = runtime.registry.reserve(params)
    except PermissionError:
        response.reject()
        return xml_response(response)
    except OverflowError:
        response.say("Chanakya is on another call. Please try again shortly.")
        response.hangup()
        return xml_response(response)
    stream = response.connect().stream(
        url=runtime.settings.url(MEDIA_PATH, websocket=True),
        status_callback=runtime.settings.url(STREAM_STATUS_PATH),
        status_callback_method="POST",
    )
    stream.parameter(name="session", value=call.token)
    # Closing WSS resumes these instructions, so failures cannot leave a live silent call.
    response.say("This conversation has ended. Please call again if you need help.")
    response.hangup()
    return xml_response(response)


@router.post("/call-status")
async def call_status(request: Request):
    runtime = get_runtime(request.app)
    params = await signed_form(request, runtime)
    runtime.registry.update(params.get("CallSid"), params.get("CallStatus"))
    return Response(status_code=204)


@router.post("/stream-status")
async def stream_status(request: Request):
    runtime = get_runtime(request.app)
    params = await signed_form(request, runtime)
    call = runtime.registry.calls.get(params.get("CallSid"))
    if (call and (call.stream_sid is None or call.stream_sid == params.get("StreamSid"))
            and params.get("StreamEvent") in {"stream-stopped", "stream-error"}):
        runtime.registry.finish(call.call_sid)
    return Response(status_code=204)


async def start_message(websocket):
    async def frame():
        raw = await asyncio.wait_for(websocket.receive_text(), timeout=5)
        if len(raw) > 16384:
            raise ValueError("Twilio setup frame is oversized")
        return json.loads(raw)

    connected = await frame()
    if connected != {"event": "connected", "protocol": "Call", "version": "1.0.0"}:
        raise ValueError("Unsupported Twilio stream protocol")
    message = await frame()
    if not isinstance(message, dict) or message.get("event") != "start":
        raise ValueError("Twilio start event is required")
    start = message["start"]
    if not isinstance(start, dict) or message.get("streamSid") != start.get("streamSid"):
        raise ValueError("Inconsistent Twilio stream identifiers")
    sequence = int(message.get("sequenceNumber", "0"))
    if sequence < 1:
        raise ValueError("Invalid start sequence")
    return start, sequence


@router.websocket("/media")
async def media(websocket: WebSocket):
    runtime = getattr(websocket.app.state, "telephony", None)
    if (runtime is None or websocket.url.query or not valid_signature(
        runtime.settings, MEDIA_PATH, websocket.headers.get("x-twilio-signature"),
        websocket=True,
    )):
        await websocket.close(code=1008)
        return
    await websocket.accept()
    handler = asyncio.current_task()
    runtime.sessions.add(handler)
    transport = None
    call = None
    tasks = []
    try:
        start, sequence = await start_message(websocket)
        call = runtime.registry.attach(start)
        transport = TwilioVoiceTransport(websocket, call)
        transport.sequence = sequence
        transport.start()
        session = asyncio.create_task(run_voice_session(
            transport, runtime.voice_agent, runtime.sarvam, runtime.settings.retrieval_provider,
        ))
        stop = asyncio.create_task(call.stop.wait())
        disconnected = asyncio.create_task(transport.closed.wait())
        ready = asyncio.create_task(transport.ready.wait())
        tasks = [session, stop, disconnected, ready]
        deadline = asyncio.get_running_loop().time() + runtime.settings.max_call_seconds
        done, _pending = await asyncio.wait(
            tasks, timeout=20, return_when=asyncio.FIRST_COMPLETED,
        )
        if ready in done and not transport.closed.is_set() and not call.stop.is_set():
            done, _pending = await asyncio.wait(
                [session, stop, disconnected],
                timeout=max(0, deadline - asyncio.get_running_loop().time()),
                return_when=asyncio.FIRST_COMPLETED,
            )
        if session in done:
            session.result()
    except WebSocketDisconnect:
        logger.debug("Phone caller disconnected during setup")
    except (ValueError, PermissionError, KeyError, TypeError, json.JSONDecodeError, TimeoutError) as error:
        logger.warning("Phone setup rejected: %s", type(error).__name__)
    finally:
        # Cancel session work before clearing provider/client state.
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        if transport:
            await transport.aclose()
        try:
            await websocket.close()
        except (RuntimeError, WebSocketDisconnect):
            logger.debug("Phone socket already closed")
        try:
            if call:
                runtime.registry.finish(call.call_sid)
                await runtime.voice_agent.forget_thread("phone:" + call.call_sid)
        finally:
            runtime.sessions.discard(handler)


def configure_telephony(app, voice_agent, sarvam_key):
    app.state.telephony = None
    if os.getenv("TWILIO_ENABLED", "false").lower() in {"true", "1", "yes"}:
        settings = TwilioSettings.from_env()
        if not sarvam_key:
            raise ValueError("SARVAM_API_KEY is required for phone calling")
        app.state.telephony = TelephonyRuntime(settings, voice_agent, sarvam_key)
