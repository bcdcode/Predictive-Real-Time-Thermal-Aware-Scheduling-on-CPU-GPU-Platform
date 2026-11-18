import csv
from collections import defaultdict

INPUT = "gpu_busy_model_predictions_v8.csv"
FOLD_OUTPUT = "phase_wise_ef_fold_v8.csv"
SUMMARY_OUTPUT = "phase_wise_ef_summary_v8.csv"

groups = defaultdict(lambda: {"E": [], "F": []})

with open(INPUT, newline="") as f:
    reader = csv.DictReader(f)

    required = [
        "heldout_run", "target", "horizon_s", "phase",
        "model_e_absolute_error_C",
        "model_f_absolute_error_C"
    ]

    missing = [x for x in required if x not in reader.fieldnames]
    if missing:
        raise SystemExit("Missing columns: " + str(missing))

    for r in reader:
        key = (
            r["target"],
            int(r["horizon_s"]),
            r["phase"],
            r["heldout_run"]
        )

        groups[key]["E"].append(
            float(r["model_e_absolute_error_C"])
        )
        groups[key]["F"].append(
            float(r["model_f_absolute_error_C"])
        )


def avg(values):
    return sum(values) / len(values) if values else 0.0


def gain(e, f):
    return (e - f) / e * 100.0 if e else 0.0


fold_rows = []

for (target, horizon, phase, run), values in sorted(groups.items()):
    e = avg(values["E"])
    f = avg(values["F"])

    fold_rows.append({
        "target": target,
        "horizon_s": horizon,
        "phase": phase,
        "heldout_run": run,
        "samples": len(values["E"]),
        "model_e_mae_C": e,
        "model_f_mae_C": f,
        "f_improvement_vs_e_percent": gain(e, f)
    })


with open(FOLD_OUTPUT, "w", newline="") as f:
    writer = csv.DictWriter(f, fieldnames=list(fold_rows[0].keys()))
    writer.writeheader()
    writer.writerows(fold_rows)


# Equal-fold summary, matching V7/V8 aggregation.
summary_groups = defaultdict(list)

for r in fold_rows:
    key = (r["target"], r["horizon_s"], r["phase"])
    summary_groups[key].append(r)

summary_rows = []

for (target, horizon, phase), rows in sorted(summary_groups.items()):
    e = avg([r["model_e_mae_C"] for r in rows])
    f = avg([r["model_f_mae_C"] for r in rows])

    summary_rows.append({
        "target": target,
        "horizon_s": horizon,
        "phase": phase,
        "heldout_folds": len(rows),
        "total_samples": sum(r["samples"] for r in rows),
        "model_e_mae_C": e,
        "model_f_mae_C": f,
        "f_improvement_vs_e_percent": gain(e, f),
        "f_winning_folds": sum(
            r["model_f_mae_C"] < r["model_e_mae_C"]
            for r in rows
        )
    })


with open(SUMMARY_OUTPUT, "w", newline="") as f:
    writer = csv.DictWriter(f, fieldnames=list(summary_rows[0].keys()))
    writer.writeheader()
    writer.writerows(summary_rows)


print("\n==============================================")
print("V8 MODEL E vs MODEL F PHASE-WISE ANALYSIS")
print("==============================================")

print(
    f"{'TARGET':<7} {'H':<4} {'PHASE':<17} "
    f"{'E MAE':>8} {'F MAE':>8} {'GAIN':>9} "
    f"{'FOLDS':>7} {'F WINS':>7}"
)

print("-" * 85)

for r in summary_rows:
    print(
        f"{r['target']:<7} "
        f"{r['horizon_s']:<4} "
        f"{r['phase']:<17} "
        f"{r['model_e_mae_C']:>8.4f} "
        f"{r['model_f_mae_C']:>8.4f} "
        f"{r['f_improvement_vs_e_percent']:>8.2f}% "
        f"{r['heldout_folds']:>7} "
        f"{r['f_winning_folds']:>7}"
    )

print("\nSaved:")
print(FOLD_OUTPUT)
print(SUMMARY_OUTPUT)

