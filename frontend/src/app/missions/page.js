"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useCallback, useEffect, useMemo, useRef, useState } from "react";

import Approvals from "../../components/missions/Approvals";
import AppShell from "../../components/missions/AppShell";
import ConcernMeter from "../../components/missions/ConcernMeter";
import LeavingReasons from "../../components/missions/LeavingReasons";
import { api, resetMission, useDemoTools, useMissionStream } from "../../lib/chanakyaApi";
import {
  countRows, deriveCallView, doorLabel, eventSummary, groupMissions, languageLabel, missionCounts, percent, stateLabel, time, topWorries, worryLabel,
} from "../../lib/missionView.mjs";

const TABS = [["queue", "Queue"], ["active", "In progress"], ["finished", "Finished"], ["handoffs", "Hand-offs"], ["approvals", "Approvals"]];
const SIDE_TABS = ["handoffs", "approvals"];

export default function MissionControlPage() {
  return <Suspense fallback={null}><MissionControl /></Suspense>;
}

function MissionControl() {
  const params = useSearchParams();
  const [rows, setRows] = useState(null);
  const [handoffs, setHandoffs] = useState([]);
  const [approvals, setApprovals] = useState([]);
  const [clock, setClock] = useState(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState("");
  const [tab, setTab] = useState(SIDE_TABS.includes(params.get("tab")) ? params.get("tab") : "queue");
  const [selected, setSelected] = useState(params.get("m"));
  const { events, connected } = useMissionStream({ replay: 0 });

  const load = useCallback(async () => {
    try {
      const [missions, cards, now, requests] = await Promise.all([api("/api/missions"), api("/api/handoffs"),
        api("/api/missions/clock"), api("/api/approvals").catch(() => [])]);
      setRows(missions);
      setHandoffs(cards);
      setApprovals(requests);
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

  // A run retired by Reset stays in the ledger but leaves the board; its fresh copy waits in the queue.
  const visible = useMemo(() => (rows || []).filter((r) => r.mission.outcome !== "reset"), [rows]);
  const groups = useMemo(() => groupMissions(visible), [visible]);
  const counts = useMemo(() => missionCounts(visible, handoffs), [visible, handoffs]);
  const listed = tab === "queue" ? groups.waiting : tab === "active" ? groups.active : groups.finished;
  const selectedId = selected || listed[0]?.mission.id || null;
  const next = groups.waiting.find((r) => r.queue?.ready)?.mission;
  // The primary button follows the selected row: open a running call, call a ready one, else the top of the queue.
  const running = groups.active.find((r) => r.mission.id === selectedId)?.mission;
  const ready = groups.waiting.find((r) => r.mission.id === selectedId && r.queue?.ready)?.mission;
  const target = running || ready || next;

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
        <ScenarioRunner busy={busy} act={act} />
        <button className="btn" disabled={!!busy} onClick={() => act("feed", () => api("/api/missions/signals/demo-feed", { method: "POST" }))}>{busy === "feed" ? "Loading…" : "Load demo signals"}</button>
        {target ? <Link className="btn primary" href={`/call/${target.id}`}>{target === running ? `Open ${target.card.merchant_name}'s call` : `Call ${target.card.merchant_name}`}</Link>
          : <button className="btn primary" disabled>Nobody to call right now</button>}
      </div>
    </div>

    {error && <div className="error" role="alert" style={{ marginBottom: 24 }}><span>Couldn’t reach the mission service. {error}</span><button className="text-action" onClick={load}>Retry</button></div>}

    <div className="kpis notes-optional" aria-label="Mission counts">
      <Kpi label="Ready to call" value={counts.ready} note={`of ${counts.waiting} waiting in the queue`} loading={rows === null} />
      <Kpi label="In conversation" value={counts.talking} note="calls running now" loading={rows === null} />
      <Kpi label="Waiting on the merchant" value={counts.onMerchant} note="awaiting approval, link sent or being verified" loading={rows === null} />
      <Kpi label="Done, verified" value={counts.done} note="confirmed by the system" loading={rows === null} />
      <Kpi label="Closed or handed off" value={counts.closed} note="declined, do-not-call or a person" loading={rows === null} />
    </div>

    <div className="split">
      <section aria-label="Missions">
        <div className="tabs" role="tablist">
          {TABS.map(([id, label]) => <button key={id} role="tab" aria-selected={tab === id} onClick={() => { setTab(id); setSelected(null); }}>
            {label}<span className="n">{id === "queue" ? groups.waiting.length : id === "active" ? groups.active.length : id === "finished" ? groups.finished.length : id === "handoffs" ? counts.handoffsOpen : approvals.filter((a) => a.status === "pending").length}</span>
          </button>)}
        </div>
        {tab === "handoffs"
          ? <Handoffs cards={handoffs} busy={busy} act={act} />
          : tab === "approvals" ? <Approvals requests={approvals} now={clock} busy={busy} act={act} />
          : <MissionTable rows={listed} tab={tab} loading={rows === null} selectedId={selectedId} onSelect={setSelected}
              onLoadDemo={() => act("feed", () => api("/api/missions/signals/demo-feed", { method: "POST" }))} />}
      </section>
      <aside className="stack" aria-label="Selected mission">
        {selectedId && !SIDE_TABS.includes(tab) ? <MissionDetail key={selectedId} id={selectedId} version={events.length} busy={busy} act={act} />
          : <div className="panel"><p className="meta">Select a mission to see its card, the concern meter and its ledger.</p></div>}
      </aside>
    </div>
    <Winback version={events.length} />
  </AppShell>;
}

/** Runs one of the demo storyline scenarios on a real mission and opens its live call. */
function ScenarioRunner({ busy, act }) {
  const router = useRouter();
  const [scenarios, setScenarios] = useState([]);
  const [name, setName] = useState("");
  useEffect(() => { api("/api/calls/scenarios").then(setScenarios).catch(() => setScenarios([])); }, []);
  if (!scenarios.length) return null;
  const run = () => act("scenario", async () => {
    const { mission_id: id } = await api(`/api/calls/scenarios/${name || scenarios[0].name}`, { method: "POST" });
    router.push(`/call/${id}`);
  });
  return <>
    <select className="btn" aria-label="Demo scenario" value={name || scenarios[0].name} onChange={(e) => setName(e.target.value)} disabled={!!busy}>
      {scenarios.map((s) => <option key={s.name} value={s.name}>{s.title.split(":")[0]}</option>)}
    </select>
    <button className="btn" disabled={!!busy} onClick={run}>{busy === "scenario" ? "Starting…" : "Run scenario"}</button>
  </>;
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
  const demoTools = useDemoTools();
  const [data, setData] = useState(null);
  const [outbox, setOutbox] = useState([]);
  const [error, setError] = useState("");
  const firstSeen = useRef(null);

  useEffect(() => {
    let live = true;
    api(`/api/missions/${id}`)
      .then(async (detail) => [detail, await api(`/api/messages/${detail.mission.card.merchant_id}`)])
      .then(([detail, messages]) => {
        if (!live) return;
        firstSeen.current ??= new Set(detail.events.map((e) => e.id));
        setData(detail);
        setOutbox(messages.filter((m) => m.mission_id === id));
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
        {demoTools && <button className="btn ghost" disabled={!!busy} title="Put this mission back in the queue for another run"
          onClick={() => act("reset", () => resetMission(mission.id))}>{busy === "reset" ? "Resetting…" : "Reset to queue"}</button>}
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
      <header><h2>Messages</h2><span className="meta">Mock SMS and WhatsApp</span></header>
      {outbox.map((m) => <div key={m.id} className={`message${m.direction === "in" ? " in" : ""}`}>
        <span className="meta">{m.direction === "in" ? `${mission.card.merchant_name} replied` : "Sent"} on {m.channel === "sms" ? "SMS" : "WhatsApp"} · {time(m.at)}</span>
        <span style={{ whiteSpace: "pre-line" }}>{m.link ? <>{m.body.replace(m.link, "")}<Link href={m.link}>{m.link}</Link></> : m.body}</span>
      </div>)}
      {!["DONE", "CLOSED_NOT_INTERESTED", "CLOSED_UNREACHABLE", "FAILED"].includes(mission.state) && <MerchantReply mission={mission} busy={busy} act={act} />}
    </section>}
  </>;
}

/** Simulated inbox (B13): type what the merchant answers on WhatsApp or SMS; it goes back into this mission. */
function MerchantReply({ mission, busy, act }) {
  const [body, setBody] = useState("");
  const [channel, setChannel] = useState("whatsapp");
  const [result, setResult] = useState(null);
  const send = (event) => {
    event.preventDefault();
    if (!body.trim()) return;
    act("reply", async () => {
      setResult(await api("/api/messages/reply", { method: "POST", body: { merchant_id: mission.card.merchant_id, channel, body } }));
      setBody("");
    });
  };
  return <form className="actions" style={{ justifyContent: "flex-start", marginTop: 12, flexWrap: "wrap" }} onSubmit={send}>
    <label className="meta" htmlFor="reply-body">Reply as the merchant</label>
    <select aria-label="Channel" value={channel} onChange={(e) => setChannel(e.target.value)}>
      <option value="whatsapp">WhatsApp</option><option value="sms">SMS</option>
    </select>
    <input id="reply-body" value={body} maxLength={1000} placeholder="Ho gaya / STOP / call me" onChange={(e) => setBody(e.target.value)} />
    <button className="btn small" disabled={!!busy || !body.trim()}>Send reply</button>
    {result && <p className="meta" role="status">Read as “{result.intent}”: {result.outcome}</p>}
  </form>;
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


/** Win-back at a glance (WINBACK_ENABLED): who is held out for comparison, and why former merchants left. */
function Winback({ version }) {
  const [data, setData] = useState(null);
  useEffect(() => { api("/api/missions/winback").then(setData).catch(() => setData(null)); }, [version]);
  if (!data?.enabled) return null;
  const { holdouts, reasons } = data;
  return <section aria-label="Win-back" style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(280px, 1fr))", gap: 24, marginTop: 24 }}>
    <div className="panel">
      <header><h2>Win-back holdout</h2><span className="meta">Mock merchants</span></header>
      <p className="meta" style={{ marginBottom: 12 }}>One in five eligible former merchants is not called, so the win-back rate can be compared with doing nothing.</p>
      {holdouts.length === 0 ? <p className="meta">Nobody is held out yet. Load the demo signals to run the churn scan.</p>
        : <ul className="facts">{holdouts.map((h) => <li key={h.merchant_id} style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap", fontSize: 13 }}><span className="pill">holdout (not called)</span>
          <span>{h.merchant_name} · {h.city} · stopped {h.days} days ago</span></li>)}</ul>}
    </div>
    <div className="panel">
      <header><h2>Reasons for leaving</h2><span className="meta num">{reasons.total} recorded</span></header>
      <LeavingReasons reasons={reasons} />
    </div>
  </section>;
}
