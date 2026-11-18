#!/usr/bin/env python3

import csv
import os
from collections import defaultdict
from datetime import datetime

# ============================================================
# CONFIGURATION
# ============================================================

PREDICTION_FILE = "gpu_busy_model_predictions_v8.csv"

DATASETS = {
    "RUN1_NOV03": "rt_tas_gpu_busy_aligned.csv",
    "RUN2_NOV05": "rt_tas_gpu_busy_20261105.csv",
    "RUN3_NOV05": "rt_tas_gpu_busy_20261105_run3.csv",
    "RUN4_NOV07": "rt_tas_gpu_busy_20261107_run4.csv",
    "RUN5_NOV07": "rt_tas_gpu_busy_20261107_run5.csv",
    "RUN6_NOV07": "rt_tas_gpu_busy_20261107_run6.csv"
}

HORIZONS = [1, 5, 10]

# Model selection based on current V8 results.
CPU_MODEL = "model_f_prediction_C"
GPU_MODEL = "model_e_prediction_C"

# Keep unset until validated against hardware requirements.
CPU_LIMIT_C = None
GPU_LIMIT_C = None

WARNING_MARGIN_C = 2.0

OUTPUT_FILE = (
    "rt_tas_predictive_decisions_v8_"
    + datetime.now().strftime("%Y%m%d_%H%M%S")
    + ".csv"
)


# ============================================================
# LOAD CURRENT SENSOR DATA
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
            c for c in required
            if c not in (reader.fieldnames or [])
        ]

        if missing:
            raise ValueError(
                filename + " missing columns: " + str(missing)
            )

        for row in reader:

            data[row["timestamp"]] = {
                "phase": row["phase"],
                "cpu_current": float(row["cpu_tctl_C"]),
                "gpu_current": float(row["gpu_edge_C"]),
                "gpu_busy": float(row["gpu_busy_percent"])
            }

    return data


# ============================================================
# LOAD V8 MODEL PREDICTIONS
# ============================================================

def load_predictions(filename):

    predictions = defaultdict(dict)

    with open(filename, newline="") as f:

        reader = csv.DictReader(f)

        required = [
            "heldout_run",
            "target",
            "horizon_s",
            "timestamp",
            "model_e_prediction_C",
            "model_f_prediction_C"
        ]

        missing = [
            c for c in required
            if c not in (reader.fieldnames or [])
        ]

        if missing:
            raise ValueError(
                "Prediction file missing columns: " + str(missing)
            )

        for row in reader:

            run = row["heldout_run"]
            target = row["target"].upper()
            horizon = int(row["horizon_s"])

            if run not in DATASETS or horizon not in HORIZONS:
                continue

            if target not in ("CPU", "GPU"):
                continue

            selected_model = (
                CPU_MODEL if target == "CPU" else GPU_MODEL
            )

            value = row[selected_model]

            if value == "":
                continue

            predictions[
                (run, row["timestamp"])
            ][(target, horizon)] = float(value)

    return predictions


# ============================================================
# THERMAL RISK
# ============================================================

def assess_sensor_risk(current, forecasts, limit):

    if limit is None:
        return "UNCONFIGURED"

    if current >= limit:
        return "HIGH"

    if not forecasts:
        return "UNKNOWN"

    if any(value >= limit for value in forecasts.values()):
        return "HIGH"

    if any(
        value >= limit - WARNING_MARGIN_C
        for value in forecasts.values()
    ):
        return "MODERATE"

    return "LOW"


def combine_risks(cpu, gpu):

    if "HIGH" in (cpu, gpu):
        return "HIGH"

    if "UNKNOWN" in (cpu, gpu):
        return "UNKNOWN"

    if "UNCONFIGURED" in (cpu, gpu):
        return "UNCONFIGURED"

    if "MODERATE" in (cpu, gpu):
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


# ============================================================
# MAIN
# ============================================================

