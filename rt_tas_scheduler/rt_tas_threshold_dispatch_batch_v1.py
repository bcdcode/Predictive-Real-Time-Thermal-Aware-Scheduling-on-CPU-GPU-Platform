#!/usr/bin/env python3

import argparse
import csv
import os
import shutil
import subprocess
import sys
from pathlib import Path
from collections import Counter

CONFIGS = [
    "A_RELAXED",
    "B_MODERATE",
    "C_CONSERVATIVE",
    "D_STRICT",
]

STATUS_FIELDS = [
    "DEADLINE_MET",
    "DEADLINE_MISSED_AFTER_EXECUTION",
    "EXPIRED_WITHOUT_ADMISSION",
    "PENDING",
]


def read_csv(path):
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def has_start(row):
    value = row.get("start_s", "")
    return value is not None and str(value).strip().lower() not in (
        "", "none", "null", "na"
    )


def main():
    parser = argparse.ArgumentParser(
        description="Batch replay of threshold-sweep decisions through RT-TAS Dispatcher V2"
    )
    parser.add_argument(
        "--decision-dir",
        default=os.path.expanduser(
            "~/thermal_experiment/threshold_sweep_v1"
        )
    )
    parser.add_argument(
        "--dispatcher",
        default=os.path.expanduser(
            "~/rt_tas_scheduler/rt_tas_predictive_dispatcher_v2.py"
        )
    )
    parser.add_argument(
        "--output-dir",
        default=os.path.expanduser(
            "~/thermal_experiment/threshold_sweep_v1/task_dispatch_v1"
        )
    )
    args = parser.parse_args()

    decision_dir = Path(args.decision_dir).expanduser()
    dispatcher = Path(args.dispatcher).expanduser()
    output_dir = Path(args.output_dir).expanduser()

    if not dispatcher.is_file():
        raise SystemExit(f"ERROR: Dispatcher not found: {dispatcher}")

    if not decision_dir.is_dir():
        raise SystemExit(f"ERROR: Decision directory not found: {decision_dir}")

    output_dir.mkdir(parents=True, exist_ok=True)

    summary_rows = []
    resource_rows = []
    task_rows = []
    failures = []

    print("\nRT-TAS THRESHOLD DISPATCH BATCH V1")
    print("=" * 70)
    print("Mode: CHRONOLOGICAL DISCRETE-EVENT REPLAY")
    print("Dispatcher: V2")
    print("Real workload execution: NO")
    print(f"Decision directory: {decision_dir}")
    print(f"Output directory:   {output_dir}")
    print()

    total_runs = 0

    for config in CONFIGS:
        pattern = f"*_{config}_decisions.csv"
        input_files = sorted(decision_dir.glob(pattern))

        print(f"{config}: {len(input_files)} decision files")

        for decision_file in input_files:
            run_name = decision_file.name.replace(
                f"_{config}_decisions.csv", ""
            )

            scenario_name = f"{run_name}_{config}"
            scenario_dir = output_dir / scenario_name
            scenario_dir.mkdir(parents=True, exist_ok=True)

            # Keep each dispatcher's generated files isolated.
            local_input = scenario_dir / decision_file.name
            shutil.copy2(decision_file, local_input)

            print(f"\n[{total_runs + 1}] {scenario_name}")

            command = [
                sys.executable,
                str(dispatcher),
                "--input",
                str(local_input),
            ]

            try:
                result = subprocess.run(
                    command,
                    capture_output=True,
                    text=True,
                    check=False,
                )

                log_file = scenario_dir / "dispatcher_output.log"
                with open(log_file, "w") as f:
                    f.write(result.stdout)
                    f.write("\n--- STDERR ---\n")
                    f.write(result.stderr)

                if result.returncode != 0:
                    raise RuntimeError(
                        f"Dispatcher returned exit code {result.returncode}"
                    )

                stem = local_input.with_suffix("")
                task_summary_file = Path(
                    str(stem)
                    + "_predictive_dispatch_v2_events_task_summary.csv"
                )
                event_file = Path(
                    str(stem)
                    + "_predictive_dispatch_v2_events.csv"
                )

                if not task_summary_file.is_file():
                    raise RuntimeError(
                        "Dispatcher task summary was not generated: "
                        + str(task_summary_file)
                    )

                tasks = read_csv(task_summary_file)

                if not tasks:
                    raise RuntimeError("Task summary is empty.")

                counts = Counter(
                    row.get("status", "") for row in tasks
                )

                total = len(tasks)
                dispatched = sum(1 for row in tasks if has_start(row))
                met = counts["DEADLINE_MET"]
                missed = counts["DEADLINE_MISSED_AFTER_EXECUTION"]
                expired = counts["EXPIRED_WITHOUT_ADMISSION"]
                pending = counts["PENDING"]

                summary_rows.append({
                    "run": run_name,
                    "configuration": config,
                    "total_tasks": total,
                    "dispatched_tasks": dispatched,
                    "not_dispatched_tasks": total - dispatched,
                    "deadline_met": met,
                    "deadline_missed_after_execution": missed,
                    "expired_without_admission": expired,
                    "pending": pending,
                    "deadline_success_percent": round(
                        100.0 * met / total if total else 0.0, 2
                    ),
                    "dispatch_rate_percent": round(
                        100.0 * dispatched / total if total else 0.0, 2
                    ),
                    "task_summary_file": str(task_summary_file),
                    "event_file": (
                        str(event_file) if event_file.is_file() else ""
                    ),
                })

                for resource in ("CPU", "GPU"):
                    selected = [
                        row for row in tasks
                        if row.get("resource") == resource
                    ]

                    resource_counts = Counter(
                        row.get("status", "") for row in selected
                    )

                    resource_total = len(selected)
                    resource_dispatched = sum(
                        1 for row in selected if has_start(row)
                    )

                    resource_rows.append({
                        "run": run_name,
                        "configuration": config,
                        "resource": resource,
                        "total_tasks": resource_total,
                        "dispatched": resource_dispatched,
                        "deadline_met": resource_counts["DEADLINE_MET"],
                        "deadline_missed_after_execution":
                            resource_counts[
                                "DEADLINE_MISSED_AFTER_EXECUTION"
                            ],
                        "expired_without_admission":
                            resource_counts["EXPIRED_WITHOUT_ADMISSION"],
                        "pending": resource_counts["PENDING"],
                    })

                for row in tasks:
                    task_rows.append({
                        "run": run_name,
                        "configuration": config,
                        "task_id": row.get("task_id", ""),
                        "resource": row.get("resource", ""),
                        "start_s": row.get("start_s", ""),
                        "finish_s": row.get("finish_s", ""),
                        "deadline_s": row.get("deadline_s", ""),
                        "status": row.get("status", ""),
                    })

                total_runs += 1

                print(
                    f"  Dispatched: {dispatched}/{total} | "
                    f"Met: {met} | Expired: {expired} | "
                    f"Pending: {pending}"
                )

            except Exception as exc:
                failures.append({
                    "run": run_name,
                    "configuration": config,
                    "input_file": str(decision_file),
                    "error": str(exc),
                })
                print(f"  ERROR: {exc}")

    def write_report(filename, rows):
        if not rows:
            return

        path = output_dir / filename

        with open(path, "w", newline="") as f:
            writer = csv.DictWriter(
                f,
                fieldnames=list(rows[0].keys())
            )
            writer.writeheader()
            writer.writerows(rows)

    write_report("threshold_dispatch_summary.csv", summary_rows)
    write_report("threshold_dispatch_resource_summary.csv", resource_rows)
    write_report("threshold_dispatch_task_details.csv", task_rows)
    write_report("threshold_dispatch_failures.csv", failures)

    print("\n" + "=" * 70)
    print("BATCH EVALUATION COMPLETED")
    print(f"Successful replays: {total_runs}")
    print(f"Failed replays:     {len(failures)}")
    print(f"Task summaries:     {len(summary_rows)}")
    print(f"Task detail rows:   {len(task_rows)}")
    print(f"\nOutput directory: {output_dir}")
    print("Main summary:      threshold_dispatch_summary.csv")
    print("Resource summary:  threshold_dispatch_resource_summary.csv")
    print("Task details:      threshold_dispatch_task_details.csv")
    print("Failure report:    threshold_dispatch_failures.csv")

    if failures:
        print("\nWARNING: Some replays failed. Inspect the failure report.")
        sys.exit(1)


if __name__ == "__main__":
    main()
