#!/usr/bin/env python3

import csv
import sys
import math
from pathlib import Path
from collections import Counter

# Numerical deadband, NOT a thermal safety limit.
EPSILON_C = 0.05

VALID_STATUS = "FORECAST_ONLY"

OUTPUT_FIELDS = [
    "timestamp",
    "elapsed_s",
    "phase",
    "cpu_actual_C",
    "cpu_predicted_1s_C",
    "cpu_predicted_rise_C",
    "gpu_actual_C",
    "gpu_predicted_1s_C",
    "gpu_predicted_rise_C",
    "prediction_status",
    "source_recommended_action",
    "scheduler_decision",
    "decision_reason",
    "decision_mode"
]


def number(value):
    """Convert a CSV value to a finite float."""
    try:
        x = float(str(value).strip())
        return x if math.isfinite(x) else None
    except (TypeError, ValueError):
        return None


def decide(row):
    status = row.get("prediction_status", "").strip()

    cpu_actual = number(row.get("cpu_actual_C"))
    cpu_pred = number(row.get("cpu_predicted_1s_C"))

    gpu_actual = number(row.get("gpu_actual_C"))
    gpu_pred = number(row.get("gpu_predicted_1s_C"))

    base = {
        "timestamp": row.get("timestamp", "").strip(),
        "elapsed_s": row.get("elapsed_s", "").strip(),
        "phase": row.get("phase", "").strip(),
        "cpu_actual_C": cpu_actual,
        "cpu_predicted_1s_C": cpu_pred,
        "gpu_actual_C": gpu_actual,
        "gpu_predicted_1s_C": gpu_pred,
        "prediction_status": status,
        "source_recommended_action":
            row.get("recommended_action", "").strip(),
        "decision_mode": "SHADOW_ONLY"
    }

    # Invalid or skipped predictions must not produce a new action.
    if status != VALID_STATUS:
        base.update({
            "cpu_predicted_rise_C": "",
            "gpu_predicted_rise_C": "",
            "scheduler_decision": "BASELINE_FALLBACK",
            "decision_reason": "Forecast unavailable or invalid"
        })
        return base

    if None in (cpu_actual, cpu_pred, gpu_actual, gpu_pred):
        base.update({
            "cpu_predicted_rise_C": "",
            "gpu_predicted_rise_C": "",
            "scheduler_decision": "BASELINE_FALLBACK",
            "decision_reason": "Missing or invalid temperature value"
        })
        return base

    # Predicted change over the next one-second horizon.
    cpu_rise = cpu_pred - cpu_actual
    gpu_rise = gpu_pred - gpu_actual

    cpu_hot = cpu_rise > EPSILON_C
    gpu_hot = gpu_rise > EPSILON_C

    base["cpu_predicted_rise_C"] = round(cpu_rise, 4)
    base["gpu_predicted_rise_C"] = round(gpu_rise, 4)

    if cpu_hot and gpu_hot:
        decision = "AVOID_CONCURRENT_START"
        reason = (
            "Both CPU and GPU temperatures are predicted to rise"
        )

    elif cpu_hot and not gpu_hot:
        decision = "GPU_PREFERRED_IF_READY"
        reason = (
            "CPU temperature is predicted to rise; "
            "GPU temperature is stable or falling"
        )

    elif gpu_hot and not cpu_hot:
        decision = "CPU_PREFERRED_IF_READY"
        reason = (
            "GPU temperature is predicted to rise; "
            "CPU temperature is stable or falling"
        )

    else:
        decision = "CONCURRENT_EXECUTION_ALLOWED"
        reason = (
            "Neither temperature is predicted to rise "
            "beyond the numerical deadband"
        )

    base["scheduler_decision"] = decision
    base["decision_reason"] = reason

    return base


def main():
    if len(sys.argv) < 2:
        print(
            "Usage: python3 rt_tas_decision_engine.py "
            "<live_predictions.csv> [output.csv]"
        )
        sys.exit(1)

    input_path = Path(sys.argv[1])

    if not input_path.is_file():
        print("ERROR: Input file not found:", input_path)
        sys.exit(1)

    if len(sys.argv) >= 3:
        output_path = Path(sys.argv[2])
    else:
        output_path = input_path.with_name(
            input_path.stem + "_decisions.csv"
        )

    counts = Counter()
    total = 0

    with input_path.open(
        "r", newline="", encoding="utf-8-sig"
    ) as infile:

        reader = csv.DictReader(infile)

        required = {
            "timestamp",
            "elapsed_s",
            "phase",
            "cpu_actual_C",
            "cpu_predicted_1s_C",
            "gpu_actual_C",
            "gpu_predicted_1s_C",
            "prediction_status"
        }

        if not required.issubset(set(reader.fieldnames or [])):
            print("ERROR: Input CSV is missing required columns.")
            print("Found:", reader.fieldnames)
            sys.exit(1)

        with output_path.open(
            "w", newline="", encoding="utf-8"
        ) as outfile:

            writer = csv.DictWriter(
                outfile,
                fieldnames=OUTPUT_FIELDS
            )
            writer.writeheader()

            for row in reader:
                result = decide(row)
                writer.writerow(result)

                counts[result["scheduler_decision"]] += 1
                total += 1

    print("\nRT-TAS SHADOW DECISION ENGINE")
    print("-----------------------------------")
    print("Input :", input_path)
    print("Output:", output_path)
    print("Rows  :", total)

    print("\nDECISION DISTRIBUTION")
    for decision, count in sorted(counts.items()):
        print("{:<38} {}".format(decision, count))

    print("\nMode: SHADOW ONLY")
    print("No CPU/GPU workload was started, stopped, or paused.")
    print("Decision log generated successfully.")


if __name__ == "__main__":
    main()
