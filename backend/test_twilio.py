"""Twilio protocol, admission, playback, and signed endpoint regressions."""

import asyncio
import base64
import json
import os
import threading
import unittest
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch
from xml.etree import ElementTree

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sarvamai.types.audio_output import AudioOutput
from sarvamai.types.audio_output_data import AudioOutputData
from sarvamai.types.event_response import EventResponse
from sarvamai.types.event_response_data import EventResponseData
from twilio.request_validator import RequestValidator

from backend.test_voice_pipeline import FakeSarvamClient, FakeTtsSocket, QueueStt
from backend.twilio_routes import TelephonyRuntime, configure_telephony, router
from backend.twilio_security import CallRegistry, TwilioSettings, valid_signature
from backend.twilio_transport import (
    MAX_PENDING_SEGMENTS,
    SEGMENT_BYTES,
    TwilioVoiceTransport,
)
from backend.voice_transport import VoiceAudioChunk, VoiceInput

SETTINGS = TwilioSettings(
    enabled=True, account_sid="AC" + "a" * 32, auth_token="test-token",
    phone_number="+14155550100", allowed_phone_number="+919876543210",
    public_base_url="https://chanakya.example.com",
)
CALL = "CA" + "b" * 32
STREAM = "MZ" + "c" * 32


def call_params(sid=CALL):
    return {"AccountSid": SETTINGS.account_sid, "CallSid": sid, "Direction": "inbound",
            "From": SETTINGS.allowed_phone_number, "To": SETTINGS.phone_number}


def stream_start(call):
    return {"accountSid": SETTINGS.account_sid, "callSid": call.call_sid, "streamSid": STREAM,
            "tracks": ["inbound"], "customParameters": {"session": call.token},
            "mediaFormat": {"encoding": "audio/x-mulaw", "sampleRate": 8000, "channels": 1}}


class TwilioAdmissionTests(unittest.TestCase):
    def test_only_valid_server_configuration_is_accepted(self):
        SETTINGS.validate()
        self.assertEqual(SETTINGS.retrieval_provider, "llm_batch")
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(TwilioSettings.from_env().retrieval_provider, "llm_batch")
        for update in [{"public_base_url": "http://chanakya.example.com"},
                       {"public_base_url": "https://chanakya.example.com/query?secret=x"},
                       {"phone_number": "+919999999999"}, {"max_call_seconds": 0},
                       {"retrieval_provider": "other"}]:
            with self.subTest(update=update), self.assertRaises(ValueError):
                replace(SETTINGS, **update).validate()
        self.assertNotIn("test-token", repr(SETTINGS))
        self.assertNotIn(SETTINGS.allowed_phone_number, repr(SETTINGS))

    def test_signatures_pin_public_url_and_all_parameters(self):
        params = call_params()
        validator = RequestValidator(SETTINGS.auth_token)
        path = "/api/telephony/voice"
        sig = validator.compute_signature(SETTINGS.url(path), params)
        self.assertTrue(valid_signature(SETTINGS, path, sig, params))
        self.assertFalse(valid_signature(SETTINGS, path, sig, {**params, "From": "+12345678901"}))
        self.assertFalse(valid_signature(SETTINGS, "/api/telephony/call-status", sig, params))
        self.assertFalse(valid_signature(SETTINGS, path, None, params))
        for websocket in [False, True]:
            for suffix in ["", "/"]:
                url = SETTINGS.url("/api/telephony/media", websocket=websocket) + suffix
                signature = validator.compute_signature(url, {})
                self.assertTrue(valid_signature(SETTINGS, "/api/telephony/media", signature, websocket=True))

    def test_duplicate_reservations_reuse_token_and_concurrency_is_bounded(self):
        registry = CallRegistry(SETTINGS)
        call = registry.reserve(call_params())
        self.assertIs(registry.reserve(call_params()), call)
        with self.assertRaises(OverflowError):
            registry.reserve(call_params("CA" + "d" * 32))
        with self.assertRaises(PermissionError):
            registry.reserve({**call_params(), "From": "+12345678901"})

    def test_stream_tokens_are_bound_to_call_account_and_audio_format(self):
        registry = CallRegistry(SETTINGS)
        call = registry.reserve(call_params())
        for update in [{"customParameters": {"session": "wrong"}},
                       {"accountSid": "AC" + "f" * 32},
                       {"mediaFormat": {"encoding": "linear16", "sampleRate": 16000, "channels": 1}}]:
            with self.subTest(update=update), self.assertRaises((PermissionError, ValueError)):
                registry.attach({**stream_start(call), **update})
        self.assertIs(registry.attach(stream_start(call)), call)
        with self.assertRaises(PermissionError):
            registry.attach(stream_start(call))

    def test_terminal_state_never_regresses_and_pending_calls_expire(self):
        now = [0]
        registry = CallRegistry(SETTINGS, clock=lambda: now[0])
        call = registry.reserve(call_params())
        registry.update(CALL, "in-progress")
        registry.update(CALL, "ringing")
        self.assertEqual(call.state, "in-progress")
        registry.update(CALL, "completed")
        registry.update(CALL, "in-progress")
        self.assertEqual(call.state, "completed")
        self.assertTrue(call.stop.is_set())
        second = registry.reserve(call_params("CA" + "d" * 32))
        now[0] = 61
        registry.prune()
        self.assertTrue(second.stop.is_set())
        with self.assertRaises(PermissionError):
            registry.attach(stream_start(second))


