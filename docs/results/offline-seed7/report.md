# Chanakya evaluation

- Command: `python -m chanakya.eval.harness --mode offline --merchants 100 --seed 7 --out docs/results/offline-seed7`
- Mode: offline (offline means template voices and declared moves, no network)
- Seed: 7; held-out Twin-B calls per variant: 100; adversarial calls per variant: 12
- Elapsed: 55.4 s

| Metric | reactive | actions_only | chanakya | chanakya_no_belief |
|---|---|---|---|---|
| Mission success (consent to onboarding) | 0.0 | 0.99 | 0.97 | 0.54 |
| Follow-up agreed | 0.0 | 0.0 | 0.0 | 0.0 |
| Merchant walked away | 0.07 | 0.01 | 0.03 | 0.46 |
| Agent turns to close | n/a | 5.49 | 5.09 | 4.44 |
| Agent turns on failed calls | 11.93 | 8 | 6.67 | 5.3 |
| Escalation precision | n/a | n/a | 1.0 | 1.0 |
| Escalation recall | 0.0 | 0.0 | 1.0 | 1.0 |
| Wrong actions per call | 0.0 | 0.0 | 0.0 | 0.0 |
| Safety violations | 0 | 0 | 0 | 0 |
| Violations on adversarial calls | 0 | 0 | 0 | 0 |
| Turn latency p50 (ms) | 0.1 | 0.2 | 68.1 | 74.0 |
| Turn latency p90 (ms) | 0.2 | 0.3 | 84.7 | 86.5 |
| LLM calls per completed mission | n/a | n/a | n/a | n/a |
| Agent turns that failed (provider errors) | 0 | 0 | 0 | 0 |

Violations by kind:

- reactive: none
- actions_only: none
- chanakya: none
- chanakya_no_belief: none

Speed to lead and cost per completed mission in currency are not measured by this text-mode harness: it has no scheduler clock or provider billing. LLM calls per completed mission is reported instead.
