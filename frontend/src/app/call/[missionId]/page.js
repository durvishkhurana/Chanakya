"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";

import CallView from "../../../components/call/CallView";
import { demoEvents } from "../../../components/call/demoFixture";
import AppShell from "../../../components/missions/AppShell";
import { api, useMissionStream } from "../../../lib/chanakyaApi";
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
  const { events, connected } = useMissionStream({ missionId, replay: 500 });

  useEffect(() => {
    api(`/api/missions/${missionId}`).then((d) => setMission(d.mission)).catch((e) => setError(e.message));
  }, [missionId, events.length]);

  return <AppShell current="/call/live" connected={connected}>
    <div className="title-row">
      <div>
        <h1>{mission?.card.merchant_name || "Live call"}</h1>
        <p className="sub">{mission ? `Live · ${mission.card.why_now}` : error ? "This mission could not be loaded." : "Connecting to the mission ledger…"}</p>
      </div>
      <div className="actions"><Link className="btn" href={`/missions?m=${missionId}`}>Open in Mission control</Link></div>
    </div>
    {error && <div className="error" role="alert" style={{ marginBottom: 24 }}><span>{error}</span><Link className="text-action" href="/missions">Back to Mission control</Link></div>}
    {!error && <CallView events={events} mission={mission} newSince={Infinity} />}
    {mission && !FINISHED.has(mission.state) && <SayAsMerchant missionId={missionId} />}
  </AppShell>;
}

/** Type what the merchant says; Chanakya answers on this mission and the call above updates from the ledger. */
function SayAsMerchant({ missionId }) {
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  async function send(e) {
    e.preventDefault();
    if (!text.trim()) return;
    setBusy(true);
    try { await api(`/api/calls/${missionId}/say`, { method: "POST", body: { text } }); setText(""); setError(""); }
    catch (err) { setError(err.message); }
    finally { setBusy(false); }
  }
  return <form className="panel" onSubmit={send} style={{ marginTop: 24, display: "flex", gap: 12, flexWrap: "wrap" }}>
    <label htmlFor="say" className="meta" style={{ flexBasis: "100%" }}>Speak as the merchant (text stands in for the phone line)</label>
    <input id="say" className="btn" style={{ flex: 1, minWidth: 0, textAlign: "left" }} value={text} maxLength={500}
      onChange={(e) => setText(e.target.value)} placeholder="Haan ji, boliye?" disabled={busy} />
    <button className="btn primary" disabled={busy || !text.trim()}>{busy ? "Chanakya is thinking…" : "Say"}</button>
    {error && <p className="error" role="alert" style={{ flexBasis: "100%" }}>{error}</p>}
  </form>;
}
