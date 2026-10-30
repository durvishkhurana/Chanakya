"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import "../../components/call/call.css";
import AppShell from "../../components/missions/AppShell";
import ConcernMeter from "../../components/missions/ConcernMeter";
import { api } from "../../lib/chanakyaApi";
import { coachMoveLabel, handoffText, turnPause } from "../../lib/coachView.mjs";
import { percent, topWorries, worryLabel } from "../../lib/missionView.mjs";
import "./coach.css";

/** Coach mode: Chanakya follows a human telecaller's call and suggests each next move. It never speaks or acts. */
export default function CoachPage() {
  const [recorded, setRecorded] = useState([]);
  const [session, setSession] = useState(null);
  const [turns, setTurns] = useState([]);
  const [next, setNext] = useState(0);
  const [playing, setPlaying] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [draft, setDraft] = useState({ speaker: "merchant", text: "" });
  const end = useRef(null);

  const start = useCallback(async () => {
    setError("");
    try {
      const [call, fresh] = await Promise.all([api("/api/coach/recorded"), api("/api/coach/sessions", { method: "POST", body: { recorded: true } })]);
      setRecorded(call.turns);
      setSession(fresh);
      setTurns([]);
      setNext(0);
      return true;
    } catch (e) {
      setError(e.message.includes("404") || e.message === "Not Found"
        ? "Coach mode is off. Set COACH_ENABLED=true in .env and restart the backend." : e.message);
      return false;
    }
  }, []);

  const send = useCallback(async (turn) => {
    if (!session) return;
    setBusy(true);
    try {
      const reply = await api(`/api/coach/sessions/${session.session_id}/turns`, { method: "POST", body: turn });
      setTurns((all) => [...all, { ...turn, suggestion: reply.suggestion, turn: reply.turns }]);
      setSession(reply);
    } catch (e) {
      setError(e.message);
      setPlaying(false);
    } finally {
      setBusy(false);
    }
  }, [session]);

  useEffect(() => { start(); }, [start]);

  // Recorded playback: post the next turn after a pause sized to what was just said.
  useEffect(() => {
    if (!playing || busy || !session || next >= recorded.length) return undefined;
    const timer = setTimeout(() => { setNext((n) => n + 1); send(recorded[next]); }, next === 0 ? 600 : turnPause(recorded[next - 1].speaker));
    return () => clearTimeout(timer);
  }, [playing, busy, session, next, recorded, send]);

  // Scroll the transcript box only, never the page, so the suggestion stays where the reader left it.
  useEffect(() => { if (end.current) end.current.scrollTo({ top: end.current.scrollHeight, behavior: "smooth" }); }, [turns.length]);

  const showAll = async () => {
    setPlaying(false);
    for (let i = next; i < recorded.length; i += 1) {
      setNext(i + 1);
      await send(recorded[i]);
    }
  };

  const say = (event) => {
    event.preventDefault();
    const text = draft.text.trim();
    if (!text || busy) return;
    setPlaying(false);
    send({ speaker: draft.speaker, text });
    setDraft({ ...draft, text: "" });
  };

  const latest = [...turns].reverse().find((t) => t.suggestion)?.suggestion || null;
  const suggestedAt = turns.length - [...turns].reverse().findIndex((t) => t.suggestion);
  const [topId, topP] = topWorries(session?.worries, 1)[0] || [];
  const done = next >= recorded.length && recorded.length > 0;
  const merchantName = session?.merchant.name || "Merchant";

  return <AppShell current="/coach" connected={!!session && !error}>
    <div className="title-row">
      <div>
        <h1>Coach mode</h1>
        <p className="sub">Chanakya listens to a telecaller’s call and suggests the next move. It never speaks and takes no action.</p>
      </div>
      <div className="playback">
        <button className="btn" onClick={() => setPlaying(!playing)} disabled={done || !session}>{playing && !done ? "Pause" : "Play recorded call"}</button>
        <button className="btn" onClick={async () => { if (await start()) setPlaying(true); }} disabled={busy}>Restart</button>
        <button className="btn ghost" onClick={showAll} disabled={done || busy || !session}>Show whole call</button>
      </div>
    </div>
    <p className="note">The recorded call is fictional and scripted: a telecaller named Sunita and a kirana merchant in Jaipur. It replays with a fixed planner seed, so every replay shows the same suggestions. Pause it, or type below to coach your own lines.</p>
    {error && <div className="error" role="alert" style={{ marginBottom: 24 }}><span>{error}</span></div>}

    <div className="kpis" aria-label="Call at a glance">
      <div className="kpi"><div className="kpi-label">Turn</div><div className="kpi-value">{turns.length}</div><div className="kpi-note">{done ? "recording finished" : playing ? "playing the recording" : "paused"}</div></div>
      <div className="kpi"><div className="kpi-label">Most likely worry</div><div className="kpi-value">{topId ? percent(topP) : "—"}</div><div className="kpi-note">{topId ? worryLabel(topId) : "no estimate yet"}</div></div>
      <div className="kpi"><div className="kpi-label">Value of the suggestion</div><div className="kpi-value">{latest?.value != null ? latest.value.toFixed(2) : "—"}</div><div className="kpi-note">look-ahead chance of a yes, 0 to 1</div></div>
      <div className="kpi"><div className="kpi-label">Hand-off</div><div className="kpi-value">{session?.handoff ? "Now" : "No"}</div><div className="kpi-note">{session?.handoff ? "a senior should take over" : "not needed so far"}</div></div>
    </div>

    <div className="coach-grid">
      <section className="panel" aria-label="The call">
        <header><h2>The call</h2><span className="meta">{merchantName}</span></header>
        {turns.length === 0
          ? <div className="empty">{session ? "Waiting for the first words. Press Play, or type what was said below." : "Starting a coach session…"}</div>
          : <div className="call-transcript" ref={end} aria-live="polite">{turns.map((t, i) => <div key={i} className={`turn ${t.speaker} arrive`}>
            <span className="who">{t.speaker === "merchant" ? merchantName : "Telecaller"}</span>
            {t.text}
            {t.suggestion && <span className="coach-chip">Coach: {coachMoveLabel(t.suggestion.move)}</span>}
          </div>)}</div>}
        <form className="say" onSubmit={say}>
          <label className="sr-only" htmlFor="coach-speaker">Who spoke</label>
          <select id="coach-speaker" value={draft.speaker} onChange={(e) => setDraft({ ...draft, speaker: e.target.value })}>
            <option value="merchant">Merchant said</option>
            <option value="human_agent">I said</option>
          </select>
          <label className="sr-only" htmlFor="coach-text">What was said</label>
          <input id="coach-text" value={draft.text} maxLength={1000} placeholder="Abhi customer hain, baad mein call karo" onChange={(e) => setDraft({ ...draft, text: e.target.value })} />
          <button className="btn primary" type="submit" disabled={!session || busy || !draft.text.trim()}>Add</button>
        </form>
      </section>

      <section className="stack" aria-label="Chanakya's suggestions">
        <div className="panel" aria-live="polite">
          <header><h2>Suggested next move</h2><span className="meta">{latest ? `after turn ${suggestedAt}` : ""}</span></header>
          {latest ? <Suggestion suggestion={latest} /> : <div className="empty">A suggestion appears each time the merchant speaks.</div>}
        </div>
        <div className="panel">
          <header><h2>What the scorer heard</h2><span className="meta">{session?.scorer ? `${SCORER_LABELS[session.scorer] || session.scorer} scorer, latest merchant line` : "latest merchant line"}</span></header>
          {topWorries(session?.evidence, 3).filter(([, s]) => s > 0.01).length
            ? <ul className="checks">{topWorries(session.evidence, 3).filter(([, s]) => s > 0.01).map(([id, s]) => <li key={id}><span>{worryLabel(id)}</span><span className="num">{percent(s)}</span></li>)}</ul>
            : <p className="meta">After the merchant speaks, the worries their words point to appear here.</p>}
        </div>
        <div className="panel">
          <header><h2>What the merchant is worried about</h2><span className="meta">updates every merchant turn</span></header>
          {session ? <ConcernMeter current={session.worries} starting={session.starting_worries} /> : <div className="skeleton" style={{ height: 120 }} />}
        </div>
        <div className="panel">
          <header><h2>Hand-off</h2><span className="meta">for a senior colleague</span></header>
          {session?.handoff ? <HandoffCard card={session.handoff} />
            : <div className="empty">No hand-off needed. If the merchant sounds distressed, Chanakya says so and drafts the card for your senior here.</div>}
        </div>
      </section>
    </div>
  </AppShell>;
}

