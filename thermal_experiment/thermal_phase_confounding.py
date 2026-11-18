#!/usr/bin/env python3

import csv
import os
from collections import defaultdict

BASE_DIR = os.path.expanduser("~/thermal_experiment")

RUNS = [
    "rt_tas_controlled_20261011_172905.csv",
    "rt_tas_controlled_20261014_011135.csv",
    "rt_tas_controlled_20261021_163039.csv",
    "rt_tas_controlled_20261025_175625.csv",
    "rt_tas_controlled_20261026_221300.csv",
]

PREDICTIONS_FILE = os.path.join(
    BASE_DIR, "thermal_state_cpu_loro_predictions.csv"
)

TRANSITION_WINDOW_S = 5.0


def read_csv(path):
    with open(path, "r", newline="") as f:
        return list(csv.DictReader(f))


def parse_state(value):
    value = str(value).strip().upper()
    if value in ("ON", "1", "TRUE", "YES"):
        return 1
    if value in ("OFF", "0", "FALSE", "NO"):
        return 0
    return None


def metric_row(rows, horizon, detector, group_name, group_value):
    tp = fp = fn = tn = 0

    for row in rows:
        actual = int(row["actual_rise"])
        predicted = int(row["predicted_rise"])

        if actual == 1 and predicted == 1:
            tp += 1
        elif actual == 0 and predicted == 1:
            fp += 1
        elif actual == 1 and predicted == 0:
            fn += 1
        else:
            tn += 1

    n = tp + fp + fn + tn
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = (
        2 * precision * recall / (precision + recall)
        if precision + recall else 0.0
    )

    return {
        "Horizon_s": horizon,
        "Detector": detector,
        "Group": group_name,
        "Group_value": group_value,
        "N": n,
        "TP": tp,
        "FP": fp,
        "FN": fn,
        "TN": tn,
        "Precision": round(precision, 4),
        "Recall": round(recall, 4),
        "F1": round(f1, 4),
    }


