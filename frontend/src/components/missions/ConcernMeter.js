"use client";

import { useEffect, useRef } from "react";

import { percent, topWorries, worryLabel } from "../../lib/missionView.mjs";
import useCharts from "./useCharts";

/**
 * The concern meter: each likely worry as a bar at its current probability, with a tick at the mission card's
 * starting guess, so the screen shows how the conversation moved Chanakya's belief.
 */
export default function ConcernMeter({ current, starting, limit = 4 }) {
  const ref = useRef(null);
  const Charts = useCharts();
  const ids = topWorries(current, limit).map(([id]) => id);
  const rows = ids.map((id) => ({ label: worryLabel(id), value: current[id] || 0, target: starting?.[id] || 0 }));
  const key = JSON.stringify(rows);

  useEffect(() => {
    if (!Charts || !ref.current || !rows.length) return;
    ref.current.replaceChildren();
    Charts.bullet(ref.current, rows, { format: Charts.fmt.pct(0), max: 1 });
  }, [Charts, key]); // eslint-disable-line react-hooks/exhaustive-deps

  if (!rows.length) return <p className="meta">No worries estimated yet.</p>;
  return <div>
    <div ref={ref} className="chart" role="img" aria-label={rows.map((r) => `${r.label} ${percent(r.value)}`).join(", ")} />
    {!Charts && <ul>{rows.map((r) => <li key={r.label} className="meta">{r.label} {percent(r.value)}</li>)}</ul>}
    <p className="meta" style={{ marginTop: 6 }}>Bar: Chanakya’s current estimate. Tick: the starting guess from the mission card.</p>
  </div>;
}
