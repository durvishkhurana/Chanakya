import assert from "node:assert/strict";
import test from "node:test";

import { coachMoveLabel, handoffText, turnPause } from "./coachView.mjs";

test("every move the coach engine suggests reads as an instruction to the telecaller", () => {
  assert.equal(coachMoveLabel({ type: "RESOLVE_CONCERN", concern: "competitor_qr" }), "Answer the worry: Already has a QR");
  assert.equal(coachMoveLabel({ type: "PROBE_CONCERN", concern: "rental_cost" }), "Gently ask about rental cost");
  assert.equal(coachMoveLabel({ type: "CONFIRM_CONSENT", tool: "send_onboarding_link" }), "Ask a clear yes before you send onboarding link");
  assert.equal(coachMoveLabel({ type: "RECOMMEND", product: "soundbox" }), "Recommend the Soundbox");
  assert.equal(coachMoveLabel({ type: "ESCALATE" }), "Hand over to a senior colleague");
  for (const type of ["DISCOVER_NEED", "TAKE_ACTION", "SCHEDULE_FOLLOWUP", "END_CALL_POLITELY", "RECOMMEND"]) {
    assert.ok(coachMoveLabel({ type }).length > 0 && !coachMoveLabel({ type }).includes("_"), type);
  }
  assert.equal(coachMoveLabel(null), "");
});

test("recorded playback lingers on merchant turns", () => {
  assert.ok(turnPause("merchant") > turnPause("human_agent"));
});

test("the hand-off card copies as plain text with worries highest first", () => {
  const text = handoffText({ summary: "Gupta Medicals needs a senior.", reason: "Signs of distress",
    open_concerns: { just_busy: 0.1, settlement_delay: 0.7 } });
  assert.equal(text, "Gupta Medicals needs a senior.\nReason: Signs of distress\nLikely worries: Settlement delay 70%, Just busy 10%");
});
