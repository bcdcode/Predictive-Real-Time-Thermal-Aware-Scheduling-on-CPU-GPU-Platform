#!/usr/bin/env python3

"""
RT-TAS Live Thermal Admission Controller V1

Reads V3.3 prediction CSV records and independently evaluates
CPU and GPU thermal admission gates.

Modes:
  Default: replay an existing prediction CSV and exit.
  --follow: wait for and process new prediction records.

This is an advisory/shadow controller.
It does not execute, pause, or resume workloads.
"""

import argparse
import csv
import math
import os
import sys
import time


REQUIRED_COLUMNS = [
    "timestamp",
    "elapsed_s",
    "monotonic_elapsed_s",
    "phase",
    "cpu_hybrid_predicted_1s_C",
    "gpu_hybrid_predicted_1s_C",
    "prediction_status",
]


OUTPUT_COLUMNS = [
    "timestamp",
    "elapsed_s",
    "monotonic_elapsed_s",
    "phase",
    "prediction_status",
    "cpu_predicted_C",
    "cpu_margin_C",
    "cpu_safe_C",
    "cpu_limit_C",
    "cpu_gate",
    "cpu_decision",
    "gpu_predicted_C",
    "gpu_margin_C",
    "gpu_safe_C",
    "gpu_limit_C",
    "gpu_gate",
    "gpu_decision",
    "decision_reason",
]


def finite_float(value):
    try:
        number = float(value)
        if math.isfinite(number):
            return number
    except (ValueError, TypeError):
        pass
    return None


def evaluate_resource(prediction, margin, limit):
    if prediction is None:
        return "", "INVALID", "DEFER_INVALID"

    safe_temperature = prediction + margin

    if safe_temperature < limit:
        return f"{safe_temperature:.4f}", "PASS", "ADVISORY_ADMIT"

    return f"{safe_temperature:.4f}", "FAIL", "DEFER_THERMAL"


def process_row(row, args, previous_monotonic):
    status = row.get("prediction_status", "").strip()

    cpu_prediction = finite_float(
        row.get("cpu_hybrid_predicted_1s_C")
    )
    gpu_prediction = finite_float(
        row.get("gpu_hybrid_predicted_1s_C")
    )

    monotonic_value = finite_float(
        row.get("monotonic_elapsed_s")
    )

    cpu_safe = ""
    gpu_safe = ""
    cpu_gate = "INVALID"
    gpu_gate = "INVALID"

    if status != "FORECAST_ONLY":
        cpu_decision = "DEFER_INVALID"
        gpu_decision = "DEFER_INVALID"
        reason = "PREDICTION_STATUS_" + (status or "MISSING")

    elif monotonic_value is None:
        cpu_decision = "DEFER_INVALID"
        gpu_decision = "DEFER_INVALID"
        reason = "INVALID_MONOTONIC_TIMESTAMP"

    elif (
        previous_monotonic is not None
        and (
            monotonic_value <= previous_monotonic
            or monotonic_value - previous_monotonic > args.max_gap
        )
    ):
        cpu_decision = "DEFER_STALE"
        gpu_decision = "DEFER_STALE"
        reason = "TIMESTAMP_SEQUENCE_OR_GAP"

    else:
        cpu_safe, cpu_gate, cpu_decision = evaluate_resource(
            cpu_prediction, args.cpu_margin, args.cpu_limit
        )

        gpu_safe, gpu_gate, gpu_decision = evaluate_resource(
            gpu_prediction, args.gpu_margin, args.gpu_limit
        )

        reason = "RESOURCE_SPECIFIC_THERMAL_GATES"

    record = {
        "timestamp": row.get("timestamp", ""),
        "elapsed_s": row.get("elapsed_s", ""),
        "monotonic_elapsed_s": row.get("monotonic_elapsed_s", ""),
        "phase": row.get("phase", ""),
        "prediction_status": status,
        "cpu_predicted_C": (
            "" if cpu_prediction is None else f"{cpu_prediction:.4f}"
        ),
        "cpu_margin_C": f"{args.cpu_margin:.4f}",
        "cpu_safe_C": cpu_safe,
        "cpu_limit_C": f"{args.cpu_limit:.4f}",
        "cpu_gate": cpu_gate,
        "cpu_decision": cpu_decision,
        "gpu_predicted_C": (
            "" if gpu_prediction is None else f"{gpu_prediction:.4f}"
        ),
        "gpu_margin_C": f"{args.gpu_margin:.4f}",
        "gpu_safe_C": gpu_safe,
        "gpu_limit_C": f"{args.gpu_limit:.4f}",
        "gpu_gate": gpu_gate,
        "gpu_decision": gpu_decision,
        "decision_reason": reason,
    }

    return record, monotonic_value


