#!/usr/bin/env python3

"""
RT-TAS: Baseline EDF vs Thermal-Aware EDF

Offline comparison using identical synthetic CPU-GPU tasks.

Thermal-aware policy uses a selected V3.3 historical forecast.
No real workload execution or control.
"""

import argparse
import csv
import math
import os
from collections import Counter

from rt_tas_scheduler_v1 import TASKS, schedule_resource


def finite_float(value):
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (ValueError, TypeError):
        return None


def load_forecast(path, elapsed):
    with open(path, newline="") as f:
        reader = csv.DictReader(f)

        required = [
            "elapsed_s",
            "phase",
            "prediction_status",
            "cpu_hybrid_predicted_1s_C",
            "gpu_hybrid_predicted_1s_C",
        ]

        missing = [
            c for c in required
            if c not in (reader.fieldnames or [])
        ]

        if missing:
            raise ValueError(
                "Missing columns: " + ", ".join(missing)
            )

        matches = [
            r for r in reader
            if r["elapsed_s"] == str(elapsed)
        ]

    if len(matches) != 1:
        raise ValueError("Expected exactly one matching forecast.")

    row = matches[0]

    if row["prediction_status"] != "FORECAST_ONLY":
        raise ValueError("Selected forecast is not valid.")

    cpu = finite_float(row["cpu_hybrid_predicted_1s_C"])
    gpu = finite_float(row["gpu_hybrid_predicted_1s_C"])

    if cpu is None or gpu is None:
        raise ValueError("Invalid CPU or GPU prediction.")

    return row, cpu, gpu


def get_edf_schedule(tasks):
    cpu = schedule_resource(tasks, "CPU")
    gpu = schedule_resource(tasks, "GPU")

    return sorted(
        cpu + gpu,
        key=lambda x: (x["start"], x["task"].task_id)
    )


def main():
    parser = argparse.ArgumentParser(
        description="Baseline EDF vs thermal-aware EDF"
    )

    parser.add_argument("--input", required=True)
    parser.add_argument("--elapsed", type=int, required=True)
    parser.add_argument("--cpu-limit", type=float, required=True)
    parser.add_argument("--gpu-limit", type=float, required=True)
    parser.add_argument("--cpu-margin", type=float, default=0.75)
    parser.add_argument("--gpu-margin", type=float, default=1.00)
    parser.add_argument("--output", default=None)

    args = parser.parse_args()

    values = [
        args.cpu_limit,
        args.gpu_limit,
        args.cpu_margin,
        args.gpu_margin,
    ]

    if not all(math.isfinite(x) for x in values):
        parser.error("All limits and margins must be finite.")

    if args.cpu_limit <= 0 or args.gpu_limit <= 0:
        parser.error("Thermal limits must be positive.")

    if args.cpu_margin < 0 or args.gpu_margin < 0:
        parser.error("Margins cannot be negative.")

    if not os.path.isfile(args.input):
        parser.error("Prediction CSV not found.")

    try:
        forecast, cpu_pred, gpu_pred = load_forecast(
            args.input, args.elapsed
        )
    except ValueError as e:
        parser.error(str(e))

    cpu_safe = cpu_pred + args.cpu_margin
    gpu_safe = gpu_pred + args.gpu_margin

    cpu_thermal_ok = cpu_safe < args.cpu_limit
    gpu_thermal_ok = gpu_safe < args.gpu_limit

    schedule = get_edf_schedule(TASKS)

    output_rows = []

    for entry in schedule:
        task = entry["task"]
        deadline_ok = entry["deadline_met"]

        baseline = (
            "EDF_SCHEDULED"
            if deadline_ok else "DEADLINE_MISS"
        )

        resource_thermal_ok = (
            cpu_thermal_ok if task.resource == "CPU"
            else gpu_thermal_ok
        )

        if not resource_thermal_ok:
            thermal_decision = "DEFER_THERMAL"
        elif not deadline_ok:
            thermal_decision = "DEFER_DEADLINE"
        else:
            thermal_decision = "ADVISORY_ADMIT"

        output_rows.append({
            "task_id": task.task_id,
            "resource": task.resource,
            "release_ms": task.release_ms,
            "start_ms": entry["start"],
            "finish_ms": entry["finish"],
            "deadline_ms": task.deadline_ms,
            "deadline_feasible": deadline_ok,
            "baseline_edf_decision": baseline,
            "thermal_edf_decision": thermal_decision,
            "cpu_safe_C": f"{cpu_safe:.4f}",
            "gpu_safe_C": f"{gpu_safe:.4f}",
        })

    output_path = args.output or (
        os.path.splitext(args.input)[0]
        + f"_edf_comparison_t{args.elapsed}.csv"
    )

    with open(output_path, "w", newline="") as f:
        writer = csv.DictWriter(
            f, fieldnames=list(output_rows[0].keys())
        )
        writer.writeheader()
        writer.writerows(output_rows)

    baseline_counts = Counter(
        r["baseline_edf_decision"] for r in output_rows
    )

    thermal_counts = Counter(
        r["thermal_edf_decision"] for r in output_rows
    )

    total = len(output_rows)

    print("\nRT-TAS EDF POLICY COMPARISON V2.2")
    print("Mode: OFFLINE ADVISORY SIMULATION")
    print("Phase:", forecast["phase"])
    print("Elapsed:", args.elapsed, "s")

    print("\nThermal prediction:")
    print(f"CPU predicted: {cpu_pred:.3f} C")
    print(f"CPU safe:      {cpu_safe:.3f} C")
    print(f"CPU limit:     {args.cpu_limit:.3f} C")
    print(f"GPU predicted: {gpu_pred:.3f} C")
    print(f"GPU safe:      {gpu_safe:.3f} C")
    print(f"GPU limit:     {args.gpu_limit:.3f} C")
    print("CPU thermal gate:", "PASS" if cpu_thermal_ok else "FAIL")
    print("GPU thermal gate:", "PASS" if gpu_thermal_ok else "FAIL")

    print("\nTask-level comparison:")
    print(
        f"{'Task':<8}{'Resource':<10}"
        f"{'Baseline EDF':<20}{'Thermal EDF'}"
    )
    print("-" * 65)

    for r in output_rows:
        print(
            f"{r['task_id']:<8}"
            f"{r['resource']:<10}"
            f"{r['baseline_edf_decision']:<20}"
            f"{r['thermal_edf_decision']}"
        )

    print("\nBASELINE EDF")
    print("Scheduled:", baseline_counts["EDF_SCHEDULED"])
    print("Deadline misses:", baseline_counts["DEADLINE_MISS"])

    print("\nTHERMAL-AWARE EDF")
    print("Advisory admissions:", thermal_counts["ADVISORY_ADMIT"])
    print("Thermal deferrals:", thermal_counts["DEFER_THERMAL"])
    print("Deadline deferrals:", thermal_counts["DEFER_DEADLINE"])

    print("\nAdmission rates:")
    print(
        "Baseline EDF:",
        f"{100 * baseline_counts['EDF_SCHEDULED'] / total:.2f}%"
    )
    print(
        "Thermal-aware EDF:",
        f"{100 * thermal_counts['ADVISORY_ADMIT'] / total:.2f}%"
    )

    print("\nOutput:", output_path)
    print("No real CPU/GPU workload was executed.")


if __name__ == "__main__":
    main()
