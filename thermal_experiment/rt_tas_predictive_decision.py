#!/usr/bin/env python3

import csv
import os
from collections import defaultdict
from datetime import datetime

# ============================================================
# CONFIGURATION
# ============================================================

PREDICTION_FILE = "gpu_busy_model_predictions_v2.csv"

DATASETS = {
    "RUN1_NOV03": "rt_tas_gpu_busy_aligned.csv",
    "RUN2_NOV05": "rt_tas_gpu_busy_20261105.csv",
    "RUN3_NOV05": "rt_tas_gpu_busy_20261105_run3.csv"
}

HORIZONS = [1, 5, 10]

# Leave these unset until experimentally validated.
# Example only: CPU_LIMIT_C = 80.0
CPU_LIMIT_C = None
GPU_LIMIT_C = None

# Provisional warning margin. This is configurable,
# not a validated hardware safety threshold.
WARNING_MARGIN_C = 2.0

# Output is timestamped to avoid overwriting earlier results.
OUTPUT_FILE = (
    "rt_tas_predictive_decisions_replay_"
    + datetime.now().strftime("%Y%m%d_%H%M%S")
    + ".csv"
)


# ============================================================
# DATA LOADING
# ============================================================

def load_current_data(filename):

    data = {}

    with open(filename, newline="") as f:
        reader = csv.DictReader(f)

        required = [
            "timestamp",
            "phase",
            "cpu_tctl_C",
            "gpu_edge_C",
            "gpu_busy_percent"
        ]

        missing = [
            col for col in required
            if col not in (reader.fieldnames or [])
        ]

        if missing:
            raise ValueError(
                "Missing columns in " + filename + ": "
                + str(missing)
            )

        for row in reader:
            timestamp = row["timestamp"]

            data[timestamp] = {
                "phase": row["phase"],
                "cpu_current": float(row["cpu_tctl_C"]),
                "gpu_current": float(row["gpu_edge_C"]),
                "gpu_busy": float(row["gpu_busy_percent"])
            }

    return data


def load_predictions(filename):

    predictions = defaultdict(dict)

    with open(filename, newline="") as f:
        reader = csv.DictReader(f)

        required = [
            "heldout_run",
            "target",
            "horizon_s",
            "timestamp",
            "phase",
            "gpu_busy_percent",
            "model_b_prediction_C"
        ]

        missing = [
            col for col in required
            if col not in (reader.fieldnames or [])
        ]

        if missing:
            raise ValueError(
                "Missing prediction columns: " + str(missing)
            )

        for row in reader:

            run = row["heldout_run"]
            timestamp = row["timestamp"]
            target = row["target"].upper()
            horizon = int(row["horizon_s"])

            if run not in DATASETS:
                continue

            if target not in ("CPU", "GPU"):
                continue

            if horizon not in HORIZONS:
                continue

            key = (run, timestamp)

            predictions[key][
                (target, horizon)
            ] = float(row["model_b_prediction_C"])

    return predictions


# ============================================================
# RISK ASSESSMENT
# ============================================================

def assess_sensor_risk(
    current,
    forecasts,
    thermal_limit
):

    if thermal_limit is None:
        return "UNCONFIGURED"

    if not forecasts:
        return "UNKNOWN"

    predicted_values = list(forecasts.values())

    if any(value >= thermal_limit for value in predicted_values):
        return "HIGH"

    if any(
        value >= thermal_limit - WARNING_MARGIN_C
        for value in predicted_values
    ):
        return "MODERATE"

    return "LOW"


def combine_risks(cpu_risk, gpu_risk):

    risks = [cpu_risk, gpu_risk]

    if "UNKNOWN" in risks:
        return "UNKNOWN"

    if "UNCONFIGURED" in risks:
        return "UNCONFIGURED"

    if "HIGH" in risks:
        return "HIGH"

    if "MODERATE" in risks:
        return "MODERATE"

    return "LOW"


def recommend_action(risk):

    if risk == "HIGH":
        return "SHADOW_REDUCE_CONCURRENT_WORKLOAD"

    if risk == "MODERATE":
        return "SHADOW_MONITOR"

    if risk == "LOW":
        return "SHADOW_CONTINUE"

    if risk == "UNCONFIGURED":
        return "FORECAST_ONLY_CONFIGURE_LIMITS"

    return "SHADOW_REASSESS"


