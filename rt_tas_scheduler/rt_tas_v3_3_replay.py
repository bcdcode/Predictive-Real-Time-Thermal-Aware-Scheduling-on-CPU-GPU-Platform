#!/usr/bin/env python3

"""
RT-TAS V3.3 Offline Thermal Prediction Replay

Reads completed V3.3 prediction records and evaluates
CPU/GPU thermal headroom.

This is an offline advisory evaluation.
It does not control real CPU/GPU workloads.
"""

import argparse
import csv
import math
import os


REQUIRED_COLUMNS = [
    "timestamp",
    "elapsed_s",
    "phase",
    "cpu_hybrid_predicted_1s_C",
    "cpu_hybrid_method",
    "gpu_hybrid_predicted_1s_C",
    "gpu_hybrid_method",
    "prediction_status",
]


def parse_args():
    parser = argparse.ArgumentParser(
        description="RT-TAS V3.3 offline thermal replay"
    )

    parser.add_argument("--input", required=True)

    parser.add_argument("--cpu-limit", type=float, required=True)
    parser.add_argument("--gpu-limit", type=float, required=True)

    parser.add_argument("--cpu-margin", type=float, default=0.75)
    parser.add_argument("--gpu-margin", type=float, default=1.00)

    return parser.parse_args()


def valid_number(value):
    try:
        number = float(value)

        if not math.isfinite(number):
            return None

        return number

    except (ValueError, TypeError):
        return None


def validate_args(args):
    values = [
        args.cpu_limit,
        args.gpu_limit,
        args.cpu_margin,
        args.gpu_margin,
    ]

    if not all(math.isfinite(x) for x in values):
        raise ValueError("All limits and margins must be finite.")

    if args.cpu_limit <= 0 or args.gpu_limit <= 0:
        raise ValueError("Thermal limits must be positive.")

    if args.cpu_margin < 0 or args.gpu_margin < 0:
        raise ValueError("Margins cannot be negative.")


def main():
    args = parse_args()
    validate_args(args)

    if not os.path.isfile(args.input):
        raise FileNotFoundError(args.input)

    output_file = (
        os.path.splitext(args.input)[0]
        + "_thermal_replay.csv"
    )

    results = []

    with open(args.input, newline="") as source:
        reader = csv.DictReader(source)

        missing = [
            column for column in REQUIRED_COLUMNS
            if column not in (reader.fieldnames or [])
        ]

        if missing:
            raise ValueError(
                "Missing prediction columns: " + ", ".join(missing)
            )

        for row in reader:

            status = row["prediction_status"]

            cpu_pred = valid_number(
                row["cpu_hybrid_predicted_1s_C"]
            )

            gpu_pred = valid_number(
                row["gpu_hybrid_predicted_1s_C"]
            )

            if status != "FORECAST_ONLY":
                decision = "REJECT_INVALID_PREDICTION"
                cpu_safe = None
                gpu_safe = None
                cpu_decision = "INVALID_STATUS"
                gpu_decision = "INVALID_STATUS"

            elif cpu_pred is None or gpu_pred is None:
                decision = "REJECT_INVALID_PREDICTION"
                cpu_safe = None
                gpu_safe = None
                cpu_decision = "INVALID_PREDICTION"
                gpu_decision = "INVALID_PREDICTION"

            else:
                cpu_safe = cpu_pred + args.cpu_margin
                gpu_safe = gpu_pred + args.gpu_margin

                cpu_decision = (
                    "THERMAL_OK"
                    if cpu_safe < args.cpu_limit
                    else "DEFER_THERMAL"
                )

                gpu_decision = (
                    "THERMAL_OK"
                    if gpu_safe < args.gpu_limit
                    else "DEFER_THERMAL"
                )

                if (
                    cpu_decision == "THERMAL_OK"
                    and gpu_decision == "THERMAL_OK"
                ):
                    decision = "THERMAL_HEADROOM_AVAILABLE"
                else:
                    decision = "THERMAL_HEADROOM_UNAVAILABLE"

            results.append({
                "timestamp": row["timestamp"],
                "elapsed_s": row["elapsed_s"],
                "phase": row["phase"],
                "prediction_status": status,
                "cpu_hybrid_method": row["cpu_hybrid_method"],
                "cpu_predicted_1s_C": (
                    "" if cpu_pred is None else f"{cpu_pred:.4f}"
                ),
                "cpu_safe_temperature_C": (
                    "" if cpu_safe is None else f"{cpu_safe:.4f}"
                ),
                "cpu_decision": cpu_decision,
                "gpu_hybrid_method": row["gpu_hybrid_method"],
                "gpu_predicted_1s_C": (
                    "" if gpu_pred is None else f"{gpu_pred:.4f}"
                ),
                "gpu_safe_temperature_C": (
                    "" if gpu_safe is None else f"{gpu_safe:.4f}"
                ),
                "gpu_decision": gpu_decision,
                "overall_decision": decision,
            })

    fieldnames = list(results[0].keys()) if results else []

    with open(output_file, "w", newline="") as output:
        if fieldnames:
            writer = csv.DictWriter(
                output,
                fieldnames=fieldnames
            )
            writer.writeheader()
            writer.writerows(results)

    print("\nRT-TAS V3.3 OFFLINE THERMAL REPLAY")
    print("Mode: ADVISORY ONLY")
    print("Input:", args.input)
    print("Output:", output_file)

    print(f"\nCPU limit: {args.cpu_limit:.2f} C")
    print(f"GPU limit: {args.gpu_limit:.2f} C")
    print(f"CPU margin: {args.cpu_margin:.2f} C")
    print(f"GPU margin: {args.gpu_margin:.2f} C")

    from collections import Counter

    counts = Counter(
        row["overall_decision"] for row in results
    )

    print("\nPrediction records:", len(results))
    print("Decision counts:")

    for name, count in sorted(counts.items()):
        print(f"  {name}: {count}")

    print("\nNo real CPU/GPU workload was started or controlled.")


if __name__ == "__main__":
    main()
