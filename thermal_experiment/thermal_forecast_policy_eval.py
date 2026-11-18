#!/usr/bin/env python3

import csv
import os

INPUT = "thermal_shadow_forecasts_20261026.csv"
OUTPUT = "thermal_forecast_policy_results_20261026.csv"

THRESHOLDS = [0.25, 0.50, 1.00]
HORIZONS = [1, 5, 10]


def number(row, column):
    try:
        value = row.get(column, "")
        if value == "":
            return None
        return float(value)
    except (ValueError, TypeError):
        return None


def main():
    if not os.path.exists(INPUT):
        print("ERROR: Input CSV not found:", INPUT)
        print("Run thermal_shadow_forecast_eval.py first.")
        return

    results = []

    with open(INPUT, "r", newline="") as f:
        reader = csv.DictReader(f)

        required = [
            "sensor",
            "horizon_s",
            "phase",
            "elapsed_s",
            "target_elapsed_s",
            "actual_now_C",
            "selected_pred_C",
            "actual_future_C",
        ]

        missing = [c for c in required if c not in (reader.fieldnames or [])]
        if missing:
            print("ERROR: Missing CSV columns:", ", ".join(missing))
            return

        for row in reader:
            try:
                sensor = row["sensor"]
                horizon = int(float(row["horizon_s"]))
            except (ValueError, TypeError):
                continue

            if sensor not in ("CPU", "GPU") or horizon not in HORIZONS:
                continue

            now = number(row, "actual_now_C")
            predicted = number(row, "selected_pred_C")
            future = number(row, "actual_future_C")

            if now is None or predicted is None or future is None:
                continue

            predicted_rise = predicted - now
            actual_rise = future - now

            for threshold in THRESHOLDS:
                alert = predicted_rise >= threshold
                event = actual_rise >= threshold

                if alert and event:
                    outcome = "TP"
                elif alert and not event:
                    outcome = "FP"
                elif not alert and event:
                    outcome = "FN"
                else:
                    outcome = "TN"

                results.append({
                    "sensor": sensor,
                    "horizon_s": horizon,
                    "phase": row["phase"],
                    "elapsed_s": row["elapsed_s"],
                    "target_elapsed_s": row["target_elapsed_s"],
                    "predicted_rise_C": round(predicted_rise, 4),
                    "actual_rise_C": round(actual_rise, 4),
                    "threshold_C": threshold,
                    "forecast_alert": "YES" if alert else "NO",
                    "actual_rise_event": "YES" if event else "NO",
                    "outcome": outcome,
                    "applied": "NO",
                })

    if not results:
        print("ERROR: No usable forecast rows were found.")
        return

    columns = [
        "sensor", "horizon_s", "phase", "elapsed_s",
        "target_elapsed_s", "predicted_rise_C", "actual_rise_C",
        "threshold_C", "forecast_alert", "actual_rise_event",
        "outcome", "applied",
    ]

    with open(OUTPUT, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=columns)
        writer.writeheader()
        writer.writerows(results)

    print("Forecast-based policy evaluation")
    print("Input:", INPUT)
    print("Output:", OUTPUT)
    print("All actions are hypothetical. No scheduling action was applied.")
    print()

    print(
        "{:<6} {:>7} {:>10} {:>6} {:>7} {:>5} {:>5} {:>5} {:>5} {:>9} {:>8}".format(
            "Sensor", "Horizon", "Threshold", "Total",
            "Alerts", "TP", "FP", "FN", "TN", "Precision", "Recall"
        )
    )

    for sensor in ("CPU", "GPU"):
        for horizon in HORIZONS:
            for threshold in THRESHOLDS:
                subset = [
                    r for r in results
                    if r["sensor"] == sensor
                    and r["horizon_s"] == horizon
                    and r["threshold_C"] == threshold
                ]

                tp = sum(r["outcome"] == "TP" for r in subset)
                fp = sum(r["outcome"] == "FP" for r in subset)
                fn = sum(r["outcome"] == "FN" for r in subset)
                tn = sum(r["outcome"] == "TN" for r in subset)

                alerts = tp + fp
                events = tp + fn

                precision = tp / alerts if alerts else 0.0
                recall = tp / events if events else 0.0

                print(
                    "{:<6} {:>6}s {:>9.2f}C {:>6} {:>7} {:>5} {:>5} {:>5} {:>5} {:>9.3f} {:>8.3f}".format(
                        sensor, horizon, threshold, len(subset),
                        alerts, tp, fp, fn, tn, precision, recall
                    )
                )

    print()
    print("Finished successfully.")
    print("CSV saved as:", OUTPUT)
    print("Thresholds are exploratory temperature-rise criteria,")
    print("not hardware safety limits.")


if __name__ == "__main__":
    main()
