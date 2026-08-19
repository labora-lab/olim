"""Run the comparison grid and print it beside the paper's tables.

python tests/benchmarks/report.py [--rows 20000] [--seeds 2] [--quick]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Runnable as a script from anywhere: put the repo root and this folder on the path.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).parent))

from harness import load_corpus, repeat, summarise

# Genari & Goedert (2025), Tables 1 and 3 — XGBClassifier.
PAPER = {
    ("pet_product", 200, "mixed70"): ("Pet prod. (T1, 30/70)", 0.92, 0.94, "62/138"),
    ("pet_product", 100, "high_only"): ("Pet prod. (T3, high only)", 0.83, 0.79, "23/77"),
    ("pet_product", 100, "mixed50"): ("Pet prod. (T3, 50/50)", 0.80, 0.95, "27/73"),
    ("low_quality", 200, "mixed"): ("Low quality (T1, 30/70)", 0.77, 0.79, "46/154"),
    ("drinkable", 200, "mixed"): ("Drinkable (T1, 30/70)", 0.85, 0.82, "70/130"),
    ("damaged", 100, "mixed"): ("Damaged (T3, cold)", 0.97, 0.50, "2/98"),
    ("damaged", 200, "mixed"): ("Damaged (T3, cold)", 0.96, 0.75, "5/195"),
    ("damaged", 100, "seeded"): ("Damaged (T3, 40 pre-lab.)", 0.82, 0.88, "30/70"),
}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rows", type=int, default=20_000)
    ap.add_argument("--seeds", type=int, default=2)
    ap.add_argument("--quick", action="store_true", help="only the 100-label budgets")
    args = ap.parse_args()

    corpus = load_corpus(n_rows=args.rows)
    print(
        f"corpus {args.rows} reviews | prevalence: "
        + ", ".join(f"{k} {corpus.prevalence(k):.3f}" for k in sorted(corpus.labels))
    )
    print(
        f"\n{'configuration':32s} {'ours: acc':>12} {'ours: AUC':>13} {'yes/no':>9} "
        f"| {'paper acc':>9} {'paper AUC':>9} {'paper y/n':>9}"
    )
    print("-" * 106)

    budgets = [100] if args.quick else [100, 200]
    # The paper writes splits as "high/low", so its 30/70 headline means 70% LOW
    # uncertainty — certain_rate=0.7. Sweep its whole ablation on the common label.
    grid = [
        ("pet_product", "high_only", "100/0", {"certain_rate": 0.0}),
        ("pet_product", "mixed", "70/30", {"certain_rate": 0.3}),
        ("pet_product", "mixed50", "50/50", {"certain_rate": 0.5}),
        ("pet_product", "mixed70", "30/70", {"certain_rate": 0.7}),
        ("pet_product", "random", "random", {"strategy": "random"}),
        ("drinkable", "mixed", "30/70", {"certain_rate": 0.7}),
        ("low_quality", "mixed", "30/70", {"certain_rate": 0.7}),
        ("damaged", "mixed", "30/70", {"certain_rate": 0.7}),
        ("damaged", "random", "random", {"strategy": "random"}),
        (
            "damaged",
            "seeded",
            "30/70+20pos",
            {"certain_rate": 0.7, "seed_labels": 40, "seed_positives": 20},
        ),
    ]
    for budget in budgets:
        for label, variant, split_note, config in grid:
            # Copy: popping from the grid entry itself would strip seed_labels from
            # the "seeded" row on the second budget pass.
            kwargs = dict(config)
            runs = repeat(
                args.seeds,
                corpus=corpus,
                label=label,
                budget=budget,
                seed_labels=kwargs.pop("seed_labels", 20),
                **kwargs,
            )
            s = summarise(runs)
            ref = PAPER.get((label, budget, variant))
            ours = (
                f"{s['accuracy'][0]:.2f}±{s['accuracy'][1]:.2f}",
                f"{s['auc_roc'][0]:.2f}±{s['auc_roc'][1]:.2f}",
                f"{s['positives'][0]:.0f}/{budget - s['positives'][0]:.0f}",
            )
            tail = f"| {ref[1]:>9.2f} {ref[2]:>9.2f} {ref[3]:>9}" if ref else "| " + " " * 29
            name = f"{label} {split_note} @{budget}"
            print(f"{name:32s} {ours[0]:>12} {ours[1]:>13} {ours[2]:>9} {tail}")
        print()


if __name__ == "__main__":
    main()
