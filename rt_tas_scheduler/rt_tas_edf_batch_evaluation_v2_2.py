#!/usr/bin/env python3

"""
RT-TAS V2.2: Batch evaluation of baseline EDF and
resource-specific thermal-aware EDF.

Offline evaluation only. No real workload execution or control.
"""

import argparse
import csv
import math
import os
from collections import defaultdict

from rt_tas_scheduler_v1 import TASKS, schedule_resource


def finite_float(value):
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (ValueError, TypeError):
        return None


def get_edf_schedule():
    cpu = schedule_resource(TASKS, "CPU")
    gpu = schedule_resource(TASKS, "GPU")

    return sorted(
        cpu + gpu,
        key=lambda x: (x["start"], x["task"].task_id)
    )


def load_valid_forecasts(path):
    required = [
        "elapsed_s",
        "phase",
        "prediction_status",
        "cpu_hybrid_predicted_1s_C",
        "gpu_hybrid_predicted_1s_C",
    ]

    valid = []
    skipped = defaultdict(int)
    seen_elapsed = set()

    with open(path, newline="") as f:
        reader = csv.DictReader(f)

        missing = [
            column for column in required
            if column not in (reader.fieldnames or [])
        ]

        if missing:
            raise ValueError(
                f"{path}: missing columns: {', '.join(missing)}"
            )

        for row in reader:
            if row["prediction_status"] != "FORECAST_ONLY":
                skipped[row["prediction_status"]] += 1
                continue

            elapsed = row["elapsed_s"]

            if elapsed in seen_elapsed:
                raise ValueError(
                    f"{path}: duplicate FORECAST_ONLY elapsed_s={elapsed}"
                )

            cpu = finite_float(row["cpu_hybrid_predicted_1s_C"])
            gpu = finite_float(row["gpu_hybrid_predicted_1s_C"])

            if cpu is None or gpu is None:
                skipped["INVALID_FORECAST_VALUES"] += 1
                continue

            seen_elapsed.add(elapsed)

            valid.append({
                "elapsed_s": elapsed,
                "phase": row["phase"],
                "cpu_prediction": cpu,
                "gpu_prediction": gpu,
            })

    return valid, dict(skipped)


