#!/usr/bin/env python3

import csv
import glob

decision_file = sorted(
    glob.glob("rt_tas_predictive_decisions_replay_*.csv")
)[-1]

prediction_file = "gpu_busy_model_predictions_v2.csv"

# Load actual future temperatures and prediction errors.
actual_lookup = {}

with open(prediction_file, newline="") as f:
    for row in csv.DictReader(f):

        key = (
            row["heldout_run"],
            row["timestamp"],
            row["target"],
            int(row["horizon_s"])
        )

        actual_lookup[key] = {
            "actual": float(row["actual_temperature_C"]),
            "prediction": float(row["model_b_prediction_C"]),
            "error": float(row["model_b_absolute_error_C"])
        }

records = []

with open(decision_file, newline="") as f:
    for row in csv.DictReader(f):

        for sensor in ("cpu", "gpu"):

            current = float(row[sensor + "_current_C"])

            for horizon in (5, 10):

                column = sensor + "_pred_" + str(horizon) + "s_C"

                if row[column] == "":
                    continue

                predicted = float(row[column])

                key = (
                    row["heldout_run"],
                    row["timestamp"],
                    sensor.upper(),
                    horizon
                )

                result = actual_lookup.get(key)

                if result is None:
                    continue

                records.append({
                    "run": row["heldout_run"],
                    "phase": row["phase"],
                    "timestamp": row["timestamp"],
                    "sensor": sensor.upper(),
                    "horizon": horizon,
                    "current": current,
                    "predicted": predicted,
                    "delta": predicted - current,
                    "actual": result["actual"],
                    "error": result["error"]
                })

records.sort(
    key=lambda r: r["delta"],
    reverse=True
)

print("\nLARGEST PREDICTED TEMPERATURE INCREASES")

for r in records[:15]:

    print(
        "\nRun:", r["run"],
        "| Phase:", r["phase"],
        "| Sensor:", r["sensor"],
        "| Horizon:", r["horizon"], "s"
    )

    print("Timestamp:", r["timestamp"])
    print("Current: %.3f C" % r["current"])
    print("Predicted: %.3f C" % r["predicted"])
    print("Predicted increase: %.3f C" % r["delta"])
    print("Actual future temperature: %.3f C" % r["actual"])
    print("Absolute prediction error: %.3f C" % r["error"])

