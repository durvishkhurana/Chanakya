# Chanakya evaluation

- Command: `python -m chanakya.eval.harness --mode offline --merchants 100 --seed 13 --voice test --variants chanakya,chanakya_forest,chanakya_memory,chanakya_value --out docs/results/neural-combined/seed13`
- Mode: offline (offline means template voices and declared moves, no network)
- Seed: 13; held-out Twin-B calls per variant: 100; adversarial calls per variant: 12
- Elapsed: 763.5 s

| Metric | chanakya | chanakya_forest | chanakya_memory | chanakya_value |
|---|---|---|---|---|
| Mission success (consent to onboarding) | 0.77 | 0.79 | 0.8 | 0.81 |
| Follow-up agreed | 0.0 | 0.0 | 0.0 | 0.0 |
| Merchant walked away | 0.22 | 0.21 | 0.18 | 0.13 |
| Belief top-1 accuracy (top worry is one the merchant holds) | 0.53 | 0.52 | 0.52 | 0.55 |
| Agent turns to close | 4.94 | 4.96 | 4.92 | 5.32 |
| Agent turns on failed calls | 6.09 | 6.24 | 6.05 | 5.68 |
| Escalation precision | 1.0 | 1.0 | 1.0 | 1.0 |
| Escalation recall | 1.0 | 1.0 | 1.0 | 1.0 |
| Wrong actions per call | 0.0 | 0.0 | 0.0 | 0.0 |
| Safety violations | 0 | 0 | 0 | 0 |
| Violations on adversarial calls | 0 | 0 | 0 | 0 |
| Turn latency p50 (ms) | 121.5 | 121.1 | 144.9 | 180.8 |
| Turn latency p90 (ms) | 138.9 | 139.2 | 162.1 | 214.5 |
| LLM calls per completed mission | n/a | n/a | n/a | n/a |
| Agent turns that failed (provider errors) | 0 | 0 | 0 | 0 |

Violations by kind:

- chanakya: none
- chanakya_forest: none
- chanakya_memory: none
- chanakya_value: none

Speed to lead and cost per completed mission in currency are not measured by this text-mode harness: it has no scheduler clock or provider billing. LLM calls per completed mission is reported instead.
