#!/usr/bin/env python3

import csv
import glob
import os
import time
from datetime import datetime
from collections import deque

CPU_TEMP = "/sys/class/hwmon/hwmon2/temp1_input"
GPU_TEMP = "/sys/class/hwmon/hwmon1/temp1_input"
GPU_FREQ = "/sys/class/hwmon/hwmon1/freq1_input"
GPU_CONTROL = os.path.expanduser(
    "~/thermal_experiment/gpu_control.txt"
)
INTERVAL = 1.0
HISTORY_SECONDS = 6

OUTPUT = "thermal_predictor_shadow_" + datetime.now().strftime(
    "%Y%m%d_%H%M%S"
) + ".csv"


def read_number(path, divisor=1.0):
    try:
        with open(path) as f:
            return float(f.read().strip()) / divisor
    except (OSError, ValueError):
        return None


def process_active(names):
    """Read-only check for existing workload processes."""
    for name in names:
        for path in glob.glob("/proc/[0-9]*/comm"):
            try:
                with open(path) as f:
                    if f.read().strip() == name:
                        return 1
            except (OSError, ValueError):
                pass
    return 0

def gpu_workload_enabled():
    """Check whether the controlled GPU workload is enabled."""
    try:
        with open(GPU_CONTROL) as f:
            return 1 if f.read().strip().upper() == "ON" else 0
    except OSError:
        return 0

def gpu_activity_proxy(freq_mhz):
    # Frequency-derived proxy, NOT actual GPU utilization.
    if freq_mhz is None:
        return None
    return max(0.0, min(1.0, (freq_mhz - 400.0) / 1600.0))


def difference_from_past(history, now, seconds, key):
    candidates = [
        row for row in history
        if now - row["time"] >= seconds - 0.5
        and now - row["time"] <= seconds + 1.5
        and row.get(key) is not None
    ]
    if not candidates:
        return None
    old = min(candidates, key=lambda row: abs(
        (now - row["time"]) - seconds
    ))
    return old[key]


