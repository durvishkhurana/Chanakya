# Win-back evaluation (offline)

- Command: `python -m chanakya.eval.winback --seed 13 --repeats 5 --out docs/results/winback/embedding-evaluation-seed13`
- Seed 13, 50 calls (5 per former-customer persona of the evaluation split, template twin voice, Chanakya with the look-ahead planner and template realizer)

| Metric | Value |
|---|---|
| Reason accuracy (acted-on or final top reason = hidden reason) | 0.84 (42/50) |
| Fix rate for fixable reasons | 0.833 (25/30) |
| Pitches when the reason is not needed | 1 (15 calls) |
| Writes when the reason is not needed | 0 |
| Pitches or writes when Chanakya identified not needed | 0 (15 calls) |
| Safety violations | 0 |

| Hidden reason | Calls | Reason matched | Fixed | Reasons acted on |
|---|---|---|---|---|
| competitor_qr | 5 | 5 | 0 | competitor_qr 5 |
| customers_pay_cash | 5 | 5 | 0 | customers_pay_cash 5 |
| device_issue | 10 | 6 | 6 | device_issue 6, trust_in_caller 3, competitor_qr 1 |
| just_busy | 5 | 4 | 4 | just_busy 4, not_needed 1 |
| not_needed | 10 | 7 | 0 | not_needed 7, customers_pay_cash 2, device_issue 1 |
| per_swipe_charges | 5 | 5 | 5 | per_swipe_charges 5 |
| rental_cost | 5 | 5 | 5 | rental_cost 5 |
| settlement_delay | 5 | 5 | 5 | settlement_delay 5 |

Outcomes: ended:accepted_choice 9, ended:declined 1, ended:not_needed 15, fixed 25
