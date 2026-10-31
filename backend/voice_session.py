"""Shared call-scoped STT and response-scoped voice orchestration."""

import asyncio
import base64
import logging
import os
import socket
import uuid

from fastapi import WebSocketDisconnect
from sarvamai.types.realtime_audio_input import RealtimeAudioInput
from sarvamai.types.realtime_end import RealtimeEnd

from backend.voice_activity import CHECK_INS, VoiceActivity
from backend.voice_interruption import VoiceInterruptionClassifier
from backend.voice_language import VoiceLanguage
from backend.voice_response import PROTOCOL_VERSION, VoiceResponse, synthesize_response
from backend.voice_transport import VoiceTransport

logger = logging.getLogger(__name__)

def configured_ms(name, default, minimum=1, maximum=10000):
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError:
        value = default
    return max(minimum, min(maximum, value)) / 1000


async def run_voice_session(
    transport: VoiceTransport, voice_agent, sarvam_client, retrieval_provider="decisions",
    *, classifier_factory=VoiceInterruptionClassifier, activity_factory=VoiceActivity,
):
    """Retain the current response until an overlapping utterance takes a turn."""
    enabled = os.getenv("VOICE_INTERRUPTION_ENABLED", "false").lower() in {"true", "1", "yes"}
    speculative_pause = os.getenv("VOICE_INTERRUPTION_SPECULATIVE_PAUSE", "false").lower() in {"true", "1", "yes"}
    grace = configured_ms("VOICE_INTERRUPTION_GRACE_MS", 350, minimum=0, maximum=2000)
    timeout = configured_ms("VOICE_INTERRUPTION_TIMEOUT_MS", 4000, maximum=5000)
    transcript_timeout = configured_ms("VOICE_INTERRUPTION_TRANSCRIPT_TIMEOUT_MS", 1500, maximum=5000)
    classifier = None
    stt_connection = None
    stt_ws = None
    stt_task = None
    inactivity_task = None
    decision_task = None
    grace_task = None
    watchdog_task = None
    response = None
    response_counter = 0
    utterance_id = 0
    utterance_open = False
    overlap_response_id = None
    fragments = []
    detected_language = None
    detected_confidence = None
    last_user_text = ""
    recent_history = []
    response_lock = asyncio.Lock()
    background_tasks = set()
    language = VoiceLanguage()
    activity = activity_factory()
    thread_id = str(uuid.uuid4())
    # Planning while listening (off by default): agents that can prepare a turn from partials do so.
    listening = os.getenv("PLANNING_WHILE_LISTENING", "false").lower() in {"true", "1", "yes"}
    speculate = getattr(voice_agent, "prepare", None) if listening else None

    def owns(owner):
        return response is owner and not owner.cancelled

    def launch(coroutine):
        task = asyncio.create_task(coroutine)
        background_tasks.add(task)
        task.add_done_callback(background_tasks.discard)
        return task

    async def emit(kind, owner=None, **fields):
        message = {"type": kind, **fields}
        if owner is not None:
            message["response_id"] = owner.response_id
        await transport.send_event(message)

    def stop_task(task):
        if task is not None and task is not asyncio.current_task() and not task.done():
            task.cancel()

    def stop_timers():
        stop_task(grace_task)
        stop_task(watchdog_task)

    async def cancel_response():
        if response is None or response.cancelled:
            return
        owner = response
        owner.cancelled = True
        # Announce discard before waiting for provider cleanup.
        await emit("response_cancelled", owner)
        await owner.cancel()
        if response is owner:
            activity.answering = False
            activity.response_pending = False
            activity.playback_active = False
            activity.playback_paused = False
            activity.touch()

    async def resume(uid):
        if uid != utterance_id or activity.user_speaking:
            return
        activity.interruption_pending = False
        activity.awaiting_transcript = False
        if response and owns(response):
            response.playable.set()
            if activity.playback_paused:
                activity.playback_paused = False
                await emit("playback_resume", response, utterance_id=uid)
        activity.touch()

    async def pause_after_grace(uid, owner):
        await asyncio.sleep(grace)
        if uid != utterance_id or not owns(owner):
            return
        # A completed acknowledgment keeps playing while classification finishes.
        if activity.user_speaking:
            owner.playable.clear()
            activity.playback_paused = True
            activity.touch()
            await emit("playback_pause", owner, utterance_id=uid)

    def schedule_grace(uid):
        nonlocal grace_task
        stop_task(grace_task)
        if response and owns(response):
            grace_task = launch(pause_after_grace(uid, response))

    async def start_response(text, response_language, *, accepted=False, check_in=False, accepted_uid=None):
        nonlocal response, response_counter
        async with response_lock:
            if not accepted and not activity.idle:
                return
            if accepted_uid is not None and accepted_uid != utterance_id:
                return
            await cancel_response()
            if not accepted and not activity.idle:
                return
            if accepted_uid is not None and accepted_uid != utterance_id:
                return
            response_counter += 1
            owner = VoiceResponse(response_counter, response_language)
            response = owner
            activity.response_pending = True
            activity.touch()
            await emit("response_started", owner)
            if accepted:
                await emit("transcript", owner, text=text, language_code=response_language)
            elif check_in:
                await emit("check_in", owner, text=text, language_code=response_language)

        async def scoped_json(message):
            if owns(owner):
                if message["type"] == "tts_done":
                    activity.response_pending = False
                    if not owner.audio_sent:
                        activity.playback_active = False
                    activity.touch()
                await transport.send_event(message)

        async def scoped_bytes(packet):
            if owns(owner):
                await transport.send_audio(packet)

        def on_audio(_owner):
            if owns(owner):
                activity.playback_active = True
                activity.touch()

        async def producer():
            if not accepted:
                owner.generated_text = text[-6000:]
                await owner.put_text(text)
                await owner.text_queue.put(None)
                return
            activity.answering = True
            activity.touch()
            completed = False
            try:
                async for event in voice_agent.astream(text, config={"configurable": {
                    "thread_id": thread_id, "response_language": response_language,
                    "retrieval_provider": retrieval_provider,
                }}):
                    if not owns(owner):
                        return
                    activity.touch()
                    if event.get("type") == "token":
                        content = event.get("content", "")
                        owner.generated_text = (owner.generated_text + content)[-6000:]
                        await emit("agent_token", owner, content=content)
                        await owner.put_text(content)
                    elif event.get("type") == "done":
                        completed = True
                        await emit("agent_done", owner, full_content=event.get("full_content", ""))
                        recent_history.append({"role": "assistant", "text": owner.generated_text[-800:]})
                        del recent_history[:-6]
                if not completed and owns(owner):
                    await emit("agent_done", owner, full_content=owner.generated_text)
                await owner.text_queue.put(None)
            finally:
                if owns(owner):
                    activity.answering = False
                    activity.touch()

        async def run():
            try:
                await synthesize_response(
                    owner, sarvam_client, scoped_json, scoped_bytes, on_audio, producer,
                    audio_format=transport.audio_format,
                )
            except asyncio.CancelledError:
                raise
            except Exception as error:  # noqa: BLE001 - External provider/socket boundary.
                logger.debug("Voice boundary failure: %s", type(error).__name__)
                if owns(owner):
                    owner.cancelled = True
                    await emit("response_cancelled", owner)
                    activity.answering = False
                    activity.response_pending = False
                    activity.playback_active = False
                    activity.playback_paused = False
                    activity.touch()
                    await emit("voice_error", owner, message="Speech failed. Please try again.")

        if owns(owner):
            owner.task = asyncio.create_task(run())

    async def accept_turn(text, detected, confidence):
        nonlocal last_user_text, fragments, overlap_response_id, utterance_open
        stop_timers()
        stop_task(decision_task)
        fragments = []
        overlap_response_id = None
        utterance_open = False
        activity.user_speaking = False
        activity.awaiting_transcript = False
        activity.interruption_pending = False
        activity.response_pending = True
        response_language = language.observe(text, detected, confidence)
        last_user_text = text
        recent_history.append({"role": "user", "text": text[-800:]})
        del recent_history[:-6]
        await start_response(text, response_language, accepted=True, accepted_uid=utterance_id)

    async def classify_utterance(uid, owner, text, detected, confidence):
        nonlocal fragments, overlap_response_id, utterance_open
        context = {
            "assistant_text": owner.generated_text,
            "recent_history": list(recent_history),
            "last_user_text": last_user_text,
            "overlap": True,
            "thread_id": thread_id,
        }
        try:
            # Defend the call lifecycle even if an injected classifier misses its deadline.
            result = await asyncio.wait_for(classifier.classify(
                text, context, language=detected,
                response_id=owner.response_id, utterance_id=uid,
            ), timeout=timeout)
            takes_turn = result.takes_turn
        except asyncio.CancelledError:
            raise
        except Exception as error:  # noqa: BLE001 - External provider/socket boundary.
            logger.debug("Voice boundary failure: %s", type(error).__name__)
            takes_turn = True
        if uid != utterance_id or not owns(owner) or activity.user_speaking:
            return
        stop_timers()
        if takes_turn:
            await accept_turn(text, detected, confidence)
        else:
            fragments = []
            overlap_response_id = None
            utterance_open = False
            await emit("acknowledgment", owner, text=text, utterance_id=uid)
            await resume(uid)

    async def decide_pending():
        nonlocal decision_task
        if decision_task and not decision_task.done() and not decision_task.cancelling():
            return
        owner = response
        text = " ".join(fragments)
        if not text:
            return
        if enabled and owner and owns(owner) and overlap_response_id == owner.response_id:
            activity.interruption_pending = True
            activity.touch()
            await emit("interruption_pending", owner, utterance_id=utterance_id)
            decision_task = launch(classify_utterance(
                utterance_id, owner, text, detected_language, detected_confidence,
            ))
        else:
            await accept_turn(text, detected_language, detected_confidence)

    async def transcript_watchdog(uid):
        await asyncio.sleep(transcript_timeout)
        if uid != utterance_id or activity.user_speaking:
            return
        activity.awaiting_transcript = False
        if fragments:
            # A newer empty utterance cannot erase an earlier pending question.
            await decide_pending()
        else:
            # Keep the VAD overlap so a delayed final remains owned by its utterance.
            stop_task(grace_task)
            await resume(uid)

    def schedule_watchdog(uid):
        nonlocal watchdog_task
        stop_task(watchdog_task)
        watchdog_task = launch(transcript_watchdog(uid))

    async def handle_stt_events():
        nonlocal utterance_id, utterance_open, overlap_response_id
        nonlocal detected_language, detected_confidence
        nonlocal decision_task
        try:
            async for event in stt_ws:
                event_type = type(event).__name__
                if event_type.startswith(("RealtimeTranscript", "RealtimeVad")):
                    activity.touch()
                if event_type == "RealtimeTranscriptPartial":
                    partial = getattr(event, "text", "")
                    await emit("partial_transcript", text=partial, utterance_id=utterance_id)
                    if callable(speculate) and partial.strip():
                        launch(speculate(" ".join([*fragments, partial]), thread_id, language.current))
                elif event_type == "RealtimeVadSpeechStart":
                    utterance_id += 1
                    utterance_open = True
                    stop_task(decision_task)
                    decision_task = None
                    stop_timers()
                    activity.user_speaking = True
                    activity.awaiting_transcript = False
                    audible = activity.playback_active or activity.playback_paused
                    if not fragments:
                        overlap_response_id = None
                    if response and owns(response) and audible:
                        overlap_response_id = response.response_id
                    if enabled and overlap_response_id is not None:
                        activity.interruption_pending = True
                        # Preserve playback until Jev decides unless explicitly opted in.
                        if speculative_pause:
                            schedule_grace(utterance_id)
                    await emit("vad_speech_start", response, utterance_id=utterance_id)
                    if not enabled:
                        await cancel_response()
                elif event_type == "RealtimeVadSpeechEnd":
                    activity.user_speaking = False
                    activity.awaiting_transcript = True
                    await emit("vad_speech_end", response, utterance_id=utterance_id)
                    schedule_watchdog(utterance_id)
                elif event_type == "RealtimeTranscriptFinal":
                    transcript = getattr(event, "text", "").strip()
                    activity.user_speaking = False
                    activity.awaiting_transcript = False
                    stop_task(watchdog_task)
                    if not transcript:
                        if fragments:
                            await decide_pending()
                        else:
                            stop_task(grace_task)
                            utterance_open = False
                            overlap_response_id = None
                            await resume(utterance_id)
                        continue
                    if not utterance_open or (decision_task and not decision_task.done()):
                        utterance_id += 1
                        stop_task(decision_task)
                        stop_task(grace_task)
                        if not utterance_open and response and owns(response) and (
                            activity.playback_active or activity.playback_paused
                        ):
                            overlap_response_id = response.response_id
                        utterance_open = True
                    fragments.append(transcript)
                    detected_language = getattr(event, "language", None)
                    detected_confidence = getattr(event, "language_confidence", None)
                    await decide_pending()
                elif event_type == "RealtimeSessionEnd":
                    await emit("voice_error", message="Speech recognition ended. Please reconnect.")
                    return
                elif event_type == "RealtimeError" and getattr(event, "is_fatal", False):
                    await emit("voice_error", message="Speech recognition failed. Please reconnect.")
                    return
        except asyncio.CancelledError:
            raise
        except Exception as error:  # noqa: BLE001 - External provider/socket boundary.
            logger.debug("Voice boundary failure: %s", type(error).__name__)
            await emit("voice_error", message="Speech recognition failed. Please reconnect.")

    async def handle_inactivity():
        while True:
            await activity.wait_for_idle()
            # The wait can finish immediately before an STT event changes activity.
            if not activity.idle:
                continue
            text = CHECK_INS.get(language.current)
            if text is None:
                activity.touch()
                continue
            await start_response(text, language.current, check_in=True)

    try:
        initial = await asyncio.wait_for(transport.receive(), timeout=15)
        if initial.kind != "setup":
            await emit("voice_error", message="Voice setup is required. Please reconnect.")
            return
        setup = initial.data
        requested_thread = setup.get("thread_id")
        if isinstance(requested_thread, str) and requested_thread.strip():
            thread_id = requested_thread
        await asyncio.wait_for(asyncio.get_running_loop().getaddrinfo(
            "api.sarvam.ai", 443, type=socket.SOCK_STREAM,
        ), timeout=5)
        for attempt in range(3):
            try:
                stt_connection = sarvam_client.speech_to_text_realtime_streaming.connect(
                    language_code="auto", model="saaras:v3-realtime", stream_type="fast",
                    mode="transcribe", encoding=transport.audio_format.encoding,
                    sample_rate=str(transport.audio_format.sample_rate), endpointing="vad",
                    silence_duration_ms="500",
                )
                stt_ws = await asyncio.wait_for(stt_connection.__aenter__(), timeout=15)
                break
            except Exception as error:
                logger.debug("Voice boundary failure: %s", type(error).__name__)
                if stt_connection:
                    try:
                        await asyncio.wait_for(stt_connection.__aexit__(None, None, None), timeout=2)
                    except Exception as error:  # noqa: BLE001 - External provider/socket boundary.
                        logger.debug("Voice boundary failure: %s", type(error).__name__)
                    stt_connection = None
                if attempt == 2:
                    raise
                await asyncio.sleep(2 ** attempt)
        classifier = classifier_factory(timeout=timeout) if enabled else None
        activity.started = True
        activity.touch()
        await emit("voice_ready", protocol_version=PROTOCOL_VERSION,
                   interruption_enabled=enabled, grace_ms=round(grace * 1000))
        stt_task = asyncio.create_task(handle_stt_events())
        inactivity_task = asyncio.create_task(handle_inactivity())
        while True:
            message = await transport.receive()
            if message.kind == "disconnect":
                break
            if message.kind == "audio":
                await asyncio.wait_for(stt_ws.send_realtime_audio_input(RealtimeAudioInput(
                    audio=base64.b64encode(message.audio).decode("utf-8"),
                )), timeout=5)
            elif message.kind == "control":
                data = message.data
                kind = data.get("type")
                if kind in {"playback_started", "playback_done", "playback_paused", "playback_resumed"}:
                    logger.info("Browser playback: %s, speaker %s", kind, data.get("audio"))
                    if not response or not owns(response) or data.get("response_id") != response.response_id:
                        continue
                    if kind in {"playback_paused", "playback_resumed"} and data.get("utterance_id") != utterance_id:
                        continue
                    if kind == "playback_done":
                        response.playback_complete = True
                        activity.playback_active = False
                        # An in-flight decision retains its pause state until resolution.
                        if not activity.interruption_pending:
                            activity.playback_paused = False
                    elif kind == "playback_started":
                        response.playback_complete = False
                        activity.playback_active = True
                    elif kind == "playback_paused":
                        if activity.interruption_pending:
                            activity.playback_paused = True
                            response.playable.clear()
                    elif not activity.interruption_pending and not activity.user_speaking:
                        activity.playback_paused = False
                        response.playable.set()
                    activity.touch()
                elif kind == "tts":
                    text = data.get("text", "").strip()
                    if text and activity.idle:
                        await start_response(text, language.current)
                elif kind == "end_call":
                    break
    except WebSocketDisconnect:
        pass
    except Exception as error:  # noqa: BLE001 - External provider/socket boundary.
        logger.debug("Voice boundary failure: %s", type(error).__name__)
        try:
            await emit("voice_error", message="Could not connect to the voice service. Please try again.")
        except Exception as error:  # noqa: BLE001 - External provider/socket boundary.
            logger.debug("Voice boundary failure: %s", type(error).__name__)
    finally:
        tasks = list(background_tasks | {
            task for task in (stt_task, inactivity_task, decision_task, grace_task, watchdog_task) if task
        })
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        if response:
            await response.cancel()
        if classifier:
            try:
                await asyncio.wait_for(classifier.aclose(), timeout=2)
            except Exception as error:  # noqa: BLE001 - External provider/socket boundary.
                logger.debug("Voice boundary failure: %s", type(error).__name__)
        if stt_ws:
            send_end = getattr(stt_ws, "send_realtime_end", None)
            transport = getattr(stt_ws, "_websocket", stt_ws)
            state = getattr(transport, "state", None)
            closed = getattr(transport, "closed", None)
            socket_open = (
                getattr(state, "name", None) == "OPEN" if state is not None
                else closed is not True
            )
            if callable(send_end) and socket_open:
                try:
                    await asyncio.wait_for(send_end(RealtimeEnd()), timeout=1)
                except Exception as error:  # noqa: BLE001 - External provider/socket boundary.
                    logger.debug("Voice boundary failure: %s", type(error).__name__)
        if stt_connection:
            try:
                await asyncio.wait_for(stt_connection.__aexit__(None, None, None), timeout=2)
            except Exception as error:  # noqa: BLE001 - External provider/socket boundary.
                logger.debug("Voice boundary failure: %s", type(error).__name__)
