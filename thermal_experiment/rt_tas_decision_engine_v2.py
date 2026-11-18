#!/usr/bin/env python3

import csv
import sys
import math
from pathlib import Path
from collections import Counter, defaultdict

EPSILON_C = 0.05

IDLE_PHASES = {
    "IDLE_BASELINE1",
    "IDLE_BASELINE2"
}

COOLDOWN_PHASES = {
    "COOLDOWN1",
    "COOLDOWN2"
}

KNOWN_PHASES = IDLE_PHASES | COOLDOWN_PHASES | {
    "SIMULTANEOUS", "TA_CPU", "TA_GPU"
}

OUTPUT_FIELDS = [
    "timestamp",
    "elapsed_s",
    "phase",
    "cpu_actual_C",
    "cpu_predicted_1s_C",
    "cpu_predicted_rise_C",
    "gpu_actual_C",
    "gpu_predicted_1s_C",
    "gpu_predicted_rise_C",
    "prediction_status",
    "scheduler_decision",
    "decision_reason",
    "decision_mode"
]


def to_float(value):
    try:
        result = float(str(value).strip())
        return result if math.isfinite(result) else None
    except (TypeError, ValueError):
        return None


def make_result(row, decision, reason, cpu_rise=None, gpu_rise=None):
    return {
        "timestamp": row.get("timestamp", "").strip(),
        "elapsed_s": row.get("elapsed_s", "").strip(),
        "phase": row.get("phase", "").strip(),
        "cpu_actual_C": row.get("cpu_actual_C", "").strip(),
        "cpu_predicted_1s_C": row.get("cpu_predicted_1s_C", "").strip(),
        "cpu_predicted_rise_C": (
            "" if cpu_rise is None else round(cpu_rise, 4)
        ),
        "gpu_actual_C": row.get("gpu_actual_C", "").strip(),
        "gpu_predicted_1s_C": row.get("gpu_predicted_1s_C", "").strip(),
        "gpu_predicted_rise_C": (
            "" if gpu_rise is None else round(gpu_rise, 4)
        ),
        "prediction_status": row.get("prediction_status", "").strip(),
        "scheduler_decision": decision,
        "decision_reason": reason,
        "decision_mode": "SHADOW_ONLY"
    }


def decide(row):
    phase = row.get("phase", "").strip()
    status = row.get("prediction_status", "").strip()

    # Idle and cooldown are observation-only phases.
    if phase in IDLE_PHASES:
        return make_result(
            row, "MONITOR_ONLY",
            "Idle baseline phase: no workload admission decision"
        )

    if phase in COOLDOWN_PHASES:
        return make_result(
            row, "MONITOR_ONLY",
            "Cooldown phase: preserve cooldown; do not admit workloads"
        )

    if phase not in KNOWN_PHASES:
        return make_result(
            row, "BASELINE_FALLBACK",
            "Unknown experimental phase"
        )

    if status != "FORECAST_ONLY":
        return make_result(
            row, "BASELINE_FALLBACK",
            "Forecast unavailable or skipped"
        )

    cpu_actual = to_float(row.get("cpu_actual_C"))
    cpu_pred = to_float(row.get("cpu_predicted_1s_C"))
    gpu_actual = to_float(row.get("gpu_actual_C"))
    gpu_pred = to_float(row.get("gpu_predicted_1s_C"))

    if None in (cpu_actual, cpu_pred, gpu_actual, gpu_pred):
        return make_result(
            row, "BASELINE_FALLBACK",
            "Missing or invalid temperature prediction"
        )

    cpu_rise = cpu_pred - cpu_actual
    gpu_rise = gpu_pred - gpu_actual

    cpu_rising = cpu_rise > EPSILON_C
    gpu_rising = gpu_rise > EPSILON_C

    # Both workloads are already active in this phase.
    # This evaluates admission of ADDITIONAL concurrent work.
    if phase == "SIMULTANEOUS":
        if cpu_rising and gpu_rising:
            decision = "DEFER_ADDITIONAL_CONCURRENT_WORK"
            reason = "Both predicted temperatures are rising"
        else:
            decision = "CONCURRENT_ADMISSION_CANDIDATE"
            reason = (
                "At least one predicted temperature is stable or falling; "
                "check workload and deadline constraints"
            )

    # CPU is the current workload. Evaluate admission of GPU work.
    elif phase == "TA_CPU":
        if gpu_rising:
            decision = "DEFER_GPU_ADMISSION"
            reason = (
                "GPU temperature is predicted to rise while CPU work is active"
            )
        else:
            decision = "GPU_ADMISSION_CANDIDATE"
            reason = (
                "GPU temperature is predicted stable or falling; "
                "check workload and deadline constraints"
            )

    # GPU is the current workload. Evaluate admission of CPU work.
    elif phase == "TA_GPU":
        if cpu_rising:
            decision = "DEFER_CPU_ADMISSION"
            reason = (
                "CPU temperature is predicted to rise while GPU work is active"
            )
        else:
            decision = "CPU_ADMISSION_CANDIDATE"
            reason = (
                "CPU temperature is predicted stable or falling; "
                "check workload and deadline constraints"
            )

    else:
        decision = "BASELINE_FALLBACK"
        reason = "No scheduling rule defined for this phase"

    return make_result(
        row, decision, reason, cpu_rise, gpu_rise
    )


def main():
    if len(sys.argv) < 2:
        print(
            "Usage: python3 rt_tas_decision_engine_v2.py "
            "<predictions.csv> [output.csv]"
        )
        sys.exit(1)

    input_path = Path(sys.argv[1])

    if not input_path.is_file():
        print("ERROR: Input file not found:", input_path)
        sys.exit(1)

    if len(sys.argv) >= 3:
        output_path = Path(sys.argv[2])
    else:
        output_path = input_path.with_name(
            input_path.stem + "_decisions_v2.csv"
        )

    counts = Counter()
    phase_counts = defaultdict(Counter)
    total = 0

    with input_path.open(
        "r", newline="", encoding="utf-8-sig"
    ) as infile:

        reader = csv.DictReader(infile)

        required = {
            "timestamp", "elapsed_s", "phase",
            "cpu_actual_C", "cpu_predicted_1s_C",
            "gpu_actual_C", "gpu_predicted_1s_C",
            "prediction_status"
        }

        if not required.issubset(set(reader.fieldnames or [])):
            print("ERROR: Required CSV columns are missing.")
            print("Found:", reader.fieldnames)
            sys.exit(1)

        with output_path.open(
            "w", newline="", encoding="utf-8"
        ) as outfile:

            writer = csv.DictWriter(
                outfile, fieldnames=OUTPUT_FIELDS
            )
            writer.writeheader()

            for row in reader:
                result = decide(row)
                writer.writerow(result)

                decision = result["scheduler_decision"]
                phase = result["phase"]

                counts[decision] += 1
                phase_counts[phase][decision] += 1
                total += 1

    print("\nRT-TAS DECISION ENGINE V2")
    print("=" * 55)
    print("Input :", input_path)
    print("Output:", output_path)
    print("Rows  :", total)

    print("\nOVERALL DECISION DISTRIBUTION")
    for decision, count in sorted(counts.items()):
        print("{:<42} {}".format(decision, count))

    print("\nPHASE-WISE DECISIONS")
    for phase, decisions in phase_counts.items():
        print("\n" + phase)
        for decision, count in sorted(decisions.items()):
            print("  {:<40} {}".format(decision, count))

    print("\nMODE: SHADOW ONLY")
    print("No workload was started, stopped, paused, or resumed.")
    print("Decision log generated successfully.")


if __name__ == "__main__":
    main()
