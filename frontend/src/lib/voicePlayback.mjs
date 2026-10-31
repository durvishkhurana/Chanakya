export const VOICE_PROTOCOL_VERSION = 2;

export function parseVoiceAudioPacket(packet) {
  if (!(packet instanceof ArrayBuffer) || packet.byteLength <= 5) {
    throw new Error("Invalid voice audio packet.");
  }
  const header = new DataView(packet);
  if (header.getUint8(0) !== VOICE_PROTOCOL_VERSION) {
    throw new Error("Unsupported voice audio protocol. Please reload and try again.");
  }
  const responseId = header.getUint32(1, false);
  if (!responseId) throw new Error("Invalid voice response ID.");
  return { responseId, audio: packet.slice(5) };
}

// Playback owns a separate AudioContext; pausing never touches microphone capture.
export function createVoicePlayback({ createContext, notify, onState, onAnalyser, onError }) {
  let context = null;
  let analyser = null;
  let responseId = 0;
  let generation = 0;
  let cancelled = false;
  let disposed = false;
  let paused = false;
  let started = false;
  let complete = false;
  let nextStart = 0;
  let pendingDecodes = 0;
  let decodeChain = Promise.resolve();
  let controlChain = Promise.resolve();
  let controlVersion = 0;
  const sources = new Set();

  const accepts = (id) => !disposed && !cancelled && id === responseId && id > 0;
  const reportError = (error) => { if (!disposed) onError(error); };
  const stopSources = () => {
    for (const source of sources) {
      source.onended = null;
      try { source.stop(); } catch {}
      try { source.disconnect(); } catch {}
    }
    sources.clear();
    nextStart = 0;
    started = false;
  };
  const finishIfIdle = () => {
    if (cancelled || disposed || paused || sources.size || pendingDecodes) return;
    if (started) {
      started = false;
      notify("playback_done", responseId);
    }
    if (complete) onState("listening");
  };
  const changeContextState = (id, shouldPause, utteranceId, emit) => {
    const version = ++controlVersion;
    controlChain = controlChain.then(async () => {
      if (!accepts(id) || version !== controlVersion) return;
      if (context && context.state !== "closed") {
        if (shouldPause) await context.suspend();
        else await context.resume();
      }
      if (!accepts(id) || version !== controlVersion) return;
      if (emit) notify(shouldPause ? "playback_paused" : "playback_resumed", id, utteranceId);
      if (!shouldPause) {
        if (sources.size) onState("speaking");
        else finishIfIdle();
      }
    }).catch(reportError);
    return controlChain;
  };

  return {
    accepts,
    get responseId() { return responseId; },
    get paused() { return paused; },
    /** The speaker's state for diagnostics, for example "running@22050"; "suspended" means the browser muted it. */
    get audioState() { return context ? `${context.state}@${context.sampleRate}` : "none"; },
    get playing() { return sources.size > 0 && !paused; },
    begin(id) {
      if (disposed || !Number.isInteger(id) || id <= responseId) return false;
      generation += 1;
      stopSources();
      responseId = id;
      cancelled = false;
      paused = false;
      complete = false;
      pendingDecodes = 0;
      decodeChain = Promise.resolve();
      changeContextState(id, false, undefined, false);
      return true;
    },
    cancel(id) {
      if (!accepts(id)) return false;
      cancelled = true;
      generation += 1;
      controlVersion += 1;
      stopSources();
      paused = false;
      pendingDecodes = 0;
      decodeChain = Promise.resolve();
      notify("playback_done", id);
      onState("listening");
      return true;
    },
    pause(id, utteranceId) {
      if (!accepts(id) || paused) return controlChain;
      paused = true;
      onState("listening");
      return changeContextState(id, true, utteranceId, true);
    },
    resume(id, utteranceId) {
      if (!accepts(id) || !paused) return controlChain;
      paused = false;
      return changeContextState(id, false, utteranceId, true);
    },
    done(id) {
      if (!accepts(id)) return;
      complete = true;
      finishIfIdle();
    },
    enqueue(packet) {
      let parsed;
      try { parsed = parseVoiceAudioPacket(packet); } catch (error) {
        reportError(error);
        return Promise.resolve();
      }
      const { responseId: id, audio } = parsed;
      if (!accepts(id)) return Promise.resolve();
      const ownedGeneration = generation;
      pendingDecodes += 1;
      decodeChain = decodeChain.then(async () => {
        if (!accepts(id) || generation !== ownedGeneration) return;
        try {
          if (!context) {
            context = createContext();
            analyser = context.createAnalyser();
            analyser.fftSize = 256;
            analyser.connect(context.destination);
            onAnalyser(analyser);
            await changeContextState(id, paused, undefined, false);
          }
          const buffer = await context.decodeAudioData(audio);
          if (!accepts(id) || generation !== ownedGeneration) return;
          const scheduleTime = Math.max(context.currentTime + 0.02, nextStart);
          if (paused && scheduleTime + buffer.duration - context.currentTime > 60) {
            throw new Error("Voice playback was paused too long. Please start a new call.");
          }
          const source = context.createBufferSource();
          source.buffer = buffer;
          source.connect(analyser);
          sources.add(source);
          nextStart = scheduleTime + buffer.duration;
          source.onended = () => {
            source.disconnect();
            if (!accepts(id) || generation !== ownedGeneration) return;
            sources.delete(source);
            finishIfIdle();
          };
          source.start(scheduleTime);
          if (!started) {
            started = true;
            if (!paused) notify("playback_started", id);
          }
          if (!paused) onState("speaking");
        } catch (error) {
          if (accepts(id) && generation === ownedGeneration) reportError(error);
        } finally {
          if (accepts(id) && generation === ownedGeneration) {
            pendingDecodes -= 1;
            finishIfIdle();
          }
        }
      });
      return decodeChain;
    },
    dispose() {
      if (disposed) return;
      disposed = true;
      generation += 1;
      controlVersion += 1;
      stopSources();
      onAnalyser(null);
      if (context) context.close().catch(() => {});
      context = null;
    },
  };
}
