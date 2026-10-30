"use client";

import { useEffect, useRef, useState } from "react";

import AppShell from "../../components/missions/AppShell";
import LeavingReasons from "../../components/missions/LeavingReasons";
import useCharts from "../../components/missions/useCharts";
import { api } from "../../lib/chanakyaApi";
import { breakdownRows, escalationLabel, funnelRows, moveRows, productLabel, typeLabel } from "../../lib/insightsView.mjs";
import { languageLabel, percent, worryLabel } from "../../lib/missionView.mjs";
import "./insights.css";

const BREAKDOWNS = [["by_product", "Product", productLabel], ["by_language", "Language", languageLabel], ["by_day", "Day", (d) => d]];

/** Manager insights: what merchants worry about, where missions drop out, which answers work, and why calls escalate. */
export default function InsightsPage() {
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  const [type, setType] = useState("overall");

  useEffect(() => { api("/api/insights").then(setData).catch((e) => setError(e.message)); }, []);

  const head = data?.headline;
  const loading = !data && !error;
  const empty = data && head.missions === 0;
  const stages = funnelRows(type === "overall" ? data?.funnel.overall : data?.funnel.by_type[type]);

  return <AppShell current="/insights" connected={!!data}>
    <div className="title-row">
      <div>
        <h1>Insights</h1>
        <p className="sub">What merchants worry about, where missions drop out, and which answers work. Counted from the mission ledger.</p>
      </div>
    </div>
    {error && <div className="error" role="alert" style={{ marginBottom: 24 }}><span>{error.includes("404") || error === "Not Found"
      ? "Insights need the mission APIs. Set MISSIONS_ENABLED=true and restart the backend." : error}</span></div>}
    {empty && <div className="empty" style={{ marginBottom: 24 }}>
      No missions in this ledger yet. Load the demo signals in Mission control, or seed a simulated ledger:
      <code> python -m chanakya.insights.seed</code>, then start the backend with its <code>CHANAKYA_DB_PATH</code>.
    </div>}

    <div className="kpis" aria-label="At a glance">
      <Kpi label="Missions" value={head?.missions} note={head ? `${head.talked} reached the merchant` : ""} loading={loading} />
      <Kpi label="Clear yes" value={head ? percent(head.consent_rate) : null} note="of calls that reached the merchant" loading={loading} />
      <Kpi label="Verified done" value={head?.done} note={head ? `${percent(head.done_rate)} of missions, confirmed by a system` : ""} loading={loading} />
      <Kpi label="Handed to a person" value={head?.escalated} note={head?.median_agent_turns != null ? `median call: ${head.median_agent_turns} Chanakya turns` : ""} loading={loading} />
    </div>

    {data && !empty && <>
      <div className="insights-grid">
        <section className="panel" aria-label="Mission funnel">
          <header><h2>Mission funnel</h2>
            <div className="tabs small" role="tablist" aria-label="Mission type">
              {["overall", ...Object.keys(data.funnel.by_type)].map((key) => <button key={key} role="tab" aria-selected={type === key}
                className={type === key ? "active" : ""} onClick={() => setType(key)}>{key === "overall" ? "All" : typeLabel(key)}</button>)}
            </div>
          </header>
          <ol className="funnel">{stages.map((s) => <li key={s.stage}>
            <span className="label">{s.label}</span>
            <span className="track" aria-hidden="true"><span className="fill" style={{ width: `${s.share * 100}%` }} /></span>
            <span className="num value">{s.missions}</span>
            <span className="meta drop">{s.dropped ? `−${s.dropped}` : ""}</span>
          </li>)}</ol>
          <p className="meta" style={{ marginTop: 12 }}>Not done yet: {Object.entries(data.funnel.not_done).map(([state, n]) => `${n} ${state.toLowerCase().replaceAll("_", " ")}`).join(", ") || "none"}.</p>
        </section>

        <section className="panel" aria-label="Worries found">
          <header><h2>What merchants worry about</h2><span className="meta num">{data.worries.calls} calls</span></header>
          <BarList rows={Object.entries(data.worries.overall).slice(0, 8).map(([id, n]) => ({ label: worryLabel(id), value: n }))} />
          {data.worries.differs_from_card != null && <p className="meta" style={{ marginTop: 12 }}>
            In {percent(data.worries.differs_from_card)} of calls the worry Chanakya found differed from the starting guess on the mission card.</p>}
        </section>
      </div>

      <section className="panel" aria-label="Worries by product, language and day" style={{ marginTop: 24 }}>
        <header><h2>Worries by product, language and day</h2><span className="meta">top three worries in each group</span></header>
        <div className="breakdowns">{BREAKDOWNS.map(([key, title, label]) => <div key={key}>
          <h3 className="subhead">{title}</h3>
          <ul className="breakdown">{breakdownRows(key === "by_day"
            ? Object.fromEntries(data.worries.by_day.map((d) => [d.day, d.counts])) : data.worries[key]).map((row) => <li key={row.group}>
            <div className="group"><span>{label(row.group)}</span><span className="meta num">{row.total} {row.total === 1 ? "call" : "calls"}</span></div>
            <div>{row.worries.map((w) => <span key={w.id} className="chip">{w.label} <b className="num">{percent(w.share)}</b></span>)}</div>
          </li>)}</ul>
        </div>)}</div>
      </section>

      <section className="panel" aria-label="Which answers work" style={{ marginTop: 24 }}>
        <header><h2>Does answering the worry help?</h2><span className="meta">clear yes rate; a difference needs 3 or more calls on each side</span></header>
        <MovesTable rows={moveRows(data.moves)} />
      </section>

      <div className="insights-grid" style={{ marginTop: 24 }}>
        <section className="panel" aria-label="Hand-offs">
          <header><h2>Why calls went to a person</h2><span className="meta num">{data.escalations.total} hand-offs, {data.escalations.urgent} urgent</span></header>
          {data.escalations.total === 0 ? <p className="meta">No call has been handed to a person yet.</p>
            : <BarList rows={Object.entries(data.escalations.by_reason).map(([reason, n]) => ({ label: escalationLabel(reason), value: n }))} />}
          {data.escalations.total > 0 && <p className="meta" style={{ marginTop: 12 }}>
            {Object.entries(data.escalations.by_status).map(([status, n]) => `${n} ${status}`).join(", ")}.</p>}
        </section>
        <section className="panel" aria-label="Why merchants leave">
          <header><h2>Why merchants leave</h2><span className="meta num">{data.leaving.total} recorded by win-back calls</span></header>
          <LeavingReasons reasons={data.leaving} />
        </section>
      </div>
    </>}
  </AppShell>;
}

