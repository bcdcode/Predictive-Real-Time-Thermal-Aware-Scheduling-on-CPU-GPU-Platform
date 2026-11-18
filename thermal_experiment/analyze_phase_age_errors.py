#!/usr/bin/env python3

import csv
from collections import defaultdict

PREDICTION_FILE = "gpu_busy_model_predictions_v2.csv"

DATASETS = {
    "RUN1_NOV03": "rt_tas_gpu_busy_aligned.csv",
    "RUN2_NOV05": "rt_tas_gpu_busy_20261105.csv",
    "RUN3_NOV05": "rt_tas_gpu_busy_20261105_run3.csv"
}

AGE_BINS = [
    (0, 4, "0-4s"),
    (5, 9, "5-9s"),
    (10, 19, "10-19s"),
    (20, 39, "20-39s"),
    (40, 999999, "40s+")
]


def load_dataset(filename):

    data = {}

    with open(filename, newline="") as f:
        for row in csv.DictReader(f):
            elapsed = int(float(row["elapsed_s"]))

            data[row["timestamp"]] = {
                "elapsed": elapsed,
                "phase": row["phase"],
                "cpu": float(row["cpu_tctl_C"]),
                "gpu": float(row["gpu_edge_C"])
            }

    return data


def calculate_phase_ages(data):

    ordered = sorted(
        data.items(),
        key=lambda item: item[1]["elapsed"]
    )

    phase_start = {}
    result = {}

    for timestamp, row in ordered:

        phase = row["phase"]

        if phase not in phase_start:
            phase_start[phase] = row["elapsed"]

        # Reset when phase changes, including repeated phases.
        previous_phase = None

        if result:
            previous_phase = next(reversed(result.values()))["phase"]

        if previous_phase != phase:
            phase_start[phase] = row["elapsed"]

        result[timestamp] = {
            **row,
            "phase_age": row["elapsed"] - phase_start[phase]
        }

    return result


def age_bin(age):

    for lower, upper, label in AGE_BINS:
        if lower <= age <= upper:
            return label

    return "OTHER"


def main():

    datasets = {}

    print("\nLOADING EXPERIMENTAL RUNS")

    for run, filename in DATASETS.items():

        datasets[run] = calculate_phase_ages(
            load_dataset(filename)
        )

        print(run, "loaded:", len(datasets[run]))

    groups = defaultdict(list)
    missing = 0

    with open(PREDICTION_FILE, newline="") as f:

        for row in csv.DictReader(f):

            run = row["heldout_run"]
            timestamp = row["timestamp"]

            current = datasets[run].get(timestamp)

            if current is None:
                missing += 1
                continue

            sensor = row["target"].lower()
            horizon = int(row["horizon_s"])

            predicted = float(row["model_b_prediction_C"])
            actual = float(row["actual_temperature_C"])

            current_temp = current[sensor]

            prediction_error = predicted - actual

            record = {
                "error": prediction_error,
                "absolute_error": abs(prediction_error),
                "predicted_delta": predicted - current_temp,
                "actual_delta": actual - current_temp
            }

            key = (
                current["phase"],
                sensor.upper(),
                horizon,
                age_bin(current["phase_age"])
            )

            groups[key].append(record)

    print("\nPHASE-AGE PREDICTION ERROR ANALYSIS")
    print("Negative bias = model underpredicts temperature")
    print("Positive bias = model overpredicts temperature")

    header = (
        "{:<16} {:<6} {:<5} {:<8} "
        "{:<7} {:<9} {:<11} {:<11}"
    )

    print("\n" + header.format(
        "PHASE", "SENSOR", "HORIZ", "AGE",
        "COUNT", "MAE", "BIAS", "ACTUAL_DT"
    ))

    output = []

    for key in sorted(groups):

        phase, sensor, horizon, age = key
        records = groups[key]

        n = len(records)

        mae = sum(
            r["absolute_error"] for r in records
        ) / n

        bias = sum(
            r["error"] for r in records
        ) / n

        predicted_delta = sum(
            r["predicted_delta"] for r in records
        ) / n

        actual_delta = sum(
            r["actual_delta"] for r in records
        ) / n

        print(header.format(
            phase,
            sensor,
            str(horizon) + "s",
            age,
            n,
            "%.3f" % mae,
            "%.3f" % bias,
            "%.3f" % actual_delta
        ))

        output.append({
            "phase": phase,
            "sensor": sensor,
            "horizon_s": horizon,
            "phase_age_bin": age,
            "samples": n,
            "mae_C": mae,
            "bias_C": bias,
            "avg_predicted_delta_C": predicted_delta,
            "avg_actual_delta_C": actual_delta
        })

    if output:

        filename = "phase_age_error_analysis.csv"

        with open(filename, "w", newline="") as f:

            writer = csv.DictWriter(
                f,
                fieldnames=list(output[0].keys())
            )

            writer.writeheader()
            writer.writerows(output)

        print("\nSaved:", filename)

    print("Missing timestamp matches:", missing)


if __name__ == "__main__":
    main()

