#!/usr/bin/env python3

"""
RT-TAS V2.1: Integrated Offline Advisory Simulator.

Combines:
  - V1 synthetic CPU/GPU task set
  - Independent non-preemptive EDF
  - V3.3 historical hybrid temperature forecasts
  - Conservative joint thermal-headroom checks

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
        number = float(value)
        return number if math.isfinite(number) else None
    except (TypeError, ValueError):
        return None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--elapsed", type=int, required=True)
    parser.add_argument("--output", default=None,
                        help="Optional output CSV path")
    parser.add_argument("--cpu-limit", type=float, required=True)
    parser.add_argument("--gpu-limit", type=float, required=True)
    parser.add_argument("--cpu-margin", type=float, default=0.75)
    parser.add_argument("--gpu-margin", type=float, default=1.0)
    args = parser.parse_args()

    if not os.path.isfile(args.input):
        parser.error("Prediction CSV not found.")

    if not all(math.isfinite(x) for x in (
        args.cpu_limit, args.gpu_limit,
        args.cpu_margin, args.gpu_margin
    )):
        parser.error("Limits and margins must be finite.")

    if args.cpu_limit <= 0 or args.gpu_limit <= 0:
        parser.error("Limits must be positive.")

    if args.cpu_margin < 0 or args.gpu_margin < 0:
        parser.error("Margins must be nonnegative.")

    with open(args.input, newline="") as f:
        reader = csv.DictReader(f)
        required = {
            "elapsed_s", "phase", "prediction_status",
            "cpu_hybrid_predicted_1s_C",
            "gpu_hybrid_predicted_1s_C",
        }
        if not required.issubset(reader.fieldnames or []):
            parser.error("Prediction CSV is missing required columns.")

        matching = [
            row for row in reader
            if row["elapsed_s"] == str(args.elapsed)
        ]

    if len(matching) != 1:
        parser.error(
            "Expected exactly one prediction at the requested elapsed second."
        )

    row = matching[0]

    if row["prediction_status"] != "FORECAST_ONLY":
        parser.error(
            "Selected prediction is not valid for advisory evaluation."
        )

    cpu_pred = finite_float(row["cpu_hybrid_predicted_1s_C"])
    gpu_pred = finite_float(row["gpu_hybrid_predicted_1s_C"])

    if cpu_pred is None or gpu_pred is None:
        parser.error("Missing or invalid hybrid prediction.")

    cpu_safe = cpu_pred + args.cpu_margin
    gpu_safe = gpu_pred + args.gpu_margin

    joint_thermal_ok = (
        cpu_safe < args.cpu_limit
        and gpu_safe < args.gpu_limit
    )

    cpu_schedule = schedule_resource(TASKS, "CPU")
    gpu_schedule = schedule_resource(TASKS, "GPU")

    combined = sorted(
        cpu_schedule + gpu_schedule,
        key=lambda entry: (entry["start"], entry["task"].task_id)
    )

    output_path = args.output or os.path.join(
        os.path.dirname(os.path.abspath(args.input)),
        os.path.splitext(os.path.basename(args.input))[0]
        + f"_edf_replay_t{args.elapsed}.csv"
    )

    output_rows = []

    for entry in combined:
        task = entry["task"]
        deadline_ok = entry["deadline_met"]

        if not joint_thermal_ok:
            decision = "DEFER_THERMAL"
        elif not deadline_ok:
            decision = "DEFER_DEADLINE"
        else:
            decision = "ADVISORY_ADMIT"

        output_rows.append({
            "task_id": task.task_id,
            "resource": task.resource,
            "release_ms": task.release_ms,
            "start_ms": entry["start"],
            "finish_ms": entry["finish"],
            "deadline_ms": task.deadline_ms,
            "deadline_feasible": deadline_ok,
            "cpu_safe_C": f"{cpu_safe:.4f}",
            "gpu_safe_C": f"{gpu_safe:.4f}",
            "decision": decision,
        })

    with open(output_path, "w", newline="") as f:
        writer = csv.DictWriter(
            f, fieldnames=list(output_rows[0].keys())
        )
        writer.writeheader()
        writer.writerows(output_rows)

    print("\nRT-TAS V2.1 INTEGRATED OFFLINE SIMULATOR")
    print("Mode: ADVISORY ONLY")
    print("Phase:", row["phase"])
    print("Elapsed:", args.elapsed, "s")
    print(f"CPU: predicted={cpu_pred:.3f}, safe={cpu_safe:.3f}, limit={args.cpu_limit:.3f}")
    print(f"GPU: predicted={gpu_pred:.3f}, safe={gpu_safe:.3f}, limit={args.gpu_limit:.3f}")
    print("Joint thermal gate:", "PASS" if joint_thermal_ok else "FAIL")

    print("\nTask   Resource  Start  Finish  Deadline  Decision")
    print("-" * 65)

    for item in output_rows:
        print(
            f"{item['task_id']:<6} "
            f"{item['resource']:<9} "
            f"{item['start_ms']:<6} "
            f"{item['finish_ms']:<7} "
            f"{item['deadline_ms']:<9} "
            f"{item['decision']}"
        )

    counts = Counter(x["decision"] for x in output_rows)
    print("\nDecision counts:", dict(counts))
    print("Output:", output_path)
    print("No real CPU/GPU workload was executed.")


if __name__ == "__main__":
    main()
