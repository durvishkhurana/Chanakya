# Win-back evaluation (offline)

- Command: `python -m chanakya.eval.winback --seed 7 --repeats 5 --out docs/results/winback/embedding-evaluation-seed7`
- Seed 7, 50 calls (5 per former-customer persona of the evaluation split, template twin voice, Chanakya with the look-ahead planner and template realizer)

| Metric | Value |
|---|---|
| Reason accuracy (acted-on or final top reason = hidden reason) | 0.9 (45/50) |
| Fix rate for fixable reasons | 0.933 (28/30) |
| Pitches when the reason is not needed | 4 (15 calls) |
| Writes when the reason is not needed | 0 |
| Pitches or writes when Chanakya identified not needed | 0 (11 calls) |
| Safety violations | 0 |

| Hidden reason | Calls | Reason matched | Fixed | Reasons acted on |
|---|---|---|---|---|
| competitor_qr | 5 | 5 | 0 | competitor_qr 5 |
| customers_pay_cash | 5 | 5 | 0 | customers_pay_cash 5 |
| device_issue | 10 | 9 | 8 | device_issue 9, trust_in_caller 1 |
| just_busy | 5 | 5 | 5 | just_busy 5 |
| not_needed | 10 | 6 | 0 | not_needed 6, device_issue 4 |
| per_swipe_charges | 5 | 5 | 5 | per_swipe_charges 5 |
| rental_cost | 5 | 5 | 5 | rental_cost 5 |
| settlement_delay | 5 | 5 | 5 | settlement_delay 5 |

Outcomes: ended:accepted_choice 7, ended:declined 4, ended:not_needed 11, fixed 28