def main():
    parser = argparse.ArgumentParser(
        description="Batch comparison of baseline EDF and RT-TAS V2.2"
    )

    parser.add_argument(
        "--input",
        nargs="+",
        required=True,
        help="One or more V3.3 prediction CSV files"
    )

    parser.add_argument("--cpu-limit", type=float, default=70.0)
    parser.add_argument("--gpu-limit", type=float, default=65.0)
    parser.add_argument("--cpu-margin", type=float, default=0.75)
    parser.add_argument("--gpu-margin", type=float, default=1.00)

    parser.add_argument(
        "--output-prefix",
        default="rt_tas_v2_2_batch"
    )

    args = parser.parse_args()

    values = [
        args.cpu_limit,
        args.gpu_limit,
        args.cpu_margin,
        args.gpu_margin,
    ]

    if not all(math.isfinite(x) for x in values):
        parser.error("Limits and margins must be finite.")

    if args.cpu_limit <= 0 or args.gpu_limit <= 0:
        parser.error("Thermal limits must be positive.")

    if args.cpu_margin < 0 or args.gpu_margin < 0:
        parser.error("Margins cannot be negative.")

    for path in args.input:
        if not os.path.isfile(path):
            parser.error(f"Input file not found: {path}")

    schedule = get_edf_schedule()

    detailed_rows = []
    summary_groups = defaultdict(list)
    skipped_by_run = {}

    for path in args.input:
        run_id = os.path.basename(path)

        forecasts, skipped = load_valid_forecasts(path)
        skipped_by_run[run_id] = skipped

        print(f"\nProcessing: {run_id}")
        print(f"Valid forecasts: {len(forecasts)}")
        print(f"Skipped records: {sum(skipped.values())}")

        for forecast in forecasts:
            cpu_pred = forecast["cpu_prediction"]
            gpu_pred = forecast["gpu_prediction"]

            cpu_safe = cpu_pred + args.cpu_margin
            gpu_safe = gpu_pred + args.gpu_margin

            cpu_ok = cpu_safe < args.cpu_limit
            gpu_ok = gpu_safe < args.gpu_limit

            for entry in schedule:
                task = entry["task"]
                deadline_ok = entry["deadline_met"]

                baseline = (
                    "EDF_SCHEDULED"
                    if deadline_ok else "DEADLINE_MISS"
                )

                resource_ok = (
                    cpu_ok if task.resource == "CPU"
                    else gpu_ok
                )

                if not resource_ok:
                    thermal_decision = "DEFER_THERMAL"
                elif not deadline_ok:
                    thermal_decision = "DEFER_DEADLINE"
                else:
                    thermal_decision = "ADVISORY_ADMIT"

                record = {
                    "run": run_id,
                    "elapsed_s": forecast["elapsed_s"],
                    "phase": forecast["phase"],
                    "task_id": task.task_id,
                    "resource": task.resource,
                    "release_ms": task.release_ms,
                    "start_ms": entry["start"],
                    "finish_ms": entry["finish"],
                    "deadline_ms": task.deadline_ms,
                    "deadline_feasible": deadline_ok,
                    "cpu_predicted_C": f"{cpu_pred:.4f}",
                    "gpu_predicted_C": f"{gpu_pred:.4f}",
                    "cpu_safe_C": f"{cpu_safe:.4f}",
                    "gpu_safe_C": f"{gpu_safe:.4f}",
                    "cpu_gate": "PASS" if cpu_ok else "FAIL",
                    "gpu_gate": "PASS" if gpu_ok else "FAIL",
                    "baseline_edf_decision": baseline,
                    "thermal_edf_decision": thermal_decision,
                }

                detailed_rows.append(record)

                # Three aggregation levels:
                # run + phase + resource
                # run + ALL phases + resource
                # all runs + all phases + resource
                keys = [
                    (run_id, forecast["phase"], task.resource),
                    (run_id, "ALL", task.resource),
                    ("ALL_RUNS", "ALL", task.resource),
                ]

                for key in keys:
                    summary_groups[key].append(record)

    summary_rows = []

    for (run, phase, resource), records in sorted(
        summary_groups.items()
    ):
        forecast_ids = {
            (r["run"], r["elapsed_s"]) for r in records
        }

        baseline_scheduled = sum(
            r["baseline_edf_decision"] == "EDF_SCHEDULED"
            for r in records
        )

        baseline_misses = sum(
            r["baseline_edf_decision"] == "DEADLINE_MISS"
            for r in records
        )

        admissions = sum(
            r["thermal_edf_decision"] == "ADVISORY_ADMIT"
            for r in records
        )

        thermal_deferrals = sum(
            r["thermal_edf_decision"] == "DEFER_THERMAL"
            for r in records
        )

        deadline_deferrals = sum(
            r["thermal_edf_decision"] == "DEFER_DEADLINE"
            for r in records
        )

        total = len(records)

        summary_rows.append({
            "run": run,
            "phase": phase,
            "resource": resource,
            "forecast_count": len(forecast_ids),
            "task_count": total,
            "baseline_scheduled": baseline_scheduled,
            "baseline_deadline_misses": baseline_misses,
            "thermal_admissions": admissions,
            "thermal_deferrals": thermal_deferrals,
            "deadline_deferrals": deadline_deferrals,
            "baseline_admission_rate_percent": (
                100 * baseline_scheduled / total if total else 0
            ),
            "thermal_admission_rate_percent": (
                100 * admissions / total if total else 0
            ),
        })

    detailed_path = args.output_prefix + "_detailed.csv"
    summary_path = args.output_prefix + "_summary.csv"

    if not detailed_rows:
        parser.error("No valid forecasts found in the input files.")

    with open(detailed_path, "w", newline="") as f:
        writer = csv.DictWriter(
            f, fieldnames=list(detailed_rows[0].keys())
        )
        writer.writeheader()
        writer.writerows(detailed_rows)

    with open(summary_path, "w", newline="") as f:
        writer = csv.DictWriter(
            f, fieldnames=list(summary_rows[0].keys())
        )
        writer.writeheader()
        writer.writerows(summary_rows)

    print("\n" + "=" * 65)
    print("RT-TAS V2.2 BATCH EVALUATION")
    print("Mode: OFFLINE ADVISORY SIMULATION")
    print("=" * 65)

    print(f"Input runs: {len(args.input)}")
    print(f"Valid forecasts: {sum(len(load_valid_forecasts(p)[0]) for p in args.input)}")
    print(f"Task-level decisions: {len(detailed_rows)}")

    print("\nHypothetical thermal configuration:")
    print(f"CPU limit:  {args.cpu_limit:.2f} C")
    print(f"GPU limit:  {args.gpu_limit:.2f} C")
    print(f"CPU margin: {args.cpu_margin:.2f} C")
    print(f"GPU margin: {args.gpu_margin:.2f} C")

    print("\nSkipped prediction records:")
    for run, counts in skipped_by_run.items():
        print(run)
        for status, count in sorted(counts.items()):
            print(f"  {status}: {count}")

    print("\nOVERALL RESULTS BY RESOURCE")
    print("-" * 65)

    for row in summary_rows:
        if row["run"] == "ALL_RUNS":
            print(
                f"{row['resource']}: "
                f"Baseline={row['baseline_scheduled']}/"
                f"{row['task_count']} "
                f"({row['baseline_admission_rate_percent']:.2f}%), "
                f"Thermal={row['thermal_admissions']}/"
                f"{row['task_count']} "
                f"({row['thermal_admission_rate_percent']:.2f}%), "
                f"Thermal deferrals={row['thermal_deferrals']}"
            )

    print("\nOutput files:")
    print(detailed_path)
    print(summary_path)

    print("\nNo real CPU/GPU workload was executed.")
    print("Results are offline decisions using historical forecasts.")


if __name__ == "__main__":
    main()