def main():

    print("\n==========================================")
    print("PREDICTIVE RT-TAS V8")
    print("OFFLINE REPLAY - SHADOW MODE")
    print("==========================================")

    print("\nCPU model:", CPU_MODEL)
    print("GPU model:", GPU_MODEL)

    current_data = {}

    for run, filename in DATASETS.items():

        if not os.path.isfile(filename):
            raise SystemExit("Missing dataset: " + filename)

        current_data[run] = load_current_data(filename)

        print(run, "|", len(current_data[run]), "samples")

    if not os.path.isfile(PREDICTION_FILE):
        raise SystemExit("Missing " + PREDICTION_FILE)

    predictions = load_predictions(PREDICTION_FILE)

    print("\nPrediction timestamps:", len(predictions))

    output_rows = []
    unmatched = 0

    for (run, timestamp), forecast_data in sorted(predictions.items()):

        current = current_data[run].get(timestamp)

        if current is None:
            unmatched += 1
            continue

        cpu = {
            h: forecast_data[("CPU", h)]
            for h in HORIZONS
            if ("CPU", h) in forecast_data
        }

        gpu = {
            h: forecast_data[("GPU", h)]
            for h in HORIZONS
            if ("GPU", h) in forecast_data
        }

        cpu_risk = assess_sensor_risk(
            current["cpu_current"], cpu, CPU_LIMIT_C
        )

        gpu_risk = assess_sensor_risk(
            current["gpu_current"], gpu, GPU_LIMIT_C
        )

        combined = combine_risks(cpu_risk, gpu_risk)

        action = recommend_action(combined)

        row = {
            "heldout_run": run,
            "timestamp": timestamp,
            "phase": current["phase"],

            "cpu_current_C": current["cpu_current"],
            "gpu_current_C": current["gpu_current"],
            "gpu_busy_percent": current["gpu_busy"],

            "cpu_model": "F",
            "gpu_model": "E",

            "cpu_pred_1s_C": cpu.get(1, ""),
            "cpu_pred_5s_C": cpu.get(5, ""),
            "cpu_pred_10s_C": cpu.get(10, ""),

            "gpu_pred_1s_C": gpu.get(1, ""),
            "gpu_pred_5s_C": gpu.get(5, ""),
            "gpu_pred_10s_C": gpu.get(10, ""),

            "cpu_risk": cpu_risk,
            "gpu_risk": gpu_risk,
            "combined_risk": combined,
            "recommended_action": action,

            "mode": "SHADOW_REPLAY"
        }

        output_rows.append(row)

    if not output_rows:
        raise SystemExit("No matching records found.")

    with open(OUTPUT_FILE, "w", newline="") as f:

        writer = csv.DictWriter(
            f, fieldnames=list(output_rows[0].keys())
        )

        writer.writeheader()
        writer.writerows(output_rows)

    # ========================================================
    # SUMMARY
    # ========================================================

    risk_counts = defaultdict(int)
    action_counts = defaultdict(int)
    run_counts = defaultdict(int)

    for row in output_rows:
        risk_counts[row["combined_risk"]] += 1
        action_counts[row["recommended_action"]] += 1
        run_counts[row["heldout_run"]] += 1

    print("\n==========================================")
    print("PREDICTIVE RT-TAS SUMMARY")
    print("==========================================")

    print("Matched records:", len(output_rows))
    print("Unmatched records:", unmatched)

    print("\nRecords per run:")

    for run, count in sorted(run_counts.items()):
        print(" ", run, ":", count)

    print("\nThermal risk distribution:")

    for risk, count in sorted(risk_counts.items()):
        print(" ", risk, ":", count)

    print("\nScheduling recommendations:")

    for action, count in sorted(action_counts.items()):
        print(" ", action, ":", count)

    print("\nSaved:", OUTPUT_FILE)

    print("\nSHADOW MODE: No workload controls changed.")
    print("Predictive decision replay completed.")


if __name__ == "__main__":
    main()
