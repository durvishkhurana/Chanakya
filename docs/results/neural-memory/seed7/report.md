# Chanakya evaluation

- Command: `python -m chanakya.eval.harness --mode offline --merchants 100 --seed 7 --voice test --variants chanakya,chanakya_forest,chanakya_memory --out docs/results/neural-memory/seed7`
- Mode: offline (offline means template voices and declared moves, no network)
- Seed: 7; held-out Twin-B calls per variant: 100; adversarial calls per variant: 12
- Elapsed: 145.3 s

| Metric | chanakya | chanakya_forest | chanakya_memory |
|---|---|---|---|
| Mission success (consent to onboarding) | 0.62 | 0.62 | 0.63 |
| Follow-up agreed | 0.0 | 0.0 | 0.0 |
| Merchant walked away | 0.34 | 0.35 | 0.33 |
| Belief top-1 accuracy (top worry is one the merchant holds) | 0.26 | 0.27 | 0.28 |
| Agent turns to close | 5.06 | 5 | 5.13 |
| Agent turns on failed calls | 5.74 | 5.5 | 5.49 |
| Escalation precision | 1.0 | 1.0 | 1.0 |
| Escalation recall | 1.0 | 1.0 | 1.0 |
| Wrong actions per call | 0.0 | 0.0 | 0.0 |
| Safety violations | 0 | 0 | 0 |
| Violations on adversarial calls | 0 | 0 | 0 |
| Turn latency p50 (ms) | 111.2 | 106.3 | 129.2 |
| Turn latency p90 (ms) | 128.9 | 122.8 | 150.0 |
| LLM calls per completed mission | n/a | n/a | n/a |
| Agent turns that failed (provider errors) | 0 | 0 | 0 |

Violations by kind:

- chanakya: none
- chanakya_forest: none
- chanakya_memory: none

Speed to lead and cost per completed mission in currency are not measured by this text-mode harness: it has no scheduler clock or provider billing. LLM calls per completed mission is reported instead.
