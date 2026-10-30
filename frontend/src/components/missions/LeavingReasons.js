"use client";

import { productLabel } from "../../lib/insightsView.mjs";
import { countRows, percent, worryLabel } from "../../lib/missionView.mjs";

/** Win-back calls' recorded reasons for leaving, by reason, city and product (shared by Mission Control and Insights). */
export default function LeavingReasons({ reasons }) {
  if (!reasons || reasons.total === 0) return <p className="meta">No win-back call has recorded a reason yet.</p>;
  const groups = [["Reason", reasons.by_reason, worryLabel], ["City", reasons.by_city], ["Product", reasons.by_product, productLabel]];
  return groups.map(([title, counts, label]) => <div key={title} style={{ marginBottom: 12 }}>
    <h3 className="subhead">{title}</h3>
    <dl className="facts">{countRows(counts, label).map((r) => <div key={r.key} className="fact"><dt className="num">{r.count} · {percent(r.share)}</dt><dd>{r.label}</dd></div>)}</dl>
  </div>);
}
