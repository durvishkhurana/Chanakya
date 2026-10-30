# Chanakya evaluation

- Command: `python -m chanakya.eval.harness --mode offline --merchants 100 --seed 13 --voice test --variants chanakya,chanakya_forest,chanakya_memory --out docs/results/neural-memory/seed13`
- Mode: offline (offline means template voices and declared moves, no network)
- Seed: 13; held-out Twin-B calls per variant: 100; adversarial calls per variant: 12
- Elapsed: 142.3 s

| Metric | chanakya | chanakya_forest | chanakya_memory |
|---|---|---|---|
| Mission success (consent to onboarding) | 0.62 | 0.61 | 0.61 |
| Follow-up agreed | 0.0 | 0.0 | 0.0 |
| Merchant walked away | 0.36 | 0.38 | 0.37 |
| Belief top-1 accuracy (top worry is one the merchant holds) | 0.29 | 0.3 | 0.29 |
| Agent turns to close | 4.95 | 4.97 | 5 |
| Agent turns on failed calls | 5.79 | 5.9 | 5.95 |
| Escalation precision | 1.0 | 1.0 | 1.0 |
| Escalation recall | 1.0 | 1.0 | 1.0 |
| Wrong actions per call | 0.0 | 0.0 | 0.0 |
| Safety violations | 0 | 0 | 0 |
| Violations on adversarial calls | 0 | 0 | 0 |
| Turn latency p50 (ms) | 104.6 | 105.3 | 128.0 |
| Turn latency p90 (ms) | 118.8 | 122.9 | 147.2 |
| LLM calls per completed mission | n/a | n/a | n/a |
| Agent turns that failed (provider errors) | 0 | 0 | 0 |

Violations by kind:

- chanakya: none
- chanakya_forest: none
- chanakya_memory: none

Speed to lead and cost per completed mission in currency are not measured by this text-mode harness: it has no scheduler clock or provider billing. LLM calls per completed mission is reported instead.
