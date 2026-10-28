import asyncio
import base64
import io
import json
import os
import struct
import unittest
import wave
from unittest.mock import AsyncMock, patch

from sarvamai.types.audio_output import AudioOutput
from sarvamai.types.audio_output_data import AudioOutputData
from sarvamai.types.event_response import EventResponse
from sarvamai.types.event_response_data import EventResponseData
from sarvamai.types.realtime_end import RealtimeEnd
from sarvamai.types.realtime_error import RealtimeError

from backend import voice_pipeline as voice_pipeline_module
from backend.voice_activity import CHECK_INS, VoiceActivity
from backend.voice_interruption import InterruptionDecision, VoiceInterruptionClassifier
from backend.voice_response import VoiceResponse, pcm16_to_wav


class FakeConnection:
    def __init__(self, socket):
        self.socket = socket

    async def __aenter__(self):
        return self.socket

    async def __aexit__(self, _exc_type, _exc, _traceback):
        return None


class FakeSttSocket:
    def __init__(self, events=None):
        self.events = events or []
        self.start_listening = AsyncMock(
            side_effect=AssertionError("start_listening blocks until the socket closes")
        )

    async def __aiter__(self):
        for event in self.events:
            yield event
        await asyncio.Event().wait()
        yield


class FakeTtsSocket:
    def __init__(self, events=None):
        self.events = asyncio.Queue()
        for event in events or []:
            self.events.put_nowait(event)
        self.start_listening = AsyncMock(
            side_effect=AssertionError("start_listening blocks until the socket closes")
        )
        self.configure = AsyncMock()
        self.convert = AsyncMock()
        self.flush = AsyncMock()

    async def recv(self):
        return await self.events.get()


class FakeStreamingService:
    def __init__(self, socket):
        self.socket = socket

    def connect(self, **_kwargs):
        return FakeConnection(self.socket)


class FakeSarvamClient:
    def __init__(self, stt_socket, tts_socket):
        self.speech_to_text_realtime_streaming = FakeStreamingService(stt_socket)
        self.text_to_speech_streaming = FakeStreamingService(tts_socket)


class FakeBrowserWebSocket:
    def __init__(self):
        self.accepted = False
        self.sent_json = []
        self.incoming = asyncio.Queue()

    async def accept(self):
        self.accepted = True

    async def send_json(self, message):
        self.sent_json.append(message)

    async def send_bytes(self, message):
        pass

    async def receive(self):
        return await self.incoming.get()


