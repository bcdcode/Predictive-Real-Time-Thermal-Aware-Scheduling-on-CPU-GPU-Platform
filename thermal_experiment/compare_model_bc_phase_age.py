#!/usr/bin/env python3

import csv
from collections import defaultdict

INPUT = "gpu_busy_model_predictions_v3.csv"

AGE_BINS = [
    (0, 4, "0-4s"),
    (5, 9, "5-9s"),
    (10, 19, "10-19s"),
    (20, 39, "20-39s"),
    (40, 999999, "40s+")
]


def get_age_bin(age):

    for low, high, label in AGE_BINS:
        if low <= age <= high:
            return label

    return "OTHER"


groups = defaultdict(list)

with open(INPUT, newline="") as f:

    for row in csv.DictReader(f):

        phase = row["phase"]
        target = row["target"]
        horizon = int(row["horizon_s"])

        age = float(row["phase_age_s"])
        age_group = get_age_bin(age)

        error_b = float(
            row["model_b_absolute_error_C"]
        )

        error_c = float(
            row["model_c_absolute_error_C"]
        )

        groups[
            (phase, target, horizon, age_group)
        ].append((error_b, error_c))


results = []

print("\nMODEL B vs MODEL C: PHASE-AGE ANALYSIS")

print(
    "\n{:<17} {:<6} {:<5} {:<8} "
    "{:<7} {:<9} {:<9} {:<10}".format(
        "PHASE", "TARGET", "HORIZ", "AGE",
        "COUNT", "B_MAE", "C_MAE", "CHANGE_%"
    )
)

for key in sorted(groups):

    phase, target, horizon, age = key

    values = groups[key]

    b_mae = sum(x[0] for x in values) / len(values)
    c_mae = sum(x[1] for x in values) / len(values)

    improvement = (
        100.0 * (b_mae - c_mae) / b_mae
        if b_mae else 0.0
    )

    print(
        "{:<17} {:<6} {:<5} {:<8} "
        "{:<7} {:<9.3f} {:<9.3f} {:<10.2f}".format(
            phase,
            target,
            str(horizon) + "s",
            age,
            len(values),
            b_mae,
            c_mae,
            improvement
        )
    )

    results.append({
        "phase": phase,
        "target": target,
        "horizon_s": horizon,
        "phase_age_bin": age,
        "samples": len(values),
        "model_b_mae_C": b_mae,
        "model_c_mae_C": c_mae,
        "model_c_improvement_percent": improvement
    })


OUTPUT = "model_bc_phase_age_comparison.csv"

with open(OUTPUT, "w", newline="") as f:

    writer = csv.DictWriter(
        f,
        fieldnames=list(results[0].keys())
    )

    writer.writeheader()
    writer.writerows(results)

print("\nSaved:", OUTPUT)