class Socket:
    def __init__(self):
        self.incoming = asyncio.Queue()
        self.sent = asyncio.Queue()
        self.history = []

    async def receive(self):
        return await self.incoming.get()

    async def send_json(self, message):
        self.history.append(message)
        self.sent.put_nowait(message)


class TwilioPlaybackTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        registry = CallRegistry(SETTINGS)
        call = registry.reserve(call_params())
        registry.attach(stream_start(call))
        self.socket = Socket()
        self.transport = TwilioVoiceTransport(self.socket, call)
        self.transport.start()
        await self.transport.receive()  # Consume setup.
        self.sequence = 1
        await self.transport.send_event({"type": "response_started", "response_id": 1})

    async def asyncTearDown(self):
        await self.transport.aclose()

    def feed(self, event, **fields):
        self.sequence += 1
        self.socket.incoming.put_nowait({"text": json.dumps({
            "event": event, "streamSid": STREAM, "sequenceNumber": str(self.sequence), **fields,
        })})

    async def next_mark(self):
        while True:
            message = await asyncio.wait_for(self.socket.sent.get(), 1)
            if message["event"] == "mark":
                return message["mark"]["name"]

    async def test_playback_is_bounded_and_final_mark_reports_audible_completion(self):
        audio = b"\xff" * (SEGMENT_BYTES * (MAX_PENDING_SEGMENTS + 1))
        sending = asyncio.create_task(self.transport.send_audio(VoiceAudioChunk(1, audio, "mulaw", 8000)))
        initial = [await self.next_mark() for _ in range(MAX_PENDING_SEGMENTS)]
        self.assertFalse(sending.done())
        self.assertEqual(len(self.transport.pending), MAX_PENDING_SEGMENTS)
        self.feed("mark", mark={"name": initial[0]})
        last = await self.next_mark()
        await sending
        await self.transport.send_event({"type": "tts_done", "response_id": 1})
        final = await self.next_mark()
        self.assertTrue(self.transport.inputs.empty())
        for name in [*initial[1:], last, final]:
            self.feed("mark", mark={"name": name})
        done = await asyncio.wait_for(self.transport.receive(), 1)
        self.assertEqual(done.data, {"type": "playback_done", "response_id": 1})
        payload = b"".join(base64.b64decode(m["media"]["payload"]) for m in self.socket.history if m["event"] == "media")
        self.assertEqual(payload, audio)

    async def test_audio_window_bridges_network_delay_before_playback_marks_return(self):
        # Four 100 ms segments cover a 240 ms round trip plus playback of the first mark.
        # No marks have returned yet; the old two-segment window stalls here.
        audio = b"\xff" * 3200
        await asyncio.wait_for(self.transport.send_audio(VoiceAudioChunk(1, audio, "mulaw", 8000)), 1)
        self.assertEqual(len(self.transport.pending), 4)
        payload = b"".join(base64.b64decode(m["media"]["payload"]) for m in self.socket.history if m["event"] == "media")
        self.assertEqual(payload, audio)

    async def test_acknowledgment_pause_retains_audio_without_clear(self):
        await self.transport.send_event({"type": "playback_pause", "response_id": 1, "utterance_id": 4})
        sending = asyncio.create_task(self.transport.send_audio(VoiceAudioChunk(1, b"\xff" * 160, "mulaw", 8000)))
        await self.transport.receive()  # Pause acknowledgment.
        self.assertEqual(self.socket.history, [])
        await self.transport.send_event({"type": "playback_resume", "response_id": 1, "utterance_id": 4})
        await asyncio.wait_for(sending, 1)
        self.assertEqual([m["event"] for m in self.socket.history], ["media", "mark"])

    async def test_clear_marks_cannot_complete_successor_or_send_canceled_audio(self):
        await self.transport.send_audio(VoiceAudioChunk(1, b"\xff" * (SEGMENT_BYTES * MAX_PENDING_SEGMENTS), "mulaw", 8000))
        await self.transport.send_event({"type": "tts_done", "response_id": 1})
        old = list(self.transport.pending)
        await self.transport.send_event({"type": "response_cancelled", "response_id": 1})
        await self.transport.send_event({"type": "response_started", "response_id": 2})
        count = len(self.socket.history)
        await self.transport.send_audio(VoiceAudioChunk(1, b"old", "mulaw", 8000))
        self.assertEqual(len(self.socket.history), count)
        for name in old:
            self.feed("mark", mark={"name": name})
        self.feed("media", media={"track": "inbound", "timestamp": "20", "payload": "/w=="})
        event = await asyncio.wait_for(self.transport.receive(), 1)
        self.assertEqual((event.kind, event.audio), ("audio", b"\xff"))

    async def test_malformed_audio_or_foreign_stream_terminates_without_provider_input(self):
        self.feed("media", media={"track": "inbound", "timestamp": "20", "payload": "not-base64"})
        event = await asyncio.wait_for(self.transport.receive(), 1)
        self.assertEqual(event.kind, "disconnect")
        self.assertTrue(self.transport.failed)

    async def test_cancel_during_last_frame_does_not_reinsert_a_stale_mark(self):
        entered, release = asyncio.Event(), asyncio.Event()
        original = self.socket.send_json

        async def blocked(message):
            if message["event"] == "media":
                entered.set()
                await release.wait()
            await original(message)

        self.socket.send_json = blocked
        sending = asyncio.create_task(self.transport.send_audio(VoiceAudioChunk(1, b"\xff" * 160, "mulaw", 8000)))
        await entered.wait()
        cancel = asyncio.create_task(self.transport.send_event({"type": "response_cancelled", "response_id": 1}))
        await asyncio.sleep(0)
        self.assertIsNone(self.transport.response_id)
        release.set()
        await asyncio.gather(sending, cancel)
        self.assertEqual([m["event"] for m in self.socket.history], ["media", "clear"])
        self.assertEqual(self.transport.pending, {})

    async def test_close_wakes_a_paused_sender_and_discards_retained_audio(self):
        await self.transport.send_event({"type": "playback_pause", "response_id": 1, "utterance_id": 4})
        sending = asyncio.create_task(self.transport.send_audio(VoiceAudioChunk(1, b"\xff" * 160, "mulaw", 8000)))
        await self.transport.aclose()
        await asyncio.wait_for(sending, 1)
        self.assertEqual(self.socket.history, [])

    async def test_input_buffer_covers_startup_but_has_a_byte_and_duration_bound(self):
        for _ in range(50):
            self.transport._enqueue(VoiceInput("audio", audio=b"\xff" * 3200))
        with self.assertRaises(BufferError):
            self.transport._enqueue(VoiceInput("audio", audio=b"\xff"))
        self.assertEqual(self.transport.input_audio_bytes, 160000)
        await self.transport.receive()
        self.assertEqual(self.transport.input_audio_bytes, 156800)


class TwilioRuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def test_shutdown_cancels_call_tasks_and_closes_owned_http_client(self):
        runtime = TelephonyRuntime(SETTINGS, object(), "test-key")
        call = runtime.registry.reserve(call_params())
        task = asyncio.create_task(asyncio.Event().wait())
        runtime.sessions.add(task)
        await runtime.aclose()
        self.assertTrue(task.done())
        self.assertTrue(call.stop.is_set())
        self.assertTrue(runtime.http_client.is_closed)

    async def test_disabled_phone_settings_do_not_break_chat_startup(self):
        app = FastAPI()
        with patch.dict(os.environ, {"TWILIO_ENABLED": "false", "TWILIO_MAX_CALL_SECONDS": "not-a-number"}):
            configure_telephony(app, object(), "")
        self.assertIsNone(app.state.telephony)


class TwilioRouteTests(unittest.TestCase):
    def setUp(self):
        self.agent = SimpleNamespace(forget_thread=AsyncMock())
        self.app = FastAPI()
        self.app.include_router(router)
        self.app.state.telephony = SimpleNamespace(
            settings=SETTINGS, registry=CallRegistry(SETTINGS), voice_agent=self.agent,
            sarvam=None, sessions=set(),
        )
        self.client = TestClient(self.app)

    def post(self, path, data):
        signature = RequestValidator(SETTINGS.auth_token).compute_signature(SETTINGS.url(path), data)
        return self.client.post(path, data=data, headers={"X-Twilio-Signature": signature, "Host": "untrusted.example"})

    def test_twiml_uses_signed_admission_and_no_provider_work(self):
        path = "/api/telephony/voice"
        self.assertEqual(self.client.post(path, data=call_params()).status_code, 403)
        response = self.post(path, call_params())
        self.assertEqual(response.status_code, 200)
        root = ElementTree.fromstring(response.text)
        stream = root.find("Connect/Stream")
        self.assertEqual(stream.attrib["url"], SETTINGS.url("/api/telephony/media", websocket=True))
        self.assertEqual(stream.find("Parameter").attrib["value"], self.app.state.telephony.registry.calls[CALL].token)
        self.assertIsNotNone(root.find("Hangup"))
        self.assertEqual(self.post(path, {**call_params(), "From": "+12345678901"}).text.count("<Reject"), 1)

    def test_signed_terminal_callback_is_idempotent(self):
        call = self.app.state.telephony.registry.reserve(call_params())
        params = {"AccountSid": SETTINGS.account_sid, "CallSid": CALL, "CallStatus": "completed"}
        for _ in range(2):
            self.assertEqual(self.post("/api/telephony/call-status", params).status_code, 204)
        self.assertTrue(call.stop.is_set())

    def test_unsigned_media_socket_is_rejected_before_provider_work(self):
        from starlette.websockets import WebSocketDisconnect

        with self.assertRaises(WebSocketDisconnect), self.client.websocket_connect("/api/telephony/media"):
            pass
        self.assertEqual(self.app.state.telephony.sessions, set())

    def test_call_deadline_ends_a_stalled_response_and_releases_admission(self):
        runtime = self.app.state.telephony
        runtime.settings = replace(SETTINGS, max_call_seconds=0.02)
        runtime.sarvam = FakeSarvamClient(QueueStt(), FakeTtsSocket())
        admission = runtime.registry.reserve(call_params())
        signature = RequestValidator(SETTINGS.auth_token).compute_signature(SETTINGS.url("/api/telephony/media", websocket=True), {})
        with patch("backend.voice_session.socket.getaddrinfo", return_value=[]), self.client.websocket_connect(
            "/api/telephony/media", headers={"X-Twilio-Signature": signature},
        ) as ws:
            ws.send_json({"event": "connected", "protocol": "Call", "version": "1.0.0"})
            ws.send_json({"event": "start", "sequenceNumber": "1", "streamSid": STREAM, "start": stream_start(admission)})
            self.assertEqual(ws.receive()["type"], "websocket.close")
        self.assertTrue(admission.stop.is_set())
        self.agent.forget_thread.assert_awaited_once_with("phone:" + CALL)
        self.assertEqual(runtime.sessions, set())

    def test_real_shared_session_over_twilio_frames_greets_and_answers_then_cleans_up(self):
        stt = QueueStt()
        tts = FakeTtsSocket()
        runtime = self.app.state.telephony
        runtime.sarvam = FakeSarvamClient(stt, tts)
        service = runtime.sarvam.speech_to_text_realtime_streaming
        service.connect = Mock(wraps=service.connect)
        queries = []
        heard_first_sentence = threading.Event()
        answer_completed = threading.Event()

        async def answer(text, **kwargs):
            queries.append((text, kwargs))
            yield {"type": "tool_call", "name": "read_source", "args": "{source_id: private-tool-args}"}
            yield {"type": "token", "content": "The grounded answer. "}
            if not await asyncio.to_thread(heard_first_sentence.wait, 2):
                raise AssertionError("Phone audio waited for the complete answer")
            answer_completed.set()
            yield {"type": "done"}

        self.agent.astream = answer

        async def audio():
            await tts.events.put(AudioOutput(data=AudioOutputData(
                content_type="audio/mulaw", audio=base64.b64encode(b"\xff" * 160).decode(),
            )))

        async def convert(_text):
            if queries:
                await audio()

        async def flush():
            if not queries:
                await audio()
            await tts.events.put(EventResponse(data=EventResponseData(event_type="final")))

        async def transcribe(_audio):
            await stt.events.put(type("RealtimeTranscriptFinal", (), {
                "text": "What are the hostel fees?", "language": "en-IN", "language_confidence": 0.99,
            })())

        tts.convert.side_effect = convert
        tts.flush.side_effect = flush
        stt.send_realtime_audio_input.side_effect = transcribe
        self.post("/api/telephony/voice", call_params())
        admission = runtime.registry.calls[CALL]
        signature = RequestValidator(SETTINGS.auth_token).compute_signature(SETTINGS.url("/api/telephony/media", websocket=True), {})
        with patch("backend.voice_session.socket.getaddrinfo", return_value=[]), self.client.websocket_connect(
            "/api/telephony/media", headers={"X-Twilio-Signature": signature},
        ) as ws:
            ws.send_json({"event": "connected", "protocol": "Call", "version": "1.0.0"})
            ws.send_json({"event": "start", "sequenceNumber": "1", "streamSid": STREAM, "start": stream_start(admission)})
            sequence = 1
            for turn in range(2):
                marks = 0
                while marks < 2:
                    packet = ws.receive_json()
                    if turn == 1 and packet["event"] == "media":
                        self.assertFalse(answer_completed.is_set())
                        heard_first_sentence.set()
                    if packet["event"] == "mark":
                        marks += 1
                        sequence += 1
                        ws.send_json({"event": "mark", "streamSid": STREAM, "sequenceNumber": str(sequence), "mark": packet["mark"]})
                if turn == 0:
                    sequence += 1
                    ws.send_json({"event": "media", "streamSid": STREAM, "sequenceNumber": str(sequence),
                                  "media": {"track": "inbound", "timestamp": "20", "payload": "/w=="}})
            sequence += 1
            ws.send_json({"event": "stop", "streamSid": STREAM, "sequenceNumber": str(sequence),
                          "stop": {"accountSid": SETTINGS.account_sid, "callSid": CALL}})
            ws.receive()  # Wait for server close and lifecycle cleanup.
        self.assertEqual(queries[0][0], "What are the hostel fees?")
        self.assertTrue(heard_first_sentence.is_set())
        self.assertTrue(answer_completed.is_set())
        self.assertEqual(queries[0][1]["config"]["configurable"]["retrieval_provider"], "llm_batch")
        self.assertEqual(tts.convert.await_args_list[-1].args[0], "The grounded answer.")
        self.assertFalse(any("private-tool-args" in call.args[0] for call in tts.convert.await_args_list))
        self.assertEqual(queries[0][1]["config"]["configurable"]["thread_id"], "phone:" + CALL)
        self.agent.forget_thread.assert_awaited_once_with("phone:" + CALL)
        self.assertTrue(admission.stop.is_set())
        self.assertEqual(runtime.sessions, set())
        settings = service.connect.call_args.kwargs
        self.assertEqual((settings["encoding"], settings["sample_rate"], settings["silence_duration_ms"]),
                         ("mulaw", "8000", "500"))


if __name__ == "__main__":
    unittest.main()