const SCORER_LABELS = { lexical: "Keyword", llm: "LLM", embedding: "Neural (e5)" };

function Suggestion({ suggestion }) {
  const { move, reason, guide, alternatives = [] } = suggestion;
  return <div>
    <p className="suggest-move">{coachMoveLabel(move)}</p>
    <p className="meta">{reason}</p>
    {alternatives.length > 0 && <p className="meta">Next best: {alternatives.map((a) => `${a.key.replaceAll("_", " ").toLowerCase()} ${a.value.toFixed(2)}`).join(" · ")}</p>}
    {guide && <div className="how">
      <h3>How to answer</h3>
      <p>{guide.how}</p>
      {guide.sources.length > 0 && <ul className="sources">{guide.sources.map((s) => <li key={s.url + s.title}>
        <a className="text-action" href={s.url} target="_blank" rel="noreferrer">{s.title}</a>
        <span className="meta"> · reviewed {s.reviewed}</span>
      </li>)}</ul>}
    </div>}
  </div>;
}

function HandoffCard({ card }) {
  const [copied, setCopied] = useState(false);
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(handoffText(card));
      setCopied(true);
    } catch {
      setCopied(false);
    }
  };
  return <article className="handoff">
    <div className="handoff-head"><span className="name">{card.merchant_name}</span><span className="pill neg">Urgent</span></div>
    <p>{card.summary}</p>
    <p className="meta">Reason: {card.reason} · Worries: {topWorries(card.open_concerns, 3).map(([id, p]) => `${worryLabel(id)} ${percent(p)}`).join(", ")}</p>
    <div className="actions" style={{ justifyContent: "flex-start" }}>
      <button className="btn small" onClick={copy}>{copied ? "Copied" : "Copy for your senior"}</button>
    </div>
  </article>;
}
