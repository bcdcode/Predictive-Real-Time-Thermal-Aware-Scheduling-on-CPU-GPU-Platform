

#!/usr/bin/env python3

import os
import csv
import math
from collections import defaultdict

# ============================================================
# Thermal State + CPU Context Detector Evaluation
#
# Detectors:
#   1. gpu_state_only
#   2. cpu_context_only
#   3. gpu_state_plus_cpu
#   4. phase_only
#
# Validation:
#   - Leave-one-run-out
#   - 5-second and 10-second horizons
#   - Threshold selection uses training runs only
#
# Dependencies: Python standard library only
# No workloads are launched.
# ============================================================

BASE_DIR = os.path.expanduser("~/thermal_experiment")

FILES = [
    "rt_tas_controlled_20261011_172905.csv",
    "rt_tas_controlled_20261014_011135.csv",
    "rt_tas_controlled_20261021_163039.csv",
    "rt_tas_controlled_20261025_175625.csv",
    "rt_tas_controlled_20261026_221300.csv",
]

HORIZONS = [5, 10]

TIME_TOLERANCE = 0.75
GPU_LOOKBACK_S = 2.0
CPU_LOOKBACK_S = 4.0

COMBINED_THRESHOLDS = [0.5, 1.0, 1.5, 2.0]
PHASE_THRESHOLDS = [x / 100.0 for x in range(5, 96, 5)]


def parse_number(value):
    """Convert a CSV value to a finite float, or None."""
    try:
        result = float(str(value).strip())
        if math.isfinite(result):
            return result
    except (TypeError, ValueError):
        pass

    return None


def parse_state(value):
    """Convert ON/OFF or equivalent values to 1/0."""
    value = str(value).strip().upper()

    if value in ("ON", "1", "TRUE", "YES"):
        return 1.0

    if value in ("OFF", "0", "FALSE", "NO"):
        return 0.0

    return None


def load_run(filename):
    """Load one CSV file using only Python's csv module."""

    path = os.path.join(BASE_DIR, filename)

    if not os.path.isfile(path):
        raise FileNotFoundError("Cannot find file: " + path)

    required = [
        "elapsed_s",
        "phase",
        "cpu_tctl_C",
        "gpu_edge_C",
        "gpu_freq_MHz",
        "gpu_activity_proxy",
        "cpu_active",
        "gpu_enabled",
    ]

    rows = []

    with open(path, "r", newline="") as file:
        reader = csv.DictReader(file)

        if reader.fieldnames is None:
            raise ValueError("CSV has no header: " + filename)

        # Remove accidental spaces around column names.
        reader.fieldnames = [
            name.strip() for name in reader.fieldnames
        ]

        missing = [
            column for column in required
            if column not in reader.fieldnames
        ]

        if missing:
            raise ValueError(
                filename + " is missing columns: " + str(missing)
            )

        for raw in reader:
            # Normalize header/value whitespace.
            row = {
                str(key).strip(): (
                    value.strip() if isinstance(value, str) else value
                )
                for key, value in raw.items()
                if key is not None
            }

            elapsed = parse_number(row.get("elapsed_s"))
            cpu_temp = parse_number(row.get("cpu_tctl_C"))
            gpu_temp = parse_number(row.get("gpu_edge_C"))

            cpu_active = parse_state(row.get("cpu_active"))
            gpu_enabled = parse_state(row.get("gpu_enabled"))

            if any(value is None for value in (
                elapsed, cpu_temp, gpu_temp,
                cpu_active, gpu_enabled
            )):
                continue

            rows.append({
                "run": filename,
                "elapsed_s": elapsed,
                "phase": str(row.get("phase", "")).strip(),
                "cpu_temp": cpu_temp,
                "gpu_temp": gpu_temp,
                "gpu_freq": parse_number(row.get("gpu_freq_MHz")),
                "gpu_activity": parse_number(
                    row.get("gpu_activity_proxy")
                ),
                "cpu_active": int(cpu_active),
                "gpu_enabled": int(gpu_enabled),
            })

    rows.sort(key=lambda item: item["elapsed_s"])
    return rows


def nearest_row(rows, target_time):
    """Return the closest sample if it is within tolerance."""

    if not rows:
        return None

    best = min(
        rows,
        key=lambda item: abs(item["elapsed_s"] - target_time)
    )

    if abs(best["elapsed_s"] - target_time) > TIME_TOLERANCE:
        return None

    return best


