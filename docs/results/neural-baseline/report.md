# Neural worry scorer: phase-0 baselines

Held-out test lines from `openai/gpt-6-luna`; train lines from `deepseek/deepseek-v4-flash`. Command: `python -m chanakya.neural.baseline --seed 7 --llm-sample 112`.

| Scorer | Lines | All 14 labels | Worry lines | No-worry lines | p50 ms | p90 ms |
|---|---|---|---|---|---|---|
| lexical (today) | 668 | 0.388 | 0.415 | 0.022 | 0.07 | 0.08 |
| fastembed:paraphrase-multilingual-MiniLM-L12-v2 (nearest centroid) | 668 | 0.31 | 0.299 | 0.457 | 3.83 | 4.8 |
| st:multilingual-e5-small (nearest centroid) | 668 | 0.437 | 0.436 | 0.457 | 5.46 | 5.99 |
| LLM (deepseek/deepseek-v4-flash) | 112 | 0.777 | 0.788 | 0.625 | 1920.42 | 8639.52 |

| Scorer | english | hindi | hinglish | punjabi |
|---|---|---|---|---|
| lexical (today) | 0.387 | 0.388 | 0.449 | 0.327 |
| fastembed:paraphrase-multilingual-MiniLM-L12-v2 (nearest centroid) | 0.405 | 0.382 | 0.281 | 0.173 |
| st:multilingual-e5-small (nearest centroid) | 0.369 | 0.479 | 0.383 | 0.518 |
| LLM (deepseek/deepseek-v4-flash) | 0.893 | 0.75 | 0.72 | 0.741 |
