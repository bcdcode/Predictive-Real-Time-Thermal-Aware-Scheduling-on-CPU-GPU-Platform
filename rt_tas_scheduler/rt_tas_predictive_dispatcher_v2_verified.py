#!/usr/bin/env python3

"""
Predictive RT-TAS Dispatcher V2

Chronological discrete-event simulation using:
- Independent CPU and GPU EDF queues
- Live V3.3 thermal admission decisions
- Consistent seconds-based task timing
- Task completion and deadline evaluation
- Pending-task retry
- Invalid and stale decision rejection

This version is a simulation/replay.
It does NOT execute real CPU/GPU workloads.
"""

import argparse
import csv
import math
import os
from collections import Counter
from dataclasses import dataclass, field


# --------------------------------------------------
# TASK MODEL
# All timing values are in seconds.
# These are experimental synthetic task parameters.
# --------------------------------------------------

@dataclass
class Task:
    task_id: str
    resource: str
    release_s: float
    execution_s: float
    deadline_s: float


TASKS = [
    Task("T1", "CPU", 0,  1.0, 30),
    Task("T2", "GPU", 0,  2.0, 50),
    Task("T3", "CPU", 5,  1.5, 60),
    Task("T4", "GPU", 10, 1.5, 55),
    Task("T5", "CPU", 15, 1.0, 50),
    Task("T6", "GPU", 20, 1.0, 70),
    Task("T7", "CPU", 25, 1.2, 65),
]


def finite_float(value):
    try:
        x = float(value)
        return x if math.isfinite(x) else None
    except (ValueError, TypeError):
        return None


def load_decisions(path):
    required = {
        "elapsed_s",
        "monotonic_elapsed_s",
        "prediction_status",
        "cpu_decision",
        "gpu_decision",
        "phase",
    }

    decisions = []

    with open(path, newline="") as f:
        reader = csv.DictReader(f)

        missing = required - set(reader.fieldnames or [])
        if missing:
            raise ValueError(
                "Missing columns: " + ", ".join(sorted(missing))
            )

        for row in reader:
            elapsed = finite_float(row["elapsed_s"])
            monotonic = finite_float(row["monotonic_elapsed_s"])

            if elapsed is None or monotonic is None:
                continue

            decisions.append({
                "time_s": elapsed,
                "monotonic": monotonic,
                "status": row["prediction_status"],
                "cpu": row["cpu_decision"],
                "gpu": row["gpu_decision"],
                "phase": row["phase"],
            })

    decisions.sort(key=lambda x: x["monotonic"])

    if not decisions:
        raise ValueError("No usable decision records found.")

    return decisions


def normalize_decision(sample, resource, previous_monotonic,
                       max_gap):

    current = sample["monotonic"]

    if sample["status"] != "FORECAST_ONLY":
        return "DEFER_INVALID"

    if previous_monotonic is not None:
        gap = current - previous_monotonic

        if gap <= 0 or gap > max_gap:
            return "DEFER_STALE"

    decision = sample[resource.lower()]

    if decision in (
        "ADVISORY_ADMIT",
        "DEFER_THERMAL",
        "DEFER_INVALID",
        "DEFER_STALE",
    ):
        return decision

    return "DEFER_INVALID"


