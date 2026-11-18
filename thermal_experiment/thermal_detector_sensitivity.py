#!/usr/bin/env python3

import csv
import os

INPUT = "rt_tas_controlled_20261026_221300.csv"
OUTPUT = "thermal_detector_sensitivity_20261026.csv"

ONE_STEP_THRESHOLD_C = 0.5
SUSTAINED_RISE_C = 1.0
EVENT_RISE_C = 0.5
HORIZONS = (5, 10)


def to_float(row, key):
    try:
        value = row.get(key, "")
        if value == "":
            return None
        return float(value)
    except (ValueError, TypeError):
        return None


def calculate_metrics(records, detector, horizon):
    tp = fp = fn = tn = 0

    for row in records:
        alert = row[detector]
        event = row["event_" + str(horizon) + "s"]

        if event is None:
            continue

        if alert and event:
            tp += 1
        elif alert and not event:
            fp += 1
        elif not alert and event:
            fn += 1
        else:
            tn += 1

    total = tp + fp + fn + tn
    precision = tp / (tp + fp) if tp + fp else None
    recall = tp / (tp + fn) if tp + fn else None

    return total, tp, fp, fn, tn, precision, recall


def main():
    if not os.path.isfile(INPUT):
        print("ERROR: File not found:", INPUT)
        return

    rows = []

    with open(INPUT, "r", newline="") as f:
        reader = csv.DictReader(f)

        required = ["elapsed_s", "phase", "gpu_edge_C"]
        missing = [
            col for col in required
            if col not in (reader.fieldnames or [])
        ]

        if missing:
            print("ERROR: Missing columns:", ", ".join(missing))
            print("Available columns:", reader.fieldnames)
            return

        for source in reader:
            elapsed = to_float(source, "elapsed_s")
            temp = to_float(source, "gpu_edge_C")

            if elapsed is None or temp is None:
                continue

            rows.append({
                "elapsed_s": elapsed,
                "phase": source["phase"],
                "gpu_temp_C": temp,
                "one_step_alert": False,
                "sustained_alert": False,
            })

    rows.sort(key=lambda r: r["elapsed_s"])

    # Build a same-phase lookup. Missing samples are not interpolated.
    lookup = {}
    by_phase = {}

    for row in rows:
        key = (row["phase"], round(row["elapsed_s"], 3))
        lookup[key] = row
        by_phase.setdefault(row["phase"], []).append(row)

    # Reconstruct both detectors using only current and past readings.
    for phase, samples in by_phase.items():
        samples.sort(key=lambda r: r["elapsed_s"])

        for i, current in enumerate(samples):
            if i >= 1:
                previous = samples[i - 1]
                consecutive = abs(
                    current["elapsed_s"] - previous["elapsed_s"] - 1.0
                ) < 0.01

                if consecutive:
                    current["one_step_alert"] = (
                        current["gpu_temp_C"] - previous["gpu_temp_C"]
                        >= ONE_STEP_THRESHOLD_C
                    )

            if i >= 2:
                first = samples[i - 2]
                middle = samples[i - 1]

                consecutive = (
                    abs(middle["elapsed_s"] - first["elapsed_s"] - 1.0)
                    < 0.01
                    and abs(
                        current["elapsed_s"] - middle["elapsed_s"] - 1.0
                    ) < 0.01
                )

                rising_each_sample = (
                    first["gpu_temp_C"] < middle["gpu_temp_C"]
                    and middle["gpu_temp_C"] < current["gpu_temp_C"]
                )

                net_rise = current["gpu_temp_C"] - first["gpu_temp_C"]

                current["sustained_alert"] = (
                    consecutive
                    and rising_each_sample
                    and net_rise >= SUSTAINED_RISE_C
                )

    # Determine future events only when the same-phase target sample exists.
    for row in rows:
        for horizon in HORIZONS:
            target_time = round(row["elapsed_s"] + horizon, 3)
            future = lookup.get((row["phase"], target_time))

            if future is None:
                row["event_" + str(horizon) + "s"] = None
            else:
                rise = future["gpu_temp_C"] - row["gpu_temp_C"]
                row["event_" + str(horizon) + "s"] = (
                    rise >= EVENT_RISE_C
                )

    phases = sorted(set(row["phase"] for row in rows))
    report = []

    print("GPU detector sensitivity evaluation")
    print("Input:", INPUT)
    print("Event: future GPU temperature rise >= {:.1f}C".format(
        EVENT_RISE_C
    ))
    print("Only same-phase future samples are scored.")
    print("No scheduling action is applied.")
    print()

    header = (
        "{:<18} {:>5} {:<13} {:>5} {:>5} {:>5} "
        "{:>5} {:>5} {:>9} {:>8}"
    )
    print(header.format(
        "Phase", "H", "Detector", "N", "TP", "FP",
        "FN", "TN", "Precision", "Recall"
    ))

    for phase in phases + ["ALL_PHASES"]:
        subset = rows if phase == "ALL_PHASES" else [
            row for row in rows if row["phase"] == phase
        ]

        for horizon in HORIZONS:
            for detector in ("one_step_alert", "sustained_alert"):
                total, tp, fp, fn, tn, precision, recall = (
                    calculate_metrics(subset, detector, horizon)
                )

                name = (
                    "one_step" if detector == "one_step_alert"
                    else "sustained"
                )

                print(header.format(
                    phase, horizon, name, total, tp, fp, fn, tn,
                    "{:.3f}".format(precision)
                    if precision is not None else "N/A",
                    "{:.3f}".format(recall)
                    if recall is not None else "N/A",
                ))

                report.append({
                    "phase": phase,
                    "horizon_s": horizon,
                    "detector": name,
                    "scored_samples": total,
                    "TP": tp,
                    "FP": fp,
                    "FN": fn,
                    "TN": tn,
                    "precision": (
                        round(precision, 4)
                        if precision is not None else ""
                    ),
                    "recall": (
                        round(recall, 4)
                        if recall is not None else ""
                    ),
                    "event_rise_C": EVENT_RISE_C,
                    "applied": "NO",
                })

    fields = [
        "phase", "horizon_s", "detector", "scored_samples",
        "TP", "FP", "FN", "TN", "precision", "recall",
        "event_rise_C", "applied",
    ]

    with open(OUTPUT, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(report)

    print()
    print("Saved:", OUTPUT)
    print("Precision/recall are sample-level metrics, not counts of")
    print("distinct heating episodes. Results are retrospective.")


if __name__ == "__main__":
    main()
