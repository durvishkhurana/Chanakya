"use client";

import Link from "next/link";
import { useState } from "react";

import { SCENARIOS } from "../../lib/landingData.mjs";
import { percent, worryLabel } from "../../lib/missionView.mjs";

/** The page's live thing: pick what the merchant says, and see the concern meter and the next move change. */
export default function TryDemo() {
  const [id, setId] = useState(SCENARIOS[0].id);
  const s = SCENARIOS.find((x) => x.id === id);
  const concerns = Object.entries(s.concerns).sort((a, b) => b[1] - a[1]);

  return <div className="demo" data-ui data-reveal style={{ "--i": 2 }}>
    <div className="stage" aria-live="polite">
      <div className="stage-head"><span>Ramesh Kirana Store · Hindi</span><span>Mission: sell Soundbox</span></div>
      <div key={`m-${id}`} className="bubble merchant swap"><small>Ramesh</small>{s.says}</div>
      <div className="meter" aria-label="What Chanakya thinks Ramesh is worried about">
        {concerns.map(([worry, p]) => <div key={worry} className="meter-row">
          <span>{worryLabel(worry)}</span>
          <span className="meter-track" aria-hidden="true"><span className="meter-fill" style={{ width: percent(p) }} /></span>
          <b>{percent(p)}</b>
        </div>)}
      </div>
      <div className="next">
        <strong>Next move: {s.move}</strong>
        <span>{s.willingness.toFixed(2)} expected · {s.rollouts} rollouts</span>
      </div>
      <div key={`a-${id}`} className="bubble agent swap"><small>Chanakya</small>{s.reply}</div>
      <Link className="more" href="/call/demo">Watch a whole recorded call</Link>
    </div>
    <fieldset className="controls">
      <legend>What Ramesh says</legend>
      {SCENARIOS.map((x) => <label key={x.id} className={`control${x.id === id ? " on" : ""}`}>
        <input type="radio" name="merchant-line" value={x.id} checked={x.id === id} onChange={() => setId(x.id)} />
        <span className="line">{x.says}</span>
        <span className="sig">{x.signals}</span>
      </label>)}
    </fieldset>
  </div>;
}
