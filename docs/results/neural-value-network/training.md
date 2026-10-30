# Value network: training

- Command: `python -m chanakya.brain.value.train --seed 7 --seeds 4`
- Self-play: 120 calls, the look-ahead planner against Twin-A (template voice) on planning personas; 3276 sampled leaves, each played to its end; 48 s
- Validation: leaves from 4 planning personas never trained on (plan_018, plan_020, plan_026, plan_027)
- Network: 27 features, tanh layers [32, 16], seed 7, data hash `f5b599ae8143611f`, 2026-10-30

| Predictor of the played-out ending | Validation MSE | All rows MSE |
|---|---|---|
| Formula (`0.8 x consent_chance`) | 0.2353 | 0.2578 |
| Value network | 0.0561 | train 0.0481 |

Lower is better. This only says the network predicts self-play endings; whether it helps the planner is measured on held-out evaluation personas in `README.md`.