def simulate(tasks, decisions, max_gap):

    resources = ("CPU", "GPU")

    pending = {
        r: [t for t in tasks if t.resource == r]
        for r in resources
    }

    running = {r: None for r in resources}

    task_results = {
        t.task_id: {
            "task": t,
            "attempts": 0,
            "thermal_deferrals": 0,
            "invalid_deferrals": 0,
            "stale_deferrals": 0,
            "start_s": None,
            "finish_s": None,
            "status": "PENDING",
        }
        for t in tasks
    }

    event_log = []
    previous_monotonic = None

    def complete_task(resource, now):
        active = running[resource]

        if active is None:
            return

        if active["finish_s"] <= now:
            task = active["task"]
            result = task_results[task.task_id]

            result["finish_s"] = active["finish_s"]

            result["status"] = (
                "DEADLINE_MET"
                if active["finish_s"] <= task.deadline_s
                else "DEADLINE_MISSED"
            )

            event_log.append({
                "time_s": active["finish_s"],
                "task_id": task.task_id,
                "resource": resource,
                "event": "COMPLETED",
                "decision": result["status"],
                "deadline_s": task.deadline_s,
                "start_s": result["start_s"],
                "finish_s": active["finish_s"],
                "phase": "",
            })

            running[resource] = None

    def expire_impossible_tasks(resource, now):
        for task in list(pending[resource]):

            if task.release_s > now:
                continue

            # If even immediate execution cannot meet
            # the deadline, this task is no longer feasible.
            if now + task.execution_s > task.deadline_s:
                task_results[task.task_id]["status"] = "EXPIRED_WITHOUT_ADMISSION"
                pending[resource].remove(task)

                event_log.append({
                    "time_s": now,
                    "task_id": task.task_id,
                    "resource": resource,
                    "event": "EXPIRED",
                    "decision": "DEADLINE_INFEASIBLE",
                    "deadline_s": task.deadline_s,
                    "start_s": "",
                    "finish_s": "",
                    "phase": "",
                })

    for index, sample in enumerate(decisions):

        now = sample["time_s"]

        # Use the preceding record to validate the
        # current monotonic timestamp sequence.
        for resource in resources:
            complete_task(resource, now)
            expire_impossible_tasks(resource, now)

        for resource in resources:

            if running[resource] is not None:
                continue

            ready = [
                t for t in pending[resource]
                if t.release_s <= now
            ]

            if not ready:
                continue

            # Independent non-preemptive EDF selection.
            task = min(
                ready,
                key=lambda t: (
                    t.deadline_s,
                    t.release_s,
                    t.task_id
                )
            )

            decision = normalize_decision(
                sample,
                resource,
                previous_monotonic,
                max_gap,
            )

            result = task_results[task.task_id]
            result["attempts"] += 1

            if decision == "DEFER_THERMAL":
                result["thermal_deferrals"] += 1

            elif decision == "DEFER_INVALID":
                result["invalid_deferrals"] += 1

            elif decision == "DEFER_STALE":
                result["stale_deferrals"] += 1

            if decision != "ADVISORY_ADMIT":

                event_log.append({
                    "time_s": now,
                    "task_id": task.task_id,
                    "resource": resource,
                    "event": "ADMISSION_ATTEMPT",
                    "decision": decision,
                    "deadline_s": task.deadline_s,
                    "start_s": "",
                    "finish_s": "",
                    "phase": sample["phase"],
                })

                # Keep task pending for a future decision.
                continue

            # Final deadline feasibility check.
            if now + task.execution_s > task.deadline_s:

                result["status"] = "DEADLINE_MISSED_AFTER_EXECUTION"
                pending[resource].remove(task)

                event_log.append({
                    "time_s": now,
                    "task_id": task.task_id,
                    "resource": resource,
                    "event": "ADMISSION_ATTEMPT",
                    "decision": "DEFER_DEADLINE",
                    "deadline_s": task.deadline_s,
                    "start_s": "",
                    "finish_s": "",
                    "phase": sample["phase"],
                })

                continue

            start = now
            finish = start + task.execution_s

            result["start_s"] = start
            result["status"] = "SIMULATED_RUNNING"

            running[resource] = {
                "task": task,
                "finish_s": finish,
            }

            pending[resource].remove(task)

            event_log.append({
                "time_s": now,
                "task_id": task.task_id,
                "resource": resource,
                "event": "DISPATCHED",
                "decision": "ADVISORY_ADMIT",
                "deadline_s": task.deadline_s,
                "start_s": start,
                "finish_s": finish,
                "phase": sample["phase"],
            })

        previous_monotonic = sample["monotonic"]

    # Finalize any task whose simulated execution ends
    # after the final thermal decision sample.
    for resource in resources:
        active = running[resource]

        if active is not None:
            complete_task(resource, active["finish_s"])

    return event_log, task_results, pending


