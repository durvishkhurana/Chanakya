import assert from "node:assert/strict";
import test from "node:test";

import { deriveCallView, eventSummary, groupMissions, missionCounts, topWorries, worryLabel } from "./missionView.mjs";

const card = { goal: "Sell soundbox -> verified onboarding", starting_worries: { hidden_charges: 0.5, competitor_qr: 0.3, just_busy: 0.2 }, priority: 0.9 };
const row = (id, state, priority, ready) => ({ mission: { id, state, card: { ...card, priority } }, queue: ready === undefined ? null : { ready } });

test("missions are grouped and waiting ones sorted ready first, then priority", () => {
  const groups = groupMissions([row("a", "CREATED", 0.9, false), row("b", "SCHEDULED", 0.3, true), row("c", "IN_CONVERSATION", 1),
    row("d", "DONE", 1), row("e", "CREATED", 0.5, true)]);
  assert.deepEqual(groups.waiting.map((r) => r.mission.id), ["e", "b", "a"]);
  assert.deepEqual(groups.active.map((r) => r.mission.id), ["c"]);
  assert.deepEqual(groups.finished.map((r) => r.mission.id), ["d"]);
});

test("top worries are sorted and labelled", () => {
  assert.deepEqual(topWorries({ a: 0.1, b: 0.7, c: 0.2 }, 2), [["b", 0.7], ["c", 0.2]]);
  assert.equal(worryLabel("hidden_charges"), "Hidden charges");
  assert.equal(worryLabel("brand_new_concern"), "brand new concern");
});

test("every ledger event kind has a readable summary", () => {
  const events = [
    { kind: "state_changed", payload: { from: "CREATED", to: "CONTACTING", reason: "" } },
    { kind: "action_decision", payload: { call: { tool: "send_onboarding_link" }, verdict: "blocked", reason: "no consent" } },
    { kind: "followup_scheduled", payload: { kind: "verify", due_at: "2026-10-29T11:30:00+00:00" } },
    { kind: "consent_given", payload: { utterance: "Haan" } },
  ];
  assert.deepEqual(events.map(eventSummary), [
    "created → contacting", "send_onboarding_link: blocked (no consent)", "Scheduled verify for 17:00 IST", "Merchant said yes: “Haan”",
  ]);
});

test("call view follows the ledger: transcript, concern meter, plans, willingness, actions", () => {
  const plan = (type, score) => ({ chosen: { type }, candidates: [{ move: { type }, score, visits: 3 }, { move: { type: "RECOMMEND" }, score: 0.1, visits: 1 }] });
  const view = deriveCallView([
    { kind: "mission_created", payload: { card } },
    { kind: "state_changed", payload: { from: "CREATED", to: "IN_CONVERSATION" } },
    { kind: "turn_completed", payload: { speaker: "merchant", text: "Kitna katega?" } },
    { kind: "belief_updated", payload: { probabilities: { hidden_charges: 0.62, rental_cost: 0.3, just_busy: 0.08 } } },
    { kind: "plan_computed", payload: plan("DISCOVER_NEED", 0.2) },
    { kind: "plan_computed", payload: plan("CONFIRM_CONSENT", 0.55) },
    { kind: "consent_given", payload: { tools: ["send_onboarding_link"] } },
    { kind: "action_decision", payload: { call: { tool: "send_onboarding_link" }, verdict: "executed", reason: "ok", result: { data: { link: "/demo/onboard/x" } } } },
  ]);
  assert.equal(view.state, "IN_CONVERSATION");
  assert.equal(view.transcript[0].text, "Kitna katega?");
  assert.equal(view.concerns.hidden_charges, 0.62);
  assert.deepEqual(view.willingness, [{ turn: 1, value: 0.2 }, { turn: 2, value: 0.55 }]);
  assert.equal(view.consent, "given");
  assert.equal(view.actions[0].data.link, "/demo/onboard/x");
});

test("headline counts add up from the rows", () => {
  const rows = [row("a", "CREATED", 1, true), row("b", "SCHEDULED", 1, false), row("c", "IN_CONVERSATION", 1),
    row("d", "AWAITING_CONFIRMATION", 1), row("e", "DONE", 1), row("f", "CLOSED_NOT_INTERESTED", 1), row("g", "ESCALATED", 1)];
  const counts = missionCounts(rows, [{ status: "open" }, { status: "resolved" }]);
  assert.deepEqual(counts, { ready: 1, waiting: 2, talking: 1, onMerchant: 1, done: 1, closed: 2, handoffsOpen: 1 });
  assert.equal(counts.waiting + counts.talking + counts.onMerchant + counts.done + counts.closed, rows.length);
});

test("without belief updates the meter shows the card's starting worries", () => {
  assert.deepEqual(deriveCallView([{ kind: "mission_created", payload: { card } }]).concerns, card.starting_worries);
});
