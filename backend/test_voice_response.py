import asyncio
import base64
import unittest
from unittest.mock import AsyncMock

from sarvamai.types.audio_output import AudioOutput
from sarvamai.types.audio_output_data import AudioOutputData
from sarvamai.types.event_response import EventResponse
from sarvamai.types.event_response_data import EventResponseData

from backend.voice_response import VoiceResponse, synthesize_response
from backend.voice_transport import PHONE_AUDIO


class FakeTtsSocket:
    def __init__(self):
        self.configure = AsyncMock()
        self.convert = AsyncMock()
        self.flush = AsyncMock()
        self.events = asyncio.Queue()
        self.events.put_nowait(EventResponse(data=EventResponseData(event_type="final")))

    async def recv(self):
        return await self.events.get()


class FakeConnection:
    def __init__(self, socket):
        self.socket = socket

    async def __aenter__(self):
        return self.socket

    async def __aexit__(self, _exc_type, _exc, _traceback):
        return None


class FakeStreamingService:
    def __init__(self, socket):
        self.socket = socket

    def connect(self, **_kwargs):
        return FakeConnection(self.socket)


class FakeSarvamClient:
    def __init__(self, socket):
        self.text_to_speech_streaming = FakeStreamingService(socket)


class VoiceResponseSynthesisTests(unittest.IsolatedAsyncioTestCase):
    async def synthesize(self, content):
        response = VoiceResponse(response_id=7, language="en-IN")
        tts = FakeTtsSocket()
        sent_json = []

        async def producer():
            for chunk in content:
                await response.put_text(chunk)
            await response.text_queue.put(None)

        await asyncio.wait_for(
            synthesize_response(
                response,
                FakeSarvamClient(tts),
                lambda message: self._append(sent_json, message),
                AsyncMock(),
                lambda _response: None,
                producer,
            ),
            timeout=1,
        )
        return tts, sent_json

    @staticmethod
    async def _append(target, value):
        target.append(value)

    async def test_punctuation_only_tail_is_not_converted_and_response_completes(self):
        tts, sent_json = await self.synthesize(["The answer is 42. ", "...?!  "])

        self.assertEqual([call.args[0] for call in tts.convert.await_args_list], ["The answer is 42."])
        tts.flush.assert_awaited_once()
        self.assertIn({"type": "tts_done", "response_id": 7}, sent_json)

    async def test_unicode_and_numeric_utterances_are_preserved(self):
        tts, _sent_json = await self.synthesize(["ਸਤ ਸ੍ਰੀ ਅਕਾਲ। ", "12345"])

        self.assertEqual(
            [call.args[0] for call in tts.convert.await_args_list],
            ["ਸਤ ਸ੍ਰੀ ਅਕਾਲ।", "12345"],
        )
        tts.flush.assert_awaited_once()

    async def test_phone_synthesis_preserves_raw_mulaw_without_browser_framing(self):
        tts = FakeTtsSocket()
        tts.events = asyncio.Queue()
        audio = b"\xff\x7f\x00\x80" * 40
        tts.events.put_nowait(AudioOutput(data=AudioOutputData(
            content_type="audio/mulaw", audio=base64.b64encode(audio).decode(),
        )))
        tts.events.put_nowait(EventResponse(data=EventResponseData(event_type="final")))
        response = VoiceResponse(7, "hi-IN")

        async def producer():
            await response.put_text("नमस्ते")
            await response.text_queue.put(None)

        output = AsyncMock()
        await synthesize_response(
            response, FakeSarvamClient(tts), AsyncMock(), output, lambda _: None,
            producer, audio_format=PHONE_AUDIO,
        )
        tts.configure.assert_awaited_once_with(
            target_language_code="hi-IN", speaker="shubh",
            output_audio_codec="mulaw", speech_sample_rate=8000,
        )
        chunk = output.await_args.args[0]
        self.assertEqual((chunk.response_id, chunk.audio, chunk.encoding, chunk.sample_rate),
                         (7, audio, "mulaw", 8000))


if __name__ == "__main__":
    unittest.main()
