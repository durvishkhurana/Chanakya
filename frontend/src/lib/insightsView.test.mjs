import assert from "node:assert/strict";
import test from "node:test";

import { breakdownRows, escalationLabel, funnelRows, moveRows, productLabel, typeLabel } from "./insightsView.mjs";

test("funnel rows carry each stage's share of opened missions and the drop since the stage before", () => {
  const rows = funnelRows([{ stage: "opened", missions: 88 }, { stage: "consent", missions: 55 }, { stage: "done", missions: 35 }]);
  assert.deepEqual(rows.map((r) => [r.share, r.dropped]), [[1, 0], [55 / 88, 33], [35 / 88, 20]]);
  assert.deepEqual(funnelRows([]), []);
});

test("breakdowns list the biggest groups first with their top worries as shares", () => {
  const rows = breakdownRows({ card_machine: { per_swipe_charges: 1 }, soundbox: { rental_cost: 3, competitor_qr: 1 } }, 1);
  assert.equal(rows[0].group, "soundbox");
  assert.equal(rows[0].total, 4);
  assert.deepEqual(rows[0].worries, [{ id: "rental_cost", label: "Rental cost", share: 0.75 }]);
});

test("move rows keep worries with enough calls and compute the consent difference", () => {
  const moves = [
    { worry: "rental_cost", missions: 7, addressed: { missions: 4, consent_rate: 0.75 }, not_addressed: { missions: 3, consent_rate: 0.5 } },
    { worry: "data_privacy", missions: 2, addressed: { missions: 1, consent_rate: 1 }, not_addressed: { missions: 1, consent_rate: 0 } },
    { worry: "hidden_charges", missions: 5, addressed: { missions: 5, consent_rate: 0.4 }, not_addressed: { missions: 0, consent_rate: null } },
  ];
  const rows = moveRows(moves);
  assert.deepEqual(rows.map((r) => r.worry), ["rental_cost", "hidden_charges"]);
  assert.equal(rows[0].lift, 0.25);
  assert.equal(rows[1].lift, null, "no comparison when every call addressed the worry");
  const thin = moveRows([{ worry: "not_needed", missions: 16, addressed: { missions: 14, consent_rate: 0.79 }, not_addressed: { missions: 2, consent_rate: 0 } }]);
  assert.equal(thin[0].lift, null, "14 calls against 2 is too few to compare");
});

test("labels read as plain words", () => {
  assert.equal(typeLabel("win_back"), "Win-back");
  assert.equal(productLabel("card_machine"), "Card machine");
  assert.equal(escalationLabel("distress"), "Merchant in distress");
  assert.equal(escalationLabel("asked twice"), "Asked twice");
});
