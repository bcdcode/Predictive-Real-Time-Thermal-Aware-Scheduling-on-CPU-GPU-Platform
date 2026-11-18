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


def simulate_resource(tasks, resource):
    pending = [
        dict(t) for t in tasks if t["resource"] == resource
    ]

    now = 0.0
    results = []
    events = []

    while pending:
        ready = [
            t for t in pending if float(t["release"]) <= now
        ]

        if not ready:
            now = min(float(t["release"]) for t in pending)
            ready = [
                t for t in pending if float(t["release"]) <= now
            ]

        # EDF among currently released tasks only.
        task = min(
            ready,
            key=lambda t: (
                float(t["deadline"]),
                float(t["release"]),
                t["id"]
            )
        )

        pending.remove(task)

        start = now
        finish = start + float(task["execution"])

        status = (
            "DEADLINE_MET"
            if finish <= float(task["deadline"])
            else "DEADLINE_MISSED_AFTER_EXECUTION"
        )

        results.append({
            "task_id": task["id"],
            "resource": resource,
            "release_s": task["release"],
            "start_s": round(start, 3),
            "finish_s": round(finish, 3),
            "execution_s": task["execution"],
            "deadline_s": task["deadline"],
            "status": status,
        })

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

        now = finish

    return results, events


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output-prefix",
        default="rt_tas_edf_baseline_v2"
    )
    args = parser.parse_args()

    all_results = []
    all_events = []

    for resource in ("CPU", "GPU"):
        results, events = simulate_resource(TASKS, resource)
        all_results.extend(results)
        all_events.extend(events)

    all_results.sort(
        key=lambda r: (r["start_s"], r["resource"], r["task_id"])
    )
    all_events.sort(
        key=lambda e: (e["time_s"], e["event"], e["task_id"])
    )

    summary_file = args.output_prefix + "_task_summary.csv"
    events_file = args.output_prefix + "_events.csv"

    with open(summary_file, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(all_results[0].keys()))
        writer.writeheader()
        writer.writerows(all_results)

    with open(events_file, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(all_events[0].keys()))
        writer.writeheader()
        writer.writerows(all_events)

    counts = defaultdict(int)
    for row in all_results:
        counts[row["status"]] += 1

    print("\nRT-TAS EDF BASELINE V2")
    print("=" * 55)
    print("Mode: EVENT-DRIVEN NON-PREEMPTIVE EDF SIMULATION")
    print("Thermal prediction: NO")
    print("Thermal admission gate: NO")
    print("CPU/GPU queues: Independent")
    print("Real workload execution: NO")

    print("\nTask summary:")
    print(
        f"{'Task':<7}{'Resource':<10}{'Start':<10}"
        f"{'Finish':<10}{'Deadline':<11}{'Status'}"
    )

    for row in all_results:
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
