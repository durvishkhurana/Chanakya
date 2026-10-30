# Chanakya evaluation

- Command: `python -m chanakya.eval.harness --mode offline --merchants 100 --seed 13 --variants chanakya,chanakya_forest --out /tmp/n0_harness_13`
- Mode: offline (offline means template voices and declared moves, no network)
- Seed: 13; held-out Twin-B calls per variant: 100; adversarial calls per variant: 12
- Elapsed: 24.9 s

| Metric | chanakya | chanakya_forest |
|---|---|---|
| Mission success (consent to onboarding) | 0.98 | 0.98 |
| Follow-up agreed | 0.0 | 0.0 |
| Merchant walked away | 0.01 | 0.02 |
| Agent turns to close | 5.06 | 5.01 |
| Agent turns on failed calls | 8.5 | 8 |
| Escalation precision | 1.0 | 1.0 |
| Escalation recall | 1.0 | 1.0 |
| Wrong actions per call | 0.0 | 0.0 |
| Safety violations | 0 | 0 |
| Violations on adversarial calls | 0 | 0 |
| Turn latency p50 (ms) | 34.1 | 34.4 |
| Turn latency p90 (ms) | 38.5 | 39.1 |
| LLM calls per completed mission | n/a | n/a |
| Agent turns that failed (provider errors) | 0 | 0 |

Violations by kind:

- chanakya: none
- chanakya_forest: none

Speed to lead and cost per completed mission in currency are not measured by this text-mode harness: it has no scheduler clock or provider billing. LLM calls per completed mission is reported instead.
