import assert from "node:assert/strict";
import test from "node:test";

import { DOORS, SCENARIOS, STAGES, STARTING_WORRIES, stageWeights } from "./landingData.mjs";

const sum = (o) => Object.values(o).reduce((a, b) => a + b, 0);

test("every concern estimate is a probability distribution", () => {
  assert.ok(Math.abs(sum(STARTING_WORRIES) - 1) < 1e-9);
  for (const s of SCENARIOS) assert.ok(Math.abs(sum(s.concerns) - 1) < 1e-9, s.id);
});

test("the signalled worry is the top concern of each line, except the plain yes", () => {
  const labels = { hidden_charges: "Hidden charges", competitor_qr: "Already has a QR", just_busy: "Just busy", data_privacy: "Data privacy", trust_in_caller: "Trust in caller" };
  for (const s of SCENARIOS.filter((x) => x.id !== "yes")) {
    const [top] = Object.entries(s.concerns).sort((a, b) => b[1] - a[1])[0];
    assert.equal(labels[top], s.signals, s.id);
  }
});

test("replies follow the agent's safety rules", () => {
  for (const s of SCENARIOS) {
    assert.doesNotMatch(s.reply, /₹|\d+ ?(rs|rupees?)\b|free|cashback|offer/i, `${s.id} quotes a price or offer`);
    assert.doesNotMatch(s.reply, /(batayein|bataiye|share karein).*(otp|pin)/i, `${s.id} asks for a secret`);
    assert.doesNotMatch(s.reply, /—/, `${s.id} uses an em dash`);
  }
  assert.match(SCENARIOS.find((s) => s.id === "yes").reply, /haan ya na/i);
});

test("doors have rows and stage weights are proportional with a 12% floor", () => {
  assert.equal(DOORS.length, 3);
  assert.ok(DOORS.every((d) => d.rows.length >= 3));
  const w = stageWeights();
  assert.ok(Math.abs(w.reduce((a, b) => a + b, 0) - 1) < 1e-9);
  assert.ok(w.every((x) => x >= 0.1));
  assert.ok(w[2] > w[1] && w[1] > w[0]);
  assert.equal(w.length, STAGES.length);
});
