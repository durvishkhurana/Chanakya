"""Typed voice input and format-aware output at each client boundary."""

import json
import struct
from dataclasses import dataclass, field
from typing import Literal, Protocol

from backend.voice_response import PROTOCOL_VERSION, pcm16_to_wav


@dataclass(frozen=True)
class VoiceAudioFormat:
    encoding: str = "linear16"
    sample_rate: int = 16000
    output_encoding: str = "wav"
    output_sample_rate: int = 22050


BROWSER_AUDIO = VoiceAudioFormat()
PHONE_AUDIO = VoiceAudioFormat("mulaw", 8000, "mulaw", 8000)


@dataclass(frozen=True)
class VoiceInput:
    kind: Literal["setup", "audio", "control", "disconnect"]
    data: dict = field(default_factory=dict)
    audio: bytes = b""


@dataclass(frozen=True)
class VoiceAudioChunk:
    response_id: int
    audio: bytes
    encoding: str
    sample_rate: int


class VoiceTransport(Protocol):
    audio_format: VoiceAudioFormat

    async def receive(self) -> VoiceInput: ...
    async def send_event(self, message: dict) -> None: ...
    async def send_audio(self, chunk: VoiceAudioChunk) -> None: ...


class BrowserVoiceTransport:
    audio_format = BROWSER_AUDIO

    def __init__(self, websocket):
        self.websocket = websocket
        self.started = False

    async def receive(self):
        message = await self.websocket.receive()
        if message.get("type") == "websocket.disconnect":
            return VoiceInput("disconnect")
        if not self.started:
            setup = json.loads(message.get("text") or "{}")
            if (setup.get("type") != "start_call"
                    or type(setup.get("protocol_version")) is not int
                    or setup["protocol_version"] != PROTOCOL_VERSION):
                await self.send_event({"type": "voice_error", "message": "Voice protocol 2 is required. Refresh and retry."})
                return VoiceInput("disconnect")
            self.started = True
            return VoiceInput("setup", setup)
        if message.get("bytes") is not None:
            return VoiceInput("audio", audio=message["bytes"])
        return VoiceInput("control", json.loads(message.get("text") or "{}"))

    async def send_event(self, message):
        await self.websocket.send_json(message)

    async def send_audio(self, chunk):
        packet = struct.pack(">BI", PROTOCOL_VERSION, chunk.response_id)
        await self.websocket.send_bytes(packet + pcm16_to_wav(chunk.audio, chunk.sample_rate))
