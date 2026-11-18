#!/usr/bin/env python3

"""
RT-TAS Scheduler V2
Independent EDF + advisory thermal-headroom simulation.

This version:
- Preserves the V1 task model and EDF policy.
- Requires explicit CPU and GPU thermal limits.
- Uses configurable empirical prediction margins.
- Rejects admission when thermal or deadline checks fail.
- Does not launch, pause, or control real workloads.

This is a simulation, not a live hardware controller.
"""

from dataclasses import dataclass
import argparse


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


def parse_args():
    parser = argparse.ArgumentParser(
        description="RT-TAS V2 advisory EDF thermal scheduler"
    )

    parser.add_argument("--cpu-temp", type=float, required=True)
    parser.add_argument("--gpu-temp", type=float, required=True)
    parser.add_argument("--cpu-limit", type=float, required=True)
    parser.add_argument("--gpu-limit", type=float, required=True)

    parser.add_argument("--cpu-margin", type=float, default=0.75)
    parser.add_argument("--gpu-margin", type=float, default=1.00)

    return parser.parse_args()


def validate(args):
    values = [
        args.cpu_temp,
        args.gpu_temp,
        args.cpu_limit,
        args.gpu_limit,
        args.cpu_margin,
        args.gpu_margin,
    ]

    if not all(map(lambda x: x == x and abs(x) != float("inf"), values)):
        raise ValueError("All temperature inputs must be finite numbers.")

    if args.cpu_margin < 0 or args.gpu_margin < 0:
        raise ValueError("Prediction margins cannot be negative.")

    if args.cpu_limit <= 0 or args.gpu_limit <= 0:
        raise ValueError("Thermal limits must be positive.")

    if args.cpu_temp < 0 or args.gpu_temp < 0:
        raise ValueError("Temperatures cannot be negative.")


def schedule_resource(tasks, resource, current_temp, limit, margin):
    pending = [t for t in tasks if t.resource == resource]
    current_time = 0
    results = []

    while pending:
        ready = [
            t for t in pending
            if t.release_ms <= current_time
        ]

        if not ready:
            current_time = min(t.release_ms for t in pending)
            ready = [
                t for t in pending
                if t.release_ms <= current_time
            ]

        selected = min(ready, key=lambda t: t.deadline_ms)

        start = max(current_time, selected.release_ms)
        finish = start + selected.execution_ms

        # Conservative estimate based on the supplied temperature
        # and empirical prediction margin.
        safe_temp = current_temp + margin

        thermal_ok = safe_temp < limit
        deadline_ok = finish <= selected.deadline_ms

        if thermal_ok and deadline_ok:
            decision = "ADVISORY_ADMIT"
            current_time = finish
        else:
            reasons = []
            if not thermal_ok:
                reasons.append("THERMAL_HEADROOM")
            if not deadline_ok:
                reasons.append("DEADLINE")
            decision = "DEFER_" + "_AND_".join(reasons)

            # This simulation does not model a future cooling period.
            # A deferred task is reported and removed from this pass.

        results.append({
            "task": selected,
            "start": start,
            "finish": finish,
            "safe_temp": safe_temp,
            "decision": decision,
        })

        pending.remove(selected)

    return results


def main():
    args = parse_args()
    validate(args)

    print("\nRT-TAS SCHEDULER V2")
    print("Mode: ADVISORY SIMULATION ONLY")
    print("Policy: EDF + thermal-headroom gate")
    print("-" * 100)

    print(
        f"CPU temperature: {args.cpu_temp:.2f} C | "
        f"CPU limit: {args.cpu_limit:.2f} C | "
        f"Margin: {args.cpu_margin:.2f} C"
    )

    print(
        f"GPU temperature: {args.gpu_temp:.2f} C | "
        f"GPU limit: {args.gpu_limit:.2f} C | "
        f"Margin: {args.gpu_margin:.2f} C"
    )

    cpu = schedule_resource(
        TASKS, "CPU",
        args.cpu_temp, args.cpu_limit, args.cpu_margin
    )

    gpu = schedule_resource(
        TASKS, "GPU",
        args.gpu_temp, args.gpu_limit, args.gpu_margin
    )

    combined = sorted(
        cpu + gpu,
        key=lambda entry: entry["start"]
    )

    print("-" * 100)
    print(
        f"{'Task':<8}{'Resource':<10}{'Start':<10}"
        f"{'Finish':<10}{'Deadline':<10}"
        f"{'Safe Temp':<13}{'Decision'}"
    )
    print("-" * 100)

    admitted = 0
    deferred = 0

    for entry in combined:
        task = entry["task"]
        decision = entry["decision"]

        if decision == "ADVISORY_ADMIT":
            admitted += 1
        else:
            deferred += 1

        print(
            f"{task.task_id:<8}{task.resource:<10}"
            f"{entry['start']:<10}{entry['finish']:<10}"
            f"{task.deadline_ms:<10}"
            f"{entry['safe_temp']:<13.2f}{decision}"
        )

    print("-" * 100)
    print(f"Total tasks: {len(combined)}")
    print(f"Advisory admissions: {admitted}")
    print(f"Deferred tasks: {deferred}")
    print("\nNo real CPU/GPU workload was started or controlled.")


if __name__ == "__main__":
    main()
