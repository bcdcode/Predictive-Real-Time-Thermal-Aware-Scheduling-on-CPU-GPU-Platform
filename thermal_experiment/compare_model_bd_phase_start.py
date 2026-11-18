#!/usr/bin/env python3

import csv
from collections import defaultdict

INPUT = "gpu_busy_model_predictions_v4.csv"
OUTPUT = "model_bd_phase_start_comparison.csv"

groups = defaultdict(lambda: {
    "b_error": [],
    "d_error": []
})

with open(INPUT, newline="") as f:

    reader = csv.DictReader(f)

    for row in reader:

        phase = row["phase"]
        target = row["target"]
        horizon = int(row["horizon_s"])

        # Group by whether the sample is in the first
        # five seconds of its current phase.
        phase_start = int(float(row["phase_start_5s"]))

        age_group = (
            "START_0_4S"
            if phase_start == 1
            else "AFTER_5S"
        )

        key = (phase, target, horizon, age_group)

        groups[key]["b_error"].append(
            float(row["model_b_absolute_error_C"])
        )

        groups[key]["d_error"].append(
            float(row["model_d_absolute_error_C"])
        )


results = []

print("\nMODEL B vs MODEL D: PHASE-START ANALYSIS\n")

print(
    "{:<18} {:<7} {:<7} {:<12} {:<7} {:<10} {:<10} {:<10}".format(
        "PHASE",
        "TARGET",
        "HORIZ",
        "AGE_GROUP",
        "COUNT",
        "B_MAE",
        "D_MAE",
        "CHANGE_%"
    )
)

for key in sorted(groups):

    phase, target, horizon, age_group = key

    b_errors = groups[key]["b_error"]
    d_errors = groups[key]["d_error"]

    b_mae = sum(b_errors) / len(b_errors)
    d_mae = sum(d_errors) / len(d_errors)

    improvement = (
        100.0 * (b_mae - d_mae) / b_mae
        if b_mae != 0 else 0.0
    )

    result = {
        "phase": phase,
        "target": target,
        "horizon_s": horizon,
        "age_group": age_group,
        "count": len(b_errors),
        "model_b_mae_C": b_mae,
        "model_d_mae_C": d_mae,
        "model_d_improvement_percent": improvement
    }

    results.append(result)

    print(
        "{:<18} {:<7} {:<7} {:<12} {:<7} {:<10.3f} {:<10.3f} {:<10.2f}".format(
            phase,
            target,
            str(horizon) + "s",
            age_group,
            len(b_errors),
            b_mae,
            d_mae,
            improvement
        )
    )


with open(OUTPUT, "w", newline="") as f:

    writer = csv.DictWriter(
        f,
        fieldnames=list(results[0].keys())
    )

    writer.writeheader()
    writer.writerows(results)

print("\nSaved:", OUTPUT)

