// Pure helpers for the manager insights screen. Tested in insightsView.test.mjs.

import { worryLabel } from "./missionView.mjs";

const TYPES = { sales: "Sales", win_back: "Win-back", follow_up: "Follow-up", retention: "Retention" };
const PRODUCTS = { soundbox: "Soundbox", card_machine: "Card machine", qr: "QR", payment_gateway: "Payment gateway", payment_links: "Payment links", business_app: "Business app", unknown: "No product" };

export const typeLabel = (key) => TYPES[key] || key.replaceAll("_", " ");
export const productLabel = (key) => PRODUCTS[key] || key.replaceAll("_", " ");

/** Funnel stages with each stage's share of opened missions and how many dropped out since the stage before. */
export function funnelRows(stages = []) {
  const opened = stages[0]?.missions || 0;
  return stages.map((s, i) => ({ ...s, share: opened ? s.missions / opened : 0, dropped: i ? stages[i - 1].missions - s.missions : 0 }));
}

/** One row per group (a product, a language or a day): calls, and its top worries with their share of that group. */
export function breakdownRows(groups = {}, top = 3) {
  return Object.entries(groups).map(([group, counts]) => {
    const total = Object.values(counts).reduce((a, b) => a + b, 0);
    const worries = Object.entries(counts).sort(([a, x], [b, y]) => y - x || a.localeCompare(b)).slice(0, top)
      .map(([id, n]) => ({ id, label: worryLabel(id), share: total ? n / total : 0 }));
    return { group, total, worries };
  }).sort((a, b) => b.total - a.total || a.group.localeCompare(b.group));
}

/** Worries with enough calls to show: consent when the worry was addressed and when it was not. The difference is only
 * given when both sides have at least ``minimum`` calls; a gap between 14 calls and 2 is not a finding. */
export function moveRows(moves = [], minimum = 3) {
  return moves
    .filter((m) => m.addressed.missions >= minimum || m.not_addressed.missions >= minimum)
    .map((m) => ({
      worry: m.worry, label: worryLabel(m.worry), missions: m.missions,
      addressed: m.addressed, notAddressed: m.not_addressed,
      lift: m.addressed.missions >= minimum && m.not_addressed.missions >= minimum
        ? m.addressed.consent_rate - m.not_addressed.consent_rate : null,
    }));
}

/** Hand-off reasons as readable labels. */
export function escalationLabel(reason) {
  if (reason === "distress") return "Merchant in distress";
  if (reason === "open complaint") return "Open complaint, a person answers first";
  if (reason === "needs a person") return "Asked for a person";
  return reason.charAt(0).toUpperCase() + reason.slice(1);
}