class VoicePipelineConnectionTests(unittest.IsolatedAsyncioTestCase):
    async def test_consecutive_final_transcripts_do_not_stop_stt_after_cancellation(self):
        events = [type("RealtimeTranscriptFinal", (), {
            "text": text, "language": "en-IN", "language_confidence": 0.99,
        })() for text in ("First question", "Second question", "Third question")]
        answered = asyncio.Event()
        calls = []

        class Agent:
            async def astream(self, text, **kwargs):
                calls.append(text)
                answered.set()
                yield {"type": "done"}

        class Browser(FakeBrowserWebSocket):
            def __init__(self):
                super().__init__()
                self.started = False

            async def receive(self):
                if not self.started:
                    self.started = True
                    return {"text": json.dumps({"type": "start_call", "protocol_version": 2})}
                await answered.wait()
                return {"text": json.dumps({"type": "end_call"})}

        browser = Browser()
        client = FakeSarvamClient(FakeSttSocket(events), FakeTtsSocket())
        with patch.object(voice_pipeline_module, "sarvam_client", client), patch.object(
            voice_pipeline_module.socket, "getaddrinfo", return_value=[],
        ):
            await asyncio.wait_for(voice_pipeline_module.voice_pipeline(browser, Agent()), 1)
        self.assertEqual([msg["text"] for msg in browser.sent_json if msg["type"] == "transcript"], [event.text for event in events])
        self.assertEqual(calls, ["Third question"])

    async def test_check_in_waits_until_browser_finishes_playback(self):
        audio_sent, checked_in = asyncio.Event(), asyncio.Event()
        tts = FakeTtsSocket(events=[
            AudioOutput(data=AudioOutputData(
                content_type="audio/wav", audio=base64.b64encode(b"\x01\x02").decode("ascii"),
            )),
            EventResponse(data=EventResponseData(event_type="final")),
        ])
        self_test = self

        class Browser(FakeBrowserWebSocket):
            def __init__(self):
                super().__init__()
                self.step = 0

            async def send_bytes(self, message):
                audio_sent.set()

            async def send_json(self, message):
                await super().send_json(message)
                if message["type"] == "check_in":
                    checked_in.set()

            async def receive(self):
                self.step += 1
                if self.step == 1:
                    return {"text": json.dumps({"type": "start_call", "protocol_version": 2})}
                if self.step == 2:
                    return {"text": json.dumps({"type": "tts", "text": "Initial speech"})}
                if self.step == 3:
                    await audio_sent.wait()
                    return {"text": json.dumps({"type": "playback_started", "response_id": 1})}
                if self.step == 4:
                    with self_test.assertRaises(TimeoutError):
                        await asyncio.wait_for(checked_in.wait(), 0.05)
                    return {"text": json.dumps({"type": "playback_done", "response_id": 1})}
                await checked_in.wait()
                return {"text": json.dumps({"type": "end_call"})}

        original_wait = VoiceActivity.wait_for_idle
        async def short_wait(activity):
            await original_wait(activity, seconds=0.01)

        browser = Browser()
        with patch.object(voice_pipeline_module, "sarvam_client", FakeSarvamClient(FakeSttSocket(), tts)), patch.object(
            voice_pipeline_module.socket, "getaddrinfo", return_value=[],
        ), patch.object(VoiceActivity, "wait_for_idle", short_wait):
            await asyncio.wait_for(voice_pipeline_module.voice_pipeline(browser, object()), 2)
        self.assertIn({"type": "tts_done", "response_id": 1}, browser.sent_json)
        self.assertIn({"type": "check_in", "response_id": 2, "text": CHECK_INS["en-IN"], "language_code": "en-IN"}, browser.sent_json)

    async def test_punjabi_check_in_waits_for_answer_and_never_cancels_it(self):
        started, release, checked_in, spoken = (asyncio.Event() for _ in range(4))
        tts = FakeTtsSocket()
        cancelled = []
        language_event = type("RealtimeTranscriptFinal", (), {
            "text": "ਸਤ ਸ੍ਰੀ ਅਕਾਲ", "language": "pa-IN", "language_confidence": 0.99,
        })()

        class Agent:
            async def astream(self, text, **kwargs):
                started.set()
                try:
                    await release.wait()
                    yield {"type": "token", "content": "ਪੰਜਾਬੀ ਜਵਾਬ"}
                    yield {"type": "done"}
                except asyncio.CancelledError:
                    cancelled.append(True)
                    raise

        class Browser(FakeBrowserWebSocket):
            def __init__(self):
                super().__init__()
                self.step = 0

            async def send_json(self, message):
                await super().send_json(message)
                if message["type"] == "check_in":
                    checked_in.set()

            async def receive(self):
                self.step += 1
                if self.step == 1:
                    return {"text": json.dumps({"type": "start_call", "protocol_version": 2})}
                if self.step == 2:
                    await started.wait()
                    return {"text": json.dumps({"type": "tts", "text": "English interruption"})}
                with self_test.assertRaises(TimeoutError):
                    await asyncio.wait_for(checked_in.wait(), 0.05)
                release.set()
                await checked_in.wait()
                await spoken.wait()
                return {"text": json.dumps({"type": "end_call"})}

        async def flush():
            await tts.events.put(EventResponse(data=EventResponseData(event_type="final")))
            if tts.convert.await_count > 1:
                spoken.set()

        original_wait = VoiceActivity.wait_for_idle
        async def short_wait(activity):
            await original_wait(activity, seconds=0.01)

        self_test = self
        browser = Browser()
        tts.flush.side_effect = flush
        with patch.object(voice_pipeline_module, "sarvam_client", FakeSarvamClient(FakeSttSocket([language_event]), tts)), patch.object(
            voice_pipeline_module.socket, "getaddrinfo", return_value=[],
        ), patch.object(VoiceActivity, "wait_for_idle", short_wait):
            await asyncio.wait_for(voice_pipeline_module.voice_pipeline(browser, Agent()), 2)
        self.assertEqual(cancelled, [])
        texts = [call.args[0] for call in tts.convert.await_args_list]
        self.assertEqual(texts[0], "ਪੰਜਾਬੀ ਜਵਾਬ")
        self.assertEqual(" ".join(texts[1:]), CHECK_INS["pa-IN"])
        self.assertIn({"type": "check_in", "response_id": 2, "text": CHECK_INS["pa-IN"], "language_code": "pa-IN"}, browser.sent_json)

    async def test_stable_language_is_shared_by_agent_and_serialized_tts(self):
        turns = [
            ("What are the hostel fees?", "en-IN", 0.99),
            ("Tell me about hostel charges", "hi-IN", 0.01),
            ("Yes", "hi-IN", 0.99),
            ("मुझे हॉस्टल के बारे में बताओ", "hi-IN", 0.99),
            ("मुझे एडमिशन के बारे में बताओ", "hi-IN", 0.99),
            ("Please respond in Punjabi", "en-IN", 0.99),
        ]
        handled = asyncio.Queue()
        flushed = asyncio.Event()

        class Stt(FakeSttSocket):
            async def __aiter__(self):
                for text, language, confidence in turns:
                    yield type("RealtimeTranscriptFinal", (), {
                        "text": text, "language": language, "language_confidence": confidence,
                    })()
                    await handled.get()
                await asyncio.Event().wait()

        class Agent:
            def __init__(self):
                self.languages = []

            async def astream(self, text, **kwargs):
                self.languages.append(kwargs["config"]["configurable"]["response_language"])
                yield {"type": "token", "content": "Synthetic response"}
                yield {"type": "done", "full_content": "Synthetic response"}
                await handled.put(True)

        class Browser(FakeBrowserWebSocket):
            def __init__(self):
                super().__init__()
                self.started = False

            async def receive(self):
                if not self.started:
                    self.started = True
                    return {"text": json.dumps({"type": "start_call", "protocol_version": 2})}
                await flushed.wait()
                return {"text": json.dumps({"type": "end_call"})}

        agent, browser, tts = Agent(), Browser(), FakeTtsSocket()
        order = []
        async def configure(**kwargs):
            order.append(("language", kwargs["target_language_code"]))

        async def convert(text):
            order.append(("text", text))

        async def flush():
            if len(agent.languages) == len(turns):
                flushed.set()

        tts.configure.side_effect = configure
        tts.convert.side_effect = convert
        tts.flush.side_effect = flush
        with patch.object(voice_pipeline_module, "sarvam_client", FakeSarvamClient(Stt(), tts)), patch.object(
            voice_pipeline_module.socket, "getaddrinfo", return_value=[],
        ):
            await asyncio.wait_for(voice_pipeline_module.voice_pipeline(browser, agent), 2)
        expected = ["en-IN", "en-IN", "en-IN", "en-IN", "hi-IN", "pa-IN"]
        self.assertEqual(agent.languages, expected)
        self.assertEqual([event["language_code"] for event in browser.sent_json if event["type"] == "transcript"], expected)
        self.assertEqual([code for kind, code in order if kind == "language"], expected)
        self.assertEqual(order[-2:], [("language", "pa-IN"), ("text", "Synthetic response")])

    async def test_marks_browser_ready_without_awaiting_sdk_listener_loops(self):
        browser = FakeBrowserWebSocket()
        stt_socket = FakeSttSocket()
        tts_socket = FakeTtsSocket()
        client = FakeSarvamClient(stt_socket, tts_socket)
        await browser.incoming.put({"text": json.dumps({"type": "start_call", "protocol_version": 2})})
        await browser.incoming.put({"text": json.dumps({"type": "end_call"})})

        with patch.dict(os.environ, {"VOICE_INTERRUPTION_ENABLED": "false", "VOICE_INTERRUPTION_GRACE_MS": "350"}), patch.object(voice_pipeline_module, "sarvam_client", client), patch.object(
            voice_pipeline_module.socket,
            "getaddrinfo",
            return_value=[],
        ):
            await asyncio.wait_for(
                voice_pipeline_module.voice_pipeline(browser, object()),
                timeout=1,
            )

        self.assertTrue(browser.accepted)
        self.assertIn({"type": "voice_ready", "protocol_version": 2, "interruption_enabled": False, "grace_ms": 350}, browser.sent_json)
        stt_socket.start_listening.assert_not_awaited()
        tts_socket.start_listening.assert_not_awaited()
        tts_socket.configure.assert_not_awaited()

    async def test_passes_call_thread_id_to_voice_agent(self):
        await self.check_call_provider("decisions")

    async def test_passes_selected_jev_provider_to_voice_agent(self):
        await self.check_call_provider("jev")

    async def check_call_provider(self, provider):
        transcript_event = type(
            "RealtimeTranscriptFinal",
            (),
            {"text": "Hello", "language": "en-IN"},
        )()
        stt_socket = FakeSttSocket(events=[transcript_event])
        tts_socket = FakeTtsSocket()
        client = FakeSarvamClient(stt_socket, tts_socket)
        agent_called = asyncio.Event()

        class FakeAgent:
            def __init__(self):
                self.calls = []

            async def astream(self, text, **kwargs):
                self.calls.append((text, kwargs))
                agent_called.set()
                yield {"type": "token", "content": "Hi there"}
                yield {"type": "done", "full_content": ""}

        class CoordinatedBrowser(FakeBrowserWebSocket):
            def __init__(self):
                super().__init__()
                self.receive_count = 0

            async def receive(self):
                self.receive_count += 1
                if self.receive_count == 1:
                    return {
                        "text": json.dumps(
                            {"type": "start_call", "protocol_version": 2, "thread_id": "voice-call-123"}
                        )
                    }
                await asyncio.wait_for(agent_called.wait(), timeout=1)
                return {"text": json.dumps({"type": "end_call"})}

        browser = CoordinatedBrowser()
        agent = FakeAgent()

        with patch.object(voice_pipeline_module, "sarvam_client", client), patch.object(
            voice_pipeline_module.socket,
            "getaddrinfo",
            return_value=[],
        ):
            await asyncio.wait_for(
                voice_pipeline_module.voice_pipeline(browser, agent, provider),
                timeout=1,
            )

        self.assertEqual(
            agent.calls,
            [
                (
                    "Hello",
                    {"config": {"configurable": {
                        "thread_id": "voice-call-123", "response_language": "en-IN",
                        "retrieval_provider": provider,
                    }}},
                )
            ],
        )
        self.assertIn({"type": "transcript", "response_id": 1, "text": "Hello", "language_code": "en-IN"}, browser.sent_json)
        self.assertIn({"type": "agent_token", "response_id": 1, "content": "Hi there"}, browser.sent_json)

    async def test_wraps_each_pcm_chunk_as_playable_wav_for_streaming(self):
        wav_header = pcm16_to_wav(b"")
        pcm_audio = b"\x01\x02\x03\x04"
        tts_socket = FakeTtsSocket(events=[
            AudioOutput(data=AudioOutputData(
                content_type="audio/wav",
                audio=base64.b64encode(wav_header).decode("ascii"),
            )),
            AudioOutput(data=AudioOutputData(
                content_type="audio/wav",
                audio=base64.b64encode(pcm_audio).decode("ascii"),
            )),
            EventResponse(data=EventResponseData(event_type="final")),
        ])
        client = FakeSarvamClient(FakeSttSocket(), tts_socket)
        audio_sent = asyncio.Event()

        class AudioBrowser(FakeBrowserWebSocket):
            def __init__(self):
                super().__init__()
                self.receive_count = 0
                self.sent_audio = []

            async def receive(self):
                self.receive_count += 1
                if self.receive_count == 1:
                    return {"text": json.dumps({"type": "start_call", "protocol_version": 2})}
                if self.receive_count == 2:
                    return {"text": json.dumps({"type": "tts", "text": "Initial speech"})}
                await asyncio.wait_for(audio_sent.wait(), timeout=1)
                return {"text": json.dumps({"type": "end_call"})}

            async def send_bytes(self, message):
                self.sent_audio.append(message)
                audio_sent.set()

        browser = AudioBrowser()
        with patch.object(voice_pipeline_module, "sarvam_client", client), patch.object(
            voice_pipeline_module.socket,
            "getaddrinfo",
            return_value=[],
        ):
            await asyncio.wait_for(
                voice_pipeline_module.voice_pipeline(browser, object()),
                timeout=1,
            )

        self.assertEqual(len(browser.sent_audio), 1)
        with wave.open(io.BytesIO(browser.sent_audio[0][5:]), "rb") as wav_file:
            self.assertEqual(wav_file.getframerate(), 22050)
            self.assertEqual(wav_file.getnchannels(), 1)
            self.assertEqual(wav_file.getsampwidth(), 2)
            self.assertEqual(wav_file.readframes(wav_file.getnframes()), pcm_audio)


