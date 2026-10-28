// A scripted demo recording of one Door 1 mission, in the exact ledger-event format the backend streams.
// It is labelled as a recording wherever it is shown. Live missions render the same view from their real ledger.
// Prices and charges are never stated: the agent points to the official channel, as the safety rules require.

const START = Date.parse("2026-10-29T09:30:00Z");
let n = 0;
const ev = (kind, payload) => ({ id: `demo_${++n}`, mission_id: "demo", seq: n, kind, payload, at: new Date(START + n * 7000).toISOString() });

const card = {
  merchant_id: "mer_ramesh", merchant_name: "Ramesh Kirana Store", language: "hi-IN", door: "merchant",
  signal_kind: "callback_request", signal_id: "sig_demo", mission_type: "sales", goal: "Sell Soundbox → verified onboarding",
  product: "soundbox", why_now: "Requested a callback on the Soundbox page",
  starting_worries: { hidden_charges: 0.5, competitor_qr: 0.3, just_busy: 0.2 }, priority: 0.9,
  contact_window: { start_hour: 14, end_hour: 17 },
};

const move = (type, extra = {}) => ({ type, concern_id: null, product: null, tool_call: null, reason: null, ...extra });
const plan = (chosenIndex, candidates, ms) => {
  const scored = candidates.map(([m, score, visits, reply]) => ({ move: m, score, visits, reply }));
  return {
    chosen: scored[chosenIndex].move,
    candidates: scored.map(({ move: m, score, visits }) => ({ move: m, score, visits })),
    tree: { label: "now", children: scored.map(({ move: m, score, visits, reply }) => ({ move: m, score, visits, reply })) },
    elapsed_ms: ms, fallback: false,
  };
};
const say = (speaker, text, m = null, cues = {}) => ev("turn_completed", { speaker, text, language: "hi-IN", move: m, cues });

const greet = move("DISCLOSE_AND_GREET");
const discover = move("DISCOVER_NEED");
const resolveCharges = move("RESOLVE_CONCERN", { concern_id: "hidden_charges" });
const consent = move("CONFIRM_CONSENT");
const goodbye = move("END_CALL_POLITELY");

export const demoEvents = [
  ev("mission_created", { card }),
  ev("signal_received", { kind: "callback_request", source: "mock product page" }),
  ev("state_changed", { from: "CREATED", to: "CONTACTING", reason: "callback requested", outcome: null }),
  ev("state_changed", { from: "CONTACTING", to: "IN_CONVERSATION", reason: "merchant answered", outcome: null }),
  ev("plan_computed", plan(0, [[greet, 0.30, 1, "Haan bolo"]], 4)),
  say("agent", "Namaste Ramesh ji, main Chanakya hoon, ek AI assistant. Aapne Soundbox ke liye callback maanga tha. Do minute baat kar sakte hain?", greet),
  ev("ai_disclosed", { text: "Main Chanakya hoon, ek AI assistant" }),
  ev("action_decision", { call: { id: "call_d1", mission_id: "demo", tool: "get_merchant_profile", args: { merchant_id: "mer_ramesh" } }, verdict: "executed", reason: "ok", kind: "read", result: { call_id: "call_d1", tool: "get_merchant_profile", ok: true, data: {} } }),
  say("merchant", "Haan bolo, jaldi. Dukaan pe customer hain.", null, { pause_ms: 300 }),
  ev("belief_updated", { probabilities: { hidden_charges: 0.41, just_busy: 0.34, competitor_qr: 0.25 }, turn: 1 }),
  ev("plan_computed", plan(0, [
    [discover, 0.42, 14, "UPI hi zyada hai…"],
    [move("PROBE_CONCERN", { concern_id: "hidden_charges" }), 0.38, 12, "Haan, kitna katega?"],
    [move("RECOMMEND", { product: "soundbox" }), 0.21, 8, "Abhi nahi chahiye"],
    [goodbye, 0.12, 4, "(call ends)"],
  ], 840)),
  say("agent", "Bilkul, jaldi baat karta hoon. Aapke customers zyada tar UPI se pay karte hain ya cash?", discover),
  say("merchant", "UPI hi zyada hai. Par PhonePe ka QR already laga hai. Aur matlab… ye Soundbox ka mahine ka kitna katega, pehle bata do.", null, { pause_ms: 900, filler_count: 1 }),
  ev("belief_updated", { probabilities: { hidden_charges: 0.62, competitor_qr: 0.29, just_busy: 0.09 }, turn: 2 }),
  ev("plan_computed", plan(0, [
    [resolveCharges, 0.61, 18, "Accha, koi chhupa charge nahi?"],
    [move("PROBE_CONCERN", { concern_id: "competitor_qr" }), 0.33, 9, "QR toh hai hi"],
    [move("RECOMMEND", { product: "soundbox" }), 0.27, 6, "Pehle charges batao"],
    [move("ESCALATE"), 0.08, 2, "(hand-off)"],
  ], 910)),
  say("agent", "Sahi sawaal hai. Main koi daam guess nahi karunga: rental aur charges aapko official channel par likhit mein dikhenge, sign karne se pehle. Aapka QR bhi chalta rahega, Soundbox bas har payment bol ke batata hai.", resolveCharges),
  say("merchant", "Accha, matlab koi chhupa charge nahi? Theek hai, link bhej do, dekh leta hoon.", null, { pause_ms: 250 }),
  ev("belief_updated", { probabilities: { competitor_qr: 0.31, setup_hassle: 0.29, hidden_charges: 0.22, just_busy: 0.18 }, turn: 3 }),
  ev("plan_computed", plan(0, [
    [consent, 0.72, 16, "Haan, dono theek hai"],
    [move("RESOLVE_CONCERN", { concern_id: "competitor_qr" }), 0.40, 7, "Haan woh toh pata hai"],
    [goodbye, 0.15, 3, "(call ends)"],
  ], 760)),
  say("agent", "Main aapke number par SMS se onboarding link bhej doon? Aur zarurat ho to WhatsApp par ek reminder?", consent),
  say("merchant", "Haan, dono theek hai."),
  ev("consent_given", { tools: ["send_onboarding_link", "send_summary"], utterance: "Haan, dono theek hai." }),
  ev("state_changed", { from: "IN_CONVERSATION", to: "ACTION_PENDING", reason: "explicit consent", outcome: null }),
  ev("action_decision", { call: { id: "call_d2", mission_id: "demo", tool: "send_onboarding_link", args: { merchant_id: "mer_ramesh", product: "soundbox", channel: "sms" } }, verdict: "executed", reason: "ok", kind: "write", result: { call_id: "call_d2", tool: "send_onboarding_link", ok: true, data: { link: "/demo/onboard/onb_demo" } } }),
  ev("state_changed", { from: "ACTION_PENDING", to: "AWAITING_CONFIRMATION", reason: "onboarding link sent", outcome: null }),
  ev("followup_scheduled", { kind: "verify", due_at: new Date(START + 2 * 3600 * 1000).toISOString() }),
  ev("plan_computed", plan(0, [[goodbye, 0.80, 6, "Shukriya"]], 120)),
  say("agent", "Link bhej diya hai. Shukriya Ramesh ji, aapka din achha jaaye.", goodbye),
];
