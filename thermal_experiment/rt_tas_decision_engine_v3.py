#!/usr/bin/env python3

import csv
import glob
import math
import os
import statistics
from collections import Counter, defaultdict

EPSILON_C = 0.05

IDLE_PHASES = {"IDLE_BASELINE1", "IDLE_BASELINE2"}
COOLDOWN_PHASES = {"COOLDOWN1", "COOLDOWN2"}

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
    "v2_scheduler_decision",
    "scheduler_decision",
    "decision_reason",
    "decision_mode"
]

SAMPLE_FIELDS = [
    "run",
    "phase",
    "elapsed_s",
    "v2_decision",
    "v3_decision",
    "cpu_predicted_rise_C",
    "cpu_actual_change_C",
    "gpu_predicted_rise_C",
    "gpu_actual_change_C"
]


def read_csv(path):
    with open(path, newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def to_float(value):
    try:
        result = float(str(value).strip())
        return result if math.isfinite(result) else None
    except (TypeError, ValueError):
        return None


def elapsed_key(value):
    number = to_float(value)
    return int(round(number)) if number is not None else None


def decide(row):
    phase = row.get("phase", "").strip()
    status = row.get("prediction_status", "").strip()

    cpu_actual = to_float(row.get("cpu_actual_C"))
    cpu_pred = to_float(row.get("cpu_predicted_1s_C"))
    gpu_actual = to_float(row.get("gpu_actual_C"))
    gpu_pred = to_float(row.get("gpu_predicted_1s_C"))

    if phase in IDLE_PHASES:
        return "MONITOR_ONLY", "Idle phase: observation only", None, None

    if phase in COOLDOWN_PHASES:
        return "MONITOR_ONLY", "Cooldown phase: preserve cooldown", None, None

    if phase not in KNOWN_PHASES:
        return "BASELINE_FALLBACK", "Unknown experimental phase", None, None

    if status != "FORECAST_ONLY":
        return "BASELINE_FALLBACK", "Forecast unavailable or skipped", None, None

    if None in (cpu_actual, cpu_pred, gpu_actual, gpu_pred):
        return "BASELINE_FALLBACK", "Missing or invalid temperature prediction", None, None

    cpu_rise = cpu_pred - cpu_actual
    gpu_rise = gpu_pred - gpu_actual

    # Conservative V3 rule:
    # Both CPU and GPU must be stable or falling.
    both_stable = (
        cpu_rise <= EPSILON_C and
        gpu_rise <= EPSILON_C
    )

    if phase == "SIMULTANEOUS":
        if both_stable:
            decision = "CONCURRENT_ADMISSION_CANDIDATE"
            reason = "Both predicted temperatures are stable or falling"
        else:
            decision = "DEFER_ADDITIONAL_CONCURRENT_WORK"
            reason = "At least one predicted temperature is rising"

    elif phase == "TA_CPU":
        if both_stable:
            decision = "GPU_ADMISSION_CANDIDATE"
            reason = "Both temperatures are stable or falling; GPU admission may be evaluated"
        else:
            decision = "DEFER_GPU_ADMISSION"
            reason = "At least one temperature is rising during CPU workload"

    elif phase == "TA_GPU":
        if both_stable:
            decision = "CPU_ADMISSION_CANDIDATE"
            reason = "Both temperatures are stable or falling; CPU admission may be evaluated"
        else:
            decision = "DEFER_CPU_ADMISSION"
            reason = "At least one temperature is rising during GPU workload"

    else:
        decision = "BASELINE_FALLBACK"
        reason = "No V3 rule defined for this phase"

    return decision, reason, cpu_rise, gpu_rise


def mean(values):
    values = [v for v in values if v is not None]
    return statistics.mean(values) if values else None


def fmt(value):
    return f"{value:10.3f}" if value is not None else "       N/A"


def main():

    prediction_files = sorted(
        glob.glob("*_live_predictions.csv")
    )

    all_samples = []
    v2_counts = Counter()
    v3_counts = Counter()
    processed_runs = 0

    print("\nRT-TAS DECISION ENGINE V3 - OFFLINE EVALUATION")
    print("=" * 90)

    for prediction_path in prediction_files:

        v2_path = prediction_path.replace(
            "_live_predictions.csv",
            "_live_predictions_decisions_v2.csv"
        )

        if not os.path.isfile(v2_path):
            print("SKIPPED: Missing V2 file:", v2_path)
            continue

        predictions = read_csv(prediction_path)
        v2_rows = read_csv(v2_path)

        if not predictions or not v2_rows:
            print("SKIPPED: Empty input:", prediction_path)
            continue

        run_name = os.path.basename(
            prediction_path
        ).replace("_live_predictions.csv", "")

        # Index V2 decisions for direct comparison.
        v2_lookup = {}

        for row in v2_rows:
            key = (
                row.get("phase", "").strip(),
                elapsed_key(row.get("elapsed_s"))
            )
            v2_lookup[key] = row.get(
                "scheduler_decision", ""
            ).strip()

        # Index actual temperatures for next-second matching.
        actual_lookup = {}

        for row in predictions:
            key = (
                row.get("phase", "").strip(),
                elapsed_key(row.get("elapsed_s"))
            )

            actual_lookup[key] = {
                "cpu": to_float(row.get("cpu_actual_C")),
                "gpu": to_float(row.get("gpu_actual_C"))
            }

        output_path = prediction_path.replace(
            "_live_predictions.csv",
            "_live_predictions_decisions_v3.csv"
        )

        run_samples = []
        run_v3_counts = Counter()

        with open(output_path, "w", newline="", encoding="utf-8") as f:

            writer = csv.DictWriter(
                f, fieldnames=OUTPUT_FIELDS
            )
            writer.writeheader()

            for row in predictions:

                decision, reason, cpu_rise, gpu_rise = decide(row)

                phase = row.get("phase", "").strip()
                elapsed = elapsed_key(row.get("elapsed_s"))

                key = (phase, elapsed)
                v2_decision = v2_lookup.get(key, "MISSING_V2_DECISION")

                result = {
                    "timestamp": row.get("timestamp", ""),
                    "elapsed_s": row.get("elapsed_s", ""),
                    "phase": phase,
                    "cpu_actual_C": row.get("cpu_actual_C", ""),
                    "cpu_predicted_1s_C": row.get("cpu_predicted_1s_C", ""),
                    "cpu_predicted_rise_C": (
                        "" if cpu_rise is None else round(cpu_rise, 4)
                    ),
                    "gpu_actual_C": row.get("gpu_actual_C", ""),
                    "gpu_predicted_1s_C": row.get("gpu_predicted_1s_C", ""),
                    "gpu_predicted_rise_C": (
                        "" if gpu_rise is None else round(gpu_rise, 4)
                    ),
                    "prediction_status": row.get("prediction_status", ""),
                    "v2_scheduler_decision": v2_decision,
                    "scheduler_decision": decision,
                    "decision_reason": reason,
                    "decision_mode": "OFFLINE_SHADOW_ONLY"
                }

                writer.writerow(result)

                v3_counts[decision] += 1
                v3_counts_global = decision
                v3_counts[v3_counts_global] += 0

                if v2_decision != "MISSING_V2_DECISION":
                    v2_counts[v2_decision] += 1

                # Validate against actual next-second measurements.
                if decision in {
                    "MONITOR_ONLY",
                    "BASELINE_FALLBACK"
                }:
                    continue

                current = actual_lookup.get(key)
                following = actual_lookup.get((phase, elapsed + 1))

                if current is None or following is None:
                    continue

                if None in (
                    current["cpu"], current["gpu"],
                    following["cpu"], following["gpu"],
                    cpu_rise, gpu_rise
                ):
                    continue

                sample = {
                    "run": run_name,
                    "phase": phase,
                    "elapsed_s": elapsed,
                    "v2_decision": v2_decision,
                    "v3_decision": decision,
                    "cpu_predicted_rise_C": cpu_rise,
                    "cpu_actual_change_C": following["cpu"] - current["cpu"],
                    "gpu_predicted_rise_C": gpu_rise,
                    "gpu_actual_change_C": following["gpu"] - current["gpu"]
                }

                run_samples.append(sample)
                all_samples.append(sample)

        processed_runs += 1

        print(
            f"PROCESSED: {run_name} | "
            f"V3 decisions: {sum(v3_counts.values())} "
            f"| matched samples: {len(run_samples)}"
        )

    if not processed_runs:
        print("\nNo matching prediction/V2 decision pairs found.")
        return

    # Save combined validation observations.
    sample_path = "rt_tas_v3_multirun_validation_samples.csv"

    with open(sample_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=SAMPLE_FIELDS)
        writer.writeheader()
        writer.writerows(all_samples)

    print("\nV2 VS V3 OVERALL DECISION DISTRIBUTION")
    print("=" * 90)
    print(f"{'DECISION':42s}{'V2':>10s}{'V3':>10s}")

    for decision in sorted(set(v2_counts) | set(v3_counts)):
        print(
            f"{decision:42s}"
            f"{v2_counts[decision]:10d}"
            f"{v3_counts[decision]:10d}"
        )

    print("\nV3 THERMAL VALIDATION BY DECISION")
    print("=" * 105)
    print(
        f"{'V3 DECISION':38s}"
        f"{'N':>6s}"
        f"{'RUNS':>7s}"
        f"{'CPU_PRED':>11s}"
        f"{'CPU_ACT':>11s}"
        f"{'GPU_PRED':>11s}"
        f"{'GPU_ACT':>11s}"
    )

    groups = defaultdict(list)

    for sample in all_samples:
        groups[sample["v3_decision"]].append(sample)

    for decision, samples in sorted(groups.items()):
        runs = set(s["run"] for s in samples)

        print(
            f"{decision:38s}"
            f"{len(samples):6d}"
            f"{len(runs):7d}"
            f"{fmt(mean([s['cpu_predicted_rise_C'] for s in samples]))}"
            f"{fmt(mean([s['cpu_actual_change_C'] for s in samples]))}"
            f"{fmt(mean([s['gpu_predicted_rise_C'] for s in samples]))}"
            f"{fmt(mean([s['gpu_actual_change_C'] for s in samples]))}"
        )

    print("\nV3 PER-RUN THERMAL VALIDATION")
    print("=" * 100)

    print(
        f"{'RUN':38s}"
        f"{'DECISION':34s}"
        f"{'N':>5s}"
        f"{'CPU_ACT':>11s}"
        f"{'GPU_ACT':>11s}"
    )

    for decision, samples in sorted(groups.items()):
        by_run = defaultdict(list)

        for sample in samples:
            by_run[sample["run"]].append(sample)

        for run, rows in sorted(by_run.items()):
            print(
                f"{run:38s}"
                f"{decision:34s}"
                f"{len(rows):5d}"
                f"{fmt(mean([s['cpu_actual_change_C'] for s in rows]))}"
                f"{fmt(mean([s['gpu_actual_change_C'] for s in rows]))}"
            )

    print("\nSUMMARY")
    print("=" * 90)
    print("Prediction/V2 runs processed :", processed_runs)
    print("V3 matched observations      :", len(all_samples))
    print("V3 output files              : *_live_predictions_decisions_v3.csv")
    print("Combined validation samples  :", sample_path)
    print("\nMODE: OFFLINE SHADOW EVALUATION")
    print("No workload was started, stopped, paused, or resumed.")


if __name__ == "__main__":
    main()

