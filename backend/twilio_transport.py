"""Bounded, mark-paced Twilio audio with response-safe pause and clear."""

import asyncio
import base64
import json
import logging

from fastapi import WebSocketDisconnect

from backend.voice_transport import PHONE_AUDIO, VoiceInput

logger = logging.getLogger(__name__)
FRAME_BYTES = 160  # 20 ms at 8 kHz, 8-bit mono.
SEGMENT_BYTES = 800  # One mark per 100 ms.
MAX_PENDING_SEGMENTS = 8  # 800 ms bridges playback acknowledgments over international RTT.
MAX_AUDIO_PACKET_BYTES = 80000  # Ten seconds retained at most per provider packet.


class TwilioVoiceTransport:
    audio_format = PHONE_AUDIO

    def __init__(self, websocket, admission):
        self.websocket = websocket
        self.admission = admission
        self.inputs = asyncio.Queue(maxsize=1024)
        self.input_audio_bytes = 0
        self.writer = asyncio.Lock()
        self.playable = asyncio.Event()
        self.capacity = asyncio.Event()
        self.closed = asyncio.Event()
        self.ready = asyncio.Event()
        self.playable.set()
        self.capacity.set()
        self.response_id = None
        self.generation = 0
        self.mark_counter = 0
        self.pending = {}
        self.sequence = 0
        self.timestamp = -1
        self.failed = False
        self.reader = None
        self.inputs.put_nowait(VoiceInput("setup", {"thread_id": "phone:" + admission.call_sid}))

    def start(self):
        self.reader = asyncio.create_task(self._read())

    async def receive(self):
        event = await self.inputs.get()
        self.input_audio_bytes -= len(event.audio)
        return event

    def _enqueue(self, event):
        if self.input_audio_bytes + len(event.audio) > 160000:
            raise BufferError("Caller audio exceeded twenty seconds of retained input")
        try:
            self.inputs.put_nowait(event)
            self.input_audio_bytes += len(event.audio)
        except asyncio.QueueFull as error:
            raise BufferError("Phone input exceeded its retention bound") from error

    def _disconnect(self):
        self.closed.set()
        self.playable.set()
        self.capacity.set()
        self.pending.clear()
        while not self.inputs.empty():
            self.inputs.get_nowait()
        self.input_audio_bytes = 0
        self.inputs.put_nowait(VoiceInput("disconnect"))

    async def _write(self, event, **fields):
        try:
            await asyncio.wait_for(self.websocket.send_json({
                "event": event, "streamSid": self.admission.stream_sid, **fields,
            }), timeout=5)
        except Exception:
            self.failed = True
            self._disconnect()
            raise

    async def _mark(self, response_id, *, final=False):
        self.mark_counter += 1
        name = f"r{response_id}:g{self.generation}:m{self.mark_counter}"
        self.pending[name] = (response_id, self.generation, final)
        if len(self.pending) >= MAX_PENDING_SEGMENTS:
            self.capacity.clear()
        await self._write("mark", mark={"name": name})

    async def send_event(self, message):
        kind = message["type"]
        rid = message.get("response_id")
        if kind == "voice_ready":
            self.ready.set()
            self._enqueue(VoiceInput("control", {
                "type": "tts", "text": "Hi, I'm Chanakya, an independent AI assistant for Paytm business products. Do you collect payments in a shop or online?",
            }))
        elif kind == "response_started":
            self.response_id = rid
            self.playable.set()
        elif kind == "playback_pause" and rid == self.response_id:
            self.playable.clear()
            self._enqueue(VoiceInput("control", {
                "type": "playback_paused", "response_id": rid,
                "utterance_id": message["utterance_id"],
            }))
        elif kind == "playback_resume" and rid == self.response_id:
            self.playable.set()
            self._enqueue(VoiceInput("control", {
                "type": "playback_resumed", "response_id": rid,
                "utterance_id": message["utterance_id"],
            }))
        elif kind == "response_cancelled" and rid == self.response_id:
            # Invalidate synchronously, before waiting behind an in-flight write.
            self.response_id = None
            self.generation += 1
            self.pending.clear()
            self.capacity.set()
            self.playable.set()
            if not self.closed.is_set():
                async with self.writer:
                    await self._write("clear")
        elif kind == "tts_done" and rid == self.response_id and not self.closed.is_set():
            async with self.writer:
                if rid == self.response_id:
                    await self._mark(rid, final=True)
        elif kind == "voice_error":
            self.failed = True
            self._disconnect()

    async def send_audio(self, chunk):
        if chunk.encoding != "mulaw" or chunk.sample_rate != 8000:
            raise ValueError("Twilio requires raw mu-law at 8 kHz")
        if len(chunk.audio) > MAX_AUDIO_PACKET_BYTES:
            raise ValueError("Phone speech packet exceeds ten seconds of retained audio")
        rid, generation = chunk.response_id, self.generation
        for offset in range(0, len(chunk.audio), SEGMENT_BYTES):
            await self.playable.wait()
            await asyncio.wait_for(self.capacity.wait(), timeout=5)
            if self.closed.is_set() or rid != self.response_id or generation != self.generation:
                return
            async with self.writer:
                if self.closed.is_set() or rid != self.response_id or generation != self.generation:
                    return
                # A pause may have arrived while this sender waited for the writer.
                if not self.playable.is_set():
                    await self.playable.wait()
                    if self.closed.is_set() or rid != self.response_id or generation != self.generation:
                        return
                segment = chunk.audio[offset:offset + SEGMENT_BYTES]
                for position in range(0, len(segment), FRAME_BYTES):
                    if rid != self.response_id or generation != self.generation:
                        return
                    payload = base64.b64encode(segment[position:position + FRAME_BYTES]).decode("ascii")
                    await self._write("media", media={"payload": payload})
                if rid == self.response_id and generation == self.generation and not self.closed.is_set():
                    await self._mark(rid)

    async def _read(self):
        try:
            while not self.closed.is_set():
                message = await self.websocket.receive()
                if message.get("type") == "websocket.disconnect":
                    break
                raw = message.get("text", "")
                if not raw or len(raw) > 16384:
                    raise ValueError("Invalid phone frame")
                data = json.loads(raw)
                if not isinstance(data, dict) or data.get("streamSid") != self.admission.stream_sid:
                    raise ValueError("Phone frame is not bound to this stream")
                sequence = int(data.get("sequenceNumber", "0"))
                if sequence <= self.sequence:
                    raise ValueError("Phone frame sequence is not increasing")
                self.sequence = sequence
                kind = data.get("event")
                if kind == "media":
                    media = data["media"]
                    stamp = int(media["timestamp"])
                    if media.get("track") != "inbound" or stamp < self.timestamp:
                        raise ValueError("Invalid caller track or timestamp")
                    self.timestamp = stamp
                    encoded = media["payload"]
                    if not isinstance(encoded, str) or len(encoded) > 4400:
                        raise ValueError("Caller audio packet is oversized")
                    audio = base64.b64decode(encoded, validate=True)
                    if not audio or len(audio) > 3200:
                        raise ValueError("Invalid caller audio length")
                    self._enqueue(VoiceInput("audio", audio=audio))
                elif kind == "mark":
                    mark = self.pending.pop(data["mark"]["name"], None)
                    if len(self.pending) < MAX_PENDING_SEGMENTS:
                        self.capacity.set()
                    if mark and mark == (self.response_id, self.generation, True):
                        self._enqueue(VoiceInput("control", {
                            "type": "playback_done", "response_id": mark[0],
                        }))
                elif kind == "stop":
                    stop = data.get("stop", {})
                    if (stop.get("callSid") != self.admission.call_sid
                            or stop.get("accountSid") != self.admission.account_sid):
                        raise ValueError("Stop event belongs to another call")
                    break
                elif kind == "dtmf":
                    digit = data.get("dtmf", {}).get("digit")
                    if not isinstance(digit, str) or len(digit) != 1 or digit not in "0123456789*#":
                        raise ValueError("Invalid keypad event")
                else:
                    raise ValueError("Unexpected phone stream event")
        except WebSocketDisconnect:
            logger.debug("Phone media disconnected")
        except Exception as error:  # noqa: BLE001 - External WebSocket boundary.
            self.failed = True
            logger.warning("Phone media failed: %s", type(error).__name__)
        finally:
            self._disconnect()

    async def aclose(self):
        self._disconnect()
        if self.reader:
            self.reader.cancel()
            await asyncio.gather(self.reader, return_exceptions=True)
