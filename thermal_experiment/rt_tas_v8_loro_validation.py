#!/usr/bin/env python3

import csv
import os
import numpy as np

from sklearn.preprocessing import StandardScaler
from sklearn.linear_model import Ridge
from sklearn.pipeline import make_pipeline

DATASETS = {
    "RUN1_NOV03": "rt_tas_gpu_busy_aligned.csv",
    "RUN2_NOV05": "rt_tas_gpu_busy_20261105.csv",
    "RUN3_NOV05": "rt_tas_gpu_busy_20261105_run3.csv",
    "RUN4_NOV07": "rt_tas_gpu_busy_20261107_run4.csv",
    "RUN5_NOV07": "rt_tas_gpu_busy_20261107_run5.csv",
    "RUN6_NOV07": "rt_tas_gpu_busy_20261107_run6.csv",
}

HORIZON = 1
WINDOW = 5
ALPHA = 1.0

BASE_FEATURES = [
    "cpu_tctl_C",
    "gpu_edge_C",
    "cpu_slope_5s",
    "gpu_slope_5s",
    "gpu_freq_MHz",
    "gpu_activity_proxy",
    "cpu6_freq_MHz",
    "cpu_active_binary",
    "gpu_enabled_binary",
    "gpu_busy_percent",
]

GPU_FEATURES = BASE_FEATURES + [
    "simultaneous_start_5s",
    "cooldown1_start_5s",
    "cooldown2_start_5s",
    "idle1_start_5s",
    "idle2_start_5s",
]

CPU_FEATURES = GPU_FEATURES + [
    "ta_cpu_phase",
    "ta_gpu_phase",
]

TARGETS = {
    "CPU": ("cpu_tctl_C", CPU_FEATURES),
    "GPU": ("gpu_edge_C", GPU_FEATURES),
}


def load_dataset(filename):
    rows = []

    with open(filename, newline="") as f:
        reader = csv.DictReader(f)

        for row in reader:
            for col in [
                "elapsed_s",
                "cpu_tctl_C",
                "gpu_edge_C",
                "gpu_freq_MHz",
                "gpu_activity_proxy",
                "cpu6_freq_MHz",
                "gpu_busy_percent",
            ]:
                row[col] = float(row[col])

            row["cpu_active_binary"] = float(
                row["cpu_active"].strip().upper() == "ON"
            )

            row["gpu_enabled_binary"] = float(
                row["gpu_enabled"].strip().upper() == "ON"
            )

            rows.append(row)

    rows.sort(key=lambda r: int(r["elapsed_s"]))

    lookup = {int(r["elapsed_s"]): r for r in rows}

    if len(lookup) != len(rows):
        raise ValueError("Duplicate elapsed_s in " + filename)

    phase_start = None
    previous_phase = None

    for row in rows:
        phase = row["phase"]
        elapsed = row["elapsed_s"]

        if phase != previous_phase:
            phase_start = elapsed
            previous_phase = phase

        age = elapsed - phase_start
        is_start = age < 5

        row["simultaneous_start_5s"] = float(
            phase == "SIMULTANEOUS" and is_start
        )
        row["cooldown1_start_5s"] = float(
            phase == "COOLDOWN1" and is_start
        )
        row["cooldown2_start_5s"] = float(
            phase == "COOLDOWN2" and is_start
        )
        row["idle1_start_5s"] = float(
            phase == "IDLE_BASELINE1" and is_start
        )
        row["idle2_start_5s"] = float(
            phase == "IDLE_BASELINE2" and is_start
        )
        row["ta_cpu_phase"] = float(phase == "TA_CPU")
        row["ta_gpu_phase"] = float(phase == "TA_GPU")

    for row in rows:
        t = int(row["elapsed_s"])
        previous = lookup.get(t - WINDOW)

        if previous is None:
            row["cpu_slope_5s"] = None
            row["gpu_slope_5s"] = None
        else:
            row["cpu_slope_5s"] = (
                row["cpu_tctl_C"] - previous["cpu_tctl_C"]
            ) / WINDOW

            row["gpu_slope_5s"] = (
                row["gpu_edge_C"] - previous["gpu_edge_C"]
            ) / WINDOW

    return rows