def validate_header(fieldnames):
    missing = [
        name for name in REQUIRED_COLUMNS
        if name not in (fieldnames or [])
    ]

    if missing:
        raise ValueError(
            "Prediction CSV missing columns: " + ", ".join(missing)
        )


def open_output(path):
    output = open(path, "w", newline="")
    writer = csv.DictWriter(output, fieldnames=OUTPUT_COLUMNS)
    writer.writeheader()
    output.flush()
    return output, writer


def write_decision(writer, output, record):
    writer.writerow(record)
    output.flush()

    print(
        "[{elapsed:>3}s] {phase:<16} | CPU {cpu:<15} | GPU {gpu:<15}".format(
            elapsed=record["elapsed_s"],
            phase=record["phase"],
            cpu=record["cpu_decision"],
            gpu=record["gpu_decision"],
        ),
        flush=True,
    )


def run_replay(args):
    if not os.path.isfile(args.input):
        raise FileNotFoundError(args.input)

    with open(args.input, "r", newline="") as source:
        reader = csv.DictReader(source)
        validate_header(reader.fieldnames)

        output, writer = open_output(args.output)

        previous_monotonic = None
        count = 0

        try:
            for row in reader:
                record, current_monotonic = process_row(
                    row, args, previous_monotonic
                )

                if current_monotonic is not None:
                    previous_monotonic = current_monotonic

                write_decision(writer, output, record)
                count += 1

        finally:
            output.close()

    print("\nReplay completed.")
    print("Records processed:", count)
    print("Decision CSV:", args.output)


def run_follow(args):
    print("RT-TAS LIVE CONTROLLER V1")
    print("Mode: SHADOW / ADVISORY ONLY")
    print("Input:", args.input)
    print("Output:", args.output)
    print("CPU limit:", args.cpu_limit, "C")
    print("GPU limit:", args.gpu_limit, "C")
    print("Waiting for prediction CSV...", flush=True)

    while not os.path.isfile(args.input):
        time.sleep(0.2)

    source = open(args.input, "r", newline="")

    try:
        header_line = source.readline()

        if not header_line:
            raise ValueError("Prediction CSV header is empty.")

        fieldnames = next(csv.reader([header_line]))
        validate_header(fieldnames)

        output, writer = open_output(args.output)

        previous_monotonic = None

        try:
            while True:
                position = source.tell()
                line = source.readline()

                if not line:
                    time.sleep(0.1)
                    source.seek(position)
                    continue

                try:
                    values = next(csv.reader([line]))
                except csv.Error:
                    continue

                if len(values) != len(fieldnames):
                    continue

                row = dict(zip(fieldnames, values))

                record, current_monotonic = process_row(
                    row, args, previous_monotonic
                )

                if current_monotonic is not None:
                    previous_monotonic = current_monotonic

                write_decision(writer, output, record)

        finally:
            output.close()

    finally:
        source.close()


def main():
    parser = argparse.ArgumentParser(
        description="RT-TAS V3.3 live thermal shadow controller"
    )

    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)

    parser.add_argument("--cpu-limit", type=float, default=70.0)
    parser.add_argument("--gpu-limit", type=float, default=65.0)

    parser.add_argument("--cpu-margin", type=float, default=0.75)
    parser.add_argument("--gpu-margin", type=float, default=1.00)

    parser.add_argument(
        "--max-gap",
        type=float,
        default=3.0,
        help="Maximum allowed gap between prediction timestamps",
    )

    parser.add_argument(
        "--follow",
        action="store_true",
        help="Follow new prediction rows instead of replaying the file",
    )

    args = parser.parse_args()

    values = [
        args.cpu_limit,
        args.gpu_limit,
        args.cpu_margin,
        args.gpu_margin,
        args.max_gap,
    ]

    if not all(math.isfinite(value) for value in values):
        parser.error("Limits and margins must be finite.")

    if args.cpu_limit <= 0 or args.gpu_limit <= 0:
        parser.error("Thermal limits must be positive.")

    if args.cpu_margin < 0 or args.gpu_margin < 0:
        parser.error("Margins cannot be negative.")

    if args.max_gap <= 0:
        parser.error("--max-gap must be positive.")

    try:
        if args.follow:
            run_follow(args)
        else:
            run_replay(args)

    except KeyboardInterrupt:
        print("\nController stopped.")

    except (OSError, ValueError) as error:
        print("ERROR:", error, file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
