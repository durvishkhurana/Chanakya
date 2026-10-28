"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, useCallback, useEffect, useMemo, useRef, useState } from "react";

import AppShell from "../../components/missions/AppShell";
import ConcernMeter from "../../components/missions/ConcernMeter";
import { api, useMissionStream } from "../../lib/chanakyaApi";
import {
  deriveCallView, doorLabel, eventSummary, groupMissions, languageLabel, missionCounts, percent, stateLabel, time, topWorries, worryLabel,
} from "../../lib/missionView.mjs";

const TABS = [["queue", "Queue"], ["active", "In progress"], ["finished", "Finished"], ["handoffs", "Hand-offs"]];

export default function MissionControlPage() {
  return <Suspense fallback={null}><MissionControl /></Suspense>;
}

function MissionControl() {
  const params = useSearchParams();
  const [rows, setRows] = useState(null);
  const [handoffs, setHandoffs] = useState([]);
  const [clock, setClock] = useState(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState("");
  const [tab, setTab] = useState(params.get("tab") === "handoffs" ? "handoffs" : "queue");
  const [selected, setSelected] = useState(params.get("m"));
  const { events, connected } = useMissionStream({ replay: 0 });

  const load = useCallback(async () => {
    try {
      const [missions, cards, now] = await Promise.all([api("/api/missions"), api("/api/handoffs"), api("/api/missions/clock")]);
      setRows(missions);
      setHandoffs(cards);
      setClock(now.now);
      setError("");
    } catch (e) {
      setError(e.message);
    }
  }, []);

  // Reload when the ledger changes; bursts of events collapse into one reload.
  useEffect(() => {
    const timer = setTimeout(load, events.length ? 150 : 0);
    return () => clearTimeout(timer);
  }, [load, events.length]);

  const groups = useMemo(() => groupMissions(rows || []), [rows]);
  const counts = useMemo(() => missionCounts(rows || [], handoffs), [rows, handoffs]);
  const listed = tab === "queue" ? groups.waiting : tab === "active" ? groups.active : groups.finished;
  const selectedId = selected || listed[0]?.mission.id || null;
  const next = groups.waiting.find((r) => r.queue?.ready)?.mission;

  async function act(label, fn) {
    setBusy(label);
    try { await fn(); await load(); } catch (e) { setError(e.message); } finally { setBusy(""); }
  }

  const topbar = <>
    <span className="clock">Demo clock <b className="num">{clock ? time(clock) : "--:--"}</b> IST</span>
    <button className="btn small" disabled={!!busy} onClick={() => act("2h", () => api("/api/missions/clock/advance", { method: "POST", body: { minutes: 120 } }))}>+2 hours</button>
    <button className="btn small hide-phone" disabled={!!busy} onClick={() => act("1d", () => api("/api/missions/clock/advance", { method: "POST", body: { minutes: 1440 } }))}>+1 day</button>
  </>;

  return <AppShell current="/missions" counts={{ handoffs: counts.handoffsOpen }} connected={connected} topbar={topbar}>
    <div className="title-row">
      <div>
        <h1>Mission control</h1>
        <p className="sub">{rows === null ? "Loading missions…" : rows.length === 0
          ? "No missions yet. Load the demo signals, or request a callback on the mock product page."
          : <><b>{counts.ready} ready to call now</b> · {counts.handoffsOpen} {counts.handoffsOpen === 1 ? "hand-off is" : "hand-offs are"} waiting for a person</>}</p>
      </div>
      <div className="actions">
        <button className="btn" disabled={!!busy} onClick={() => act("feed", () => api("/api/missions/signals/demo-feed", { method: "POST" }))}>{busy === "feed" ? "Loading…" : "Load demo signals"}</button>
        {next ? <Link className="btn primary" href={`/call/${next.id}`}>Call {next.card.merchant_name}</Link>
          : <button className="btn primary" disabled>Nobody to call right now</button>}
      </div>
    </div>

    {error && <div className="error" role="alert" style={{ marginBottom: 24 }}><span>Couldn’t reach the mission service. {error}</span><button className="text-action" onClick={load}>Retry</button></div>}

    <div className="kpis" aria-label="Mission counts">
      <Kpi label="Ready to call" value={counts.ready} note={`of ${counts.waiting} waiting in the queue`} loading={rows === null} />
      <Kpi label="In conversation" value={counts.talking} note="calls running now" loading={rows === null} />
      <Kpi label="Waiting on the merchant" value={counts.onMerchant} note="link sent, being verified" loading={rows === null} />
      <Kpi label="Done, verified" value={counts.done} note="confirmed by the system" loading={rows === null} />
      <Kpi label="Closed or handed off" value={counts.closed} note="declined, do-not-call or a person" loading={rows === null} />
    </div>

    <div className="split">
      <section aria-label="Missions">
        <div className="tabs" role="tablist">
          {TABS.map(([id, label]) => <button key={id} role="tab" aria-selected={tab === id} onClick={() => { setTab(id); setSelected(null); }}>
            {label}<span className="n">{id === "queue" ? groups.waiting.length : id === "active" ? groups.active.length : id === "finished" ? groups.finished.length : counts.handoffsOpen}</span>
          </button>)}
        </div>
        {tab === "handoffs"
          ? <Handoffs cards={handoffs} busy={busy} act={act} />
          : <MissionTable rows={listed} tab={tab} loading={rows === null} selectedId={selectedId} onSelect={setSelected}
              onLoadDemo={() => act("feed", () => api("/api/missions/signals/demo-feed", { method: "POST" }))} />}
      </section>
      <aside className="stack" aria-label="Selected mission">
        {selectedId && tab !== "handoffs" ? <MissionDetail key={selectedId} id={selectedId} version={events.length} busy={busy} act={act} />
          : <div className="panel"><p className="meta">Select a mission to see its card, the concern meter and its ledger.</p></div>}
      </aside>
    </div>
  </AppShell>;
}

function Kpi({ label, value, note, loading }) {
  return <div className="kpi">
    <div className="kpi-label">{label}</div>
    {loading ? <div className="skeleton" style={{ height: 28, width: 40, marginTop: 7 }} /> : <div className="kpi-value">{value}</div>}
    <div className="kpi-note">{note}</div>
  </div>;
}

function MissionTable({ rows, tab, loading, selectedId, onSelect, onLoadDemo }) {
  if (loading) return <div aria-busy="true">{[0, 1, 2, 3].map((i) => <div key={i} className="skeleton" style={{ height: 40, margin: "12px 0" }} />)}</div>;
  if (!rows.length) {
    const sentence = { queue: "Nobody is waiting to be called.", active: "No call is running right now.", finished: "No mission has finished yet." }[tab];
    return <div className="empty"><span>{sentence}</span>{tab === "queue" && <button className="btn" onClick={onLoadDemo}>Load demo signals</button>}</div>;
  }
  return <div className="table-wrap">
    <table>
      <thead><tr>
        <th>Merchant</th><th className="hide-phone">Why now</th><th>Likely worry</th>
        {tab === "queue" ? <><th className="n hide-phone">Priority</th><th>Status</th></> : <th>State</th>}
      </tr></thead>
      <tbody>{rows.map(({ mission, queue }) => {
        const [worry, p] = topWorries(mission.card.starting_worries, 1)[0] || [];
        return <tr key={mission.id} aria-selected={mission.id === selectedId} onClick={() => onSelect(mission.id)}
          tabIndex={0} onKeyDown={(e) => { if (e.key === "Enter") onSelect(mission.id); }}>
          <td><span className="name">{mission.card.merchant_name}</span><span className="sub">{languageLabel(mission.card.language)} · {mission.card.goal}</span></td>
          <td className="why hide-phone">{mission.card.why_now}<span className="sub">{doorLabel(mission.card.door)}</span></td>
          <td>{worry ? worryLabel(worry) : "—"}<span className="sub num">{worry ? `${percent(p)} starting guess` : ""}</span></td>
          {tab === "queue" ? <>
            <td className="n num hide-phone">{mission.card.priority.toFixed(2)}</td>
            <td>{queue?.ready ? <span className="pill pos">Ready</span> : <span className="pill">{queue?.reason || "Waiting"}</span>}</td>
          </> : <td><StatePill state={mission.state} />{mission.outcome && <span className="sub">{mission.outcome}</span>}</td>}
        </tr>;
      })}</tbody>
    </table>
  </div>;
}

function StatePill({ state }) {
  const tone = state === "DONE" ? "pos" : ["FAILED", "CLOSED_NOT_INTERESTED", "CLOSED_UNREACHABLE"].includes(state) ? "" : state === "ESCALATED" ? "warn" : "live";
  return <span className={`pill ${tone}`}>{stateLabel(state)}</span>;
}

function MissionDetail({ id, version, busy, act }) {
  const [data, setData] = useState(null);
  const [outbox, setOutbox] = useState([]);
  const [error, setError] = useState("");
  const firstSeen = useRef(null);

  useEffect(() => {
    let live = true;
    Promise.all([api(`/api/missions/${id}`), api(`/api/actions/outbox?mission_id=${id}`)])
      .then(([detail, messages]) => {
        if (!live) return;
        firstSeen.current ??= new Set(detail.events.map((e) => e.id));
        setData(detail);
        setOutbox(messages);
        setError("");
      })
      .catch((e) => live && setError(e.message));
    return () => { live = false; };
  }, [id, version]);

  if (error) return <div className="panel"><div className="error"><span>Couldn’t load this mission. {error}</span></div></div>;
  if (!data) return <div className="panel" aria-busy="true"><div className="skeleton" style={{ width: "60%" }} /><div className="skeleton" style={{ height: 120, marginTop: 16 }} /></div>;

  const { mission, events } = data;
  const view = deriveCallView(events, mission.card);
  const canEscalate = !["DONE", "ESCALATED", "CLOSED_NOT_INTERESTED", "CLOSED_UNREACHABLE", "FAILED", "CREATED", "SCHEDULED", "CONTACTING"].includes(mission.state);
  return <>
    <section className="panel">
      <header><h2>{mission.card.merchant_name}</h2><StatePill state={mission.state} /></header>
      <dl className="facts">
        <div className="fact"><dt>Goal</dt><dd>{mission.card.goal}</dd></div>
        <div className="fact"><dt>Why now</dt><dd>{mission.card.why_now}</dd></div>
        <div className="fact"><dt>Door</dt><dd>{doorLabel(mission.card.door)}</dd></div>
        <div className="fact"><dt>Window</dt><dd className="num">{mission.card.contact_window.start_hour}:00 to {mission.card.contact_window.end_hour}:00 IST · {languageLabel(mission.card.language)}</dd></div>
        {mission.outcome && <div className="fact"><dt>Outcome</dt><dd>{mission.outcome}</dd></div>}
      </dl>
      <h3 className="subhead">Concern meter</h3>
      <ConcernMeter current={view.concerns} starting={mission.card.starting_worries} />
      <div className="actions" style={{ justifyContent: "flex-start", marginTop: 16 }}>
        <Link className="btn" href={`/call/${mission.id}`}>Open live call view</Link>
        {canEscalate && <button className="btn ghost" disabled={!!busy} onClick={() => act("escalate", () => api("/api/handoffs/escalate", {
          method: "POST", body: { mission_id: mission.id, reason: "Operator asked a person to take over" } }))}>Hand to a person</button>}
      </div>
    </section>
    <section className="panel">
      <header><h2>Ledger</h2><span className="meta num">{events.length} events</span></header>
      <ol className="feed">{[...events].reverse().slice(0, 10).map((event) =>
        <li key={event.id} className={firstSeen.current && !firstSeen.current.has(event.id) ? "new" : undefined}>
          <time dateTime={event.at}>{time(event.at)}</time><span>{eventSummary(event)}</span>
        </li>)}</ol>
    </section>
    {outbox.length > 0 && <section className="panel">
      <header><h2>Messages sent</h2><span className="meta">Mock SMS and WhatsApp</span></header>
      {outbox.map((m) => <div key={m.id} className="message">
        <span className="meta">{m.channel === "sms" ? "SMS" : "WhatsApp"} · {time(m.at)}</span>
        {m.link ? <>{m.body.replace(m.link, "")}<Link href={m.link}>{m.link}</Link></> : m.body}
      </div>)}
    </section>}
  </>;
}

function Handoffs({ cards, busy, act }) {
  const open = cards.filter((c) => c.status !== "resolved");
  if (!cards.length) return <div className="empty">No hand-offs yet. When Chanakya hands a merchant to a person, the full context appears here.</div>;
  return <div>{[...open, ...cards.filter((c) => c.status === "resolved")].map((card) => <article key={card.id} className="handoff">
    <div className="handoff-head">
      <span className="name">{card.merchant_name}</span>
      <span className={`pill ${card.status === "resolved" ? "pos" : card.urgent ? "neg" : "warn"}`}>{card.status === "resolved" ? "Resolved" : card.urgent ? "Urgent" : card.status === "claimed" ? `With ${card.claimed_by}` : "Waiting"}</span>
    </div>
    <p>{card.summary}</p>
    <p className="meta">Reason: {card.reason} · Worries: {topWorries(card.open_concerns, 3).map(([id, p]) => `${worryLabel(id)} ${percent(p)}`).join(", ") || "—"}</p>
    {card.actions.length > 0 && <p className="meta">Done so far: {card.actions.join(", ")}</p>}
    {card.status === "resolved" && <p className="meta">Resolution: {card.resolution}</p>}
    <div className="actions" style={{ justifyContent: "flex-start" }}>
      {card.status === "open" && <button className="btn small" disabled={!!busy} onClick={() => act("claim", () => api(`/api/handoffs/${card.id}/claim`, { method: "POST", body: { agent: "Sunita" } }))}>Claim as Sunita</button>}
      {card.status === "claimed" && <button className="btn small" disabled={!!busy} onClick={() => act("resolve", () => api(`/api/handoffs/${card.id}/resolve`, { method: "POST", body: { resolution: "Called the merchant back and settled it" } }))}>Mark resolved</button>}
      <Link className="btn small ghost" href={`/missions?m=${card.mission_id}`}>Open mission</Link>
    </div>
  </article>)}</div>;
}
