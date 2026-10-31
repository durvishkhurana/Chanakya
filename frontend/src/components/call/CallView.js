"use client";

import Link from "next/link";
import { useEffect, useRef } from "react";

import ConcernMeter from "../missions/ConcernMeter";
import useCharts from "../missions/useCharts";
import { deriveCallView, doorLabel, languageLabel, percent, stateLabel, topWorries, worryLabel } from "../../lib/missionView.mjs";
import "./call.css";

const MOVE_LABELS = {
  DISCLOSE_AND_GREET: "Greet and say it is an AI", ASK_PERMISSION: "Ask for two minutes first", DISCOVER_NEED: "Ask about the business", PROBE_CONCERN: "Gently raise a worry",
  RESOLVE_CONCERN: "Answer a worry with sourced facts", RECOMMEND: "Recommend one product", CONFIRM_CONSENT: "Ask for an explicit yes",
  TAKE_ACTION: "Take an action", SCHEDULE_FOLLOWUP: "Set the next step", ESCALATE: "Hand to a person", END_CALL_POLITELY: "End the call politely",
};

export function moveLabel(move) {
  if (!move) return "";
  const base = MOVE_LABELS[move.type] || move.type;
  return move.concern_id ? `${base}: ${worryLabel(move.concern_id)}` : base;
}

/** Everything the Live Call View shows, from one mission's ledger events. ``composer`` sits right under the transcript. */
export default function CallView({ events, mission = null, newSince = 0, composer = null }) {
  const view = deriveCallView(events, mission?.card || null);
  const card = view.card;
  const plan = view.plans.at(-1);
  const [topId, topP] = topWorries(view.concerns, 1)[0] || [];
  const chosenScore = view.willingness.at(-1)?.value;
  const transcriptEnd = useRef(null);
  const lastTurns = view.transcript.length;

  useEffect(() => { transcriptEnd.current?.scrollIntoView({ block: "nearest", behavior: "smooth" }); }, [lastTurns]);

  if (!card) return <div className="panel" aria-busy="true"><div className="skeleton" style={{ width: "40%" }} /><div className="skeleton" style={{ height: 160, marginTop: 16 }} /></div>;
  const writes = view.actions.filter((a) => a.verdict === "executed");
  const blocked = view.actions.filter((a) => a.verdict !== "executed");

  return <>
    <div className="kpis" aria-label="Call at a glance">
      <div className="kpi"><div className="kpi-label">Turn</div><div className="kpi-value">{view.transcript.length}</div><div className="kpi-note">{stateLabel(mission?.state || view.state)}</div></div>
      <div className="kpi"><div className="kpi-label">Most likely worry</div><div className="kpi-value">{topId ? percent(topP) : "—"}</div><div className="kpi-note">{topId ? worryLabel(topId) : "no estimate yet"}</div></div>
      <div className="kpi"><div className="kpi-label">Expected willingness</div><div className="kpi-value">{chosenScore != null ? chosenScore.toFixed(2) : "—"}</div><div className="kpi-note">of the chosen move, 0 to 1</div></div>
      <div className="kpi"><div className="kpi-label">Planner time</div><div className="kpi-value">{plan ? Math.round(plan.elapsed_ms) : "—"}{plan && <small style={{ fontSize: 14, color: "var(--muted)", marginLeft: 3 }}>ms</small>}</div><div className="kpi-note">{plan ? `${plan.candidates.length} moves tested` : "no plan yet"}</div></div>
    </div>

    <div className="call-grid">
      <section className="panel" aria-label="The call">
        <header><h2>The call</h2><span className="meta">{languageLabel(card.language)} · {doorLabel(card.door)}</span></header>
        {view.transcript.length === 0
          ? <div className="empty">No words yet. Turns appear here as the merchant and Chanakya speak.</div>
          : <div className="call-transcript" aria-live="polite">{view.transcript.map((turn, i) => <div key={i} className={`turn ${turn.speaker}${i >= newSince ? " arrive" : ""}`}>
            <span className="who">{turn.speaker === "agent" ? "Chanakya" : turn.speaker === "merchant" ? card.merchant_name : "Telecaller"}</span>
            {turn.text}
            {turn.move && <span className="move">Move: {moveLabel({ type: turn.move })}</span>}
          </div>)}<div ref={transcriptEnd} /></div>}
        {composer}
        <h3 className="subhead">Actions</h3>
        {view.actions.length === 0 ? <p className="meta">No actions yet. Reads may run while the merchant talks; writes wait for an explicit yes.</p>
          : <ul className="checks">{view.actions.map((a, i) => <li key={i}>
            <span>{a.tool.replaceAll("_", " ")}{a.data?.link && <> · <Link href={a.data.link} className="text-action">{a.data.link}</Link></>}</span>
            <span className={a.verdict === "executed" ? "ok" : "no"}>{a.verdict}{a.verdict !== "executed" ? `: ${a.reason}` : ""}</span>
          </li>)}</ul>}
      </section>

      <section className="stack" aria-label="Chanakya's thinking">
        <div className="panel">
          <header><h2>What the merchant is worried about</h2><span className="meta">updates every turn</span></header>
          <ConcernMeter current={view.concerns} starting={card.starting_worries} />
        </div>
        <div className="panel">
          <header><h2>What the scorer heard</h2><span className="meta">{view.scorer ? `${SCORER_LABELS[view.scorer] || view.scorer} scorer` : "latest merchant line"}</span></header>
          <Evidence evidence={view.evidence} />
        </div>
        <div className="panel">
          <header><h2>Next move</h2><span className="meta">{plan ? `${plan.candidates.reduce((s, c) => s + (c.visits || 0), 0)} simulated replies` : ""}</span></header>
          {plan ? <PlanTree plan={plan} /> : <div className="empty">The look-ahead planner’s candidate moves appear here once the brain is on for this mission.</div>}
        </div>
        <div className="panel">
          <header><h2>Willingness over the call</h2><span className="meta">expected, of each chosen move</span></header>
          {view.willingness.length > 1 ? <WillingnessChart points={view.willingness} />
            : <p className="meta">The curve starts after the second planned move.</p>}
        </div>
        <div className="panel">
          <header><h2>Safety</h2><span className="meta">checked before every write</span></header>
          <ul className="checks">
            <li><span>Said it is an AI assistant</span><span className={events.some((e) => e.kind === "ai_disclosed") ? "ok" : "no"}>{events.some((e) => e.kind === "ai_disclosed") ? "Yes" : "Not yet"}</span></li>
            <li><span>Explicit consent</span><span className={view.consent === "given" ? "ok" : "no"}>{view.consent === "given" ? "Given" : view.consent === "declined" ? "Declined" : "Not asked yet"}</span></li>
            <li><span>Writes executed</span><span className="num">{writes.filter((a) => a.tool !== "get_merchant_profile").length}</span></li>
            <li><span>Blocked or rejected</span><span className="num">{blocked.length}</span></li>
          </ul>
        </div>
      </section>
    </div>
  </>;
}

