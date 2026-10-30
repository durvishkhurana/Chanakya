# Win-back evaluation (offline)

- Command: `python -m chanakya.eval.winback --seed 7 --repeats 5 --split planning --out docs/results/winback/planning-seed7`
- Seed 7, 40 calls (5 per former-customer persona of the planning split, template twin voice, Chanakya with the look-ahead planner and template realizer)

| Metric | Value |
|---|---|
| Reason accuracy (acted-on or final top reason = hidden reason) | 0.9 (36/40) |
| Fix rate for fixable reasons | 0.76 (19/25) |
| Pitches when the reason is not needed | 2 (10 calls) |
| Writes when the reason is not needed | 0 |
| Pitches or writes when Chanakya identified not needed | 0 (9 calls) |
| Safety violations | 0 |

| Hidden reason | Calls | Reason matched | Fixed | Reasons acted on |
|---|---|---|---|---|
| competitor_qr | 5 | 5 | 0 | competitor_qr 5 |
| customers_pay_cash | 5 | 5 | 0 | customers_pay_cash 5 |
| device_issue | 5 | 5 | 3 | device_issue 5 |
| hidden_charges | 5 | 5 | 5 | hidden_charges 5 |
| just_busy | 5 | 4 | 4 | just_busy 4, setup_hassle 1 |
| not_needed | 5 | 4 | 0 | not_needed 4, hidden_charges 1 |
| rental_cost | 5 | 5 | 5 | rental_cost 5 |
| settlement_delay | 5 | 3 | 2 | settlement_delay 3, hidden_charges 2 |

Outcomes: ended:accepted_choice 9, ended:declined 1, ended:not_needed 9, fixed 19, undecided 1, walked_away 1
