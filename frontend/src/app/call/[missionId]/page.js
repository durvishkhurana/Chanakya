"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";

import CallView from "../../../components/call/CallView";
import { demoEvents } from "../../../components/call/demoFixture";
import PhoneLink from "../../../components/call/PhoneLink";
import AppShell from "../../../components/missions/AppShell";
import { api, useMissionStream } from "../../../lib/chanakyaApi";
import useVoiceCall, { primeVoiceAudio } from "../../../lib/useVoiceCall";
import { FINISHED } from "../../../lib/missionView.mjs";

export default function CallPage() {
  const { missionId } = useParams();
  return missionId === "demo" ? <RecordedCall /> : <LiveCall missionId={missionId} />;
}

/** The scripted recording, played back event by event so the screen behaves as it does on a live call. */
function RecordedCall() {
  const [shown, setShown] = useState(4);
  const [playing, setPlaying] = useState(true);
  const done = shown >= demoEvents.length;

  useEffect(() => {
    if (!playing || done) return undefined;
    const next = demoEvents[shown];
    const pause = next.kind === "turn_completed" ? 1600 : 500;
    const timer = setTimeout(() => setShown((n) => n + 1), pause);
    return () => clearTimeout(timer);
  }, [playing, done, shown]);

  const events = demoEvents.slice(0, shown);
  const card = demoEvents[0].payload.card;
  const turns = events.filter((e) => e.kind === "turn_completed").length;
  return <AppShell current="/call/demo" connected>
    <div className="title-row">
      <div>
        <h1>{card.merchant_name}</h1>
        <p className="sub">Recorded demo call · {card.why_now}</p>
      </div>
      <div className="playback">
        <button className="btn" onClick={() => setPlaying(!playing)} disabled={done}>{playing && !done ? "Pause" : "Play"}</button>
        <button className="btn" onClick={() => { setShown(4); setPlaying(true); }}>Restart</button>
        <button className="btn ghost" onClick={() => setShown(demoEvents.length)} disabled={done}>Show whole call</button>
      </div>
    </div>
    <p className="note">This is a scripted recording with a simulated merchant, in the same event format the ledger streams. Calls on real missions open this view at their own mission id.</p>
    <CallView events={events} newSince={Math.max(0, turns - 1)} />
  </AppShell>;
}

/** A real mission: its whole ledger, then live events as they happen. */
function LiveCall({ missionId }) {
  const [mission, setMission] = useState(null);
  const [error, setError] = useState("");
  const [scenarioRunning, setScenarioRunning] = useState(false);
  const { events, connected } = useMissionStream({ missionId, replay: 500 });

  useEffect(() => {
    api(`/api/missions/${missionId}`).then((d) => setMission(d.mission)).catch((e) => setError(e.message));
    // While a demo scenario plays on this mission, nobody else may speak on it (the server refuses with 409).
    api(`/api/calls/${missionId}/status`).then((d) => setScenarioRunning(d.scenario_running)).catch(() => setScenarioRunning(false));
  }, [missionId, events.length]);

  const canSpeak = mission && !scenarioRunning;
  const finished = !!mission && FINISHED.has(mission.state);

  return <AppShell current="/call/live" connected={connected}>
    <div className="title-row">
      <div>
        <h1>{mission?.card.merchant_name || "Live call"}</h1>
        <p className="sub">{mission ? `Live · ${mission.card.why_now}` : error ? "This mission could not be loaded." : "Connecting to the mission ledger…"}</p>
      </div>
      <div className="actions"><Link className="btn" href={`/missions?m=${missionId}`}>Open in Mission control</Link></div>
    </div>
    {error && <div className="error" role="alert" style={{ marginBottom: 24 }}><span>{error}</span><Link className="text-action" href="/missions">Back to Mission control</Link></div>}
    {!error && <CallView events={events} mission={mission} newSince={Infinity}
      composer={canSpeak ? <SayAsMerchant missionId={missionId} finished={finished} /> : null} />}
    {mission && scenarioRunning && <p className="note" style={{ marginTop: 24 }}>A demo scenario is playing on this mission. You can speak on it once the scenario has finished.</p>}
    {mission && <PhoneLink missionId={missionId} />}
  </AppShell>;
}