def main():
    history = deque(maxlen=HISTORY_SECONDS + 3)
    previous_states = None

    fields = [
        "timestamp", "elapsed_s", "phase",
        "cpu_tctl_C", "gpu_edge_C", "gpu_freq_MHz",
        "gpu_activity_proxy", "cpu_active", "gpu_enabled",
        "gpu_temp_rising", "gpu_freq_increasing",
        "gpu_activity_increasing", "cpu_temp_rising",
        "recent_transition", "dynamic_score",
        "prediction_level", "recommended_action",
    ]

    start = time.monotonic()

    print("RT_TAS thermal predictor — SHADOW MODE")
    print("Output:", OUTPUT)
    print("This script does not start, stop, or reschedule workloads.")
    print("Press Ctrl+C to stop.")
    print()

    try:
        with open(OUTPUT, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fields)
            writer.writeheader()
            f.flush()

            while True:
                tick = time.monotonic()
                elapsed = tick - start

                cpu_temp = read_number(CPU_TEMP, 1000.0)
                gpu_temp = read_number(GPU_TEMP, 1000.0)
                gpu_freq = read_number(GPU_FREQ, 1_000_000.0)
                activity = gpu_activity_proxy(gpu_freq)

                cpu_active = process_active(["cpu_duty", "cpu_burn"])
                gpu_enabled = gpu_workload_enabled()

                phase = (
                    "CPU_GPU_ACTIVE" if cpu_active and gpu_enabled
                    else "CPU_ACTIVE" if cpu_active
                    else "GPU_ACTIVE" if gpu_enabled
                    else "IDLE_OR_OTHER"
                )

                current = {
                    "time": tick,
                    "cpu_temp": cpu_temp,
                    "gpu_temp": gpu_temp,
                    "gpu_freq": gpu_freq,
                    "activity": activity,
                    "cpu_active": cpu_active,
                    "gpu_enabled": gpu_enabled,
                }

                gpu_temp_delta = None
                gpu_freq_delta = None
                activity_delta = None
                cpu_temp_delta = None

                for key, output_key in [
                    ("gpu_temp", "gpu_temp_delta"),
                    ("gpu_freq", "gpu_freq_delta"),
                    ("activity", "activity_delta"),
                    ("cpu_temp", "cpu_temp_delta"),
                ]:
                    past = difference_from_past(
                        history, tick, 4.0, key
                    )
                    current[output_key] = (
                        current[key] - past
                        if current[key] is not None and past is not None
                        else None
                    )

                gpu_temp_delta = current["gpu_temp_delta"]
                gpu_freq_delta = current["gpu_freq_delta"]
                activity_delta = current["activity_delta"]
                cpu_temp_delta = current["cpu_temp_delta"]

				# GPU temperature trend remains active during workload and recovery.
                gpu_temp_rising = int(
                    gpu_temp_delta is not None
                    and gpu_temp_delta >= 0.15
                )

                # GPU frequency trend counts only during controlled GPU activity.
                gpu_freq_increasing = int(
                    gpu_enabled
                    and gpu_freq_delta is not None
                    and gpu_freq_delta >= 25.0
                )

                # GPU activity-proxy trend counts only during controlled GPU activity.
                gpu_activity_increasing = int(
                    gpu_enabled
                    and activity_delta is not None
                    and activity_delta >= 0.05
                )
                # Offline feature used temperature slope in C/second.
                cpu_temp_rising = int(
                    cpu_temp_delta is not None
                    and cpu_temp_delta / 4.0 >= 0.05
                )

                states = (cpu_active, gpu_enabled)
                recent_transition = int(
                    previous_states is not None
                    and states != previous_states
                )

                # Preserve state changes for the following 5 seconds.
                transition_history = [
                    row for row in history
                    if tick - row["time"] <= 5.0
                ]
                if any(row["states"] != states for row in transition_history):
                    recent_transition = 1

                score = (
                    2 * gpu_temp_rising
                    + gpu_freq_increasing
                    + gpu_activity_increasing
                    + cpu_temp_rising
                    + cpu_active
                    + recent_transition
                )

                # Provisional threshold from a small exploratory run.
                # Shadow mode only: never change task placement or execution.
                if score >= 3:
                    level = "THRESHOLD_MET"
                    action = "SHADOW_ONLY_REVIEW_TWFD_PLACEMENT"
                else:
                    level = "BELOW_THRESHOLD"
                    action = "SHADOW_ONLY_KEEP_TWFD_UNCHANGED"

                row = {
                    "timestamp": datetime.now().isoformat(
                        timespec="seconds"
                    ),
                    "elapsed_s": round(elapsed, 2),
                    "phase": phase,
                    "cpu_tctl_C": cpu_temp,
                    "gpu_edge_C": gpu_temp,
                    "gpu_freq_MHz": gpu_freq,
                    "gpu_activity_proxy": activity,
                    "cpu_active": cpu_active,
                    "gpu_enabled": gpu_enabled,
                    "gpu_temp_rising": gpu_temp_rising,
                    "gpu_freq_increasing": gpu_freq_increasing,
                    "gpu_activity_increasing": gpu_activity_increasing,
                    "cpu_temp_rising": cpu_temp_rising,
                    "recent_transition": recent_transition,
                    "dynamic_score": score,
                    "prediction_level": level,
                    "recommended_action": action,
                }

                writer.writerow(row)
                f.flush()

                print(
                    f"\rElapsed={elapsed:6.0f}s "
                    f"CPU={cpu_temp if cpu_temp is not None else 'NA'} "
                    f"GPU={gpu_temp if gpu_temp is not None else 'NA'} "
                    f"Score={score}/7 {level}       ",
                    end="",
                    flush=True,
                )

                current["states"] = states
                history.append(current)
                previous_states = states

                remaining = INTERVAL - (time.monotonic() - tick)
                if remaining > 0:
                    time.sleep(remaining)

    except KeyboardInterrupt:
        print("\nShadow logger stopped.")
        print("CSV saved to:", OUTPUT)


if __name__ == "__main__":
    main()
