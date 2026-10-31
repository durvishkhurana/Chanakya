"use client";

import { useRef, useState, useCallback, useEffect } from "react";
import { wsBase } from "./chanakyaApi";
import { createVoicePlayback, VOICE_PROTOCOL_VERSION } from "./voicePlayback.mjs";

function float32ToPcm16(float32Array) {
  const len = float32Array.length;
  const buffer = new ArrayBuffer(len * 2);
  const view = new DataView(buffer);
  for (let i = 0; i < len; i++) {
    const s = Math.max(-1, Math.min(1, float32Array[i]));
    view.setInt16(i * 2, s < 0 ? s * 0x8000 : s * 0x7fff, true);
  }
  return new Uint8Array(buffer);
}


/**
 * CallOverlay - Full-screen hands-free voice call with Chanakya.
 *
 * Features:
 * 1. Multilingual matching (STT language detection passed through to TTS and agent).
 * 2. Backend check-ins after 60 seconds of actual call inactivity.
 * 3. Persistent, scrollable transcription history viewable throughout the call.
 */
/** `path` picks the voice endpoint (a mission call uses its own); `modal: false` leaves the page usable behind the call. */
export default function useVoiceCall({ isOpen, onClose, retrievalProvider = "llm_batch", path = "/api/voice/ws", modal = true, pushToTalk = false }) {
  const onCloseRef = useRef(onClose);
  useEffect(() => { onCloseRef.current = onClose; }, [onClose]);
  // Push-to-talk: only send live mic audio while the button is held; otherwise send silence so the
  // server's speech detection segments the utterance at release. Default off keeps continuous streaming.
  const pushToTalkRef = useRef(pushToTalk);
  useEffect(() => { pushToTalkRef.current = pushToTalk; }, [pushToTalk]);
  const micHeldRef = useRef(false);
  const [talking, setTalking] = useState(false);
  const [callState, setCallState] = useState("connecting");
  const [connectionError, setConnectionError] = useState("");
  // "connecting" | "listening" | "processing" | "thinking" | "speaking"

  const [callMessages, setCallMessages] = useState([]);
  const [callDuration, setCallDuration] = useState(0);
  const wsRef = useRef(null);                     // WebSocket connection
  const audioCtxRef = useRef(null);               // AudioContext for mic capture
  const processorRef = useRef(null);              // ScriptProcessor for raw PCM
  const micStreamRef = useRef(null);              // Mic stream
  const activeRef = useRef(false);
  const threadIdRef = useRef(crypto.randomUUID());
  const durationTimerRef = useRef(null);
  const messagesContainerRef = useRef(null);
  const endButtonRef = useRef(null);
  const callOverlayRef = useRef(null);

  const playbackRef = useRef(null);
  const playbackAnalyserRef = useRef(null);
  const sessionVersionRef = useRef(0);

  // Auto-scroll transcript container to bottom
  useEffect(() => {
    const container = messagesContainerRef.current;
    container?.scrollTo({ top: container.scrollHeight, behavior: "smooth" });
  }, [callMessages, callState]);

  // ── Call Duration Timer ──
  useEffect(() => {
    if (isOpen) {
      setCallDuration(0);
      setCallMessages([]);
      setConnectionError("");
      durationTimerRef.current = setInterval(() => {
        setCallDuration((d) => d + 1);
      }, 1000);
    } else {
      clearInterval(durationTimerRef.current);
    }
    return () => {
      clearInterval(durationTimerRef.current);
    };
  }, [isOpen]);

  const formatDuration = (s) => {
    const m = Math.floor(s / 60);
    const sec = s % 60;
    return `${m.toString().padStart(2, "0")}:${sec.toString().padStart(2, "0")}`;
  };


// ── Start raw PCM audio capture → WebSocket ──
const startAudioCapture = useCallback((stream, ws) => {
  // Use default AudioContext sample rate (browser picks its native rate).
  // We'll resample to 16 kHz ourselves rather than trusting the hint.
  const audioCtx = new (window.AudioContext || window.webkitAudioContext)();
  audioCtxRef.current = audioCtx;
  const inputSampleRate = audioCtx.sampleRate;
  const targetSampleRate = 16000;
  const resampleRatio = targetSampleRate / inputSampleRate;

  const source = audioCtx.createMediaStreamSource(stream);
  const gainNode = audioCtx.createGain();
  gainNode.gain.value = 1;
  source.connect(gainNode);

  // ScriptProcessor is deprecated but still widely supported
  // AudioWorklet is the modern alternative if you want lower latency
  const bufferSize = 4096;
  const processor = audioCtx.createScriptProcessor(bufferSize, 1, 1);
  processorRef.current = processor;

  // Accumulate samples for resampling (linear interpolation)
  let accumBuffer = [];

  processor.onaudioprocess = (e) => {
    if (ws.readyState !== WebSocket.OPEN) return;

    const inputData = e.inputBuffer.getChannelData(0);
    accumBuffer.push(...inputData);

    // Resample accumulated samples to 16 kHz using linear interpolation
    const totalSamples = accumBuffer.length;
    const outputLen = Math.floor(totalSamples * resampleRatio);
    if (outputLen < 1) return; // not enough samples yet

    const output = new Float32Array(outputLen);
    for (let i = 0; i < outputLen; i++) {
      const srcIdx = i / resampleRatio;
      const idxLow = Math.floor(srcIdx);
      const frac = srcIdx - idxLow;
      if (idxLow + 1 < totalSamples) {
        output[i] = accumBuffer[idxLow] + frac * (accumBuffer[idxLow + 1] - accumBuffer[idxLow]);
      } else {
        output[i] = accumBuffer[idxLow] || 0;
      }
    }

    // Keep any leftover samples for next callback
    const consumed = Math.floor(outputLen / resampleRatio);
    accumBuffer = accumBuffer.slice(consumed);

    // While push-to-talk is on and the button is not held, mute the frame to silence.
    if (pushToTalkRef.current && !micHeldRef.current) output.fill(0);

    const pcm16Bytes = float32ToPcm16(output);
    ws.send(pcm16Bytes);
  };

  gainNode.connect(processor);
  processor.connect(audioCtx.destination);
}, []);

  // Tear down every resource on end, errors, external close, or unmount.
  const releaseCallResources = useCallback(() => {
    activeRef.current = false;
    sessionVersionRef.current += 1;
    clearInterval(durationTimerRef.current);
    const ws = wsRef.current;
    wsRef.current = null;
    if (ws) {
      ws.onopen = ws.onmessage = ws.onclose = ws.onerror = null;
      if (ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ type: "end_call" }));
      }
      ws.close();
    }
    processorRef.current?.disconnect();
    if (processorRef.current) processorRef.current.onaudioprocess = null;
    processorRef.current = null;
    micStreamRef.current?.getTracks().forEach((track) => track.stop());
    micStreamRef.current = null;
    playbackRef.current?.dispose();
    playbackRef.current = null;
    if (audioCtxRef.current) audioCtxRef.current.close().catch(() => {});
    audioCtxRef.current = null;
  }, []);

  const handleEndCall = useCallback(() => {
    releaseCallResources();
    setCallState("connecting");
    onCloseRef.current();
  }, [releaseCallResources]);

  const startCallSession = useCallback(async () => {
    if (!activeRef.current) return;
    const sessionVersion = sessionVersionRef.current;
    const isCurrentSession = () => activeRef.current && sessionVersionRef.current === sessionVersion;
    const failCall = (message) => {
      if (!isCurrentSession()) return;
      releaseCallResources();
      setConnectionError(message || "Unable to connect to the voice service.");
      setCallState("error");
    };
    setCallState("connecting");

    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: { sampleRate: 16000, channelCount: 1, echoCancellation: true, noiseSuppression: true },
      });
      if (!isCurrentSession()) {
        stream.getTracks().forEach((track) => track.stop());
        return;
      }
      micStreamRef.current = stream;
      const ws = new WebSocket(wsBase() +
        `${path}?retrieval_provider=${encodeURIComponent(retrievalProvider)}`);
      wsRef.current = ws;
      ws.binaryType = "arraybuffer";
      let ready = false;
      let interruptionEnabled = false;
      let userSpeaking = false;
      let decisionPending = false;
      let utteranceId = 0;
      let assistantMsgId = null;
      const playback = createVoicePlayback({
        createContext: () => new (window.AudioContext || window.webkitAudioContext)({ sampleRate: 22050 }),
        notify: (type, responseId, currentUtteranceId) => {
          if (isCurrentSession() && ws.readyState === WebSocket.OPEN) {
            ws.send(JSON.stringify({ type, response_id: responseId, utterance_id: currentUtteranceId }));
          }
        },
        onState: (state) => {
          if (!isCurrentSession()) return;
          if (state === "speaking" && (userSpeaking || decisionPending)) return;
          setCallState(decisionPending ? "processing" : state);
        },
        onAnalyser: (analyser) => {
          if (isCurrentSession() || analyser === null) playbackAnalyserRef.current = analyser;
        },
        onError: (error) => failCall(error.message),
      });
      playbackRef.current = playback;
      const appendUser = (text) => {
        setCallMessages((messages) => [...messages, { id: crypto.randomUUID(), role: "user", text }]);
      };
      const clearEmptyAssistant = () => {
        const ownedMessageId = assistantMsgId;
        if (ownedMessageId) {
          setCallMessages((messages) => messages.filter((message) => message.id !== ownedMessageId || message.text));
        }
        assistantMsgId = null;
      };
      const acceptsUtterance = (msg) => {
        if (!playback.accepts(msg.response_id)) return false;
        if (Number.isInteger(msg.utterance_id) && msg.utterance_id < utteranceId) return false;
        if (Number.isInteger(msg.utterance_id)) utteranceId = msg.utterance_id;
        return true;
      };

      ws.onopen = () => {
        if (!isCurrentSession()) return;
        ws.send(JSON.stringify({ type: "start_call", protocol_version: VOICE_PROTOCOL_VERSION, thread_id: threadIdRef.current }));
        try { startAudioCapture(stream, ws); } catch (error) { failCall(error.message); }
      };
      ws.onmessage = (event) => {
        if (!isCurrentSession()) return;
        if (event.data instanceof ArrayBuffer) {
          if (!ready) {
            failCall("The voice service sent audio before connecting. Please reload and try again.");
            return;
          }
          playback.enqueue(event.data);
          return;
        }
        let msg;
        try { msg = JSON.parse(event.data); } catch { return; }
        switch (msg.type) {
          case "voice_ready":
            if (msg.protocol_version !== VOICE_PROTOCOL_VERSION) {
              failCall("The voice service needs an update. Please reload and try again.");
              break;
            }
            ready = true;
            interruptionEnabled = msg.interruption_enabled === true;
            setCallState("listening");
            break;
          case "voice_error":
            failCall(msg.message);
            break;
          case "response_started":
            if (!playback.begin(msg.response_id)) break;
            assistantMsgId = null;
            decisionPending = false;
            break;
          case "response_cancelled":
            if (!playback.cancel(msg.response_id)) break;
            clearEmptyAssistant();
            decisionPending = false;
            break;
          case "transcript":
            if (!playback.accepts(msg.response_id)) break;
            userSpeaking = false;
            decisionPending = false;
            appendUser(msg.text);
            assistantMsgId = crypto.randomUUID();
            {
              const ownedMessageId = assistantMsgId;
              setCallMessages((messages) => [...messages, { id: ownedMessageId, role: "assistant", text: "" }]);
            }
            setCallState("thinking");
            break;
          case "acknowledgment":
            if (!acceptsUtterance(msg)) break;
            userSpeaking = false;
            decisionPending = false;
            appendUser(msg.text);
            setCallState(playback.playing ? "speaking" : "listening");
            break;
          case "interruption_pending":
            if (!acceptsUtterance(msg)) break;
            decisionPending = true;
            if (!playback.playing) setCallState("processing");
            break;
          case "playback_pause":
            if (!acceptsUtterance(msg)) break;
            playback.pause(msg.response_id, msg.utterance_id);
            break;
          case "playback_resume":
            if (!acceptsUtterance(msg)) break;
            userSpeaking = false;
            decisionPending = false;
            playback.resume(msg.response_id, msg.utterance_id);
            break;
          case "agent_token":
            if (!playback.accepts(msg.response_id) || !assistantMsgId) break;
            {
              const ownedMessageId = assistantMsgId;
              setCallMessages((messages) => messages.map((message) => message.id === ownedMessageId
                ? { ...message, text: message.text + (msg.content || "") } : message));
            }
            break;
          case "agent_done":
            if (!playback.accepts(msg.response_id) || !assistantMsgId || !msg.full_content) break;
            {
              const ownedMessageId = assistantMsgId;
              setCallMessages((messages) => messages.map((message) => message.id === ownedMessageId && !message.text
                ? { ...message, text: msg.full_content } : message));
            }
            break;
          case "check_in":
            if (!playback.accepts(msg.response_id)) break;
            setCallMessages((messages) => [...messages, { id: crypto.randomUUID(), role: "assistant", text: msg.text }]);
            break;
          case "tts_done":
            playback.done(msg.response_id);
            break;
          case "vad_speech_start":
            userSpeaking = true;
            if (Number.isInteger(msg.utterance_id)) utteranceId = Math.max(utteranceId, msg.utterance_id);
            if (!interruptionEnabled) {
              playback.cancel(playback.responseId);
              clearEmptyAssistant();
              setCallState("listening");
            } else if (!playback.playing) {
              setCallState("listening");
            }
            break;
          case "vad_speech_end":
          case "speech_end":
            userSpeaking = false;
            if (!interruptionEnabled || !playback.playing) setCallState("processing");
            break;
        }
      };
      ws.onclose = () => failCall("The call disconnected. Please start a new call.");
      ws.onerror = () => failCall("Unable to connect to the voice service.");
    } catch (error) {
      failCall(error.name === "NotAllowedError" ? "Microphone access is required to start a call." : error.message);
    }
  }, [releaseCallResources, startAudioCapture, retrievalProvider, path]);

  useEffect(() => {
    if (!isOpen) return;
    activeRef.current = true;
    sessionVersionRef.current += 1;
    threadIdRef.current = crypto.randomUUID();
    const startupTimer = setTimeout(startCallSession, 600);
    return () => {
      clearTimeout(startupTimer);
      releaseCallResources();
    };
  }, [isOpen, startCallSession, releaseCallResources]);

  useEffect(() => {
    if (!isOpen || !modal) return;
    const previousFocus = document.activeElement;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    endButtonRef.current?.focus({ preventScroll: true });
    const handleKey = (event) => {
      if (event.key === "Escape") handleEndCall();
      if (event.key === "Tab") {
        event.preventDefault();
        const target = document.activeElement === endButtonRef.current
          ? messagesContainerRef.current : endButtonRef.current;
        target?.focus({ preventScroll: true });
      }
    };
    document.addEventListener("keydown", handleKey);
    return () => {
      document.body.style.overflow = previousOverflow;
      document.removeEventListener("keydown", handleKey);
      previousFocus?.focus?.({ preventScroll: true });
    };
  }, [isOpen, modal, handleEndCall]);

  const holdMic = useCallback(() => { micHeldRef.current = true; setTalking(true); }, []);
  const releaseMic = useCallback(() => { micHeldRef.current = false; setTalking(false); }, []);

  return { callState, connectionError, callMessages, duration: formatDuration(callDuration),
    messagesContainerRef, endButtonRef, callOverlayRef, handleEndCall,
    pushToTalk, talking, holdMic, releaseMic };
}
