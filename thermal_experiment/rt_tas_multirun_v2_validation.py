#!/usr/bin/env python3

import csv
import glob
import os
import statistics
from collections import defaultdict

EPSILON = 0.05

DECISION_SUFFIX = "_live_predictions_decisions_v2.csv"

EXCLUDED_DECISIONS = {
    "MONITOR_ONLY",
    "BASELINE_FALLBACK",
    "",
}

def read_csv(path):
    with open(path, "r", newline="") as f:
        return list(csv.DictReader(f))


def number(row, column):
    try:
        value = row.get(column, "")
        if value is None or value.strip() == "":
            return None
        return float(value)
    except (ValueError, AttributeError):
        return None


def get_action_column(rows):
    if not rows:
        return None

    for name in (
    "scheduler_decision",
    "decision",
    "recommended_action",
    "action"
    ):
        if name in rows[0]:
            return name

    return None


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
    processed_runs = 0

    print("\nMULTI-RUN V2 DECISION VALIDATION")
    print("=" * 105)

    for prediction_path in prediction_files:

        decision_path = prediction_path.replace(
            "_live_predictions.csv",
            DECISION_SUFFIX
        )

        if not os.path.exists(decision_path):
            print(f"SKIPPED: No V2 decisions for {prediction_path}")
            continue

        predictions = read_csv(prediction_path)
        decisions = read_csv(decision_path)

        if not predictions or not decisions:
            print(f"SKIPPED: Empty CSV: {prediction_path}")
            continue

        action_column = get_action_column(decisions)

        if action_column is None:
            print(f"SKIPPED: Cannot identify decision column in {decision_path}")
            continue

        # Actual measurements indexed by phase and elapsed second.
        actual = {}

        for row in predictions:
            phase = row.get("phase", "").strip()
            elapsed = number(row, "elapsed_s")

            cpu = number(row, "cpu_actual_C")
            gpu = number(row, "gpu_actual_C")

            if elapsed is None:
                continue

            key = (phase, round(elapsed))
            actual[key] = {
                "cpu": cpu,
                "gpu": gpu,
            }

        run_name = os.path.basename(
            prediction_path
        ).replace("_live_predictions.csv", "")

        run_count = 0

        for row in decisions:

            action = row.get(action_column, "").strip()

            if action in EXCLUDED_DECISIONS:
                continue

            phase = row.get("phase", "").strip()
            elapsed = number(row, "elapsed_s")

            if elapsed is None:
                continue

            current_key = (phase, round(elapsed))
            next_key = (phase, round(elapsed) + 1)

            current = actual.get(current_key)
            following = actual.get(next_key)

            if current is None or following is None:
                continue

            # Require both actual measurements.
            if any(
                v is None
                for v in (
                    current["cpu"], current["gpu"],
                    following["cpu"], following["gpu"]
                )
            ):
                continue

            cpu_predicted = number(row, "cpu_predicted_1s_C")
            gpu_predicted = number(row, "gpu_predicted_1s_C")

            if cpu_predicted is None or gpu_predicted is None:
                continue

            # Predicted temperature rise relative to current temperature.
            cpu_pred_rise = cpu_predicted - current["cpu"]
            gpu_pred_rise = gpu_predicted - current["gpu"]

            # Measured next-second temperature change.
            cpu_actual_rise = following["cpu"] - current["cpu"]
            gpu_actual_rise = following["gpu"] - current["gpu"]

            sample = {
                "run": run_name,
                "phase": phase,
                "decision": action,
                "elapsed_s": round(elapsed),
                "cpu_pred": cpu_pred_rise,
                "cpu_actual": cpu_actual_rise,
                "gpu_pred": gpu_pred_rise,
                "gpu_actual": gpu_actual_rise,
            }

            all_samples.append(sample)
            run_count += 1

        processed_runs += 1
        print(f"PROCESSED: {run_name} | matched decisions: {run_count}")

    if not all_samples:
        print("\nNo matching validation samples found.")
        print("Check that the prediction and V2 decision CSV files exist.")
        return

    # Save individual matched observations.
    sample_path = "rt_tas_v2_multirun_validation_samples.csv"

    with open(sample_path, "w", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=list(all_samples[0].keys())
        )
        writer.writeheader()
        writer.writerows(all_samples)

    # Group by decision category and run.
    groups = defaultdict(list)

    for sample in all_samples:
        groups[sample["decision"]].append(sample)

    print("\nAGGREGATE RESULTS BY DECISION")
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
            f"{fmt(mean([s['cpu_pred'] for s in samples]))}"
            f"{fmt(mean([s['cpu_actual'] for s in samples]))}"
            f"{fmt(mean([s['gpu_pred'] for s in samples]))}"
            f"{fmt(mean([s['gpu_actual'] for s in samples]))}"
        )

    print("\nPER-RUN RESULTS")
    print("=" * 105)

    print(
        f"{'RUN':42s}"
        f"{'DECISION':34s}"
        f"{'N':>5s}"
        f"{'CPU_ACT':>11s}"
        f"{'GPU_ACT':>11s}"
    )

    for decision, samples in sorted(groups.items()):

        by_run = defaultdict(list)

        for sample in samples:
            by_run[sample["run"]].append(sample)

        for run, run_samples in sorted(by_run.items()):

            print(
                f"{run:42s}"
                f"{decision:34s}"
                f"{len(run_samples):5d}"
                f"{fmt(mean([s['cpu_actual'] for s in run_samples]))}"
                f"{fmt(mean([s['gpu_actual'] for s in run_samples]))}"
            )

    print("\nSUMMARY")
    print("=" * 105)
    print(f"Prediction/decision runs processed : {processed_runs}")
    print(f"Total matched decision observations: {len(all_samples)}")
    print(f"Unique decision categories         : {len(groups)}")
    print(f"Detailed samples saved to          : {sample_path}")


if __name__ == "__main__":
    main()
