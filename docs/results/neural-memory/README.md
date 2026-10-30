# Semantic memory (N2): results

Not measured yet. Building the memory and the win-rate comparison need the e5 encoder, which is downloaded from
`huggingface.co`. Run them where that host is reachable:

```bash
pip install -r requirements-neural.txt
python -m chanakya.neural.encoder --download
python -m chanakya.brain.memory.build --seed 11
python -m chanakya.eval.harness --mode offline --merchants 100 --seed 7  --voice test --variants chanakya,chanakya_forest,chanakya_memory --out docs/results/neural-memory/seed7
python -m chanakya.eval.harness --mode offline --merchants 100 --seed 13 --voice test --variants chanakya,chanakya_forest,chanakya_memory --out docs/results/neural-memory/seed13
```

`build.md` will record the conversations, the number of remembered moments and the lookup p50 and p90.
