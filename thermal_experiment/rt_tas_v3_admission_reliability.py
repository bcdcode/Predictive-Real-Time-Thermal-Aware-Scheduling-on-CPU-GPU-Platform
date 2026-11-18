#!/usr/bin/env python3

import csv
import math
import statistics
from collections import defaultdict

INPUT_FILE = "rt_tas_v3_multirun_validation_samples.csv"
EPSILON_C = 0.05

ADMISSION_CANDIDATES = {
    "CONCURRENT_ADMISSION_CANDIDATE",
    "GPU_ADMISSION_CANDIDATE",
    "CPU_ADMISSION_CANDIDATE",
}

def number(value):
    try:
        result = float(str(value).strip())
        return result if math.isfinite(result) else None
    except (TypeError, ValueError):
        return None


def mean(values):
    return statistics.mean(values) if values else None


def rmse(errors):
    return math.sqrt(mean([e * e for e in errors])) if errors else None


def fmt(value):
    return f"{value:10.3f}" if value is not None else "       N/A"


def analyze(samples):
    result = {}

    for sensor in ("cpu", "gpu"):
        predicted = [
            s[f"{sensor}_predicted_rise_C"] for s in samples
        ]
        actual = [
            s[f"{sensor}_actual_change_C"] for s in samples
        ]

        errors = [
            a - p for p, a in zip(predicted, actual)
        ]

        result[sensor] = {
            "n": len(samples),
            "pred_mae": mean([abs(e) for e in errors]),
            "pred_rmse": rmse(errors),
            "bias": mean(errors),
            "predicted_rising": sum(
                p > EPSILON_C for p in predicted
            ),
            "actual_rising": sum(
                a > EPSILON_C for a in actual
            ),
            "actual_falling": sum(
                a < -EPSILON_C for a in actual
            ),
            "actual_stable": sum(
                -EPSILON_C <= a <= EPSILON_C for a in actual
            ),
            "false_safe": sum(
                p <= EPSILON_C and a > EPSILON_C
                for p, a in zip(predicted, actual)
            )
        }

    # A candidate is considered thermally consistent only when
    # neither actual temperature rises beyond the threshold.
    result["joint"] = {
        "n": len(samples),
        "actual_cpu_rising": sum(
            s["cpu_actual_change_C"] > EPSILON_C
            for s in samples
        ),
        "actual_gpu_rising": sum(
            s["gpu_actual_change_C"] > EPSILON_C
            for s in samples
        ),
        "actual_either_rising": sum(
            s["cpu_actual_change_C"] > EPSILON_C or
            s["gpu_actual_change_C"] > EPSILON_C
            for s in samples
        ),
        "actual_both_stable_or_falling": sum(
            s["cpu_actual_change_C"] <= EPSILON_C and
            s["gpu_actual_change_C"] <= EPSILON_C
            for s in samples
        )
    }

    return result


def print_sensor_metrics(label, metrics):
    print(f"\n{label}")
    print("-" * 100)

    print(
        f"{'SENSOR':10s}"
        f"{'N':>6s}"
        f"{'MAE':>11s}"
        f"{'RMSE':>11s}"
        f"{'BIAS':>11s}"
        f"{'ACT_RISE':>11s}"
        f"{'ACT_FALL':>11s}"
        f"{'FALSE_SAFE':>12s}"
    )

    for sensor in ("cpu", "gpu"):
        m = metrics[sensor]

        print(
            f"{sensor.upper():10s}"
            f"{m['n']:6d}"
            f"{fmt(m['pred_mae'])}"
            f"{fmt(m['pred_rmse'])}"
            f"{fmt(m['bias'])}"
            f"{m['actual_rising']:11d}"
            f"{m['actual_falling']:11d}"
            f"{m['false_safe']:12d}"
        )


