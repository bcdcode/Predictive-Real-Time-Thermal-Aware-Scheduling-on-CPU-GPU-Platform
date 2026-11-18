#!/usr/bin/env python3

import csv
import os
import argparse
from collections import defaultdict

CONFIGS = [
    "A_RELAXED",
    "B_MODERATE",
    "C_CONSERVATIVE",
    "D_STRICT",
]


def read_csv(path):
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def write_csv(path, rows):
    if not rows:
        print(f"WARNING: No rows for {path}")
        return

    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def as_int(row, key):
    return int(float(row.get(key, 0) or 0))


def percentage(numerator, denominator):
    return round(100.0 * numerator / denominator, 2) if denominator else 0.0


def main():
    parser = argparse.ArgumentParser(
        description="Consolidate EDF and predictive RT-TAS evaluation results"
    )

    parser.add_argument(
        "--edf",
        default=os.path.expanduser(
            "~/rt_tas_scheduler/rt_tas_edf_baseline_v2_task_summary.csv"
        )
    )
    parser.add_argument(
        "--forecast",
        default=os.path.expanduser(
            "~/thermal_experiment/threshold_sweep_v1/threshold_sweep_summary.csv"
        )
    )
    parser.add_argument(
        "--dispatch",
        default=os.path.expanduser(
            "~/thermal_experiment/threshold_sweep_v1/task_dispatch_v1/threshold_dispatch_summary.csv"
        )
    )
    parser.add_argument(
        "--resource",
        default=os.path.expanduser(
            "~/thermal_experiment/threshold_sweep_v1/task_dispatch_v1/threshold_dispatch_resource_summary.csv"
        )
    )
    parser.add_argument(
        "--output-dir",
        default=os.path.expanduser(
            "~/thermal_experiment/final_evaluation_v1"
        )
    )

    args = parser.parse_args()

    for path in (args.edf, args.forecast, args.dispatch, args.resource):
        if not os.path.isfile(path):
            raise SystemExit(f"ERROR: Required input file not found: {path}")

    os.makedirs(args.output_dir, exist_ok=True)

    edf_rows = read_csv(args.edf)
    forecast_rows = read_csv(args.forecast)
    dispatch_rows = read_csv(args.dispatch)
    resource_rows = read_csv(args.resource)

    # EDF baseline: one deterministic seven-task schedule.
    edf_met = sum(
        1 for row in edf_rows if row["status"] == "DEADLINE_MET"
    )
    edf_total = len(edf_rows)

    # Nine repetitions are used only to normalize the denominator.
    repetitions = 9

    final_rows = [{
        "policy": "EDF_BASELINE",
        "cpu_limit_C": "NA",
        "gpu_limit_C": "NA",
        "runs": 1,
        "forecast_records": 0,
        "valid_forecasts": 0,
        "cpu_forecast_admission_percent": "NA",
        "gpu_forecast_admission_percent": "NA",
        "task_total": edf_total * repetitions,
        "tasks_dispatched": edf_total * repetitions,
        "deadlines_met": edf_met * repetitions,
        "expired_without_admission": 0,
        "pending": 0,
        "deadline_success_percent": percentage(edf_met, edf_total),
        "dispatch_rate_percent": 100.0,
        "comparison_note": "One deterministic EDF schedule normalized across nine runs",
    }]

    for config in CONFIGS:
        forecasts = [
            row for row in forecast_rows
            if row["configuration"] == config
        ]

        dispatches = [
            row for row in dispatch_rows
            if row["configuration"] == config
        ]

        if not forecasts or not dispatches:
            raise SystemExit(
                f"ERROR: Missing forecast or dispatch results for {config}"
            )

        forecast_records = sum(as_int(r, "records") for r in forecasts)
        valid_forecasts = sum(
            as_int(r, "valid_status_records") for r in forecasts
        )

        cpu_admit = sum(as_int(r, "cpu_admit") for r in forecasts)
        cpu_defer = sum(as_int(r, "cpu_thermal_defer") for r in forecasts)
        gpu_admit = sum(as_int(r, "gpu_admit") for r in forecasts)
        gpu_defer = sum(as_int(r, "gpu_thermal_defer") for r in forecasts)

        total_tasks = sum(as_int(r, "total_tasks") for r in dispatches)
        dispatched = sum(as_int(r, "dispatched_tasks") for r in dispatches)
        met = sum(as_int(r, "deadline_met") for r in dispatches)
        expired = sum(
            as_int(r, "expired_without_admission") for r in dispatches
        )
        pending = sum(as_int(r, "pending") for r in dispatches)

        first = forecasts[0]

        final_rows.append({
            "policy": config,
            "cpu_limit_C": first["cpu_limit_C"],
            "gpu_limit_C": first["gpu_limit_C"],
            "runs": len(dispatches),
            "forecast_records": forecast_records,
            "valid_forecasts": valid_forecasts,
            "cpu_forecast_admission_percent": percentage(
                cpu_admit, cpu_admit + cpu_defer
            ),
            "gpu_forecast_admission_percent": percentage(
                gpu_admit, gpu_admit + gpu_defer
            ),
            "task_total": total_tasks,
            "tasks_dispatched": dispatched,
            "deadlines_met": met,
            "expired_without_admission": expired,
            "pending": pending,
            "deadline_success_percent": percentage(met, total_tasks),
            "dispatch_rate_percent": percentage(dispatched, total_tasks),
            "comparison_note": "Nine recorded runs; seven synthetic tasks per replay",
        })

    # Resource-level aggregation.
    resource_output = []

    for config in CONFIGS:
        for resource in ("CPU", "GPU"):
            selected = [
                row for row in resource_rows
                if row["configuration"] == config
                and row["resource"] == resource
            ]

            if not selected:
                continue

            total = sum(as_int(r, "total_tasks") for r in selected)
            dispatched = sum(as_int(r, "dispatched") for r in selected)
            met = sum(as_int(r, "deadline_met") for r in selected)
            expired = sum(
                as_int(r, "expired_without_admission") for r in selected
            )
            pending = sum(as_int(r, "pending") for r in selected)

            resource_output.append({
                "configuration": config,
                "resource": resource,
                "runs": len(selected),
                "total_tasks": total,
                "dispatched": dispatched,
                "deadline_met": met,
                "expired_without_admission": expired,
                "pending": pending,
                "deadline_success_percent": percentage(met, total),
                "dispatch_rate_percent": percentage(dispatched, total),
            })

    summary_path = os.path.join(
        args.output_dir, "final_evaluation_summary.csv"
    )
    resource_path = os.path.join(
        args.output_dir, "final_evaluation_resource_summary.csv"
    )
    report_path = os.path.join(
        args.output_dir, "final_evaluation_report.txt"
    )

    write_csv(summary_path, final_rows)
    write_csv(resource_path, resource_output)

    with open(report_path, "w") as f:
        f.write("THERMAL-AWARE CPU-GPU SCHEDULING\n")
        f.write("FINAL OFFLINE EVALUATION REPORT\n")
        f.write("=" * 72 + "\n\n")

        f.write("Methodology:\n")
        f.write("- EDF is a deterministic non-preemptive simulation.\n")
        f.write("- RT-TAS uses recorded V3.3 prediction traces.\n")
        f.write("- Four threshold configurations are replayed.\n")
        f.write("- Each replay uses seven synthetic tasks.\n")
        f.write("- No real workload execution is performed.\n")
        f.write("- No physical thermal reduction is measured here.\n\n")

        f.write(
            f"{'Policy':<20}{'Tasks':>9}{'Dispatched':>13}"
            f"{'Met':>8}{'Expired':>10}{'Pending':>9}"
            f"{'Success %':>12}\n"
        )
        f.write("-" * 81 + "\n")

        for row in final_rows:
            f.write(
                f"{row['policy']:<20}"
                f"{row['task_total']:>9}"
                f"{row['tasks_dispatched']:>13}"
                f"{row['deadlines_met']:>8}"
                f"{row['expired_without_admission']:>10}"
                f"{row['pending']:>9}"
                f"{row['deadline_success_percent']:>12}\n"
            )

        f.write("\nResource-level results:\n")
        f.write("-" * 72 + "\n")

        for row in resource_output:
            f.write(
                f"{row['configuration']} | {row['resource']} | "
                f"met={row['deadline_met']}/{row['total_tasks']} | "
                f"expired={row['expired_without_admission']} | "
                f"pending={row['pending']}\n"
            )

    print("\nFINAL RT-TAS EVALUATION")
    print("=" * 90)
    print(
        f"{'Policy':<20}{'Tasks':>9}{'Dispatched':>13}"
        f"{'Met':>8}{'Expired':>10}{'Pending':>9}"
        f"{'Success %':>12}"
    )
    print("-" * 90)

    for row in final_rows:
        print(
            f"{row['policy']:<20}"
            f"{row['task_total']:>9}"
            f"{row['tasks_dispatched']:>13}"
            f"{row['deadlines_met']:>8}"
            f"{row['expired_without_admission']:>10}"
            f"{row['pending']:>9}"
            f"{row['deadline_success_percent']:>12.2f}"
        )

    print("\nOutput files:")
    print(summary_path)
    print(resource_path)
    print(report_path)


if __name__ == "__main__":
    main()
