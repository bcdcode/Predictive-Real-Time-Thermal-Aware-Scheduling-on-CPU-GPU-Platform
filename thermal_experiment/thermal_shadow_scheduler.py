#!/usr/bin/env python3
import csv
from collections import Counter, defaultdict

SOURCE = "rt_tas_controlled_20261026_221300.csv"
OUTPUT = "thermal_shadow_schedule.csv"

# Initial observation threshold, not a hardware safety limit.
# Temperature changes smaller than this are treated as stable.
DELTA_THRESHOLD_C = 0.5

def main():
    with open(SOURCE, newline="") as f:
        rows = list(csv.DictReader(f))

    if not rows:
        raise SystemExit("No source samples found.")

    required = {
        "timestamp", "elapsed_s", "phase",
        "cpu_tctl_C", "gpu_edge_C", "cpu_active", "gpu_enabled"
    }
    missing = required - set(rows[0])
    if missing:
        raise SystemExit(f"Missing source columns: {sorted(missing)}")

    output = []
    counts = Counter()
    previous = None

    for row in rows:
        cpu = float(row["cpu_tctl_C"])
        gpu = float(row["gpu_edge_C"])
        phase = row["phase"]

        # Compare against the previous sample only within the same phase.
        cpu_delta = None
        gpu_delta = None
        if previous and previous["phase"] == phase:
            cpu_delta = cpu - previous["cpu"]
            gpu_delta = gpu - previous["gpu"]

        if row["cpu_active"] == "ON" and row["gpu_enabled"] == "ON":
            action = "OBSERVE_SHARED_LOAD"
            reason = "CPU and GPU workloads active"
        elif cpu_delta is None or gpu_delta is None:
            action = "NO_DECISION"
            reason = "No same-phase previous sample"
        elif gpu_delta >= DELTA_THRESHOLD_C:
            action = "MONITOR_GPU_TREND"
            reason = "GPU temperature rose by at least threshold"
        elif cpu_delta >= DELTA_THRESHOLD_C:
            action = "MONITOR_CPU_TREND"
            reason = "CPU temperature rose by at least threshold"
        else:
            action = "KEEP_RUNNING"
            reason = "No large same-phase temperature rise"

        output.append({
            "timestamp": row["timestamp"],
            "elapsed_s": row["elapsed_s"],
            "phase": phase,
            "cpu_temp_C": cpu,
            "gpu_temp_C": gpu,
            "cpu_delta_C": "" if cpu_delta is None else round(cpu_delta, 3),
            "gpu_delta_C": "" if gpu_delta is None else round(gpu_delta, 3),
            "cpu_active": row["cpu_active"],
            "gpu_enabled": row["gpu_enabled"],
            "recommendation": action,
            "reason": reason,
            "applied": "NO",
        })
        counts[action] += 1
        previous = {"phase": phase, "cpu": cpu, "gpu": gpu}

    with open(OUTPUT, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(output[0]))
        writer.writeheader()
        writer.writerows(output)

    print(f"Read {len(rows)} samples from {SOURCE}")
    print(f"Wrote shadow recommendations to {OUTPUT}")
    print("\nRecommendation counts:")
    for action, count in sorted(counts.items()):
        print(f"{action:<24} {count:>4}")
    print("\nNo scheduling action was applied.")

if __name__ == "__main__":
    main()