const VOICE_LABELS = { connecting: "Connecting the microphone…", listening: "Hold the mic and speak", processing: "One moment", thinking: "Chanakya is thinking", speaking: "Chanakya is speaking", error: "Voice stopped" };

/** Type what the merchant says, or hold the mic and say it; Chanakya answers on this mission and the call above updates from the ledger. */
function SayAsMerchant({ missionId, finished }) {
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  // The first press opens a voice session on this mission; while it is open, only held speech is sent.
  const [voiceOpen, setVoiceOpen] = useState(false);
  const voice = useVoiceCall({ isOpen: voiceOpen, onClose: () => setVoiceOpen(false), path: `/api/calls/${missionId}/voice`, modal: false, pushToTalk: true });
  const voiceFailed = voiceOpen && voice.callState === "error";
  // When the call ends, the voice session stays open until Chanakya's last line has been spoken.
  const replying = ["processing", "thinking", "speaking"].includes(voice.callState);
  useEffect(() => {
    if (finished && voiceOpen && !replying) setVoiceOpen(false);
  }, [finished, voiceOpen, replying]);
  function hold(e) {
    e.preventDefault();
    if (voiceFailed) return;
    if (!voiceOpen) { primeVoiceAudio(); setVoiceOpen(true); }
    voice.holdMic();
  }
  async function send(e) {
    e.preventDefault();
    if (!text.trim()) return;
    setBusy(true);
    try { await api(`/api/calls/${missionId}/say`, { method: "POST", body: { text } }); setText(""); setError(""); }
    catch (err) { setError(err.message); }
    finally { setBusy(false); }
  }
  if (finished) {
    return voiceOpen ? <p className="voice-status" role="status"><b>{VOICE_LABELS[voice.callState] || "Call ended"}</b></p> : null;
  }
  return <form className="say-box" onSubmit={send}>
    <label htmlFor="say" className="meta" style={{ flexBasis: "100%" }}>Speak as the merchant: type a line, or hold the mic and talk</label>
    <input id="say" className="btn" style={{ flex: 1, minWidth: 0, textAlign: "left" }} value={text} maxLength={500}
      onChange={(e) => setText(e.target.value)} placeholder="Haan ji, boliye?" disabled={busy} />
    <button
      type="button"
      className={`mic-btn${voice.talking ? " talking" : ""}`}
      aria-label={voice.talking ? "Release to send" : "Hold to talk"}
      aria-pressed={voice.talking}
      title="Hold to talk"
      disabled={voiceFailed}
      onPointerDown={hold}
      onPointerUp={voice.releaseMic}
      onPointerLeave={() => voice.talking && voice.releaseMic()}
      onPointerCancel={voice.releaseMic}
      onKeyDown={(e) => { if ((e.key === " " || e.key === "Enter") && !e.repeat) hold(e); }}
      onKeyUp={(e) => { if (e.key === " " || e.key === "Enter") { e.preventDefault(); voice.releaseMic(); } }}
    ><MicIcon /></button>
    <button className="btn primary" disabled={busy || !text.trim()}>{busy ? "Chanakya is thinking…" : "Say"}</button>
    {voiceOpen && <div className="voice-status" role="status" style={{ flexBasis: "100%" }}>
      <b>{voice.talking ? "Listening, release to send" : VOICE_LABELS[voice.callState] || voice.callState}</b>
      <span className="meta num">{voice.duration}</span>
      {voiceFailed && <span className="meta">{voice.connectionError}</span>}
      <span ref={voice.messagesContainerRef} hidden />
      <button type="button" className="text-action" onClick={voice.handleEndCall}>Turn off the mic</button>
    </div>}
    {error && <p className="error" role="alert" style={{ flexBasis: "100%" }}>{error}</p>}
  </form>;
}

function MicIcon() {
  return <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <rect x="9" y="3" width="6" height="12" rx="3" /><path d="M5 11a7 7 0 0 0 14 0M12 18v3M8 21h8" />
  </svg>;
}
