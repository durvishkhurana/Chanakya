# Chanakya evaluation

- Command: `python -m chanakya.eval.harness --mode offline --merchants 100 --seed 13 --variants chanakya,chanakya_embedding --voice test --out docs/results/neural-worry-scorer/filler-diagnosis/clamp/test-seed13`
- Mode: offline (offline means template voices and declared moves, no network)
- Seed: 13; held-out Twin-B calls per variant: 100; adversarial calls per variant: 12
- Elapsed: 67.9 s

| Metric | chanakya | chanakya_embedding |
|---|---|---|
| Mission success (consent to onboarding) | 0.62 | 0.69 |
| Follow-up agreed | 0.0 | 0.0 |
| Merchant walked away | 0.36 | 0.27 |
| Belief top-1 accuracy (top worry is one the merchant holds) | 0.29 | 0.69 |
| Agent turns to close | 4.95 | 4.49 |
| Agent turns on failed calls | 5.79 | 5.55 |
| Escalation precision | 1.0 | 1.0 |
| Escalation recall | 1.0 | 1.0 |
| Wrong actions per call | 0.0 | 0.0 |
| Safety violations | 0 | 0 |
| Violations on adversarial calls | 0 | 0 |
| Turn latency p50 (ms) | 34.6 | 50.2 |
| Turn latency p90 (ms) | 38.7 | 54.6 |
| LLM calls per completed mission | n/a | n/a |
| Agent turns that failed (provider errors) | 0 | 0 |

Violations by kind:

- chanakya: none
- chanakya_embedding: none

Speed to lead and cost per completed mission in currency are not measured by this text-mode harness: it has no scheduler clock or provider billing. LLM calls per completed mission is reported instead.
