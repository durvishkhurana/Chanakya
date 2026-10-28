import test from "node:test";
import assert from "node:assert/strict";
import { createVoicePlayback, parseVoiceAudioPacket } from "./voicePlayback.mjs";

function packet(id, version = 2) {
  const bytes = new ArrayBuffer(9);
  const view = new DataView(bytes);
  view.setUint8(0, version);
  view.setUint32(1, id, false);
  return bytes;
}

function deferred() {
  let resolve;
  const promise = new Promise((done) => { resolve = done; });
  return { promise, resolve };
}

function fixture() {
  const events = [];
  const states = [];
  const errors = [];
  const sources = [];
  const context = {
    currentTime: 3,
    state: "running",
    destination: {},
    createAnalyser: () => ({ connect() {} }),
    decodeAudioData: async () => ({ duration: 1 }),
    async suspend() { this.state = "suspended"; },
    async resume() { this.state = "running"; },
    async close() { this.state = "closed"; },
    createBufferSource() {
      const source = { connect() {}, disconnect() {}, start(time) { this.time = time; }, stop() { this.stopped = true; } };
      sources.push(source);
      return source;
    },
  };
  const playback = createVoicePlayback({
    createContext: () => context,
    notify: (...args) => events.push(args),
    onState: (state) => states.push(state),
    onAnalyser() {},
    onError: (error) => errors.push(error),
  });
  return { playback, context, events, states, errors, sources };
}

test("audio protocol rejects malformed packets and reads big-endian response identity", () => {
  assert.equal(parseVoiceAudioPacket(packet(65537)).responseId, 65537);
  assert.equal(parseVoiceAudioPacket(packet(1)).audio.byteLength, 4);
  assert.throws(() => parseVoiceAudioPacket(new ArrayBuffer(5)));
  assert.throws(() => parseVoiceAudioPacket(packet(1, 1)));
  assert.throws(() => parseVoiceAudioPacket(packet(0)));
});

test("temporary pause retains scheduled samples and does not emit playback_done", async () => {
  const { playback, context, events, states, sources } = fixture();
  playback.begin(1);
  await playback.enqueue(packet(1));
  const originalTime = sources[0].time;
  await playback.pause(1, 7);
  assert.equal(context.state, "suspended");
  await playback.enqueue(packet(1));
  assert.equal(sources[0].time, originalTime);
  assert.equal(sources[0].stopped, undefined);
  assert.equal(sources[1].time, originalTime + 1);
  assert.equal(states.at(-1), "listening");
  assert.equal(events.filter(([type]) => type === "playback_done").length, 0);
  await playback.resume(1, 7);
  assert.equal(context.state, "running");
  assert.equal(states.at(-1), "speaking");
  assert.deepEqual(events.at(-1), ["playback_resumed", 1, 7]);
  await playback.resume(1, 7);
  assert.equal(events.filter(([type]) => type === "playback_resumed").length, 1);
});

test("cancellation rejects late decoding and stale onended callbacks", async () => {
  const { playback, context, sources, events } = fixture();
  playback.begin(1);
  await playback.enqueue(packet(1));
  const staleEnd = sources[0].onended;
  const decoding = deferred();
  context.decodeAudioData = () => decoding.promise;
  const oldChunk = playback.enqueue(packet(1));
  await Promise.resolve();
  playback.cancel(1);
  playback.begin(2);
  context.decodeAudioData = async () => ({ duration: 2 });
  await playback.enqueue(packet(2));
  const successorSource = sources.at(-1);
  decoding.resolve({ duration: 3 });
  await oldChunk;
  staleEnd();
  await playback.enqueue(packet(1));
  assert.equal(sources.length, 2);
  assert.equal(playback.playing, true);
  assert.equal(successorSource.stopped, undefined);
  assert.equal(events.at(-1)[1], 2);
});

test("a successor response resumes a suspended context and ignores old controls", async () => {
  const { playback, context, events } = fixture();
  playback.begin(1);
  await playback.enqueue(packet(1));
  await playback.pause(1, 1);
  playback.cancel(1);
  playback.begin(2);
  await playback.pause(1, 2);
  await playback.enqueue(packet(2));
  assert.equal(context.state, "running");
  assert.equal(playback.paused, false);
  assert.equal(playback.begin(1), false);
  assert.equal(playback.begin(2), false);
  assert.equal(events.at(-1)[1], 2);
});

test("completion waits for decoding and audible samples to finish", async () => {
  const { playback, states, sources, events } = fixture();
  playback.begin(1);
  const chunk = playback.enqueue(packet(1));
  playback.done(1);
  assert.equal(states.length, 0);
  await chunk;
  sources[0].onended();
  assert.equal(states.at(-1), "listening");
  assert.deepEqual(events.at(-1), ["playback_done", 1]);
});

test("ending a paused call closes playback and invalidates pending decode", async () => {
  const { playback, context, sources } = fixture();
  playback.begin(1);
  await playback.pause(1, 1);
  const decoding = deferred();
  context.decodeAudioData = () => decoding.promise;
  const chunk = playback.enqueue(packet(1));
  await Promise.resolve();
  playback.dispose();
  decoding.resolve({ duration: 1 });
  await chunk;
  assert.equal(context.state, "closed");
  assert.equal(sources.length, 0);
  assert.equal(playback.accepts(1), false);
});

test("retained audio has a bound and fails explicitly without dropping middle samples", async () => {
  const { playback, context, errors, sources } = fixture();
  playback.begin(1);
  await playback.enqueue(packet(1));
  await playback.pause(1, 1);
  context.decodeAudioData = async () => ({ duration: 61 });
  await playback.enqueue(packet(1));
  assert.equal(errors.length, 1);
  assert.equal(sources.length, 1);
  assert.match(errors[0].message, /paused too long/);
});

test("an in-flight suspend cannot leave a successor response suspended", async () => {
  const { playback, context, events } = fixture();
  playback.begin(1);
  await playback.enqueue(packet(1));
  const suspended = deferred();
  context.suspend = async function () {
    await suspended.promise;
    this.state = "suspended";
  };
  const pause = playback.pause(1, 1);
  await Promise.resolve();
  playback.cancel(1);
  playback.begin(2);
  suspended.resolve();
  await pause;
  await playback.enqueue(packet(2));
  assert.equal(context.state, "running");
  assert.equal(events.some(([type]) => type === "playback_paused"), false);
  assert.equal(events.at(-1)[1], 2);
});

test("ending and opening a new call cannot schedule old decoding into the new context", async () => {
  const first = fixture();
  first.playback.begin(1);
  await first.playback.enqueue(packet(1));
  await first.playback.pause(1, 1);
  const oldDecode = deferred();
  first.context.decodeAudioData = () => oldDecode.promise;
  const oldChunk = first.playback.enqueue(packet(1));
  await Promise.resolve();
  first.playback.dispose();
  const second = fixture();
  second.playback.begin(1);
  await second.playback.enqueue(packet(1));
  oldDecode.resolve({ duration: 3 });
  await oldChunk;
  assert.equal(first.context.state, "closed");
  assert.equal(first.sources.length, 1);
  assert.equal(second.sources.length, 1);
  assert.equal(second.playback.playing, true);
});
