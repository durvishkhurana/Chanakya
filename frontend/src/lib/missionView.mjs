// Pure helpers that turn missions and ledger events into what the screens show. Tested in missionView.test.mjs.

export const WAITING = new Set(["CREATED", "SCHEDULED"]);
export const FINISHED = new Set(["DONE", "ESCALATED", "CLOSED_NOT_INTERESTED", "CLOSED_UNREACHABLE", "FAILED"]);

const DOORS = { merchant: "Merchant raised a hand", data: "Data says so", human: "Handed over by a colleague" };
const WORRIES = {
  hidden_charges: "Hidden charges", competitor_qr: "Already has a QR", just_busy: "Just busy",
  setup_hassle: "Setup hassle", data_privacy: "Data privacy", trust_in_caller: "Trust in caller",
  swipe_charges: "Swipe charges", rental_cost: "Rental cost", not_needed: "Not needed",
  customers_pay_cash: "Customers pay cash", device_reliability: "Device reliability", cash_flow: "Cash flow",
  settlement_delay: "Settlement delay",
  per_swipe_charges: "Swipe charges", device_issue: "Device reliability", language_comfort: "Language comfort",
};

export const doorLabel = (door) => DOORS[door] || door;
export const worryLabel = (id) => WORRIES[id] || id.replaceAll("_", " ");
export const percent = (p) => `${Math.round((p || 0) * 100)}%`;
export const stateLabel = (state) => state.toLowerCase().replaceAll("_", " ");

/** Top ``n`` entries of a probability map, highest first, as [id, p] pairs. */
export function topWorries(probabilities, n = 3) {
  return Object.entries(probabilities || {}).sort((a, b) => b[1] - a[1]).slice(0, n);
}

/** Split API mission rows into waiting (ready first, then priority), active, and finished (newest first). */
export function groupMissions(rows) {
  const waiting = [], active = [], finished = [];
  for (const row of rows) {
    const state = row.mission.state;
    (WAITING.has(state) ? waiting : FINISHED.has(state) ? finished : active).push(row);
  }
  waiting.sort((a, b) => (b.queue?.ready ? 1 : 0) - (a.queue?.ready ? 1 : 0) || b.mission.card.priority - a.mission.card.priority);
  return { waiting, active, finished };
}

/** 24-hour IST time of an ISO timestamp, e.g. "17:00". */
export function time(iso) {
  return new Date(iso).toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit", hourCycle: "h23", timeZone: "Asia/Kolkata" });
}

const LANGUAGES = { "hi-IN": "Hindi", "pa-IN": "Punjabi", "en-IN": "English", "bn-IN": "Bengali", "ta-IN": "Tamil", "te-IN": "Telugu", "mr-IN": "Marathi", "gu-IN": "Gujarati", "kn-IN": "Kannada", "ml-IN": "Malayalam", "od-IN": "Odia" };
export const languageLabel = (code) => LANGUAGES[code] || code;

const WAITING_ON_MERCHANT = new Set(["ACTION_PENDING", "AWAITING_CONFIRMATION", "VERIFYING"]);

/** Headline counts for Mission Control, computed from the rows on screen. */
export function missionCounts(rows, handoffs = []) {
  const count = (test) => rows.filter((r) => test(r.mission.state, r)).length;
  return {
    ready: count((s, r) => WAITING.has(s) && r.queue?.ready),
    waiting: count((s) => WAITING.has(s)),
    talking: count((s) => s === "CONTACTING" || s === "IN_CONVERSATION"),
    onMerchant: count((s) => WAITING_ON_MERCHANT.has(s)),
    done: count((s) => s === "DONE"),
    closed: count((s) => FINISHED.has(s) && s !== "DONE"),
    handoffsOpen: handoffs.filter((h) => h.status !== "resolved").length,
  };
}

const TOOLS = { book_field_visit: "Field visit", raise_ticket: "Support ticket", send_onboarding_link: "Onboarding link",
  send_onboarding_reminder: "Onboarding reminder", send_summary: "Call summary", create_lead: "New lead", book_callback: "Callback" };

/** A tool name as words, for example "book_field_visit" → "Field visit". */
export const toolLabel = (tool) => TOOLS[tool] || String(tool || "action").replaceAll("_", " ");

/** The few arguments a person needs to judge an approval, as one line. */
export function approvalDetails(args = {}) {
  const parts = [];
  if (args.purpose) parts.push(`${args.purpose} visit`);
  if (args.slot) parts.push(`slot ${time(args.slot)} IST`);
  if (args.product) parts.push(String(args.product).replaceAll("_", " "));
  if (args.category) parts.push(args.category);
  return parts.join(", ");
}

