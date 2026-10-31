"use client";

import Link from "next/link";
import { useState } from "react";

import { api } from "../../lib/chanakyaApi";
import { approvalDetails, minutesLeft, toolLabel } from "../../lib/missionView.mjs";

const PILLS = { pending: ["warn", "Waiting for approval"], approved: ["pos", "Approved"], rejected: ["neg", "Rejected"], expired: ["neg", "Timed out"] };

/** High-risk actions waiting for a person (B10): approve to run them through the gate again, or reject with a reason. */
export default function Approvals({ requests, now, busy, act }) {
  if (!requests.length) {
    return <div className="empty">No action is waiting for approval. Tools listed in <code>APPROVAL_TOOLS</code> stop here before they run.</div>;
  }
  return <div>{requests.map((r) => <ApprovalCard key={r.approval_id} request={r} now={now} busy={busy} act={act} />)}</div>;
}

function ApprovalCard({ request, now, busy, act }) {
  const [note, setNote] = useState("");
  const [pill, label] = PILLS[request.status] || ["", request.status];
  const left = minutesLeft(request.expires_at, now);
  const decide = (verb, body) => act(verb, () => api(`/api/approvals/${request.approval_id}/${verb}`, { method: "POST", body }));
  return <article className="handoff">
    <div className="handoff-head">
      <span className="name">{request.merchant_name}</span>
      <span className={`pill ${pill}`}>{label}</span>
    </div>
    <p>{toolLabel(request.tool)}{approvalDetails(request.call?.args) && <span className="meta"> · {approvalDetails(request.call.args)}</span>}</p>
    <p className="meta">
      {request.status === "pending" ? `Waiting for a person · ${left > 0 ? `${left} min left before it goes to a person` : "due now"}`
        : `${label} by ${request.decided_by}${request.note ? `: ${request.note}` : ""}${request.verdict ? ` · then ${request.verdict}${request.verdict === "executed" ? "" : ` (${request.verdict_reason})`}` : ""}`}
    </p>
    <div className="actions" style={{ justifyContent: "flex-start", flexWrap: "wrap" }}>
      {request.status === "pending" && <>
        <button className="btn small primary" disabled={!!busy} onClick={() => decide("approve", { by: "Sunita" })}>Approve as Sunita</button>
        <label className="sr-only" htmlFor={`note-${request.approval_id}`}>Reason for rejecting</label>
        <input id={`note-${request.approval_id}`} className="note-input" value={note} maxLength={300} placeholder="Reason, if rejecting"
          onChange={(e) => setNote(e.target.value)} />
        <button className="btn small" disabled={!!busy} onClick={() => decide("reject", { by: "Sunita", note })}>Reject</button>
      </>}
      <Link className="btn small ghost" href={`/missions?m=${request.mission_id}`}>Open mission</Link>
    </div>
  </article>;
}
