"use client";

import { useState } from "react";

import { DOORS } from "../../lib/landingData.mjs";
import { percent } from "../../lib/missionView.mjs";

/** The three doors into a mission, as tabs with a banded list of the signals behind each. */
export default function Doors() {
  const [id, setId] = useState(DOORS[0].id);
  const door = DOORS.find((d) => d.id === id);
  return <div className="doors-body">
    <div className="door-tabs" role="tablist" aria-label="Doors into a mission">
      {DOORS.map((d) => <button key={d.id} role="tab" id={`door-${d.id}`} aria-selected={d.id === id} aria-controls="door-panel"
        className="door-tab" onClick={() => setId(d.id)}><b>{d.name}</b><span>{d.note}</span></button>)}
    </div>
    <div className="bands" role="tabpanel" id="door-panel" aria-labelledby={`door-${id}`}>
      {door.rows.map((r, i) => <div key={`${id}-${r.trigger}`} className="band swap" style={{ animationDelay: `${i * 60}ms` }}>
        <span className="p">{percent(r.p)}</span>
        <span className="t"><b>{r.trigger}</b><span>{r.example}</span></span>
        <span className="w">Starting worry: {r.worry}</span>
      </div>)}
    </div>
  </div>;
}