def make_examples(rows, horizon):
    """
    Build examples using current and past signals only.

    Label = 1 when GPU temperature rises at least 0.5 C
    from the current sample to the future horizon sample.

    The future sample must be in the same experimental phase.
    """

    records = []
    phase_rows = defaultdict(list)

    for row in rows:
        phase_rows[row["phase"]].append(row)

    for current in rows:
        t = current["elapsed_s"]
        same_phase = phase_rows[current["phase"]]

        future = nearest_row(same_phase, t + horizon)
        gpu_past = nearest_row(same_phase, t - GPU_LOOKBACK_S)
        cpu_past = nearest_row(same_phase, t - CPU_LOOKBACK_S)

        if future is None or gpu_past is None or cpu_past is None:
            continue

        label = int(
            future["gpu_temp"] - current["gpu_temp"] >= 0.5
        )

        gpu_state = current["gpu_enabled"]
        cpu_active = current["cpu_active"]

        # CPU package-temperature trend over the previous 4 seconds.
        cpu_slope = (
            current["cpu_temp"] - cpu_past["cpu_temp"]
        ) / CPU_LOOKBACK_S

        # CPU context signal.
        cpu_context = int(
            cpu_active == 1 and cpu_slope > 0.05
        )

        # Combined score: GPU state contributes 1; CPU context contributes 1.
        combined_score = gpu_state + cpu_context

        # Diagnostic features retained for possible future ablation.
        gpu_temp_delta = (
            current["gpu_temp"] - gpu_past["gpu_temp"]
        )

        activity_change = None
        if (
            current["gpu_activity"] is not None
            and gpu_past["gpu_activity"] is not None
        ):
            activity_change = (
                current["gpu_activity"] - gpu_past["gpu_activity"]
            )

        frequency_change = None
        if (
            current["gpu_freq"] is not None
            and gpu_past["gpu_freq"] is not None
        ):
            frequency_change = (
                current["gpu_freq"] - gpu_past["gpu_freq"]
            )

        freq_activity = int(
            (
                activity_change is not None
                and activity_change > 0.02
            )
            or (
                frequency_change is not None
                and frequency_change >= 100
            )
        )

        records.append({
            "run": current["run"],
            "phase": current["phase"],
            "elapsed_s": t,
            "label": label,
            "gpu_state": gpu_state,
            "cpu_context": cpu_context,
            "combined_score": combined_score,
            "gpu_temp_delta": gpu_temp_delta,
            "gpu_freq_activity": freq_activity,
        })

    return records


def calculate_metrics(actual, predicted):
    """Calculate confusion-matrix metrics without third-party modules."""

    tp = sum(
        1 for y, p in zip(actual, predicted)
        if y == 1 and p == 1
    )

    fp = sum(
        1 for y, p in zip(actual, predicted)
        if y == 0 and p == 1
    )

    fn = sum(
        1 for y, p in zip(actual, predicted)
        if y == 1 and p == 0
    )

    tn = sum(
        1 for y, p in zip(actual, predicted)
        if y == 0 and p == 0
    )

    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0

    if precision + recall > 0:
        f1 = 2 * precision * recall / (precision + recall)
    else:
        f1 = 0.0

    return {
        "N": len(actual),
        "TP": tp,
        "FP": fp,
        "FN": fn,
        "TN": tn,
        "Precision": precision,
        "Recall": recall,
        "F1": f1,
    }


def choose_threshold(training_rows, score_key, candidates):
    """Select threshold by training-set F1 only."""

    best_threshold = candidates[0]
    best_f1 = -1.0

    actual = [row["label"] for row in training_rows]

    for threshold in candidates:
        predicted = [
            int(row[score_key] >= threshold)
            for row in training_rows
        ]

        score = calculate_metrics(actual, predicted)["F1"]

        if score > best_f1:
            best_f1 = score
            best_threshold = threshold

    return best_threshold


def calculate_phase_risks(training_rows):
    """Estimate future-rise rate for each phase from training runs."""

    counts = defaultdict(lambda: [0, 0])

    for row in training_rows:
        counts[row["phase"]][0] += row["label"]
        counts[row["phase"]][1] += 1

    risks = {}

    for phase, values in counts.items():
        positive, total = values
        if total:
            risks[phase] = positive / total

    return risks


def save_csv(filename, rows):
    """Write a list of dictionaries to a CSV file."""

    if not rows:
        print("Warning: no output rows for", filename)
        return

    with open(filename, "w", newline="") as file:
        writer = csv.DictWriter(
            file,
            fieldnames=list(rows[0].keys())
        )
        writer.writeheader()
        writer.writerows(rows)