const SCORER_LABELS = { lexical: "Keyword", llm: "LLM", embedding: "Neural (e5)" };

/** The scorer's reading of the merchant's latest line: how strongly it points at each worry, before the Bayesian update. */
function Evidence({ evidence }) {
  const rows = topWorries(evidence, 3).filter(([, score]) => score > 0.01);
  if (!rows.length) return <p className="meta">After the merchant speaks, the worries their words point to appear here.</p>;
  return <ul className="checks">{rows.map(([id, score]) => <li key={id}>
    <span>{worryLabel(id)}</span><span className="num">{percent(score)}</span>
  </li>)}</ul>;
}

function PlanTree({ plan }) {
  const branches = (plan.tree?.children || plan.candidates).map((b) => ({ move: b.move, score: b.score, visits: b.visits, reply: b.reply }));
  const max = Math.max(...branches.map((b) => b.score), 0.01);
  const isChosen = (m) => m.type === plan.chosen.type && (m.concern_id || null) === (plan.chosen.concern_id || null);
  return <div className="tree" role="list" aria-label="Candidate moves and their expected willingness">
    {branches.sort((a, b) => b.score - a.score).map((b, i) => <div key={i} role="listitem" className={`branch${isChosen(b.move) ? " chosen" : ""}`}>
      <span className="label">{moveLabel(b.move)}{b.reply && <small>Likely reply: “{b.reply}”</small>}</span>
      <span className="track" aria-hidden="true"><span className="fill" style={{ width: `${(b.score / max) * 100}%` }} /></span>
      <span className="score">{b.score.toFixed(2)}<small>{b.visits} {b.visits === 1 ? "rollout" : "rollouts"}</small></span>
    </div>)}
    {plan.fallback && <p className="meta">Planner hit its time budget; the playbook’s top move was used.</p>}
  </div>;
}

function WillingnessChart({ points }) {
  const ref = useRef(null);
  const Charts = useCharts();
  const key = JSON.stringify(points);
  useEffect(() => {
    if (!Charts || !ref.current) return;
    ref.current.replaceChildren();
    Charts.line(ref.current, { labels: points.map((p) => `Move ${p.turn}`), series: [{ name: "Expected willingness", values: points.map((p) => p.value) }],
      format: Charts.fmt.dec(2), height: 160, yTicks: [0, 0.25, 0.5, 0.75, 1], endLabel: true });
  }, [Charts, key]); // eslint-disable-line react-hooks/exhaustive-deps
  return <div ref={ref} className="chart" role="img" aria-label={`Expected willingness rose from ${points[0].value.toFixed(2)} to ${points.at(-1).value.toFixed(2)}`} />;
}
