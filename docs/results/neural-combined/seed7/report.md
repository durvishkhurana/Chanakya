# Chanakya evaluation

- Command: `python -m chanakya.eval.harness --mode offline --merchants 100 --seed 7 --voice test --variants chanakya,chanakya_forest,chanakya_memory,chanakya_value --out docs/results/neural-combined/seed7`
- Mode: offline (offline means template voices and declared moves, no network)
- Seed: 7; held-out Twin-B calls per variant: 100; adversarial calls per variant: 12
- Elapsed: 766.2 s

| Metric | chanakya | chanakya_forest | chanakya_memory | chanakya_value |
|---|---|---|---|---|
| Mission success (consent to onboarding) | 0.84 | 0.84 | 0.83 | 0.74 |
| Follow-up agreed | 0.0 | 0.0 | 0.0 | 0.01 |
| Merchant walked away | 0.12 | 0.11 | 0.11 | 0.17 |
| Belief top-1 accuracy (top worry is one the merchant holds) | 0.5 | 0.51 | 0.54 | 0.49 |
| Agent turns to close | 5.2 | 5.3 | 5.23 | 5.69 |
| Agent turns on failed calls | 5.12 | 5.56 | 5.71 | 5.88 |
| Escalation precision | 1.0 | 1.0 | 1.0 | 1.0 |
| Escalation recall | 1.0 | 1.0 | 1.0 | 1.0 |
| Wrong actions per call | 0.0 | 0.0 | 0.0 | 0.0 |
| Safety violations | 0 | 0 | 0 | 0 |
| Violations on adversarial calls | 0 | 0 | 0 | 0 |
| Turn latency p50 (ms) | 120.9 | 119.3 | 144.1 | 173.8 |
| Turn latency p90 (ms) | 142.0 | 137.5 | 161.4 | 204.9 |
| LLM calls per completed mission | n/a | n/a | n/a | n/a |
| Agent turns that failed (provider errors) | 0 | 0 | 0 | 0 |

Violations by kind:

- chanakya: none
- chanakya_forest: none
- chanakya_memory: none
- chanakya_value: none

Speed to lead and cost per completed mission in currency are not measured by this text-mode harness: it has no scheduler clock or provider billing. LLM calls per completed mission is reported instead.