def main():
    loaded_runs = {}

    print("Loading experiment data...")

    for filename in FILES:
        rows = load_run(filename)
        loaded_runs[filename] = rows

        print(
            "  {}: {} valid samples".format(
                filename, len(rows)
            )
        )

        if not rows:
            raise ValueError(
                "No valid rows in " + filename
            )

    detailed_results = []
    prediction_results = []

    for horizon in HORIZONS:
        print(
            "\nPreparing {}-second prediction examples...".format(
                horizon
            )
        )

        examples = []

        for filename, rows in loaded_runs.items():
            run_examples = make_examples(rows, horizon)
            examples.extend(run_examples)

            print(
                "  {}: {} usable examples".format(
                    filename, len(run_examples)
                )
            )

        if not examples:
            print("No valid examples for horizon", horizon)
            continue

        run_names = sorted(set(row["run"] for row in examples))

        for held_out_run in run_names:
            training = [
                row for row in examples
                if row["run"] != held_out_run
            ]

            testing = [
                row for row in examples
                if row["run"] == held_out_run
            ]

            if not training or not testing:
                continue

            # Detector 1: GPU state only.
            predictions = {
                "gpu_state_only": [
                    row["gpu_state"] for row in testing
                ]
            }

            # Detector 2: CPU context only.
            predictions["cpu_context_only"] = [
                row["cpu_context"] for row in testing
            ]

            # Detector 3: combined GPU state + CPU context.
            combined_threshold = choose_threshold(
                training,
                "combined_score",
                COMBINED_THRESHOLDS
            )

            predictions["gpu_state_plus_cpu"] = [
                int(row["combined_score"] >= combined_threshold)
                for row in testing
            ]

            # Detector 4: phase-only diagnostic.
            phase_risk = calculate_phase_risks(training)

            training_phase_rows = [
                dict(
                    row,
                    phase_risk=phase_risk.get(row["phase"], 0.0)
                )
                for row in training
            ]

            phase_threshold = choose_threshold(
                training_phase_rows,
                "phase_risk",
                PHASE_THRESHOLDS
            )

            test_phase_risks = [
                phase_risk.get(row["phase"], 0.0)
                for row in testing
            ]

            predictions["phase_only"] = [
                int(risk >= phase_threshold)
                for risk in test_phase_risks
            ]

            thresholds = {
                "gpu_state_only": "",
                "cpu_context_only": "",
                "gpu_state_plus_cpu": combined_threshold,
                "phase_only": phase_threshold,
            }

            for detector, predicted in predictions.items():
                actual = [row["label"] for row in testing]

                scores = calculate_metrics(actual, predicted)

                detailed_results.append({
                    "Horizon_s": horizon,
                    "Held_out_run": held_out_run,
                    "Detector": detector,
                    "Threshold": thresholds[detector],
                    **scores,
                })

                for index, row in enumerate(testing):
                    prediction_results.append({
                        "Horizon_s": horizon,
                        "Held_out_run": held_out_run,
                        "Detector": detector,
                        "phase": row["phase"],
                        "elapsed_s": row["elapsed_s"],
                        "actual_rise": row["label"],
                        "predicted_rise": predicted[index],
                    })

    if not prediction_results:
        print("\nERROR: No predictions were generated.")
        return

    # Pool held-out predictions for each detector and horizon.
    groups = defaultdict(list)

    for row in prediction_results:
        groups[(row["Horizon_s"], row["Detector"])].append(row)

    pooled_results = []

    for (horizon, detector), rows in groups.items():
        actual = [row["actual_rise"] for row in rows]
        predicted = [row["predicted_rise"] for row in rows]

        pooled_results.append({
            "Horizon_s": horizon,
            "Detector": detector,
            **calculate_metrics(actual, predicted),
        })

    pooled_results.sort(
        key=lambda row: (row["Horizon_s"], -row["F1"])
    )

    save_csv(
        "thermal_state_cpu_loro_summary.csv",
        pooled_results
    )

    save_csv(
        "thermal_state_cpu_loro_details.csv",
        detailed_results
    )

    save_csv(
        "thermal_state_cpu_loro_predictions.csv",
        prediction_results
    )

    print("\n" + "=" * 88)
    print("POOLED LEAVE-ONE-RUN-OUT RESULTS")
    print("=" * 88)

    print(
        "{:<9} {:<23} {:>5} {:>5} {:>5} {:>5} {:>5} "
        "{:>10} {:>10} {:>8}".format(
            "Horizon", "Detector", "N", "TP", "FP", "FN", "TN",
            "Precision", "Recall", "F1"
        )
    )

    for row in pooled_results:
        print(
            "{:<9} {:<23} {:>5} {:>5} {:>5} {:>5} {:>5} "
            "{:>10.3f} {:>10.3f} {:>8.3f}".format(
                str(row["Horizon_s"]) + "s",
                row["Detector"],
                row["N"],
                row["TP"],
                row["FP"],
                row["FN"],
                row["TN"],
                row["Precision"],
                row["Recall"],
                row["F1"],
            )
        )

    print("\n" + "=" * 88)
    print("PER-HELD-OUT-RUN RESULTS")
    print("=" * 88)

    for row in detailed_results:
        print(
            "{} | {} | {} | N={} | Precision={:.3f} | "
            "Recall={:.3f} | F1={:.3f}".format(
                row["Horizon_s"],
                row["Held_out_run"],
                row["Detector"],
                row["N"],
                row["Precision"],
                row["Recall"],
                row["F1"],
            )
        )

    print("\nSaved output files:")
    print("  thermal_state_cpu_loro_summary.csv")
    print("  thermal_state_cpu_loro_details.csv")
    print("  thermal_state_cpu_loro_predictions.csv")

    print("\nNotes:")
    print("- Standard Python only: no NumPy and no pandas.")
    print("- ON/OFF values are converted to 1/0.")
    print("- Phase-only is a diagnostic for schedule confounding.")
    print("- Overlapping windows are not independent observations.")
    print("- Predictive performance does not establish causation.")


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, KeyError) as error:
        print("\nERROR:", error)

