"""One response owns its generation, synthesis socket, and bounded text queue."""

import asyncio
import base64
import io
import logging
import re
import struct
import wave
from dataclasses import dataclass, field

from sarvamai.types.audio_output import AudioOutput

logger = logging.getLogger(__name__)

PROTOCOL_VERSION = 2


def _has_alphanumeric_text(text: str) -> bool:
    """Return whether a text chunk contains speakable letters or numbers."""
    return any(character.isalnum() for character in text)


def pcm16_to_wav(pcm_audio: bytes, sample_rate: int = 22050) -> bytes:
    """Wrap mono PCM16 bytes as a complete WAV file for browser decoding."""
    size = len(pcm_audio)
    return b"".join((
        b"RIFF", struct.pack("<I", 36 + size), b"WAVEfmt ",
        struct.pack("<IHHIIHH", 16, 1, 1, sample_rate, sample_rate * 2, 2, 16),
        b"data", struct.pack("<I", size), pcm_audio,
    ))


@dataclass
class VoiceResponse:
    response_id: int
    language: str
    text_queue: asyncio.Queue = field(default_factory=lambda: asyncio.Queue(maxsize=32))
    playable: asyncio.Event = field(default_factory=asyncio.Event)
    task: asyncio.Task | None = None
    cancelled: bool = False
    generated_text: str = ""
    audio_sent: bool = False
    playback_complete: bool = False

    def __post_init__(self):
        self.playable.set()

    async def put_text(self, text):
        # Bound token size as well as queue length, including oversized tool output.
        for offset in range(0, len(text), 400):
            await self.text_queue.put(text[offset:offset + 400])

    async def cancel(self):
        # Invalidate before awaiting: a collector already holding audio cannot send it.
        self.cancelled = True
        self.playable.set()
        if self.task and not self.task.done():
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)
        while not self.text_queue.empty():
            self.text_queue.get_nowait()


async def synthesize_response(response, client, send_json, send_audio, on_audio, producer, *, audio_format=None):
    """Never relabel provider output with a successor response's ID.

    The receiver retains at most one provider packet while paused and stops reading
    the socket, applying transport backpressure. The sender stops at the same gate;
    bounded token queues then slow generation instead of dropping middle segments.
    """
    from backend.voice_transport import BROWSER_AUDIO, VoiceAudioChunk

    audio_format = audio_format or BROWSER_AUDIO
    connection = client.text_to_speech_streaming.connect(
        model="bulbul:v3", send_completion_event="true",
    )
    children = []
    try:
        tts = await asyncio.wait_for(connection.__aenter__(), timeout=15)
        await tts.configure(
            target_language_code=response.language, speaker="shubh",
            output_audio_codec=audio_format.output_encoding,
            speech_sample_rate=audio_format.output_sample_rate,
        )

        async def convert(text):
            await response.playable.wait()
            if not response.cancelled:
                await tts.convert(text)

        async def sender():
            buffer = ""
            while not response.cancelled:
                token = await response.text_queue.get()
                if token is None:
                    if _has_alphanumeric_text(buffer):
                        await convert(buffer.strip())
                    await response.playable.wait()
                    if not response.cancelled:
                        await tts.flush()
                    return
                buffer += token
                while buffer:
                    boundary = re.search(r"[.!?।]\s", buffer)
                    cut = boundary.end() if boundary else 0
                    if not cut and len(buffer) >= 400:
                        cut = buffer.rfind(" ", 0, 400) + 1 or 400
                    if not cut:
                        break
                    sentence, buffer = buffer[:cut].strip(), buffer[cut:]
                    if _has_alphanumeric_text(sentence):
                        await convert(sentence)

        async def receiver():
            while not response.cancelled:
                # Provider silence cannot leave response_pending stuck indefinitely.
                await response.playable.wait()
                event = await asyncio.wait_for(tts.recv(), timeout=45)
                await response.playable.wait()
                if response.cancelled:
                    return
                if isinstance(event, AudioOutput):
                    encoded = event.data.audio
                    if len(encoded) > 4 * 1024 * 1024:
                        raise ValueError("Voice provider audio packet exceeds retention bound")
                    audio = base64.b64decode(encoded, validate=True)
                    if audio.startswith(b"RIFF"):
                        if audio_format.output_encoding != "wav":
                            raise ValueError("Expected raw telephony audio, received a container")
                        with wave.open(io.BytesIO(audio), "rb") as wav:
                            if (wav.getnchannels() != 1 or wav.getsampwidth() != 2
                                    or wav.getframerate() != audio_format.output_sample_rate):
                                raise ValueError("Speech audio format does not match configuration")
                            audio = wav.readframes(wav.getnframes())
                    if audio:
                        response.audio_sent = True
                        response.playback_complete = False
                        on_audio(response)
                        await send_audio(VoiceAudioChunk(
                            response.response_id, audio,
                            "linear16" if audio_format.output_encoding == "wav" else audio_format.output_encoding,
                            audio_format.output_sample_rate,
                        ))
                elif type(event).__name__ == "EventResponse" and event.data.event_type == "final":
                    await send_json({"type": "tts_done", "response_id": response.response_id})
                    return
                elif type(event).__name__ == "ErrorResponse":
                    raise RuntimeError("Voice synthesis provider rejected response")

        children = [asyncio.create_task(producer()), asyncio.create_task(sender()), asyncio.create_task(receiver())]
        # Fail promptly if one side dies instead of waiting on an abandoned queue.
        done, pending = await asyncio.wait(children, return_when=asyncio.FIRST_EXCEPTION)
        for task in done:
            task.result()
        await asyncio.gather(*pending)
    finally:
        for task in children:
            if not task.done():
                task.cancel()
        await asyncio.gather(*children, return_exceptions=True)
        try:
            await asyncio.wait_for(connection.__aexit__(None, None, None), timeout=2)
        except Exception as error:  # noqa: BLE001 - External provider/socket boundary.
            logger.debug("Voice boundary failure: %s", type(error).__name__)
