# Neural brain, phase 0 (N0): baselines and the encoder choice

Measured on 2026-10-30, macOS, Python 3.12. Every number here comes from a command in this folder.

## The labelled lines

```bash
python -m chanakya.neural.paraphrase --seed 7   # writes data/neural/worry_lines.jsonl (uses the LLM provider)
```

Durvish's synthetic transcripts cannot test a worry scorer: their 3,291 merchant lines are 82 distinct sentences, all from
the Concern Bank's own phrasings, which is exactly what the lexical scorer compares against. So the lines here are fresh
paraphrases in Hindi, Hinglish, Punjabi and English, for each of the 13 worries plus lines with no worry at all:

- **Train** (1,455 lines): written by `deepseek/deepseek-v4-flash`, the Twin-A model
- **Test** (668 lines): written by `openai/gpt-6-luna`, the Twin-B model, a different model family
- Lines close to a Concern Bank phrasing, or to any train line, are dropped (trigram Dice similarity of 0.85 or more)

These are simulated merchants, not real ones.

## Worry scorers on the held-out test lines

```bash
python -m chanakya.neural.baseline --seed 7 --llm-sample 112 --out docs/results/neural-baseline
```

Each scorer picks one of 14 labels per line (13 worries or no worry). The no-worry threshold is tuned on the train lines
only. Encoders are scored with a nearest-centroid classifier over train embeddings, with no trained head, so the number
reflects the embedding alone. The LLM scorer ran on a stratified sample of 112 test lines (8 per label) because each call
takes seconds; a failed or slow call (over 45 s) counts as a miss.

| Scorer | Lines | All 14 labels | Worry lines | No-worry lines | p50 ms | p90 ms |
|---|---|---|---|---|---|---|
| Lexical (today's `LexicalScorer`) | 668 | 0.388 | 0.415 | 0.022 | 0.07 | 0.08 |
| `paraphrase-multilingual-MiniLM-L12-v2` (fastembed), nearest centroid | 668 | 0.310 | 0.299 | 0.457 | 3.83 | 4.80 |
| `multilingual-e5-small` (sentence-transformers), nearest centroid | 668 | 0.437 | 0.436 | 0.457 | 5.46 | 5.99 |
| LLM (`deepseek/deepseek-v4-flash`, today's `LLMScorer`) | 112 | 0.777 | 0.788 | 0.625 | 1920 | 8640 |

| Scorer | English | Hindi | Hinglish | Punjabi |
|---|---|---|---|---|
| Lexical (today) | 0.387 | 0.388 | 0.449 | 0.327 |
| MiniLM, nearest centroid | 0.405 | 0.382 | 0.281 | 0.173 |
| e5-small, nearest centroid | 0.369 | 0.479 | 0.383 | 0.518 |
| LLM | 0.893 | 0.750 | 0.720 | 0.741 |

Full numbers: `results.json`; the generated table: `report.md`.

What this shows:

- **Today's lexical scorer gets 39% of worries right on wording it has not seen, and almost never says "no worry"**
  (2%): some small overlap with a phrasing always counts as evidence.
- **The LLM scorer is about twice as accurate but far too slow for a live turn** (about 2 s typical, 8.6 s at p90) and
  hits provider rate limits.
- **e5-small already beats the lexical scorer with no training** (0.437 vs 0.388) at about 5 ms, and is the best of the
  two encoders on Punjabi (0.52 vs 0.17 for MiniLM, which was not trained on Punjabi).

**Encoder choice: `intfloat/multilingual-e5-small`** (384 dimensions, loaded in about 9 s, cached after the first
download). It needs PyTorch through sentence-transformers, so it lives in the optional `requirements-neural.txt`; an ONNX
export could drop PyTorch later if install size matters.

**Target for N1:** a trained head on e5-small should move toward the LLM's accuracy (0.78) at encoder speed (under 10 ms).

## Planner baseline on current main

```bash
python -m chanakya.eval.harness --mode offline --merchants 100 --seed 7  --variants chanakya,chanakya_forest
python -m chanakya.eval.harness --mode offline --merchants 100 --seed 13 --variants chanakya,chanakya_forest
```

| Metric | chanakya, seed 7 | chanakya_forest, seed 7 | chanakya, seed 13 | chanakya_forest, seed 13 |
|---|---|---|---|---|
| Mission success | 0.96 | 0.96 | 0.98 | 0.98 |
| Walked away | 0.04 | 0.03 | 0.01 | 0.02 |
| Turn latency p50 (ms) | 33.7 | 34.4 | 34.1 | 34.4 |

Reports: `planner/seed7.md`, `planner/seed13.md`. The Strategy Forest still makes no difference; N2 tests whether
meaning-based embeddings change that.

**Caveat for N1:** the offline harness's template twins speak Concern Bank phrasings, which the lexical scorer matches
almost perfectly. A better worry scorer cannot show up there, so N1 needs a twin voice that speaks the held-out test lines.
