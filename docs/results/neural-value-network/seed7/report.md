# Chanakya evaluation

- Command: `python -m chanakya.eval.harness --mode offline --merchants 100 --seed 7 --variants chanakya,chanakya_value --out docs/results/neural-value-network/seed7`
- Mode: offline (offline means template voices and declared moves, no network)
- Seed: 7; held-out Twin-B calls per variant: 100; adversarial calls per variant: 12
- Elapsed: 106.0 s

| Metric | chanakya | chanakya_value |
|---|---|---|
| Mission success (consent to onboarding) | 0.96 | 0.94 |
| Follow-up agreed | 0.0 | 0.0 |
| Merchant walked away | 0.04 | 0.06 |
| Belief top-1 accuracy (top worry is one the merchant holds) | 0.39 | 0.41 |
| Agent turns to close | 5.09 | 5.79 |
| Agent turns on failed calls | 5.75 | 5.83 |
| Escalation precision | 1.0 | 1.0 |
| Escalation recall | 1.0 | 1.0 |
| Wrong actions per call | 0.0 | 0.0 |
| Safety violations | 0 | 0 |
| Violations on adversarial calls | 0 | 0 |
| Turn latency p50 (ms) | 99.1 | 153.7 |
| Turn latency p90 (ms) | 116.2 | 181.0 |
| LLM calls per completed mission | n/a | n/a |
| Agent turns that failed (provider errors) | 0 | 0 |

Violations by kind:

- chanakya: none
- chanakya_value: none

Speed to lead and cost per completed mission in currency are not measured by this text-mode harness: it has no scheduler clock or provider billing. LLM calls per completed mission is reported instead.