class QueueStt(FakeSttSocket):
    def __init__(self):
        super().__init__()
        self.events = asyncio.Queue()
        self.send_realtime_audio_input = AsyncMock()
        self.send_realtime_end = AsyncMock()

    async def __aiter__(self):
        while True:
            yield await self.events.get()

    async def event(self, kind, text="", language="en-IN"):
        await self.events.put(type(kind, (), {
            "text": text, "language": language, "language_confidence": 0.99,
        })())


class TrackingConnection(FakeConnection):
    def __init__(self, socket):
        super().__init__(socket)
        self.closed = False

    async def __aexit__(self, *args):
        self.closed = True


class AutoTts(FakeTtsSocket):
    def __init__(self):
        super().__init__()
        self.convert.side_effect = self.speak
        self.flush.side_effect = self.finish

    async def speak(self, _text):
        await self.events.put(AudioOutput(data=AudioOutputData(
            content_type="audio/wav", audio=base64.b64encode(b"\x01\x02").decode("ascii"),
        )))

    async def finish(self):
        await self.events.put(EventResponse(data=EventResponseData(event_type="final")))


class OwnedStreamingService:
    def __init__(self, factory):
        self.factory = factory
        self.connections = []

    def connect(self, **kwargs):
        connection = TrackingConnection(self.factory())
        self.connections.append(connection)
        return connection