function Kpi({ label, value, note, loading }) {
  return <div className="kpi">
    <div className="kpi-label">{label}</div>
    {loading ? <div className="skeleton" style={{ height: 28, width: 48, marginTop: 7 }} /> : <div className="kpi-value">{value ?? "—"}</div>}
    <div className="kpi-note">{note}</div>
  </div>;
}

function BarList({ rows }) {
  const ref = useRef(null);
  const Charts = useCharts();
  const key = JSON.stringify(rows);
  useEffect(() => {
    if (!Charts || !ref.current) return;
    Charts.barList(ref.current, rows);
  }, [Charts, key]); // eslint-disable-line react-hooks/exhaustive-deps
  if (!rows.length) return <p className="meta">Nothing recorded yet.</p>;
  return <div ref={ref} role="img" aria-label={rows.map((r) => `${r.label} ${r.value}`).join(", ")}>
    {!Charts && <ul>{rows.map((r) => <li key={r.label} className="meta">{r.label} {r.value}</li>)}</ul>}
  </div>;
}

function MovesTable({ rows }) {
  if (!rows.length) return <p className="meta">Not enough calls yet to compare.</p>;
  const cell = (side) => side.missions ? <>{percent(side.consent_rate)}<span className="meta"> of {side.missions}</span></> : <span className="meta">no calls</span>;
  return <div className="table-wrap"><table className="moves">
    <thead><tr><th scope="col">Worry found</th><th scope="col" className="num">Calls</th><th scope="col">Chanakya answered it</th><th scope="col">Chanakya did not</th><th scope="col" className="num">Difference</th></tr></thead>
    <tbody>{rows.map((r) => <tr key={r.worry}>
      <th scope="row">{r.label}</th>
      <td className="num">{r.missions}</td>
      <td className="num">{cell(r.addressed)}</td>
      <td className="num">{cell(r.notAddressed)}</td>
      <td className={`num${r.lift > 0 ? " up" : r.lift < 0 ? " down" : ""}`}>{r.lift == null ? <span className="meta">too few calls</span>
        : `${r.lift > 0 ? "+" : r.lift < 0 ? "−" : ""}${Math.round(Math.abs(r.lift) * 100)} pts`}</td>
    </tr>)}</tbody>
  </table></div>;
}
