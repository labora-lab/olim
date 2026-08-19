# Paper comparison benchmarks

Reproduces the structural claims of **"Mining Unstructured Medical Texts With
Conformal Active Learning"** (Genari & Goedert 2025, arXiv:2502.04372) — the paper
this framework implements — against OLIM's current code.

## Running

Needs `Reviews.csv` (Amazon Fine Food Reviews) at the repository root; the tests
skip if it is absent.

```bash
pytest tests/benchmarks                 # the assertions (slow, several minutes)
pytest tests/ -m "not slow"             # everything else, skipping these
python tests/benchmarks/report.py       # full grid + comparison table
```

## What is and is not comparable

The paper's four labels were annotated by hand and those annotations are not
published, so **absolute accuracy is not comparable**. `harness.py` substitutes
deterministic oracles of similar prevalence, and masks the keyword triggers out of
the model's input so the concepts have to be inferred from context rather than read
off a word (unmasked, TF-IDF recovers them at AUC ~0.95 and every configuration
saturates).

What *is* comparable, and what the tests assert:

| Paper claim | Where |
|---|---|
| Mixing low-uncertainty points beats high-uncertainty-only | Results, "Mix of high and low uncertainty"; AUC 0.79 → 0.95 on Pet product |
| The mix surfaces more positives (36 vs 23 per 100 labels) | same section |
| Active selection ≫ random on rare labels | Results, "Less frequent labels"; random found 1 positive in 200 |
| Active ≈ random on common labels | same section; random AUC 0.90 ± 0.10 on Pet product |
| Seeding with known positives rescues rare labels | Table 3, Damaged with 40 pre-labelled → AUC 0.88 |
