// Pure helpers for the coach mode screen. Tested in coachView.test.mjs.

import { worryLabel } from "./missionView.mjs";

const PRODUCTS = { soundbox: "Soundbox", card_machine: "card machine", qr: "QR", payment_links: "payment links", gateway: "payment gateway" };

/** What the telecaller should do next, in their words, from a coach suggestion's move. */
export function coachMoveLabel(move) {
  if (!move) return "";
  const tool = (move.tool || "").replaceAll("_", " ");
  switch (move.type) {
    case "ASK_PERMISSION": return "Say why you are calling and ask for two minutes";
    case "DISCOVER_NEED": return "Ask how their customers pay";
    case "PROBE_CONCERN": return `Gently ask about ${worryLabel(move.concern).toLowerCase()}`;
    case "RESOLVE_CONCERN": return `Answer the worry: ${worryLabel(move.concern)}`;
    case "RECOMMEND": return move.product ? `Recommend the ${PRODUCTS[move.product] || move.product}` : "Recommend one product";
    case "CONFIRM_CONSENT": return tool ? `Ask a clear yes before you ${tool}` : "Ask a clear yes";
    case "TAKE_ACTION": return tool ? `They agreed: ${tool}` : "They agreed: go ahead";
    case "SCHEDULE_FOLLOWUP": return "Offer a call back at their time";
    case "ESCALATE": return "Hand over to a senior colleague";
    case "END_CALL_POLITELY": return "Thank them and close";
    default: return move.type.toLowerCase().replaceAll("_", " ");
  }
}

/** Pause before the next recorded turn: longer after the merchant, so each suggestion can be read. */
export const turnPause = (speaker) => (speaker === "merchant" ? 2200 : 1200);

/** The hand-off card as plain text the telecaller can paste to a senior colleague. */
export function handoffText(card) {
  const worries = Object.entries(card.open_concerns || {}).sort((a, b) => b[1] - a[1])
    .map(([id, p]) => `${worryLabel(id)} ${Math.round(p * 100)}%`).join(", ");
  return [card.summary, `Reason: ${card.reason}`, `Likely worries: ${worries || "none estimated"}`].join("\n");
}