def main():

    parser = argparse.ArgumentParser(
        description="Predictive RT-TAS Dispatcher V2"
    )

    parser.add_argument("--input", required=True)
    parser.add_argument("--output", default=None)
    parser.add_argument("--max-gap", type=float, default=2.0)

    args = parser.parse_args()

    if not math.isfinite(args.max_gap) or args.max_gap <= 0:
        parser.error("--max-gap must be positive and finite.")

    if not os.path.isfile(args.input):
        parser.error("Decision CSV does not exist.")

    try:
        decisions = load_decisions(args.input)
    except ValueError as exc:
        parser.error(str(exc))

    event_log, results, pending = simulate(
        TASKS,
        decisions,
        args.max_gap,
    )

    base = os.path.splitext(args.input)[0]

    event_output = args.output or (
        base + "_predictive_dispatch_v2_events.csv"
    )

    summary_output = (
        os.path.splitext(event_output)[0]
        + "_task_summary.csv"
    )

    event_fields = [
        "time_s",
        "task_id",
        "resource",
        "event",
        "decision",
        "deadline_s",
        "start_s",
        "finish_s",
        "phase",
    ]

    with open(event_output, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=event_fields)
        writer.writeheader()
        writer.writerows(event_log)

    summary_fields = [
        "task_id",
        "resource",
        "release_s",
        "execution_s",
        "deadline_s",
        "start_s",
        "finish_s",
        "attempts",
        "thermal_deferrals",
        "invalid_deferrals",
        "stale_deferrals",
        "status",
    ]

    with open(summary_output, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=summary_fields)
        writer.writeheader()

        for task_id, result in results.items():
            task = result["task"]

            writer.writerow({
                "task_id": task_id,
                "resource": task.resource,
                "release_s": task.release_s,
                "execution_s": task.execution_s,
                "deadline_s": task.deadline_s,
                "start_s": result["start_s"],
                "finish_s": result["finish_s"],
                "attempts": result["attempts"],
                "thermal_deferrals": result["thermal_deferrals"],
                "invalid_deferrals": result["invalid_deferrals"],
                "stale_deferrals": result["stale_deferrals"],
                "status": result["status"],
            })

    statuses = Counter(
        result["status"] for result in results.values()
    )

    attempts = Counter(
        row["decision"] for row in event_log
        if row["event"] == "ADMISSION_ATTEMPT"
    )

    print("\nPREDICTIVE RT-TAS DISPATCHER V2")
    print("=" * 60)
    print("Mode: CHRONOLOGICAL DISCRETE-EVENT REPLAY")
    print("Tasks:", len(TASKS))
    print("Thermal decision records:", len(decisions))
    print("Task timing unit: seconds")
    print("CPU/GPU queues: Independent non-preemptive EDF")
    print("Maximum decision gap:", args.max_gap, "seconds")
    print("Real workload execution: NO")

    print("\nAdmission attempts:")
    for name, count in sorted(attempts.items()):
        print(f"{name:<24}: {count}")

    print("\nFinal task outcomes:")
    for name, count in sorted(statuses.items()):
        print(f"{name:<24}: {count}")

    print("\nTask summary:")
    print(
        f"{'Task':<6}{'Resource':<9}"
        f"{'Start':<10}{'Finish':<10}"
        f"{'Deadline':<10}{'Status'}"
    )

    for task_id, result in results.items():
        task = result["task"]

        print(
            f"{task_id:<6}{task.resource:<9}"
            f"{str(result['start_s']):<10}"
            f"{str(result['finish_s']):<10}"
            f"{task.deadline_s:<10}"
            f"{result['status']}"
        )

    print("\nPending tasks at end:")
    for resource in ("CPU", "GPU"):
        ids = [
            t.task_id for t in pending[resource]
        ]
        print(f"{resource}: {ids if ids else 'None'}")

    print("\nEvent log:", event_output)
    print("Task summary:", summary_output)


if __name__ == "__main__":
    main()
