# Chanakya evaluation

- Command: `python -m chanakya.eval.harness --mode offline --merchants 100 --seed 7 --variants chanakya,chanakya_embedding --voice template --out docs/results/neural-worry-scorer/filler-diagnosis/clamp/template-seed7`
- Mode: offline (offline means template voices and declared moves, no network)
- Seed: 7; held-out Twin-B calls per variant: 100; adversarial calls per variant: 12
- Elapsed: 67.4 s

| Metric | chanakya | chanakya_embedding |
|---|---|---|
| Mission success (consent to onboarding) | 0.96 | 0.83 |
| Follow-up agreed | 0.0 | 0.0 |
| Merchant walked away | 0.04 | 0.15 |
| Belief top-1 accuracy (top worry is one the merchant holds) | 0.39 | 0.87 |
| Agent turns to close | 5.09 | 4.87 |
| Agent turns on failed calls | 5.75 | 7.18 |
| Escalation precision | 1.0 | 1.0 |
| Escalation recall | 1.0 | 1.0 |
| Wrong actions per call | 0.0 | 0.0 |
| Safety violations | 0 | 0 |
| Violations on adversarial calls | 0 | 0 |
| Turn latency p50 (ms) | 33.7 | 48.9 |
| Turn latency p90 (ms) | 38.0 | 53.6 |
| LLM calls per completed mission | n/a | n/a |
| Agent turns that failed (provider errors) | 0 | 0 |

Violations by kind:

- chanakya: none
- chanakya_embedding: none

Speed to lead and cost per completed mission in currency are not measured by this text-mode harness: it has no scheduler clock or provider billing. LLM calls per completed mission is reported instead.