def main():
    if not os.path.isfile(PREDICTIONS_FILE):
        raise FileNotFoundError(
            "Missing predictions file: " + PREDICTIONS_FILE
            + "\nRun thermal_state_cpu_test.py first."
        )

    predictions = read_csv(PREDICTIONS_FILE)

    # Detect transitions from the original raw experiment CSVs.
    # A transition occurs when phase, GPU state, or CPU state changes.
    transition_times = defaultdict(list)
    raw_phase_lookup = {}

    print("Reading workload transitions...")

    for filename in RUNS:
        path = os.path.join(BASE_DIR, filename)

        if not os.path.isfile(path):
            raise FileNotFoundError("Missing raw CSV: " + path)

        raw = read_csv(path)
        parsed = []

        for row in raw:
            try:
                elapsed = float(row["elapsed_s"])
            except (KeyError, TypeError, ValueError):
                continue

            parsed.append({
                "t": elapsed,
                "phase": row.get("phase", "").strip(),
                "gpu": parse_state(row.get("gpu_enabled")),
                "cpu": parse_state(row.get("cpu_active")),
            })

        parsed.sort(key=lambda r: r["t"])
        previous = None

        for row in parsed:
            key = (filename, round(row["t"], 2))
            raw_phase_lookup[key] = row["phase"]

            if previous is not None:
                changed = (
                    row["phase"] != previous["phase"]
                    or row["gpu"] != previous["gpu"]
                    or row["cpu"] != previous["cpu"]
                )

                if changed:
                    transition_times[filename].append(row["t"])

            previous = row

    print("Transitions found per run:")
    for filename in RUNS:
        print(
            "  {}: {}".format(
                filename, len(transition_times[filename])
            )
        )

    # Add phase and transition-window metadata to predictions.
    enriched = []

    for row in predictions:
        filename = row["Held_out_run"]
        try:
            t = float(row["elapsed_s"])
            horizon = int(row["Horizon_s"])
        except (KeyError, TypeError, ValueError):
            continue

        phase = row.get("phase", "")
        # Use original CSV phase if the stored phase is empty.
        if not phase:
            phase = raw_phase_lookup.get(
                (filename, round(t, 2)), "UNKNOWN"
            )

        nearest_transition = min(
            (
                abs(t - transition)
                for transition in transition_times[filename]
            ),
            default=float("inf"),
        )

        near_transition = (
            nearest_transition <= TRANSITION_WINDOW_S
        )

        enriched.append({
            **row,
            "Horizon_s": horizon,
            "phase": phase,
            "near_transition": near_transition,
            "transition_distance_s": (
                nearest_transition
                if nearest_transition != float("inf")
                else ""
            ),
        })

    if not enriched:
        raise ValueError("No valid predictions were loaded.")

    # A. Pooled metrics for each phase.
    # B. Compare near-transition samples with stable-period samples.
    # C. Preserve held-out run grouping for later inspection.
    reports = []

    phase_groups = defaultdict(list)
    transition_groups = defaultdict(list)
    run_groups = defaultdict(list)

    for row in enriched:
        phase_groups[
            (row["Horizon_s"], row["Detector"], row["phase"])
        ].append(row)

        period = (
            "near_transition"
            if row["near_transition"]
            else "stable_period"
        )
        transition_groups[
            (row["Horizon_s"], row["Detector"], period)
        ].append(row)

        run_groups[
            (
                row["Horizon_s"],
                row["Detector"],
                row["Held_out_run"],
            )
        ].append(row)

    for (horizon, detector, phase), group in phase_groups.items():
        result = metric_row(
            group, horizon, detector, "phase", phase
        )
        result["Runs"] = len(set(r["Held_out_run"] for r in group))
        reports.append(result)

    for (horizon, detector, period), group in transition_groups.items():
        result = metric_row(
            group, horizon, detector, "transition_status", period
        )
        result["Runs"] = len(set(r["Held_out_run"] for r in group))
        reports.append(result)

    # Write detailed per-phase and transition summaries.
    output_path = os.path.join(
        BASE_DIR, "thermal_phase_confounding_summary.csv"
    )

    with open(output_path, "w", newline="") as f:
        fields = [
            "Horizon_s", "Detector", "Group", "Group_value",
            "N", "Runs", "TP", "FP", "FN", "TN",
            "Precision", "Recall", "F1",
        ]
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for row in reports:
            writer.writerow({
                field: row.get(field, "")
                for field in fields
            })

    # Save per-sample transition labels as well.
    sample_path = os.path.join(
        BASE_DIR, "thermal_phase_confounding_samples.csv"
    )

    with open(sample_path, "w", newline="") as f:
        fields = [
            "Horizon_s", "Held_out_run", "Detector", "phase",
            "elapsed_s", "actual_rise", "predicted_rise",
            "near_transition", "transition_distance_s",
        ]
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()

        for row in enriched:
            writer.writerow({
                field: row.get(field, "")
                for field in fields
            })

    print("\n=== PHASE-WISE RESULTS ===")
    print(
        "{:<5} {:<23} {:<23} {:>5} {:>6} {:>6} {:>6}".format(
            "Sec", "Detector", "Phase", "N", "Prec", "Recall", "F1"
        )
    )

    for row in sorted(
        [r for r in reports if r["Group"] == "phase"],
        key=lambda r: (
            r["Horizon_s"], r["Group_value"], r["Detector"]
        ),
    ):
        print(
            "{:<5} {:<23} {:<23} {:>5} {:>6.3f} {:>6.3f} {:>6.3f}".format(
                row["Horizon_s"],
                row["Detector"],
                row["Group_value"][:23],
                row["N"],
                row["Precision"],
                row["Recall"],
                row["F1"],
            )
        )

    print("\n=== TRANSITION VS STABLE-PERIOD RESULTS ===")
    print(
        "{:<5} {:<23} {:<19} {:>5} {:>6} {:>6} {:>6}".format(
            "Sec", "Detector", "Period", "N", "Prec", "Recall", "F1"
        )
    )

    for row in sorted(
        [r for r in reports if r["Group"] == "transition_status"],
        key=lambda r: (
            r["Horizon_s"], r["Group_value"], r["Detector"]
        ),
    ):
        print(
            "{:<5} {:<23} {:<19} {:>5} {:>6.3f} {:>6.3f} {:>6.3f}".format(
                row["Horizon_s"],
                row["Detector"],
                row["Group_value"],
                row["N"],
                row["Precision"],
                row["Recall"],
                row["F1"],
            )
        )

    print("\nSaved:")
    print(output_path)
    print(sample_path)

    print("\nInterpretation notes:")
    print("- Phase-wise F1 can be unstable when a phase has few positive cases.")
    print("- Phase-only predictions may be constant within a phase.")
    print("- Transition windows overlap and are not independent observations.")
    print("- A 5-second transition window is a diagnostic choice, not a proven optimum.")
    print("- This is offline analysis, not a real-time scheduling test.")


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, KeyError) as error:
        print("\nERROR:", error)