def explain_decision(cpu_risk, gpu_risk, combined_risk):

    if combined_risk == "UNCONFIGURED":
        return "CPU or GPU thermal limit has not been configured."

    if combined_risk == "UNKNOWN":
        return "Insufficient forecast information."

    if combined_risk == "HIGH":
        reasons = []

        if cpu_risk == "HIGH":
            reasons.append("CPU forecast reaches configured limit")

        if gpu_risk == "HIGH":
            reasons.append("GPU forecast reaches configured limit")

        return "; ".join(reasons)

    if combined_risk == "MODERATE":
        reasons = []

        if cpu_risk == "MODERATE":
            reasons.append("CPU forecast approaches configured limit")

        if gpu_risk == "MODERATE":
            reasons.append("GPU forecast approaches configured limit")

        return "; ".join(reasons)

    return "All available forecasts remain below configured warning levels."


# ============================================================
# MAIN DECISION REPLAY
# ============================================================

def main():

    print("\n========================================")
    print("RT-TAS PREDICTIVE DECISION ENGINE")
    print("OFFLINE REPLAY - SHADOW MODE")
    print("========================================")

    print("\nLoading synchronized experimental datasets...")

    current_data = {}

    for run, filename in DATASETS.items():

        if not os.path.isfile(filename):
            raise SystemExit(
                "Missing dataset: " + filename
            )

        current_data[run] = load_current_data(filename)

        print(
            run,
            "| loaded:",
            len(current_data[run]),
            "samples"
        )

    print("\nLoading Model B predictions...")

    predictions = load_predictions(PREDICTION_FILE)

    print("Prediction timestamps:", len(predictions))

    output_rows = []

    unmatched = 0

    for (run, timestamp), forecast_data in sorted(
        predictions.items()
    ):

        current = current_data[run].get(timestamp)

        if current is None:
            unmatched += 1
            continue

        cpu_forecasts = {}
        gpu_forecasts = {}

        for horizon in HORIZONS:

            cpu_value = forecast_data.get(("CPU", horizon))
            gpu_value = forecast_data.get(("GPU", horizon))

            if cpu_value is not None:
                cpu_forecasts[horizon] = cpu_value

            if gpu_value is not None:
                gpu_forecasts[horizon] = gpu_value

        cpu_risk = assess_sensor_risk(
            current["cpu_current"],
            cpu_forecasts,
            CPU_LIMIT_C
        )

        gpu_risk = assess_sensor_risk(
            current["gpu_current"],
            gpu_forecasts,
            GPU_LIMIT_C
        )

        combined_risk = combine_risks(
            cpu_risk,
            gpu_risk
        )

        action = recommend_action(combined_risk)

        reason = explain_decision(
            cpu_risk,
            gpu_risk,
            combined_risk
        )

        row = {
            "heldout_run": run,
            "timestamp": timestamp,
            "phase": current["phase"],
            "cpu_current_C": current["cpu_current"],
            "gpu_current_C": current["gpu_current"],
            "gpu_busy_percent": current["gpu_busy"],

            "cpu_pred_1s_C": cpu_forecasts.get(1, ""),
            "cpu_pred_5s_C": cpu_forecasts.get(5, ""),
            "cpu_pred_10s_C": cpu_forecasts.get(10, ""),

            "gpu_pred_1s_C": gpu_forecasts.get(1, ""),
            "gpu_pred_5s_C": gpu_forecasts.get(5, ""),
            "gpu_pred_10s_C": gpu_forecasts.get(10, ""),

            "cpu_risk": cpu_risk,
            "gpu_risk": gpu_risk,
            "combined_risk": combined_risk,
            "recommended_action": action,
            "reason": reason,
            "mode": "SHADOW_REPLAY"
        }

        output_rows.append(row)

    if not output_rows:
        raise SystemExit(
            "No matching prediction and sensor records found."
        )

    fields = list(output_rows[0].keys())

    with open(OUTPUT_FILE, "w", newline="") as f:

        writer = csv.DictWriter(
            f,
            fieldnames=fields
        )

        writer.writeheader()
        writer.writerows(output_rows)

    # ========================================================
    # SUMMARY
    # ========================================================

    print("\n========================================")
    print("DECISION REPLAY SUMMARY")
    print("========================================")

    print("Matched decision records:", len(output_rows))
    print("Unmatched prediction records:", unmatched)

    risk_counts = defaultdict(int)
    action_counts = defaultdict(int)

    for row in output_rows:
        risk_counts[row["combined_risk"]] += 1
        action_counts[row["recommended_action"]] += 1

    print("\nCombined risk distribution:")

    for risk, count in sorted(risk_counts.items()):
        print("  %-15s %d" % (risk, count))

    print("\nRecommended actions:")

    for action, count in sorted(action_counts.items()):
        print("  %-45s %d" % (action, count))

    print("\nOutput saved:", OUTPUT_FILE)

    print("\nSHADOW MODE: No workload or scheduling controls changed.")


if __name__ == "__main__":
    main()

