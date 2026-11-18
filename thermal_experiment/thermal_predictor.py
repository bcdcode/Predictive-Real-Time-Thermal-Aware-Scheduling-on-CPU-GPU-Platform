#!/usr/bin/env python3

import csv
import math
import os

FILES = [
    "rt_tas_controlled_20261014_011135.csv",
    "rt_tas_controlled_20261011_172905.csv",
]

HORIZONS = [1, 5, 10]
WINDOW = 5

def read_data(filename):
    rows = []
    with open(filename, "r") as f:
        reader = csv.DictReader(f)
        required = [
            "elapsed_s", "cpu_tctl_C", "gpu_edge_C"
        ]
        missing = [c for c in required if c not in (reader.fieldnames or [])]
        if missing:
            raise ValueError("Missing columns: " + str(missing))

        for row in reader:
            try:
                rows.append({
                    "elapsed": float(row["elapsed_s"]),
                    "cpu": float(row["cpu_tctl_C"]),
                    "gpu": float(row["gpu_edge_C"]),
                    "phase": row.get("phase", "")
                })
            except (ValueError, TypeError):
                continue
    return rows

def predict_trend(rows, i, target, window):
    # Linear temperature trend from the preceding samples,
    # including the current measurement.
    start = max(0, i - window + 1)
    history = rows[start:i + 1]

    if len(history) < 2:
        return rows[i][target]

    times = [r["elapsed"] for r in history]
    temps = [r[target] for r in history]

    mean_t = sum(times) / len(times)
    mean_y = sum(temps) / len(temps)

    denominator = sum((t - mean_t) ** 2 for t in times)
    if denominator == 0:
        return rows[i][target]

    slope = sum(
        (t - mean_t) * (y - mean_y)
        for t, y in zip(times, temps)
    ) / denominator

    horizon = rows[i + 1]["elapsed"] - rows[i]["elapsed"]
    return rows[i][target] + slope * horizon

def metrics(errors):
    if not errors:
        return None, None
    mae = sum(abs(e) for e in errors) / len(errors)
    rmse = math.sqrt(sum(e * e for e in errors) / len(errors))
    return mae, rmse

def main():
    all_predictions = []
    print("\nTHERMAL PREDICTION BASELINE")
    print("Persistence = future temperature equals current temperature")
    print("Trend = linear extrapolation from previous samples")
    print("Errors are in degrees Celsius.\n")

    for filename in FILES:
        if not os.path.isfile(filename):
            print("SKIP: file not found:", filename)
            continue

        rows = read_data(filename)
        print("Dataset:", filename, "| samples:", len(rows))

        if len(rows) < WINDOW + max(HORIZONS):
            print("Not enough samples; skipping.")
            continue

        for horizon in HORIZONS:
            for target in ("cpu", "gpu"):
                persistence_errors = []
                trend_errors = []

                for i in range(WINDOW - 1, len(rows) - horizon):
                    j = i + horizon

                    # Do not score across a phase transition.
                    # This evaluates prediction within a stable phase.
                    if rows[i]["phase"] != rows[j]["phase"]:
                        continue

                    actual = rows[j][target]
                    persistence = rows[i][target]

                    # Fit the trend using only measurements available
                    # at prediction time; forecast the actual time gap.
                    start = max(0, i - WINDOW + 1)
                    history = rows[start:i + 1]
                    times = [r["elapsed"] for r in history]
                    temps = [r[target] for r in history]
                    mt = sum(times) / len(times)
                    my = sum(temps) / len(temps)
                    den = sum((t - mt) ** 2 for t in times)

                    if den:
                        slope = sum(
                            (t - mt) * (y - my)
                            for t, y in zip(times, temps)
                        ) / den
                    else:
                        slope = 0.0

                    dt = rows[j]["elapsed"] - rows[i]["elapsed"]
                    trend = rows[i][target] + slope * dt

                    persistence_errors.append(persistence - actual)
                    trend_errors.append(trend - actual)

                    all_predictions.append({
                        "dataset": filename,
                        "start_elapsed_s": rows[i]["elapsed"],
                        "target_elapsed_s": rows[j]["elapsed"],
                        "horizon_s": horizon,
                        "phase": rows[i]["phase"],
                        "sensor": target,
                        "actual_C": actual,
                        "persistence_prediction_C": persistence,
                        "trend_prediction_C": trend,
                        "persistence_error_C": persistence - actual,
                        "trend_error_C": trend - actual
                    })

                p_mae, p_rmse = metrics(persistence_errors)
                t_mae, t_rmse = metrics(trend_errors)

                if p_mae is None:
                    print("  ", target, horizon, "s: no eligible samples")
                    continue

                print(
                    "  {0:3s} {1:2d}s | n={2:3d} | "
                    "persistence MAE={3:.3f} RMSE={4:.3f} | "
                    "trend MAE={5:.3f} RMSE={6:.3f}".format(
                        target.upper(), horizon,
                        len(persistence_errors),
                        p_mae, p_rmse, t_mae, t_rmse
                    )
                )
        print()

    if all_predictions:
        out = "thermal_predictions_baseline.csv"
        with open(out, "w", newline="") as f:
            fields = list(all_predictions[0].keys())
            writer = csv.DictWriter(f, fieldnames=fields)
            writer.writeheader()
            writer.writerows(all_predictions)
        print("Saved individual predictions to:", out)
    else:
        print("No predictions produced. Check the CSV files and columns.")

if __name__ == "__main__":
    main()