def main():
    try:
        with open(INPUT_FILE, newline="", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
    except FileNotFoundError:
        print("ERROR: Missing input file:", INPUT_FILE)
        print("Run rt_tas_decision_engine_v3.py first.")
        return

    required = {
        "run", "phase", "v3_decision",
        "cpu_predicted_rise_C", "cpu_actual_change_C",
        "gpu_predicted_rise_C", "gpu_actual_change_C"
    }

    if not rows or not required.issubset(rows[0].keys()):
        print("ERROR: Input CSV is empty or has unexpected columns.")
        return

    candidates = []

    for row in rows:
        decision = row["v3_decision"].strip()

        if decision not in ADMISSION_CANDIDATES:
            continue

        values = {
            "run": row["run"],
            "phase": row["phase"],
            "decision": decision,
            "cpu_predicted_rise_C": number(
                row["cpu_predicted_rise_C"]
            ),
            "cpu_actual_change_C": number(
                row["cpu_actual_change_C"]
            ),
            "gpu_predicted_rise_C": number(
                row["gpu_predicted_rise_C"]
            ),
            "gpu_actual_change_C": number(
                row["gpu_actual_change_C"]
            )
        }

        if any(
            values[k] is None
            for k in (
                "cpu_predicted_rise_C",
                "cpu_actual_change_C",
                "gpu_predicted_rise_C",
                "gpu_actual_change_C"
            )
        ):
            continue

        candidates.append(values)

    print("\nRT-TAS V3 ADMISSION PREDICTION RELIABILITY")
    print("=" * 100)
    print("Input file:", INPUT_FILE)
    print("Threshold :", EPSILON_C, "C")
    print("Candidate observations:", len(candidates))

    if not candidates:
        print("No valid admission candidate observations found.")
        return

    groups = defaultdict(list)
    run_groups = defaultdict(list)

    for sample in candidates:
        groups[sample["decision"]].append(sample)
        run_groups[(sample["run"], sample["decision"])].append(sample)

    # Overall admission candidate reliability.
    overall = analyze(candidates)

    print_sensor_metrics("ALL ADMISSION CANDIDATES", overall)

    joint = overall["joint"]
    n = joint["n"]

    print("\nJOINT ADMISSION RELIABILITY")
    print("-" * 75)
    print("Total candidate observations          :", n)
    print("Actual CPU temperature rises           :", joint["actual_cpu_rising"])
    print("Actual GPU temperature rises           :", joint["actual_gpu_rising"])
    print("Either temperature actually rises      :", joint["actual_either_rising"])
    print("Both temperatures stable/falling       :", joint["actual_both_stable_or_falling"])

    if n:
        print(
            "Either-temperature rise rate           : {:.2f}%".format(
                100 * joint["actual_either_rising"] / n
            )
        )
        print(
            "Both-stable/falling rate               : {:.2f}%".format(
                100 * joint["actual_both_stable_or_falling"] / n
            )
        )

    # Decision-specific metrics.
    print("\nRESULTS BY ADMISSION DECISION")
    print("=" * 100)

    for decision in sorted(ADMISSION_CANDIDATES):
        samples = groups.get(decision, [])

        print(f"\n{decision}")
        print("Observations:", len(samples))

        if not samples:
            print("No observations available.")
            continue

        metrics = analyze(samples)
        print_sensor_metrics("Prediction accuracy and actual thermal response", metrics)

        j = metrics["joint"]
        print(
            "Either-temperature actual rise: "
            f"{j['actual_either_rising']}/{j['n']}"
        )

    # Per-run results.
    print("\nPER-RUN ADMISSION RELIABILITY")
    print("=" * 100)

    print(
        f"{'RUN':38s}"
        f"{'DECISION':35s}"
        f"{'N':>5s}"
        f"{'CPU_RISE':>10s}"
        f"{'GPU_RISE':>10s}"
        f"{'EITHER':>9s}"
    )

    for (run, decision), samples in sorted(run_groups.items()):
        metrics = analyze(samples)
        j = metrics["joint"]

        print(
            f"{run:38s}"
            f"{decision:35s}"
            f"{len(samples):5d}"
            f"{j['actual_cpu_rising']:10d}"
            f"{j['actual_gpu_rising']:10d}"
            f"{j['actual_either_rising']:9d}"
        )

    # Save candidate-only detailed results.
    output_file = "rt_tas_v3_admission_reliability.csv"

    fields = [
        "run", "phase", "decision",
        "cpu_predicted_rise_C", "cpu_actual_change_C",
        "gpu_predicted_rise_C", "gpu_actual_change_C",
        "cpu_prediction_error_C", "gpu_prediction_error_C",
        "either_actual_temperature_rising"
    ]

    with open(output_file, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()

        for s in candidates:
            cpu_error = (
                s["cpu_actual_change_C"] -
                s["cpu_predicted_rise_C"]
            )
            gpu_error = (
                s["gpu_actual_change_C"] -
                s["gpu_predicted_rise_C"]
            )

            writer.writerow({
                "run": s["run"],
                "phase": s["phase"],
                "decision": s["decision"],
                "cpu_predicted_rise_C": s["cpu_predicted_rise_C"],
                "cpu_actual_change_C": s["cpu_actual_change_C"],
                "gpu_predicted_rise_C": s["gpu_predicted_rise_C"],
                "gpu_actual_change_C": s["gpu_actual_change_C"],
                "cpu_prediction_error_C": round(cpu_error, 4),
                "gpu_prediction_error_C": round(gpu_error, 4),
                "either_actual_temperature_rising": (
                    s["cpu_actual_change_C"] > EPSILON_C or
                    s["gpu_actual_change_C"] > EPSILON_C
                )
            })

    print("\nSUMMARY")
    print("=" * 100)
    print("Admission candidates evaluated :", len(candidates))
    print("Threshold                      :", EPSILON_C, "C")
    print("Detailed output                :", output_file)
    print("\nAnalysis complete. No experiment or workload was modified.")


if __name__ == "__main__":
    main()

