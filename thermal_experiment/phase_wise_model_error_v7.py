import csv
from collections import defaultdict

INPUT_FILE = "gpu_busy_model_predictions_v7.csv"

FOLD_OUTPUT = "phase_wise_fold_results_v7.csv"
SUMMARY_OUTPUT = "phase_wise_summary_v7.csv"

# Store absolute errors grouped by:
# target, horizon, phase, held-out run
groups = defaultdict(lambda: {
    "B": [],
    "D": [],
    "E": []
})

with open(INPUT_FILE, newline="") as f:
    reader = csv.DictReader(f)

    required = [
        "heldout_run",
        "target",
        "horizon_s",
        "phase",
        "model_b_absolute_error_C",
        "model_d_absolute_error_C",
        "model_e_absolute_error_C"
    ]

    missing = [c for c in required if c not in reader.fieldnames]

    if missing:
        raise SystemExit("Missing columns: " + str(missing))

    for row in reader:
        key = (
            row["target"],
            int(row["horizon_s"]),
            row["phase"],
            row["heldout_run"]
        )

        groups[key]["B"].append(
            float(row["model_b_absolute_error_C"])
        )
        groups[key]["D"].append(
            float(row["model_d_absolute_error_C"])
        )
        groups[key]["E"].append(
            float(row["model_e_absolute_error_C"])
        )


def mean(values):
    return sum(values) / len(values) if values else 0.0


def improvement(baseline, candidate):
    if baseline == 0:
        return 0.0
    return (baseline - candidate) / baseline * 100.0


fold_rows = []

for key, errors in sorted(groups.items()):
    target, horizon, phase, run = key

    b = mean(errors["B"])
    d = mean(errors["D"])
    e = mean(errors["E"])

    fold_rows.append({
        "target": target,
        "horizon_s": horizon,
        "phase": phase,
        "heldout_run": run,
        "samples": len(errors["B"]),
        "model_b_mae_C": b,
        "model_d_mae_C": d,
        "model_e_mae_C": e,
        "d_improvement_vs_b_percent": improvement(b, d),
        "e_improvement_vs_b_percent": improvement(b, e)
    })


# Save held-out-run-level results.
fold_fields = [
    "target",
    "horizon_s",
    "phase",
    "heldout_run",
    "samples",
    "model_b_mae_C",
    "model_d_mae_C",
    "model_e_mae_C",
    "d_improvement_vs_b_percent",
    "e_improvement_vs_b_percent"
]

with open(FOLD_OUTPUT, "w", newline="") as f:
    writer = csv.DictWriter(f, fieldnames=fold_fields)
    writer.writeheader()
    writer.writerows(fold_rows)


# Aggregate by target, horizon and phase.
# Each held-out run receives equal weight, matching
# the equal-fold aggregation used in V7.
summary_groups = defaultdict(list)

for row in fold_rows:
    key = (
        row["target"],
        row["horizon_s"],
        row["phase"]
    )
    summary_groups[key].append(row)


summary_rows = []

for key, rows in sorted(summary_groups.items()):
    target, horizon, phase = key

    b = mean([r["model_b_mae_C"] for r in rows])
    d = mean([r["model_d_mae_C"] for r in rows])
    e = mean([r["model_e_mae_C"] for r in rows])

    summary_rows.append({
        "target": target,
        "horizon_s": horizon,
        "phase": phase,
        "heldout_folds": len(rows),
        "total_samples": sum(r["samples"] for r in rows),
        "model_b_mae_C": b,
        "model_d_mae_C": d,
        "model_e_mae_C": e,
        "d_improvement_vs_b_percent": improvement(b, d),
        "e_improvement_vs_b_percent": improvement(b, e),
        "model_e_winning_folds": sum(
            r["model_e_mae_C"] < r["model_b_mae_C"]
            for r in rows
        )
    })


summary_fields = [
    "target",
    "horizon_s",
    "phase",
    "heldout_folds",
    "total_samples",
    "model_b_mae_C",
    "model_d_mae_C",
    "model_e_mae_C",
    "d_improvement_vs_b_percent",
    "e_improvement_vs_b_percent",
    "model_e_winning_folds"
]

with open(SUMMARY_OUTPUT, "w", newline="") as f:
    writer = csv.DictWriter(f, fieldnames=summary_fields)
    writer.writeheader()
    writer.writerows(summary_rows)


# Print a readable summary.
print("\n==============================================")
print("V7 PHASE-WISE MODEL ERROR ANALYSIS")
print("==============================================")

print(
    f"{'TARGET':<7} {'H':<4} {'PHASE':<17} "
    f"{'B MAE':>8} {'E MAE':>8} {'GAIN %':>9} "
    f"{'FOLDS':>7} {'E WINS':>7}"
)

print("-" * 85)

for r in summary_rows:
    print(
        f"{r['target']:<7} "
        f"{r['horizon_s']:<4} "
        f"{r['phase']:<17} "
        f"{r['model_b_mae_C']:>8.4f} "
        f"{r['model_e_mae_C']:>8.4f} "
        f"{r['e_improvement_vs_b_percent']:>8.2f}% "
        f"{r['heldout_folds']:>7} "
        f"{r['model_e_winning_folds']:>7}"
    )

print("\n==============================================")
print("ANALYSIS COMPLETED")
print("==============================================")

print("\nGenerated files:")
print("1.", FOLD_OUTPUT)
print("2.", SUMMARY_OUTPUT)