class RecordingBrowser(FakeBrowserWebSocket):
    def __init__(self):
        super().__init__()
        self.sent_audio = []
        self.changed = asyncio.Event()

    async def send_json(self, message):
        await super().send_json(message)
        self.changed.set()

    async def send_bytes(self, message):
        self.sent_audio.append(message)
        self.changed.set()

    async def command(self, kind, **kwargs):
        await self.incoming.put({"text": json.dumps({"type": kind, **kwargs})})

    async def wait_for(self, predicate):
        async def wait():
            while True:
                self.changed.clear()
                if predicate():
                    return
                await self.changed.wait()
        await asyncio.wait_for(wait(), timeout=1)

    async def event(self, kind, response_id=None, count=1):
        await self.wait_for(lambda: len([
            event for event in self.sent_json
            if event["type"] == kind and (response_id is None or event.get("response_id") == response_id)
        ]) >= count)


class RecordingAgent:
    def __init__(self, text="The hostel fees include meals."):
        self.text = text
        self.calls = []

    async def astream(self, text, **kwargs):
        self.calls.append((text, kwargs))
        yield {"type": "token", "content": self.text}
        yield {"type": "done", "full_content": self.text}


class VoiceInterruptionPipelineTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.browser = RecordingBrowser()
        self.stt = QueueStt()
        self.agent = RecordingAgent()
        self.classifier = type("Classifier", (), {})()
        self.classifier.classify = AsyncMock(return_value=InterruptionDecision("acknowledgment", None, 1))
        self.classifier.aclose = AsyncMock()
        self.client = type("Client", (), {})()
        self.client.speech_to_text_realtime_streaming = OwnedStreamingService(lambda: self.stt)
        self.client.text_to_speech_streaming = OwnedStreamingService(AutoTts)
        self.patches = [
            patch.object(voice_pipeline_module, "sarvam_client", self.client),
            patch.object(voice_pipeline_module.socket, "getaddrinfo", return_value=[]),
            patch.object(voice_pipeline_module, "VoiceInterruptionClassifier", return_value=self.classifier),
            patch.dict(os.environ, {
                "VOICE_INTERRUPTION_ENABLED": "true", "VOICE_INTERRUPTION_GRACE_MS": "10",
                "VOICE_INTERRUPTION_SPECULATIVE_PAUSE": "true",
                "VOICE_INTERRUPTION_TIMEOUT_MS": "100", "VOICE_INTERRUPTION_TRANSCRIPT_TIMEOUT_MS": "20",
            }),
        ]
        for item in self.patches:
            item.start()
        self.task = None

    async def asyncTearDown(self):
        if self.task and not self.task.done():
            await self.browser.command("end_call")
            await asyncio.wait_for(self.task, 1)
        for item in reversed(self.patches):
            item.stop()

    async def start(self, initial=True):
        await self.browser.command("start_call", protocol_version=2, thread_id="voice-test")
        self.task = asyncio.create_task(voice_pipeline_module.voice_pipeline(self.browser, self.agent))
        await self.browser.event("voice_ready")
        if initial:
            await self.stt.event("RealtimeTranscriptFinal", "What are the hostel fees?")
            await self.browser.event("tts_done", 1)

    async def utterance(self, text, language="en-IN"):
        await self.stt.event("RealtimeVadSpeechStart")
        await self.stt.event("RealtimeVadSpeechEnd")
        await self.stt.event("RealtimeTranscriptFinal", text, language)

    async def test_all_short_multilingual_acknowledgments_preserve_response_and_language(self):
        await self.start()
        for index, (text, language) in enumerate([
            ("okay", "en-IN"), ("हाँ, सुन रहा हूँ", "hi-IN"), ("ਹਾਂ, ਸੁਣ ਰਿਹਾ ਹਾਂ", "pa-IN"),
        ], 1):
            await self.utterance(text, language)
            await self.browser.event("acknowledgment", 1, count=index)
        self.assertEqual(self.classifier.classify.await_count, 3)
        self.assertEqual([call.args[0] for call in self.classifier.classify.await_args_list], [
            "okay", "हाँ, सुन रहा हूँ", "ਹਾਂ, ਸੁਣ ਰਿਹਾ ਹਾਂ",
        ])
        self.assertEqual(len(self.agent.calls), 1)
        self.assertEqual(len(self.client.text_to_speech_streaming.connections), 1)
        self.assertFalse(any(event["type"] == "response_cancelled" for event in self.browser.sent_json))
        self.assertEqual(len([event for event in self.browser.sent_json if event["type"] == "transcript"]), 1)

    async def test_no_and_what_are_classified_and_cancel_finished_generation_playback(self):
        self.classifier.classify.return_value = InterruptionDecision("take_turn", None, 1)
        await self.start()
        for response_id, text in [(2, "no"), (3, "what?")]:
            await self.utterance(text)
            await self.browser.event("tts_done", response_id)
            self.assertIn({"type": "response_cancelled", "response_id": response_id - 1}, self.browser.sent_json)
        self.assertEqual([call.args[0] for call in self.classifier.classify.await_args_list], ["no", "what?"])
        self.assertEqual([call[0] for call in self.agent.calls][1:], ["no", "what?"])
        self.assertTrue(all(connection.closed for connection in self.client.text_to_speech_streaming.connections[:-1]))

    async def test_question_context_is_labeled_generated_without_guessing_intent(self):
        self.agent.text = "Do you want to compare CSE and ECE?"
        await self.start()
        await self.utterance("okay")
        await self.browser.event("acknowledgment")
        context = self.classifier.classify.await_args.args[1]
        self.assertIsNone(context.get("answer_requested"))
        self.assertTrue(context["overlap"])
        self.assertEqual(context["assistant_text"], self.agent.text)
        self.assertEqual(context["last_user_text"], self.agent.calls[0][0])

    async def test_quoted_question_does_not_force_acknowledgment_to_take_turn(self):
        self.agent.text = 'You asked "What are the fees?" The hostel fees include meals.'
        await self.start()
        await self.utterance("okay")
        await self.browser.event("acknowledgment", 1)
        context = self.classifier.classify.await_args.args[1]
        self.assertIsNone(context.get("answer_requested"))
        self.assertEqual(context["assistant_text"], self.agent.text)

    async def test_generated_follow_up_does_not_override_classifier_acknowledgment(self):
        client = AsyncMock()
        client.adecide.return_value = {
            "answers": {"action": {"type": "choice", "choice": "acknowledgment"}},
        }
        classifier = VoiceInterruptionClassifier(client=client)
        self.classifier.classify = AsyncMock(wraps=classifier.classify)
        self.agent.text = "Scholarships cover tuition. Which programme are you interested in?"
        await self.start()
        await self.utterance("Ok.")
        await self.browser.event("acknowledgment", 1)
        self.assertIsNone(client.adecide.await_args.args[0]["answer_requested"])
        self.assertEqual(len(self.agent.calls), 1)
        self.assertFalse(any(event["type"] == "response_cancelled" for event in self.browser.sent_json))

    async def test_new_speech_after_empty_watchdog_clears_old_overlap(self):
        await self.start()
        await self.stt.event("RealtimeVadSpeechStart")
        await self.browser.event("playback_pause", 1)
        await self.stt.event("RealtimeVadSpeechEnd")
        await self.browser.event("playback_resume", 1)
        await self.browser.command("playback_done", response_id=1)
        await self.browser_barrier()
        await self.utterance("What are the admissions dates?")
        await self.browser.event("tts_done", 2)
        self.classifier.classify.assert_not_awaited()
        self.assertEqual(self.agent.calls[-1][0], "What are the admissions dates?")

    async def test_short_acknowledgments_keep_playing_during_slow_classification(self):
        requested = asyncio.Event()
        release = asyncio.Event()

        async def classify(*args, **kwargs):
            requested.set()
            await release.wait()
            return InterruptionDecision("acknowledgment", None, 1)

        self.classifier.classify.side_effect = classify
        await self.start()
        for index, (text, detected, vad) in enumerate([
            ("okay", "en-IN", True), ("ठीक है", "hi-IN", True), ("hmm", "en-IN", False),
        ], 1):
            requested.clear()
            release.clear()
            if vad:
                await self.utterance(text, detected)
            else:
                await self.stt.event("RealtimeTranscriptFinal", text, detected)
            await asyncio.wait_for(requested.wait(), 1)
            await asyncio.sleep(0.04)  # Past both the grace and transcript deadlines.
            release.set()
            await self.browser.event("acknowledgment", 1, count=index)
        self.assertFalse(any(event["type"] == "playback_pause" for event in self.browser.sent_json))
        self.assertEqual(len(self.agent.calls), 1)
        self.assertEqual(self.classifier.classify.await_count, 3)

    async def test_default_keeps_long_acknowledgment_playing_until_decision(self):
        os.environ.pop("VOICE_INTERRUPTION_SPECULATIVE_PAUSE", None)
        requested = asyncio.Event()
        release = asyncio.Event()

        async def classify(*args, **kwargs):
            requested.set()
            await release.wait()
            return InterruptionDecision("acknowledgment", None, 1)

        self.classifier.classify.side_effect = classify
        await self.start()
        await self.stt.event("RealtimeVadSpeechStart")
        await self.browser.event("vad_speech_start")
        await asyncio.sleep(0.04)  # Sustained VAD exceeds the configured grace.
        await self.stt.event("RealtimeVadSpeechEnd")
        await self.stt.event("RealtimeTranscriptFinal", "okay, yes, I am listening")
        await asyncio.wait_for(requested.wait(), 1)
        await asyncio.sleep(0.04)
        self.assertFalse(any(event["type"] == "playback_pause" for event in self.browser.sent_json))
        release.set()
        await self.browser.event("acknowledgment", 1)
        self.assertEqual(len(self.agent.calls), 1)

    async def test_no_speculative_pause_handles_noise_then_confirmed_interruption(self):
        os.environ["VOICE_INTERRUPTION_SPECULATIVE_PAUSE"] = "false"
        self.classifier.classify.return_value = InterruptionDecision("take_turn", None, 1)
        await self.start()
        await self.stt.event("RealtimeVadSpeechStart")
        await self.browser.event("vad_speech_start")
        await asyncio.sleep(0.04)
        await self.stt.event("RealtimeVadSpeechEnd")
        await asyncio.sleep(0.04)  # Empty speech-end watchdog must preserve playback.
        await self.browser_barrier()
        self.classifier.classify.assert_not_awaited()
        self.assertFalse(any(event["type"] in {"playback_pause", "response_cancelled"}
                             for event in self.browser.sent_json))
        await self.utterance("no")
        await self.browser.event("tts_done", 2)
        self.classifier.classify.assert_awaited_once()
        self.assertIn({"type": "response_cancelled", "response_id": 1}, self.browser.sent_json)
        self.assertEqual(self.agent.calls[-1][0], "no")

    async def test_late_acknowledgment_retains_overlap_after_watchdog_and_playback_end(self):
        await self.start()
        await self.stt.event("RealtimeVadSpeechStart")
        await self.browser.event("playback_pause", 1)
        await self.stt.event("RealtimeVadSpeechEnd")
        await self.browser.event("playback_resume", 1)
        await self.browser.command("playback_done", response_id=1)
        await self.browser_barrier()
        await self.stt.event("RealtimeTranscriptFinal", "okay")
        await self.browser.event("acknowledgment", 1)
        self.classifier.classify.assert_awaited_once()
        self.assertEqual(len(self.agent.calls), 1)

    async def test_silent_input_bypasses_classifier(self):
        await self.start(initial=False)
        await self.stt.event("RealtimeTranscriptFinal", "no")
        await self.browser.event("tts_done", 1)
        self.classifier.classify.assert_not_awaited()
        self.assertEqual(self.agent.calls[0][0], "no")

    async def test_fatal_stt_error_surfaces_safe_message_and_stops_listener(self):
        await self.start(initial=False)
        await self.stt.events.put(RealtimeError(
            code="invalid_config", is_fatal=True,
            message="secret provider detail and credential",
        ))
        await self.browser.event("voice_error")
        await self.stt.event("RealtimeTranscriptFinal", "this must not be accepted")
        await self.browser.command("end_call")
        await asyncio.wait_for(self.task, 1)

        errors = [event for event in self.browser.sent_json if event["type"] == "voice_error"]
        self.assertEqual(errors, [{
            "type": "voice_error",
            "message": "Speech recognition failed. Please reconnect.",
        }])
        self.assertNotIn("secret provider detail", str(self.browser.sent_json))
        self.assertEqual(self.agent.calls, [])
        self.assertNotIn("transcript", [event["type"] for event in self.browser.sent_json])
        self.stt.send_realtime_end.assert_awaited_once_with(RealtimeEnd())
        self.assertTrue(self.client.speech_to_text_realtime_streaming.connections[0].closed)

    async def test_nonfatal_stt_error_keeps_session_available_for_transcripts(self):
        await self.start(initial=False)
        await self.stt.events.put(RealtimeError(
            code="invalid_config", is_fatal=False, message="configuration was retained",
        ))
        await self.stt.event("RealtimeTranscriptFinal", "What are the fees?")
        await self.browser.event("tts_done", 1)

        self.assertEqual([call[0] for call in self.agent.calls], ["What are the fees?"])
        self.assertFalse(any(event["type"] == "voice_error" for event in self.browser.sent_json))

    async def test_shutdown_closes_connection_even_if_realtime_end_fails(self):
        self.stt.send_realtime_end.side_effect = OSError("socket already closed")
        await self.start(initial=False)
        await self.browser.command("end_call")
        await asyncio.wait_for(self.task, 1)

        self.stt.send_realtime_end.assert_awaited_once_with(RealtimeEnd())
        self.assertTrue(self.client.speech_to_text_realtime_streaming.connections[0].closed)

    async def test_thinking_input_supersedes_without_classifier(self):
        thinking = asyncio.Event()
        cancelled = asyncio.Event()
        class ThinkingAgent(RecordingAgent):
            async def astream(owner, text, **kwargs):
                owner.calls.append((text, kwargs))
                if len(owner.calls) == 1:
                    thinking.set()
                    try:
                        await asyncio.Event().wait()
                    finally:
                        cancelled.set()
                yield {"type": "token", "content": "A new answer."}
                yield {"type": "done"}
        self.agent = ThinkingAgent()
        await self.start(initial=False)
        await self.stt.event("RealtimeTranscriptFinal", "First question")
        await asyncio.wait_for(thinking.wait(), 1)
        await self.stt.event("RealtimeTranscriptFinal", "Second question")
        await self.browser.event("tts_done", 2)
        self.classifier.classify.assert_not_awaited()
        self.assertTrue(cancelled.is_set())
        self.assertEqual([call[0] for call in self.agent.calls], ["First question", "Second question"])

    async def test_no_transcript_watchdog_resumes_original_response(self):
        await self.start()
        await self.stt.event("RealtimeVadSpeechStart")
        await self.browser.event("playback_pause", 1)
        await self.stt.event("RealtimeVadSpeechEnd")
        await self.browser.event("playback_resume", 1)
        self.classifier.classify.assert_not_awaited()
        self.assertEqual(len(self.agent.calls), 1)
        self.assertFalse(any(event["type"] == "response_cancelled" for event in self.browser.sent_json))

    async def test_empty_final_resumes_paused_response(self):
        await self.start()
        await self.stt.event("RealtimeVadSpeechStart")
        await self.browser.event("playback_pause", 1)
        await self.stt.event("RealtimeTranscriptFinal", "")
        await self.browser.event("playback_resume", 1)
        self.classifier.classify.assert_not_awaited()

    async def test_pending_classifier_never_blocks_new_stt_and_merges_fragments(self):
        first_requested = asyncio.Event()
        cancelled = asyncio.Event()
        async def classify(text, *_args, **_kwargs):
            if text == "okay":
                first_requested.set()
                try:
                    await asyncio.Event().wait()
                finally:
                    cancelled.set()
            return InterruptionDecision("take_turn", None, 1)
        self.classifier.classify.side_effect = classify
        await self.start()
        await self.utterance("okay")
        await asyncio.wait_for(first_requested.wait(), 1)
        await self.utterance("but does it include electricity?")
        await self.browser.event("tts_done", 2)
        self.assertTrue(cancelled.is_set())
        self.assertEqual(self.classifier.classify.await_args.args[0], "okay but does it include electricity?")
        self.assertEqual(self.agent.calls[-1][0], "okay but does it include electricity?")

    async def test_pending_fragment_survives_new_speech_without_transcript(self):
        requested = asyncio.Event()
        async def classify(text, *_args, **_kwargs):
            if not requested.is_set():
                requested.set()
                await asyncio.Event().wait()
            return InterruptionDecision("take_turn", None, 1)
        self.classifier.classify.side_effect = classify
        await self.start()
        await self.utterance("wait, electricity?")
        await asyncio.wait_for(requested.wait(), 1)
        await self.stt.event("RealtimeVadSpeechStart")
        await self.stt.event("RealtimeVadSpeechEnd")
        await self.browser.event("tts_done", 2)
        self.assertEqual(self.agent.calls[-1][0], "wait, electricity?")
        self.assertEqual(self.classifier.classify.await_count, 2)

    async def test_timeout_and_request_failure_accept_caller_turn(self):
        await self.start()
        async def blocked(*args, **kwargs):
            await asyncio.Event().wait()
        self.classifier.classify.side_effect = blocked
        await self.utterance("no")
        await self.browser.event("tts_done", 2)
        self.classifier.classify.side_effect = RuntimeError("provider unavailable")
        await self.utterance("what?")
        await self.browser.event("tts_done", 3)
        self.assertEqual([call[0] for call in self.agent.calls][1:], ["no", "what?"])

    async def test_pause_then_acknowledgment_resumes_same_response(self):
        requested = asyncio.Event()
        release = asyncio.Event()
        async def classify(*args, **kwargs):
            requested.set()
            await release.wait()
            return InterruptionDecision("acknowledgment", None, 1)
        self.classifier.classify.side_effect = classify
        await self.start()
        await self.stt.event("RealtimeVadSpeechStart")
        await self.browser.event("playback_pause", 1)
        await self.stt.event("RealtimeVadSpeechEnd")
        await self.stt.event("RealtimeTranscriptFinal", "okay")
        await asyncio.wait_for(requested.wait(), 1)
        release.set()
        await self.browser.event("playback_resume", 1)
        self.assertEqual(len(self.agent.calls), 1)
        self.assertEqual(len(self.client.text_to_speech_streaming.connections), 1)

    async def test_disabled_feature_cancels_on_vad_and_accepts_all_input(self):
        os.environ["VOICE_INTERRUPTION_ENABLED"] = "false"
        await self.start()
        await self.utterance("okay")
        await self.browser.event("tts_done", 2)
        self.classifier.classify.assert_not_awaited()
        self.assertIn({"type": "response_cancelled", "response_id": 1}, self.browser.sent_json)
        self.assertEqual(self.agent.calls[-1][0], "okay")

    async def test_shutdown_closes_all_sessions_and_pending_decision(self):
        cancelled = asyncio.Event()
        async def classify(*args, **kwargs):
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()
        self.classifier.classify.side_effect = classify
        await self.start()
        await self.stt.event("RealtimeVadSpeechStart")
        await self.browser.event("playback_pause", 1)
        await self.stt.event("RealtimeVadSpeechEnd")
        await self.stt.event("RealtimeTranscriptFinal", "okay")
        await self.browser.event("interruption_pending", 1)
        await self.browser.command("end_call")
        await asyncio.wait_for(self.task, 1)
        self.assertTrue(cancelled.is_set())
        self.classifier.aclose.assert_awaited_once()
        for service in [self.client.speech_to_text_realtime_streaming, self.client.text_to_speech_streaming]:
            self.assertTrue(all(connection.closed for connection in service.connections))

    async def test_protocol_mismatch_fails_before_provider_connections(self):
        await self.browser.command("start_call", protocol_version=1)
        self.task = asyncio.create_task(voice_pipeline_module.voice_pipeline(self.browser, self.agent))
        await asyncio.wait_for(self.task, 1)
        await self.browser.event("voice_error")
        self.assertEqual(self.client.speech_to_text_realtime_streaming.connections, [])
        self.assertEqual(self.client.text_to_speech_streaming.connections, [])

    async def test_audio_header_preserves_owner_and_late_old_audio_is_rejected(self):
        self.classifier.classify.return_value = InterruptionDecision("take_turn", None, 1)
        await self.start()
        first_socket = self.client.text_to_speech_streaming.connections[0].socket
        await self.utterance("no")
        await self.browser.event("tts_done", 2)
        count = len(self.browser.sent_audio)
        await first_socket.speak("Obsolete words")
        await asyncio.sleep(0)
        self.assertEqual(len(self.browser.sent_audio), count)
        headers = [struct.unpack(">BI", packet[:5]) for packet in self.browser.sent_audio]
        self.assertEqual(headers, [(2, 1), (2, 2)])
        self.assertTrue(all(packet[5:9] == b"RIFF" for packet in self.browser.sent_audio))

    async def test_cancellation_suppressed_stale_classifier_cannot_resume_new_speech(self):
        requested = asyncio.Event()
        release = asyncio.Event()
        async def classify(text, *_args, **_kwargs):
            if text == "okay":
                requested.set()
                try:
                    await asyncio.Event().wait()
                except asyncio.CancelledError:
                    await release.wait()
                    return InterruptionDecision("acknowledgment", None, 1)
            return InterruptionDecision("take_turn", None, 1)
        self.classifier.classify.side_effect = classify
        await self.start()
        await self.stt.event("RealtimeVadSpeechStart")
        await self.browser.event("playback_pause", 1)
        await self.stt.event("RealtimeVadSpeechEnd")
        await self.stt.event("RealtimeTranscriptFinal", "okay")
        await asyncio.wait_for(requested.wait(), 1)
        await self.utterance("but electricity?")
        await self.browser.event("tts_done", 2)
        release.set()
        await asyncio.sleep(0)
        self.assertFalse(any(event["type"] == "playback_resume" and event["response_id"] == 1 for event in self.browser.sent_json))
        self.assertFalse(any(event["type"] == "acknowledgment" for event in self.browser.sent_json))


    async def browser_barrier(self):
        forwarded = asyncio.Event()
        self.stt.send_realtime_audio_input.side_effect = lambda *_args: forwarded.set()
        await self.browser.incoming.put({"bytes": b"\x00\x00"})
        await asyncio.wait_for(forwarded.wait(), 1)

    async def test_old_pause_notification_cannot_repause_acknowledged_or_new_utterance(self):
        activity = VoiceActivity()
        with patch.object(voice_pipeline_module, "VoiceActivity", return_value=activity):
            await self.start()
            await self.stt.event("RealtimeVadSpeechStart")
            await self.browser.event("playback_pause", 1)
            paused = next(event for event in self.browser.sent_json if event["type"] == "playback_pause")
            await self.stt.event("RealtimeTranscriptFinal", "okay")
            await self.browser.event("playback_resume", 1)
            await self.browser.command("playback_paused", response_id=1, utterance_id=paused["utterance_id"])
            await self.browser_barrier()
            self.assertFalse(activity.playback_paused)
            await self.stt.event("RealtimeVadSpeechStart")
            await self.browser.event("playback_pause", 1, count=2)
            await self.browser.command("playback_resumed", response_id=1, utterance_id=paused["utterance_id"])
            await self.browser_barrier()
            self.assertTrue(activity.playback_paused)
            self.assertTrue(activity.user_speaking)

    async def test_microphone_input_keeps_flowing_while_playback_is_paused(self):
        await self.start()
        await self.stt.event("RealtimeVadSpeechStart")
        await self.browser.event("playback_pause", 1)
        await self.browser_barrier()
        self.stt.send_realtime_audio_input.assert_awaited_once()
        self.assertEqual(self.stt.send_realtime_audio_input.await_args.args[0].audio, "AAA=")

    async def test_user_speech_during_check_in_cleanup_prevents_unsolicited_response(self):
        cancelling = asyncio.Event()
        release = asyncio.Event()
        finished = asyncio.Event()
        original_cancel = VoiceResponse.cancel
        async def slow_cancel(owner):
            cancelling.set()
            await release.wait()
            await original_cancel(owner)
            finished.set()
        original_wait = VoiceActivity.wait_for_idle
        async def short_wait(activity):
            await original_wait(activity, seconds=0.01)
        with patch.object(VoiceActivity, "wait_for_idle", short_wait):
            await self.start()
            with patch.object(VoiceResponse, "cancel", slow_cancel):
                await self.browser.command("playback_done", response_id=1)
                await asyncio.wait_for(cancelling.wait(), 1)
                await self.stt.event("RealtimeVadSpeechStart")
                await self.browser.event("vad_speech_start")
                release.set()
                await asyncio.wait_for(finished.wait(), 1)
                await self.browser_barrier()
                self.assertFalse(any(event["type"] == "check_in" for event in self.browser.sent_json))
                self.assertEqual(len(self.client.text_to_speech_streaming.connections), 1)

    async def test_classifier_close_failure_cannot_leak_stt_connection(self):
        self.classifier.aclose.side_effect = RuntimeError("close failed")
        await self.start()
        await self.browser.command("end_call")
        await asyncio.wait_for(self.task, 1)
        self.assertTrue(self.client.speech_to_text_realtime_streaming.connections[0].closed)
        self.assertTrue(all(connection.closed for connection in self.client.text_to_speech_streaming.connections))

    async def test_synthesis_failure_discards_the_response_and_clears_busy_flags(self):
        activity = VoiceActivity()
        socket = AutoTts()
        socket.convert.side_effect = RuntimeError("synthesis failed")
        self.client.text_to_speech_streaming = OwnedStreamingService(lambda: socket)
        with patch.object(voice_pipeline_module, "VoiceActivity", return_value=activity):
            await self.start(initial=False)
            await self.stt.event("RealtimeTranscriptFinal", "Hostel fees?")
            await self.browser.event("voice_error", 1)
            self.assertIn({"type": "response_cancelled", "response_id": 1}, self.browser.sent_json)
            self.assertFalse(activity.answering)
            self.assertFalse(activity.response_pending)
            self.assertFalse(activity.playback_active)
            self.assertTrue(self.client.text_to_speech_streaming.connections[0].closed)


    async def test_empty_final_does_not_duplicate_pending_classification(self):
        requested = asyncio.Event()
        release = asyncio.Event()
        async def classify(*args, **kwargs):
            requested.set()
            await release.wait()
            return InterruptionDecision("acknowledgment", None, 1)
        self.classifier.classify.side_effect = classify
        await self.start()
        await self.utterance("okay")
        await asyncio.wait_for(requested.wait(), 1)
        await self.stt.event("RealtimeTranscriptFinal", "")
        await self.stt.event("RealtimeTranscriptPartial", "still listening")
        await self.browser.event("partial_transcript")
        self.assertEqual(self.classifier.classify.await_count, 1)
        release.set()
        await self.browser.event("acknowledgment", 1)

    async def test_separate_calls_own_response_counters_sockets_and_input(self):
        second_stt = QueueStt()
        second_browser = RecordingBrowser()
        second_agent = RecordingAgent()
        sockets = iter([self.stt, second_stt])
        self.client.speech_to_text_realtime_streaming = OwnedStreamingService(lambda: next(sockets))
        await self.start()
        await second_browser.command("start_call", protocol_version=2, thread_id="second-call")
        second_task = asyncio.create_task(voice_pipeline_module.voice_pipeline(second_browser, second_agent))
        try:
            await second_browser.event("voice_ready")
            await second_stt.event("RealtimeTranscriptFinal", "Admissions?")
            await second_browser.event("tts_done", 1)
            self.classifier.classify.return_value = InterruptionDecision("take_turn", None, 1)
            await self.utterance("no")
            await self.browser.event("tts_done", 2)
            self.assertEqual([message["response_id"] for message in second_browser.sent_json if message["type"] == "response_started"], [1])
            self.assertEqual([call[0] for call in second_agent.calls], ["Admissions?"])
            self.assertEqual(second_agent.calls[0][1]["config"]["configurable"]["thread_id"], "second-call")
            self.assertEqual(struct.unpack(">BI", second_browser.sent_audio[0][:5]), (2, 1))
        finally:
            await second_browser.command("end_call")
            await asyncio.wait_for(second_task, 1)


if __name__ == "__main__":
    unittest.main()
