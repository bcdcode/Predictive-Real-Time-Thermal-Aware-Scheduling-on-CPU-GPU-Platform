from dataclasses import dataclass

@dataclass
class Task:
    task_id: str
    resource: str
    release_ms: int
    execution_ms: int
    deadline_ms: int


# Synthetic CPU-GPU task set for initial testing.
TASKS = [
    Task("T1", "CPU", 0, 10, 30),
    Task("T2", "GPU", 0, 20, 50),
    Task("T3", "CPU", 5, 15, 60),
    Task("T4", "GPU", 10, 15, 55),
    Task("T5", "CPU", 15, 10, 50),
    Task("T6", "GPU", 20, 10, 70),
    Task("T7", "CPU", 25, 12, 65),
]


def schedule_resource(tasks, resource):
    pending = [
        task for task in tasks
        if task.resource == resource
    ]

    current_time = 0
    schedule = []

    while pending:
        # Find tasks that have been released.
        ready = [
            task for task in pending
            if task.release_ms <= current_time
        ]

        # If nothing is ready, advance to the next release.
        if not ready:
            current_time = min(
                task.release_ms for task in pending
            )
            ready = [
                task for task in pending
                if task.release_ms <= current_time
            ]

        # EDF: select the ready task with earliest deadline.
        selected = min(
            ready,
            key=lambda task: task.deadline_ms
        )

        start = current_time
        finish = start + selected.execution_ms

        deadline_met = finish <= selected.deadline_ms

        schedule.append({
            "task": selected,
            "start": start,
            "finish": finish,
            "deadline_met": deadline_met
        })

        current_time = finish
        pending.remove(selected)

    return schedule


def main():
    cpu_schedule = schedule_resource(TASKS, "CPU")
    gpu_schedule = schedule_resource(TASKS, "GPU")

    combined = cpu_schedule + gpu_schedule
    combined.sort(key=lambda entry: entry["start"])

    print("\nRT-TAS SCHEDULER V1")
    print("Baseline: Independent CPU/GPU EDF scheduling")
    print("-" * 78)

    print(
        f"{'Task':<8}{'Resource':<10}"
        f"{'Release':<10}{'Start':<10}"
        f"{'Finish':<10}{'Deadline':<10}{'Status'}"
    )

    print("-" * 78)

    misses = 0

    for entry in combined:
        task = entry["task"]
        status = "MET" if entry["deadline_met"] else "MISSED"

        if not entry["deadline_met"]:
            misses += 1

        print(
            f"{task.task_id:<8}{task.resource:<10}"
            f"{task.release_ms:<10}{entry['start']:<10}"
            f"{entry['finish']:<10}{task.deadline_ms:<10}"
            f"{status}"
        )

    print("-" * 78)
    print(f"Total tasks: {len(combined)}")
    print(f"Deadlines met: {len(combined) - misses}")
    print(f"Deadline misses: {misses}")
    print("\nCPU and GPU are modelled as independent resources.")


if __name__ == "__main__":
    main()

