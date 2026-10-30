# Chanakya evaluation

- Command: `python -m chanakya.eval.harness --mode offline --merchants 100 --seed 13 --variants chanakya,chanakya_value --out docs/results/neural-value-network/seed13`
- Mode: offline (offline means template voices and declared moves, no network)
- Seed: 13; held-out Twin-B calls per variant: 100; adversarial calls per variant: 12
- Elapsed: 105.6 s

| Metric | chanakya | chanakya_value |
|---|---|---|
| Mission success (consent to onboarding) | 0.98 | 0.92 |
| Follow-up agreed | 0.0 | 0.0 |
| Merchant walked away | 0.01 | 0.07 |
| Belief top-1 accuracy (top worry is one the merchant holds) | 0.34 | 0.39 |
| Agent turns to close | 5.06 | 5.7 |
| Agent turns on failed calls | 8.5 | 7 |
| Escalation precision | 1.0 | 1.0 |
| Escalation recall | 1.0 | 1.0 |
| Wrong actions per call | 0.0 | 0.0 |
| Safety violations | 0 | 0 |
| Violations on adversarial calls | 0 | 0 |
| Turn latency p50 (ms) | 99.9 | 149.9 |
| Turn latency p90 (ms) | 115.7 | 176.8 |
| LLM calls per completed mission | n/a | n/a |
| Agent turns that failed (provider errors) | 0 | 0 |

Violations by kind:

- chanakya: none
- chanakya_value: none

Speed to lead and cost per completed mission in currency are not measured by this text-mode harness: it has no scheduler clock or provider billing. LLM calls per completed mission is reported instead.
