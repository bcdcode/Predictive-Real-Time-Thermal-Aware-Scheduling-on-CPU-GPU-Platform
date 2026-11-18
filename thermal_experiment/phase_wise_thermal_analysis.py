import csv
from collections import defaultdict

INPUT = "gpu_busy_model_predictions_v2.csv"

RUN_OUTPUT = "phase_wise_results_by_run.csv"
SUMMARY_OUTPUT = "phase_wise_thermal_summary.csv"

# Store absolute errors separately for each run, phase,
# prediction target and horizon.

groups = defaultdict(lambda: {
    "model_a_errors": [],
    "model_b_errors": []
})

with open(INPUT, newline="") as f:
    reader = csv.DictReader(f)

    required = {
        "heldout_run",
        "target",
        "horizon_s",
        "phase",
        "actual_temperature_C",
        "model_a_absolute_error_C",
        "model_b_absolute_error_C"
    }

    missing = required - set(reader.fieldnames or [])

    if missing:
        raise SystemExit("Missing columns: " + str(missing))

    for row in reader:
        key = (
            row["heldout_run"],
            row["phase"],
            row["target"],
            int(row["horizon_s"])
        )

        groups[key]["model_a_errors"].append(
            float(row["model_a_absolute_error_C"])
        )

        groups[key]["model_b_errors"].append(
            float(row["model_b_absolute_error_C"])
        )


# -------------------------------------------------
# RESULTS FOR EACH HELD-OUT RUN
# -------------------------------------------------

run_results = []

for key, values in sorted(groups.items()):
    run, phase, target, horizon = key

    a_errors = values["model_a_errors"]
    b_errors = values["model_b_errors"]

    mae_a = sum(a_errors) / len(a_errors)
    mae_b = sum(b_errors) / len(b_errors)

    improvement = mae_a - mae_b

    improvement_pct = (
        100 * improvement / mae_a if mae_a > 0 else 0
    )

    run_results.append({
        "heldout_run": run,
        "phase": phase,
        "target": target,
        "horizon_s": horizon,
        "samples": len(a_errors),
        "model_a_mae_C": mae_a,
        "model_b_mae_C": mae_b,
        "improvement_C": improvement,
        "improvement_percent": improvement_pct
    })


with open(RUN_OUTPUT, "w", newline="") as f:
    writer = csv.DictWriter(
        f, fieldnames=list(run_results[0].keys())
    )
    writer.writeheader()
    writer.writerows(run_results)


# -------------------------------------------------
# AGGREGATE ACROSS HELD-OUT RUNS
# -------------------------------------------------

aggregate = defaultdict(lambda: {
    "model_a_errors": [],
    "model_b_errors": [],
    "run_maes_a": [],
    "run_maes_b": [],
    "runs": set()
})

for row in run_results:
    key = (
        row["phase"],
        row["target"],
        row["horizon_s"]
    )

    item = aggregate[key]

    item["runs"].add(row["heldout_run"])
    item["run_maes_a"].append(row["model_a_mae_C"])
    item["run_maes_b"].append(row["model_b_mae_C"])

    # Recover total absolute error from each run's MAE.
    item["model_a_errors"].append(
        row["model_a_mae_C"] * row["samples"]
    )
    item["model_b_errors"].append(
        row["model_b_mae_C"] * row["samples"]
    )

    item.setdefault("sample_count", 0)
    item["sample_count"] += row["samples"]


summary = []

for key, item in sorted(aggregate.items()):
    phase, target, horizon = key

    total_samples = item["sample_count"]

    # Sample-weighted MAE across all held-out predictions.
    mae_a = sum(item["model_a_errors"]) / total_samples
    mae_b = sum(item["model_b_errors"]) / total_samples

    improvement = mae_a - mae_b

    improvement_pct = (
        100 * improvement / mae_a if mae_a > 0 else 0
    )

    # Also calculate the equal-weight mean of run-level MAEs.
    macro_a = sum(item["run_maes_a"]) / len(item["run_maes_a"])
    macro_b = sum(item["run_maes_b"]) / len(item["run_maes_b"])

    summary.append({
        "phase": phase,
        "target": target,
        "horizon_s": horizon,
        "heldout_runs": len(item["runs"]),
        "samples": total_samples,
        "model_a_mae_C": mae_a,
        "model_b_mae_C": mae_b,
        "improvement_C": improvement,
        "improvement_percent": improvement_pct,
        "mean_run_model_a_mae_C": macro_a,
        "mean_run_model_b_mae_C": macro_b
    })


with open(SUMMARY_OUTPUT, "w", newline="") as f:
    writer = csv.DictWriter(
        f, fieldnames=list(summary[0].keys())
    )
    writer.writeheader()
    writer.writerows(summary)


# -------------------------------------------------
# PRINT SUMMARY
# -------------------------------------------------

print("\n========== PHASE-WISE THERMAL ANALYSIS ==========")

print(
    "%-18s %-5s %4s %7s %10s %10s %12s" %
    (
        "PHASE", "TYPE", "SEC", "SAMPLES",
        "MODEL_A", "MODEL_B", "IMPROVEMENT"
    )
)

for r in summary:
    print(
        "%-18s %-5s %4d %7d %10.4f %10.4f %11.2f%%" %
        (
            r["phase"],
            r["target"],
            r["horizon_s"],
            r["samples"],
            r["model_a_mae_C"],
            r["model_b_mae_C"],
            r["improvement_percent"]
        )
    )

print("\nSaved files:")
print(RUN_OUTPUT)
print(SUMMARY_OUTPUT)

print("\nPHASE-WISE ANALYSIS COMPLETED")