def build_samples(rows, target, features):
    lookup = {int(r["elapsed_s"]): r for r in rows}

    X, y = [], []
    details = []

    for row in rows:
        t = int(row["elapsed_s"])

        current = lookup.get(t)
        future = lookup.get(t + HORIZON)
        previous = lookup.get(t - WINDOW)

        if current is None or future is None or previous is None:
            continue

        if current["phase"] != future["phase"]:
            continue

        values = [current[name] for name in features]

        if any(v is None for v in values):
            continue

        X.append(values)
        y.append(future[target])

        current_temp = current[target]

        if target == "cpu_tctl_C":
            slope = current["cpu_slope_5s"]
        else:
            slope = current["gpu_slope_5s"]

        details.append({
            "elapsed_s": t,
            "phase": current["phase"],
            "actual": future[target],
            "current": current_temp,
            "trend": current_temp + slope * HORIZON,
        })

    return np.asarray(X), np.asarray(y), details


def calculate_metrics(errors):
    errors = np.asarray(errors, dtype=float)

    return (
        len(errors),
        np.mean(np.abs(errors)),
        np.sqrt(np.mean(errors ** 2)),
        np.mean(errors),
    )


def main():
    datasets = {}

    print("\nV8 SIX-FOLD LEAVE-ONE-RUN-OUT VALIDATION")
    print("=" * 90)

    for run, filename in DATASETS.items():
        if not os.path.isfile(filename):
            raise SystemExit("Missing dataset: " + filename)

        datasets[run] = load_dataset(filename)

    all_predictions = []
    summary = []

    for sensor, (target, features) in TARGETS.items():

        print("\n" + "#" * 90)
        print("TARGET:", sensor)
        print("FEATURES:", len(features))
        print("#" * 90)

        for test_run in DATASETS:

            train_runs = [
                run for run in DATASETS if run != test_run
            ]

            train_X = []
            train_y = []

            for run in train_runs:
                X, y, _ = build_samples(
                    datasets[run], target, features
                )
                train_X.extend(X)
                train_y.extend(y)

            test_X, test_y, test_details = build_samples(
                datasets[test_run], target, features
            )

            if len(train_X) == 0 or len(test_X) == 0:
                print("Insufficient data:", test_run)
                continue

            model = make_pipeline(
                StandardScaler(),
                Ridge(alpha=ALPHA)
            )

            model.fit(np.asarray(train_X), np.asarray(train_y))
            predictions = model.predict(test_X)

            errors_model = predictions - test_y
            errors_persist = np.array([
                d["current"] for d in test_details
            ]) - test_y

            errors_trend = np.array([
                d["trend"] for d in test_details
            ]) - test_y

            methods = {
                "V8_RIDGE": errors_model,
                "PERSISTENCE": errors_persist,
                "LINEAR_TREND": errors_trend,
            }

            print("\nHeld-out run:", test_run)
            print("Training runs:", len(train_runs))
            print("Training samples:", len(train_X))
            print("Test samples:", len(test_X))

            for method, errors in methods.items():
                n, mae, rmse, bias = calculate_metrics(errors)

                print(
                    f"{method:15s} N={n:3d} "
                    f"MAE={mae:.4f} "
                    f"RMSE={rmse:.4f} "
                    f"BIAS={bias:+.4f}"
                )

                summary.append({
                    "sensor": sensor,
                    "test_run": test_run,
                    "method": method,
                    "samples": n,
                    "mae": mae,
                    "rmse": rmse,
                    "bias": bias,
                })

            for detail, prediction in zip(
                test_details, predictions
            ):
                all_predictions.append({
                    "sensor": sensor,
                    "test_run": test_run,
                    "elapsed_s": detail["elapsed_s"],
                    "phase": detail["phase"],
                    "actual": detail["actual"],
                    "predicted": float(prediction),
                    "current": detail["current"],
                    "trend": detail["trend"],
                })

    with open(
        "rt_tas_v8_loro_summary.csv", "w", newline=""
    ) as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "sensor", "test_run", "method",
                "samples", "mae", "rmse", "bias"
            ],
        )
        writer.writeheader()
        writer.writerows(summary)

    with open(
        "rt_tas_v8_loro_predictions.csv", "w", newline=""
    ) as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "sensor", "test_run", "elapsed_s", "phase",
                "actual", "predicted", "current", "trend"
            ],
        )
        writer.writeheader()
        writer.writerows(all_predictions)

    print("\n" + "=" * 90)
    print("VALIDATION COMPLETED")
    print("Summary: rt_tas_v8_loro_summary.csv")
    print("Predictions: rt_tas_v8_loro_predictions.csv")
    print("Original V8 models were not modified.")


if __name__ == "__main__":
    main()
