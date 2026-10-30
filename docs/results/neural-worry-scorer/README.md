# Neural worry scorer (N1)

Measured on 2026-10-31, macOS, Python 3.12, CPU only. Every number comes from a command on this page. All merchants
are simulated; no real calls.

## Setup

```bash
pip install -r requirements-neural.txt
python -m chanakya.neural.encoder --download                 # multilingual-e5-small, ONNX, about 470 MB, never committed
python -m chanakya.neural.paraphrase --seed 11 --extend-train mistralai/mistral-small-2603 --extend-train z-ai/glm-5.3-flash
python -m chanakya.neural.train_worry --seed 7               # writes data/neural/worry_head.npz and results.json here
```

- **Encoder:** `intfloat/multilingual-e5-small` on ONNX Runtime. It gives the same vectors as the PyTorch model (cosine
  1.0 on every line checked) at about 2.5 ms per line, with no PyTorch.
- **Head:** a numpy network, 384 → 128 (ReLU) → 13 independent sigmoid outputs. It is trained with Adam on binary
  cross-entropy, stopped early on a seeded 15% validation split, and calibrated with one temperature fitted on that
  split. The one-hidden-layer network beat a plain logistic head on validation loss (0.162 vs 0.184).
- **Training lines:** the N0 train split (DeepSeek) extended with Mistral and GLM, 4,334 lines from three model
  families. The test split, 668 lines written by GPT-6 Luna, is unchanged and never used for training or tuning.

## Per-line accuracy on the test split (14 labels: 13 worries or no worry)

| Scorer | All 14 labels | Worry lines | No-worry lines | English | Hindi | Hinglish | Punjabi | p50 ms |
|---|---|---|---|---|---|---|---|---|
| Lexical (today) | 0.388 | 0.415 | 0.022 | 0.387 | 0.388 | 0.449 | 0.327 | 0.07 |
| Embedding, trained on DeepSeek lines only | 0.536 | 0.569 | 0.087 | 0.482 | 0.594 | 0.557 | 0.512 | 2.7 |
| **Embedding, trained on three model families** | **0.627** | **0.641** | **0.435** | **0.649** | **0.661** | **0.611** | **0.589** | **2.8** |
| LLM scorer (N0, 112-line sample) | 0.777 | 0.788 | 0.625 | 0.893 | 0.750 | 0.720 | 0.741 | 1920 |

**Calibration** (validation split, every line and worry pair): expected calibration error is 0.0057 before
temperature scaling and 0.0046 after (temperature 1.047). When the scorer says 30%, the worry is there about 30% of the
time, which is what lets the belief tracker use the scores as Bayesian odds ratios instead of tuned constants.

What this shows:

- **The trained scorer beats today's lexical scorer on wording it has never seen,** by 24 points overall and by 26 on
  Punjabi, at under 3 ms per line, with no network call.
- **Training data from more model families mattered more than model size:** going from one family to three added 9
  points. It also taught the scorer to say "no worry" (0.087 to 0.435).
- **The LLM scorer is still more accurate (0.777)** but takes about 2 s per line and hits rate limits, so it is not
  usable on a live turn.

## Fine-tuning the encoder (experiment, not adopted)

Fine-tuning all of e5-small with a 13-sigmoid head (PyTorch, AdamW, encoder learning rate 3e-5, batch 32, seed 7):

| Training lines | Epoch picked on validation | Test accuracy | Frozen encoder + head |
|---|---|---|---|
| DeepSeek only | still rising at epoch 10 (validation 0.72) | 0.54 to 0.55 | 0.536 |
| Three model families | epoch 4 (validation 0.610) | 0.645 | 0.627 |

With one training family, fine-tuning learned that model's style: validation rose while test stayed flat. With three
families it adds under 2 points, at the cost of a fine-tuned copy of the 470 MB model that cannot be committed, PyTorch
for training, and a retrain on every machine. Not adopted; the frozen encoder with a trained head stays.

## Hand-written test set

`data/neural/worry_lines_human.csv` is still empty. Its per-slice results (romanized Hinglish, negations, no-worry lines,
Punjabi) will be added here once the lines are written by hand (`data/neural/README.md`).

## Full calls

Consent rate and belief top-1 accuracy with Twin-B speaking held-out lines (`--voice test`) and with the template voice,
seeds 7 and 13, are being measured; they will be added in `full-calls/`.