/** Whole minutes from ``now`` until ``iso`` (negative once it has passed). */
export function minutesLeft(iso, now) {
  return Math.floor((new Date(iso) - new Date(now)) / 60000);
}

/** One readable line per ledger event for the mission timeline. */
export function eventSummary(event) {
  const p = event.payload || {};
  switch (event.kind) {
    case "mission_created": return `Mission opened: ${p.card?.goal}`;
    case "mission_updated": return `Card refreshed (${p.reason})`;
    case "signal_received": return `Signal: ${String(p.kind).replaceAll("_", " ")} from ${p.source}`;
    case "state_changed": return `${stateLabel(p.from)} → ${stateLabel(p.to)}${p.reason ? ` (${p.reason})` : ""}`;
    case "turn_completed": return `${p.speaker === "agent" ? "Chanakya" : p.speaker === "merchant" ? "Merchant" : "Human"}: “${p.text}”`;
    case "belief_updated": return `Concern meter: ${topWorries(p.probabilities, 2).map(([id, v]) => `${worryLabel(id)} ${percent(v)}`).join(", ")}`;
    case "plan_computed": return `Planned move: ${p.chosen?.type}${p.fallback ? " (fallback)" : ""}`;
    case "ai_disclosed": return "Told the merchant it is an AI assistant";
    case "consent_given": return `Merchant said yes${p.utterance ? `: “${p.utterance}”` : ""}`;
    case "consent_declined": return `Merchant said no${p.utterance ? `: “${p.utterance}”` : ""}`;
    case "action_decision": return `${p.call?.tool}: ${p.verdict}${p.verdict === "executed" ? "" : ` (${p.reason})`}`;
    case "followup_scheduled": return `Scheduled ${p.kind} for ${time(p.due_at)} IST`;
    case "verification_checked": return `Checked onboarding: ${p.status}`;
    case "handoff_created": return `Handed to a human: ${p.reason}`;
    case "handoff_claimed": return `Hand-off claimed by ${p.agent}`;
    case "handoff_resolved": return `Hand-off resolved: ${p.resolution}`;
    case "leaving_reason_recorded": return `Reason for leaving: ${worryLabel(p.reason)}`;
    case "holdout_assigned": return "Holdout: not called, kept for comparison";
    case "approval_requested": return `${toolLabel(p.tool)} waits for a person's approval`;
    case "approval_decided": return `${toolLabel(p.tool)} ${p.status} by ${p.by}${p.note ? ` (${p.note})` : ""}`;
    default: return p.text || event.kind;
  }
}

/** Everything the Live Call View shows, derived from one mission's ledger events. */
export function deriveCallView(events, card = null) {
  const view = { card, state: "CREATED", transcript: [], concerns: card?.starting_worries || {}, plans: [], willingness: [], actions: [], consent: null, evidence: {}, scorer: null };
  for (const event of events) {
    const p = event.payload || {};
    if (event.kind === "mission_created" || event.kind === "mission_updated") {
      view.card = p.card;
      if (!view.transcript.length) view.concerns = p.card.starting_worries;
    } else if (event.kind === "state_changed") view.state = p.to;
    else if (event.kind === "turn_completed") view.transcript.push({ speaker: p.speaker, text: p.text, move: p.move?.type || null });
    else if (event.kind === "belief_updated") {
      view.concerns = p.probabilities;
      view.evidence = p.evidence || {};
      view.scorer = p.scorer || view.scorer;
    }
    else if (event.kind === "plan_computed") {
      view.plans.push(p);
      const chosen = (p.candidates || []).find((c) => c.move.type === p.chosen?.type && c.move.concern_id === p.chosen?.concern_id);
      if (chosen) view.willingness.push({ turn: view.plans.length, value: chosen.score });
    } else if (event.kind === "consent_given") view.consent = "given";
    else if (event.kind === "consent_declined") view.consent = "declined";
    else if (event.kind === "action_decision") view.actions.push({ tool: p.call?.tool, args: p.call?.args || {}, verdict: p.verdict, reason: p.reason, data: p.result?.data || {} });
  }
  return view;
}

/** Rows for a counts card (reason, city or product -> count), largest first, each with its share of the total. */
export function countRows(counts = {}, label = (key) => key) {
  const total = Object.values(counts).reduce((sum, n) => sum + n, 0);
  return Object.entries(counts)
    .sort(([a, x], [b, y]) => y - x || a.localeCompare(b))
    .map(([key, count]) => ({ key, label: label(key), count, share: total ? count / total : 0 }));
}
