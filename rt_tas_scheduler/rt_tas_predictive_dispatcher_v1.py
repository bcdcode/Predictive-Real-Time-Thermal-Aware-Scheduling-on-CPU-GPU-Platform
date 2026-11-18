#!/usr/bin/env python3

"""
Predictive RT-TAS Dispatcher V1
--------------------------------
Chronological replay of live predictive thermal decisions
with independent CPU/GPU EDF queues.

Features:
- Independent non-preemptive CPU/GPU scheduling
- Release-time and deadline handling
- Live-controller decision CSV as input
- Thermal and invalid-prediction deferrals
- Pending tasks are retried when new decisions arrive
- Task-level execution and decision logging

IMPORTANT:
This version is a discrete-event scheduling evaluation.
It does NOT execute real CPU/GPU workloads.
"""

import argparse
import csv
import math
import os
from collections import Counter, defaultdict
from dataclasses import dataclass


@dataclass
class Task:
    task_id: str
    resource: str
    release_ms: int
    execution_ms: int
    deadline_ms: int


TASKS = [
    Task("T1", "CPU", 0, 10, 30),
    Task("T2", "GPU", 0, 20, 50),
    Task("T3", "CPU", 5, 15, 60),
    Task("T4", "GPU", 10, 15, 55),
    Task("T5", "CPU", 15, 10, 50),
    Task("T6", "GPU", 20, 10, 70),
    Task("T7", "CPU", 25, 12, 65),
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
    }

    decisions = []

    with open(path, newline="") as f:
        reader = csv.DictReader(f)

        missing = required - set(reader.fieldnames or [])
        if missing:
            raise ValueError(
                "Missing decision columns: " + ", ".join(sorted(missing))
            )

        for row in reader:
            elapsed = finite_float(row["elapsed_s"])
            monotonic = finite_float(row["monotonic_elapsed_s"])

            if elapsed is None or monotonic is None:
                continue

            decisions.append({
                "time_ms": int(round(elapsed * 1000)),
                "monotonic": monotonic,
                "status": row["prediction_status"],
                "cpu": row["cpu_decision"],
                "gpu": row["gpu_decision"],
                "phase": row.get("phase", ""),
                "cpu_safe": row.get("cpu_safe_C", ""),
                "gpu_safe": row.get("gpu_safe_C", ""),
            })

    decisions.sort(key=lambda x: x["time_ms"])

    if not decisions:
        raise ValueError("No usable decision records found.")

    return decisions


def simulate(tasks, decisions):
    resources = ("CPU", "GPU")

    pending = {
        r: [t for t in tasks if t.resource == r]
        for r in resources
    }

    running = {r: None for r in resources}
    latest_decision = {r: None for r in resources}

    completed = []
    log = []

    # Each resource has an independent execution timeline.
    for sample in decisions:
        now = sample["time_ms"]

        # Update the latest decision independently.
        latest_decision["CPU"] = sample
        latest_decision["GPU"] = sample

        for resource in resources:

            # Finish any task whose simulated execution has ended.
            active = running[resource]

            if active is not None and active["finish_ms"] <= now:
                active["completion_status"] = (
                    "MET"
                    if active["finish_ms"] <= active["task"].deadline_ms
                    else "DEADLINE_MISS"
                )
                completed.append(active)
                running[resource] = None

            # A resource can execute only one non-preemptive task.
            if running[resource] is not None:
                continue

            ready = [
                t for t in pending[resource]
                if t.release_ms <= now
            ]

            if not ready:
                continue

            # EDF: earliest absolute deadline first.
            task = min(
                ready,
                key=lambda t: (t.deadline_ms, t.release_ms, t.task_id)
            )

            decision = latest_decision[resource][resource.lower()]

            if decision != "ADVISORY_ADMIT":
                log.append({
                    "time_ms": now,
                    "phase": sample["phase"],
                    "task_id": task.task_id,
                    "resource": resource,
                    "release_ms": task.release_ms,
                    "deadline_ms": task.deadline_ms,
                    "decision": decision,
                    "execution_start_ms": "",
                    "execution_finish_ms": "",
                    "result": "PENDING",
                })
                continue

            start = now
            finish = start + task.execution_ms

            record = {
                "task": task,
                "start_ms": start,
                "finish_ms": finish,
                "completion_status": "",
            }

            running[resource] = record
            pending[resource].remove(task)

            log.append({
                "time_ms": now,
                "phase": sample["phase"],
                "task_id": task.task_id,
                "resource": resource,
                "release_ms": task.release_ms,
                "deadline_ms": task.deadline_ms,
                "decision": "ADVISORY_ADMIT",
                "execution_start_ms": start,
                "execution_finish_ms": finish,
                "result": "SIMULATED_RUNNING",
            })

    # Finish remaining simulated tasks after the final decision sample.
    final_time = decisions[-1]["time_ms"]

    for resource in resources:
        active = running[resource]

        if active is not None:
            active["completion_status"] = (
                "MET"
                if active["finish_ms"] <= active["task"].deadline_ms
                else "DEADLINE_MISS"
            )
            completed.append(active)

    return log, completed, pending


def main():
    parser = argparse.ArgumentParser(
        description="Predictive RT-TAS chronological EDF dispatcher"
    )

    parser.add_argument("--input", required=True)
    parser.add_argument("--output", default=None)

    args = parser.parse_args()

    if not os.path.isfile(args.input):
        parser.error("Decision CSV does not exist.")

    try:
        decisions = load_decisions(args.input)
    except ValueError as exc:
        parser.error(str(exc))

    log, completed, pending = simulate(TASKS, decisions)

    output = args.output or (
        os.path.splitext(args.input)[0]
        + "_predictive_dispatch_v1.csv"
    )

    fields = [
        "time_ms", "phase", "task_id", "resource",
        "release_ms", "deadline_ms", "decision",
        "execution_start_ms", "execution_finish_ms", "result"
    ]

    with open(output, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(log)

    print("\nPREDICTIVE RT-TAS DISPATCHER V1")
    print("=" * 60)
    print("Mode: CHRONOLOGICAL DISCRETE-EVENT REPLAY")
    print("Tasks:", len(TASKS))
    print("Decision records:", len(decisions))
    print("CPU/GPU queues: Independent EDF")
    print("Real workload execution: NO")

    counts = Counter(row["decision"] for row in log)

    print("\nDispatch decision counts:")
    for key, value in sorted(counts.items()):
        print(f"{key:<22}: {value}")

    print("\nCompleted simulated tasks:")

    for item in sorted(
        completed,
        key=lambda x: (x["start_ms"], x["task"].task_id)
    ):
        task = item["task"]
        print(
            f"{task.task_id:<5} {task.resource:<4} "
            f"start={item['start_ms']:>5} ms "
            f"finish={item['finish_ms']:>5} ms "
            f"deadline={task.deadline_ms:>5} ms "
            f"{item['completion_status']}"
        )

    print("\nPending tasks:")
    for resource in ("CPU", "GPU"):
        ids = [t.task_id for t in pending[resource]]
        print(f"{resource}: {ids if ids else 'None'}")

    print("\nOutput:", output)


if __name__ == "__main__":
    main()
