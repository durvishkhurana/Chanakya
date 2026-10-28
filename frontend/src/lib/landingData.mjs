// Content for the landing page's live demo, door tabs and stage bar. Tested in landingData.test.mjs.
// Replies follow the agent's rules: no prices or offers, never ask for OTP or bank details, a clear yes before any write.

export const STARTING_WORRIES = { hidden_charges: 0.5, competitor_qr: 0.3, just_busy: 0.2 };

export const SCENARIOS = [
  {
    id: "price", says: "Kitna katega mahine ka?", signals: "Hidden charges",
    concerns: { hidden_charges: 0.62, rental_cost: 0.23, just_busy: 0.15 },
    move: "Answer the charges worry with sourced facts", willingness: 0.61, rollouts: 18,
    reply: "Main koi daam guess nahi karunga. Rental aur charges aapko official channel par likhit mein dikhenge, sign karne se pehle.",
  },
  {
    id: "qr", says: "PhonePe ka QR toh laga hai", signals: "Already has a QR",
    concerns: { competitor_qr: 0.58, not_needed: 0.24, hidden_charges: 0.18 },
    move: "Ask what the QR does not do yet", willingness: 0.48, rollouts: 14,
    reply: "QR chalta rahega. Soundbox bas har payment bol ke batata hai, taaki busy counter par phone na dekhna pade. Aapke yahan aisa hota hai?",
  },
  {
    id: "busy", says: "Abhi customer hain, baad mein", signals: "Just busy",
    concerns: { just_busy: 0.71, hidden_charges: 0.17, competitor_qr: 0.12 },
    move: "Offer a callback at a better time", willingness: 0.44, rollouts: 9,
    reply: "Bilkul. Aaj shaam paanch baje call karoon, ya kal subah?",
  },
  {
    id: "privacy", says: "Bank details dene mein darr lagta hai", signals: "Data privacy",
    concerns: { data_privacy: 0.55, trust_in_caller: 0.32, setup_hassle: 0.13 },
    move: "Answer the privacy worry without asking for anything", willingness: 0.52, rollouts: 12,
    reply: "Main aapse koi OTP, PIN ya bank detail nahi maangunga. Onboarding sirf official link par hota hai.",
  },
  {
    id: "person", says: "Mujhe kisi insaan se baat karni hai", signals: "Trust in caller",
    concerns: { trust_in_caller: 0.64, hidden_charges: 0.21, just_busy: 0.15 },
    move: "Hand to a person with the full context", willingness: 0.7, rollouts: 6,
    reply: "Zaroor. Main ek saathi ko aapki poori baat ke saath jod deta hoon, aapko kuch dobara batana nahi padega.",
  },
  {
    id: "yes", says: "Haan theek hai, link bhej do", signals: "Ready to start",
    concerns: { setup_hassle: 0.38, hidden_charges: 0.34, just_busy: 0.28 },
    move: "Confirm the yes for this exact action, then send", willingness: 0.74, rollouts: 16,
    reply: "Main aapke number par SMS se onboarding link bhej doon? Bas haan ya na boliye.",
  },
];

export const DOORS = [
  {
    id: "merchant", name: "Merchant raises a hand", note: "Warm intent, called back in seconds",
    rows: [
      { trigger: "Callback request", example: "Requested a callback on the Soundbox page", worry: "Hidden charges", p: 0.5 },
      { trigger: "Onboarding stalled", example: "Started two days ago, stopped at bank details", worry: "Setup hassle", p: 0.45 },
      { trigger: "Price question, then quiet", example: "Asked the card machine price and went silent", worry: "Swipe charges", p: 0.55 },
    ],
  },
  {
    id: "data", name: "Data says so", note: "Proactive, from the merchant's own numbers",
    rows: [
      { trigger: "UPI rising, no Soundbox", example: "UPI payments up 64% this month", worry: "Already has a QR", p: 0.5 },
      { trigger: "Card attempts, no machine", example: "12 customers tried to pay by card this week", worry: "Swipe charges", p: 0.55 },
      { trigger: "Soundbox unused", example: "No payment on the Soundbox for 8 days", worry: "Rental cost", p: 0.4 },
      { trigger: "Rental missed", example: "Device rental payment missed", worry: "Cash flow", p: 0.45 },
    ],
  },
  {
    id: "human", name: "A colleague hands over", note: "Work passed on like it would be to a teammate",
    rows: [
      { trigger: "Lead list", example: "From Sunita's lead list", worry: "Hidden charges", p: 0.4 },
      { trigger: "Field agent note", example: "Call after Diwali, he wants to see a demo", worry: "Just busy", p: 0.5 },
      { trigger: "Dropped call", example: "A telecaller's call dropped halfway", worry: "Just busy", p: 0.4 },
    ],
  },
];

// Stage widths follow real durations on a log scale, so seconds stay a sliver and the wait for the merchant dominates.
export const STAGES = [
  { order: "First", duration: "Seconds", seconds: 5, text: "a signal opens a mission card with why now and starting worries." },
  { order: "Then", duration: "About three minutes", seconds: 180, text: "the call, with each move planned while the merchant speaks." },
  { order: "Next", duration: "Up to two days", seconds: 172800, text: "the merchant finishes onboarding from the link, with at most two reminders." },
  { order: "Last", duration: "Seconds", seconds: 5, text: "the onboarding system confirms, and the mission closes as done." },
];

/** Flex weights from durations: log scale, never under 12% of the bar. */
export function stageWeights(stages = STAGES) {
  const raw = stages.map((s) => Math.log10(s.seconds + 1));
  const total = raw.reduce((a, b) => a + b, 0);
  const floored = raw.map((r) => Math.max(r / total, 0.12));
  const sum = floored.reduce((a, b) => a + b, 0);
  return floored.map((f) => f / sum);
}
