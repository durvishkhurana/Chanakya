# Win-back evaluation (offline)

- Command: `python -m chanakya.eval.winback --seed 7 --repeats 5 --out docs/results/neural-worry-scorer/filler-diagnosis/clamp/winback-seed7`
- Seed 7, 50 calls (5 per former-customer persona of the evaluation split, template twin voice, Chanakya with the look-ahead planner and template realizer)

| Metric | Value |
|---|---|
| Reason accuracy (acted-on or final top reason = hidden reason) | 0.96 (48/50) |
| Fix rate for fixable reasons | 0.933 (28/30) |
| Pitches when the reason is not needed | 1 (15 calls) |
| Writes when the reason is not needed | 0 |
| Pitches or writes when Chanakya identified not needed | 0 (14 calls) |
| Safety violations | 0 |

| Hidden reason | Calls | Reason matched | Fixed | Reasons acted on |
|---|---|---|---|---|
| competitor_qr | 5 | 5 | 0 | competitor_qr 5 |
| customers_pay_cash | 5 | 5 | 0 | customers_pay_cash 5 |
| device_issue | 10 | 10 | 8 | device_issue 10 |
| just_busy | 5 | 5 | 5 | just_busy 5 |
| not_needed | 10 | 8 | 0 | not_needed 8, customers_pay_cash 1, competitor_qr 1 |
| per_swipe_charges | 5 | 5 | 5 | per_swipe_charges 5 |
| rental_cost | 5 | 5 | 5 | rental_cost 5 |
| settlement_delay | 5 | 5 | 5 | settlement_delay 5 |

Outcomes: ended:accepted_choice 8, ended:not_needed 14, fixed 28
