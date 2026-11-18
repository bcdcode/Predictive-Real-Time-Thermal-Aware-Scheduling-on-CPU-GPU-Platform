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
    "v3_scheduler_decision",
    "scheduler_decision",
    "decision_reason",
    "decision_mode"
]


def number(value):
    try:
        result = float(str(value).strip())
        return result if math.isfinite(result) else None
    except (TypeError, ValueError):
        return None


def elapsed_key(value):
    result = number(value)
    return int(round(result)) if result is not None else None


def mean(values):
    return statistics.mean(values) if values else None


def fmt(value):
    return f"{value:10.3f}" if value is not None else "       N/A"


def read_csv(path):
    with open(path, newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def decide(row):
    phase = row.get("phase", "").strip()
    status = row.get("prediction_status", "").strip()

    if phase in IDLE_PHASES:
        return "MONITOR_ONLY", "Idle phase: observation only", None, None

    if phase in COOLDOWN_PHASES:
        return "MONITOR_ONLY", "Cooldown phase: preserve cooldown", None, None

    if phase not in KNOWN_PHASES:
        return "BASELINE_FALLBACK", "Unknown experimental phase", None, None

    if status != "FORECAST_ONLY":
        return "BASELINE_FALLBACK", "Forecast unavailable or skipped", None, None

    cpu_actual = number(row.get("cpu_actual_C"))
    cpu_pred = number(row.get("cpu_predicted_1s_C"))
    gpu_actual = number(row.get("gpu_actual_C"))
    gpu_pred = number(row.get("gpu_predicted_1s_C"))

    if None in (cpu_actual, cpu_pred, gpu_actual, gpu_pred):
        return "BASELINE_FALLBACK", "Missing or invalid prediction", None, None

    cpu_rise = cpu_pred - cpu_actual
    gpu_rise = gpu_pred - gpu_actual

    cpu_stable = cpu_rise <= EPSILON_C
    gpu_stable = gpu_rise <= EPSILON_C
    both_stable = cpu_stable and gpu_stable

    # V3.1 RULE 1:
    # Never recommend additional concurrent work in this phase.
    if phase == "SIMULTANEOUS":
        return (
            "DEFER_ADDITIONAL_CONCURRENT_WORK",
            "V3.1 conservative policy: defer additional concurrent work",
            cpu_rise,
            gpu_rise
        )

    # V3.1 RULE 2:
    # CPU workload is active; evaluate GPU admission.
    elif phase == "TA_CPU":
        if both_stable:
            decision = "GPU_ADMISSION_CANDIDATE"
            reason = (
                "Both predicted temperatures are stable or falling; "
                "GPU admission candidate subject to deadline checks"
            )
        else:
            decision = "DEFER_GPU_ADMISSION"
            reason = (
                "At least one predicted temperature is rising; "
                "defer GPU admission"
            )

    # V3.1 RULE 3:
    # GPU workload is active; evaluate CPU admission.
    elif phase == "TA_GPU":
        if both_stable:
            decision = "CPU_ADMISSION_CANDIDATE"
            reason = (
                "Both predicted temperatures are stable or falling; "
                "CPU admission candidate subject to deadline checks"
            )
        else:
            decision = "DEFER_CPU_ADMISSION"
            reason = (
                "At least one predicted temperature is rising; "
                "defer CPU admission"
            )

    else:
        return (
            "BASELINE_FALLBACK",
            "No scheduling rule defined",
            cpu_rise,
            gpu_rise
        )

    return decision, reason, cpu_rise, gpu_rise


def main():

    prediction_files = sorted(
        glob.glob("*_live_predictions.csv")
    )

    all_samples = []
    global_counts = {
        "V2": Counter(),
        "V3": Counter(),
        "V3.1": Counter()
    }

    processed_runs = 0

    print("\nRT-TAS DECISION ENGINE V3.1")
    print("=" * 95)

    for prediction_path in prediction_files:

        v2_path = prediction_path.replace(
            "_live_predictions.csv",
            "_live_predictions_decisions_v2.csv"
        )

        v3_path = prediction_path.replace(
            "_live_predictions.csv",
            "_live_predictions_decisions_v3.csv"
        )

        if not os.path.isfile(v2_path):
            print("SKIPPED: Missing V2 decisions:", v2_path)
            continue

        if not os.path.isfile(v3_path):
            print("SKIPPED: Missing V3 decisions:", v3_path)
            continue

        predictions = read_csv(prediction_path)
        v2_rows = read_csv(v2_path)
        v3_rows = read_csv(v3_path)

        if not predictions:
            print("SKIPPED: Empty prediction file:", prediction_path)
            continue

        run_name = os.path.basename(
            prediction_path
        ).replace("_live_predictions.csv", "")

        v2_lookup = {}
        v3_lookup = {}

        for row in v2_rows:
            key = (
                row.get("phase", "").strip(),
                elapsed_key(row.get("elapsed_s"))
            )
            v2_lookup[key] = row.get(
                "scheduler_decision", ""
            ).strip()

        for row in v3_rows:
            key = (
                row.get("phase", "").strip(),
                elapsed_key(row.get("elapsed_s"))
            )
            v3_lookup[key] = row.get(
                "scheduler_decision", ""
            ).strip()

        actual_lookup = {}

        for row in predictions:
            key = (
                row.get("phase", "").strip(),
                elapsed_key(row.get("elapsed_s"))
            )

            actual_lookup[key] = {
                "cpu": number(row.get("cpu_actual_C")),
                "gpu": number(row.get("gpu_actual_C"))
            }

        output_path = prediction_path.replace(
            "_live_predictions.csv",
            "_live_predictions_decisions_v3_1.csv"
        )

        run_counts = Counter()
        run_samples = []

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

                v2_decision = v2_lookup.get(
                    key, "MISSING_V2_DECISION"
                )

                v3_decision = v3_lookup.get(
                    key, "MISSING_V3_DECISION"
                )

                run_counts["V3.1:" + decision] += 1
                global_counts["V3.1"][decision] += 1

                if v2_decision != "MISSING_V2_DECISION":
                    global_counts["V2"][v2_decision] += 1

                if v3_decision != "MISSING_V3_DECISION":
                    global_counts["V3"][v3_decision] += 1

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
                    "v3_scheduler_decision": v3_decision,
                    "scheduler_decision": decision,
                    "decision_reason": reason,
                    "decision_mode": "OFFLINE_SHADOW_ONLY"
                }

                writer.writerow(result)

                # Match actual next-second measurements.
                if decision in {
                    "MONITOR_ONLY",
                    "BASELINE_FALLBACK"
                }:
                    continue

                current = actual_lookup.get(key)
                following = actual_lookup.get(
                    (phase, elapsed + 1)
                ) if elapsed is not None else None

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
                    "decision": decision,
                    "cpu_predicted_rise": cpu_rise,
                    "cpu_actual_change": (
                        following["cpu"] - current["cpu"]
                    ),
                    "gpu_predicted_rise": gpu_rise,
                    "gpu_actual_change": (
                        following["gpu"] - current["gpu"]
                    )
                }

                run_samples.append(sample)
                all_samples.append(sample)

        processed_runs += 1

        print(
            f"PROCESSED: {run_name} | "
            f"decisions: {sum(run_counts.values())} | "
            f"matched samples: {len(run_samples)}"
        )

    if not processed_runs:
        print("\nNo matching prediction, V2 and V3 files found.")
        return

    # Compare the three policies.
    print("\nV2 VS V3 VS V3.1 DECISION DISTRIBUTION")
    print("=" * 100)

    print(
        f"{'DECISION':42s}"
        f"{'V2':>10s}"
        f"{'V3':>10s}"
        f"{'V3.1':>10s}"
    )

    all_decisions = set()

    for counter in global_counts.values():
        all_decisions.update(counter)

    for decision in sorted(all_decisions):
        print(
            f"{decision:42s}"
            f"{global_counts['V2'][decision]:10d}"
            f"{global_counts['V3'][decision]:10d}"
            f"{global_counts['V3.1'][decision]:10d}"
        )

    # Aggregate V3.1 thermal response.
    groups = defaultdict(list)

    for sample in all_samples:
        groups[sample["decision"]].append(sample)

    print("\nV3.1 THERMAL VALIDATION")
    print("=" * 105)

    print(
        f"{'DECISION':38s}"
        f"{'N':>6s}"
        f"{'RUNS':>7s}"
        f"{'CPU_PRED':>11s}"
        f"{'CPU_ACT':>11s}"
        f"{'GPU_PRED':>11s}"
        f"{'GPU_ACT':>11s}"
    )

    for decision, samples in sorted(groups.items()):

        runs = set(s["run"] for s in samples)

        print(
            f"{decision:38s}"
            f"{len(samples):6d}"
            f"{len(runs):7d}"
            f"{fmt(mean([s['cpu_predicted_rise'] for s in samples]))}"
            f"{fmt(mean([s['cpu_actual_change'] for s in samples]))}"
            f"{fmt(mean([s['gpu_predicted_rise'] for s in samples]))}"
            f"{fmt(mean([s['gpu_actual_change'] for s in samples]))}"
        )

    # Per-run validation.
    print("\nV3.1 PER-RUN VALIDATION")
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
                f"{fmt(mean([s['cpu_actual_change'] for s in rows]))}"
                f"{fmt(mean([s['gpu_actual_change'] for s in rows]))}"
            )

    # Save combined observations.
    sample_path = "rt_tas_v3_1_multirun_validation_samples.csv"

    fields = [
        "run", "phase", "decision",
        "cpu_predicted_rise", "cpu_actual_change",
        "gpu_predicted_rise", "gpu_actual_change"
    ]

    with open(sample_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(all_samples)

    print("\nSUMMARY")
    print("=" * 95)
    print("Runs processed              :", processed_runs)
    print("V3.1 matched observations   :", len(all_samples))
    print("V3.1 output files           : *_live_predictions_decisions_v3_1.csv")
    print("Combined validation samples :", sample_path)
    print("\nMODE: OFFLINE SHADOW EVALUATION")
    print("No workload was started, stopped, paused, or resumed.")


if __name__ == "__main__":
    main()

