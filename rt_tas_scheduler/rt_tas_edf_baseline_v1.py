#!/usr/bin/env python3

import csv
import argparse
from collections import defaultdict

TASKS = [
    {"id": "T1", "resource": "CPU", "release": 0,  "execution": 1.0, "deadline": 30},
    {"id": "T2", "resource": "GPU", "release": 0,  "execution": 2.0, "deadline": 50},
    {"id": "T3", "resource": "CPU", "release": 5,  "execution": 1.5, "deadline": 60},
    {"id": "T4", "resource": "GPU", "release": 10, "execution": 1.5, "deadline": 55},
    {"id": "T5", "resource": "CPU", "release": 15, "execution": 1.0, "deadline": 50},
    {"id": "T6", "resource": "GPU", "release": 20, "execution": 1.0, "deadline": 70},
    {"id": "T7", "resource": "CPU", "release": 25, "execution": 1.2, "deadline": 65},
]


def simulate_edf(tasks):
    results = []
    events = []

    for resource in ("CPU", "GPU"):
        resource_tasks = [
            dict(task) for task in tasks
            if task["resource"] == resource
        ]

        # Non-preemptive EDF: earliest absolute deadline first.
        resource_tasks.sort(
            key=lambda task: (task["deadline"], task["release"], task["id"])
        )

        available_at = 0.0

        for task in resource_tasks:
            start = max(float(task["release"]), available_at)
            finish = start + float(task["execution"])

            if finish <= float(task["deadline"]):
                status = "DEADLINE_MET"
            else:
                status = "DEADLINE_MISSED_AFTER_EXECUTION"

            result = {
                "task_id": task["id"],
                "resource": resource,
                "release_s": task["release"],
                "start_s": round(start, 3),
                "finish_s": round(finish, 3),
                "execution_s": task["execution"],
                "deadline_s": task["deadline"],
                "status": status,
            }

            results.append(result)

            events.append({
                "time_s": round(start, 3),
                "event": "DISPATCHED",
                "task_id": task["id"],
                "resource": resource,
            })

            events.append({
                "time_s": round(finish, 3),
                "event": "COMPLETED",
                "task_id": task["id"],
                "resource": resource,
            })

            available_at = finish

    results.sort(key=lambda row: (row["start_s"], row["resource"]))
    events.sort(key=lambda row: (row["time_s"], row["event"]))

    return results, events


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output-prefix",
        default="rt_tas_edf_baseline_v1"
    )
    args = parser.parse_args()

    results, events = simulate_edf(TASKS)

    summary_file = args.output_prefix + "_task_summary.csv"
    events_file = args.output_prefix + "_events.csv"

    with open(summary_file, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(results[0].keys()))
        writer.writeheader()
        writer.writerows(results)

    with open(events_file, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(events[0].keys()))
        writer.writeheader()
        writer.writerows(events)

    counts = defaultdict(int)
    for result in results:
        counts[result["status"]] += 1

    print("\nRT-TAS EDF BASELINE V1")
    print("=" * 55)
    print("Mode: NON-PREEMPTIVE EDF SIMULATION")
    print("Thermal prediction: NO")
    print("Thermal admission gate: NO")
    print("CPU/GPU queues: Independent")
    print("Real workload execution: NO")
    print("\nTask summary:")
    print(
        f"{'Task':<7}{'Resource':<10}{'Start':<10}"
        f"{'Finish':<10}{'Deadline':<11}{'Status'}"
    )

    for row in results:
        print(
            f"{row['task_id']:<7}{row['resource']:<10}"
            f"{row['start_s']:<10.1f}{row['finish_s']:<10.1f}"
            f"{row['deadline_s']:<11}{row['status']}"
        )

    print("\nFinal outcomes:")
    for status, count in sorted(counts.items()):
        print(f"{status:<35}: {count}")

    print(f"\nTask summary CSV: {summary_file}")
    print(f"Event log CSV:    {events_file}")


if __name__ == "__main__":
    main()
