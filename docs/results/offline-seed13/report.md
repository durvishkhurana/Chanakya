# Chanakya evaluation

- Command: `python -m chanakya.eval.harness --mode offline --merchants 100 --seed 13 --out docs/results/offline-seed13`
- Mode: offline (offline means template voices and declared moves, no network)
- Seed: 13; held-out Twin-B calls per variant: 100; adversarial calls per variant: 12
- Elapsed: 58.7 s

| Metric | reactive | actions_only | chanakya | chanakya_no_belief |
|---|---|---|---|---|
| Mission success (consent to onboarding) | 0.0 | 1.0 | 0.97 | 0.48 |
| Follow-up agreed | 0.0 | 0.0 | 0.0 | 0.0 |
| Merchant walked away | 0.07 | 0.0 | 0.02 | 0.52 |
| Agent turns to close | n/a | 5.12 | 5.2 | 4.65 |
| Agent turns on failed calls | 11.93 | n/a | 8 | 5.15 |
| Escalation precision | n/a | n/a | 1.0 | 1.0 |
| Escalation recall | 0.0 | 0.0 | 1.0 | 1.0 |
| Wrong actions per call | 0.0 | 0.0 | 0.0 | 0.0 |
| Safety violations | 0 | 0 | 0 | 0 |
| Violations on adversarial calls | 0 | 0 | 0 | 0 |
| Turn latency p50 (ms) | 0.1 | 0.2 | 69.3 | 74.0 |
| Turn latency p90 (ms) | 0.2 | 0.2 | 84.8 | 91.6 |
| LLM calls per completed mission | n/a | n/a | n/a | n/a |
| Agent turns that failed (provider errors) | 0 | 0 | 0 | 0 |

Violations by kind:

- reactive: none
- actions_only: none
- chanakya: none
- chanakya_no_belief: none

Speed to lead and cost per completed mission in currency are not measured by this text-mode harness: it has no scheduler clock or provider billing. LLM calls per completed mission is reported instead.
