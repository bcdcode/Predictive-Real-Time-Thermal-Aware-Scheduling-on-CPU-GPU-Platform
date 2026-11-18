#!/usr/bin/env python3

import csv
from collections import defaultdict

INPUT = "gpu_busy_model_predictions_v5.csv"
OUTPUT = "model_be_phase_age_comparison.csv"

groups = defaultdict(lambda: {
    "b_error": [],
    "e_error": []
})


def age_bin(age):

    if age < 5:
        return "0-4s"

    elif age < 10:
        return "5-9s"

    elif age < 20:
        return "10-19s"

    elif age < 40:
        return "20-39s"

    else:
        return "40s+"


with open(INPUT, newline="") as f:

    reader = csv.DictReader(f)

    for row in reader:

        phase = row["phase"]
        target = row["target"]
        horizon = int(row["horizon_s"])

        age = float(row["phase_age_s"])

        key = (
            phase,
            target,
            horizon,
            age_bin(age)
        )

        groups[key]["b_error"].append(
            float(row["model_b_absolute_error_C"])
        )

        groups[key]["e_error"].append(
            float(row["model_e_absolute_error_C"])
        )


results = []

print("\nMODEL B vs MODEL E: PHASE-AGE ANALYSIS\n")

print(
    "{:<18} {:<7} {:<7} {:<9} {:<7} {:<10} {:<10} {:<10}".format(
        "PHASE",
        "TARGET",
        "HORIZ",
        "AGE",
        "COUNT",
        "B_MAE",
        "E_MAE",
        "CHANGE_%"
    )
)

for key in sorted(groups):

    phase, target, horizon, age_group = key

    b_errors = groups[key]["b_error"]
    e_errors = groups[key]["e_error"]

    b_mae = sum(b_errors) / len(b_errors)
    e_mae = sum(e_errors) / len(e_errors)

    improvement = (
        100.0 * (b_mae - e_mae) / b_mae
        if b_mae != 0 else 0.0
    )

    result = {

        "phase": phase,
        "target": target,
        "horizon_s": horizon,
        "age_group": age_group,
        "count": len(b_errors),

        "model_b_mae_C": b_mae,
        "model_e_mae_C": e_mae,

        "model_e_improvement_percent": improvement
    }

    results.append(result)

    print(
        "{:<18} {:<7} {:<7} {:<9} {:<7} {:<10.3f} {:<10.3f} {:<10.2f}".format(
            phase,
            target,
            str(horizon) + "s",
            age_group,
            len(b_errors),
            b_mae,
            e_mae,
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

