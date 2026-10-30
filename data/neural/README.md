# Neural brain data

| File | What it is | Written by |
|---|---|---|
| `worry_lines.jsonl` | 2,123 labelled merchant lines (train and test splits) from task N0 | LLMs: train by the Twin-A model, test by the Twin-B model |
| `worry_lines_human.csv` | The hand-written test set for task N1 | People only (Gurnoor and Durvish) |
| `worry_head.npz` | The trained worry head (N1): 384 x 13 weights, biases, temperature, metadata | `python -m chanakya.neural.train_worry` |

All merchants are fictional. Encoder weights are downloaded, never committed.

## Writing the hand-written test set

Aim for about 300 lines, roughly 150 each. Write them yourself; do not ask an LLM, because the point is to test on how
real merchants talk, not on how models write. These lines are never used for training, tuning or calibration.

One row per line, in `worry_lines_human.csv`:

| Column | What to put |
|---|---|
| `text` | One thing a shopkeeper might say on the phone. Quote it if it contains a comma. |
| `concerns` | The worry ids the line shows, separated by `;`, or `none`. Ids are in `data/concerns/concerns.json`. |
| `language` | `hindi` (Devanagari), `hinglish` (Hindi and English in Latin letters), `punjabi` (Gurmukhi) or `english` |
| `slice` | `hinglish_roman`, `negation`, `no_worry`, `punjabi` or `other` |
| `author` | `gurnoor` or `durvish` |

The 13 worry ids: `hidden_charges`, `rental_cost`, `per_swipe_charges`, `setup_hassle`, `competitor_qr`,
`settlement_delay`, `trust_in_caller`, `just_busy`, `device_issue`, `language_comfort`, `data_privacy`, `not_needed`,
`customers_pay_cash`.

The four slices, about 60 to 75 lines each:

- `hinglish_roman`: Hinglish in Latin letters, the way people type and talk. Mixed spellings are good.
- `negation`: lines that mention a worry only to deny it. "Koi problem nahi hai" has no worry (`none`). "Charges ki
  tension nahi, bas setup ka jhanjhat hai" has `setup_hassle`.
- `no_worry`: greetings, okays, yeses, questions about something else. `concerns` must be `none`.
- `punjabi`: Punjabi in Gurmukhi.

Example rows (for the format only; do not copy them into the file):

```csv
text,concerns,language,slice,author
"bhai mahine ka kitna lagega, aur baad mein koi cutting toh nahi?",rental_cost;hidden_charges,hinglish,hinglish_roman,gurnoor
"koi problem nahi hai, bolo",none,hinglish,negation,durvish
ਹਾਂ ਜੀ ਦੱਸੋ ਕੀ ਗੱਲ ਹੈ,none,punjabi,punjabi,gurnoor
```

Check the file before committing it:

```bash
python -m chanakya.neural.human_set
```
