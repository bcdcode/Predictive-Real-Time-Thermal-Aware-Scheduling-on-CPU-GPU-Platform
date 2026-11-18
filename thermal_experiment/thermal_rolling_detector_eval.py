#!/usr/bin/env python3

import csv
import os

INPUT = "rt_tas_controlled_20261026_221300.csv"
OUTPUT = "thermal_rolling_detector_results_20261026.csv"

ONE_STEP_THRESHOLD_C = 0.5
SUSTAINED_RISE_C = 1.0
ROLLING_THRESHOLDS_C = (0.5, 1.0, 1.5)
EVENT_RISE_C = 0.5
HORIZONS = (5, 10)


def to_float(row, column):
    try:
        value = row.get(column, "")
        if value == "":
            return None
        return float(value)
    except (ValueError, TypeError):
        return None


def main():
    if not os.path.isfile(INPUT):
        print("ERROR: Input file not found:", INPUT)
        print("Check available files with: ls rt_tas_controlled_*.csv")
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
            })

    rows.sort(key=lambda r: r["elapsed_s"])

    # Group samples by phase. Do not join observations across phase changes.
    by_phase = {}
    lookup = {}

    for row in rows:
        phase = row["phase"]
        by_phase.setdefault(phase, []).append(row)
        lookup[(phase, round(row["elapsed_s"], 3))] = row

    for phase, samples in by_phase.items():
        samples.sort(key=lambda r: r["elapsed_s"])

        for i, row in enumerate(samples):
            row["one_step_alert"] = False
            row["sustained_alert"] = False
            row["rolling_0.5_alert"] = False
            row["rolling_1.0_alert"] = False
            row["rolling_1.5_alert"] = False

            # One-step detector: rise >= 0.5 C in the previous second.
            if i >= 1:
                previous = samples[i - 1]
                one_second_gap = abs(
                    row["elapsed_s"] - previous["elapsed_s"] - 1.0
                ) < 0.01

                if one_second_gap:
                    rise = row["gpu_temp_C"] - previous["gpu_temp_C"]
                    row["one_step_alert"] = (
                        rise >= ONE_STEP_THRESHOLD_C
                    )

            # Sustained detector: three strictly increasing readings,
            # with a net rise >= 1.0 C from first to third.
            if i >= 2:
                first = samples[i - 2]
                middle = samples[i - 1]

                consecutive = (
                    abs(middle["elapsed_s"] - first["elapsed_s"] - 1.0)
                    < 0.01
                    and abs(
                        row["elapsed_s"] - middle["elapsed_s"] - 1.0
                    ) < 0.01
                )

                increasing = (
                    first["gpu_temp_C"] < middle["gpu_temp_C"]
                    and middle["gpu_temp_C"] < row["gpu_temp_C"]
                )

                net_rise = row["gpu_temp_C"] - first["gpu_temp_C"]

                row["sustained_alert"] = (
                    consecutive
                    and increasing
                    and net_rise >= SUSTAINED_RISE_C
                )

            # Rolling detector: compare current temperature with the
            # reading exactly two seconds earlier in the same phase.
            if i >= 2:
                first = samples[i - 2]
                two_second_gap = abs(
                    row["elapsed_s"] - first["elapsed_s"] - 2.0
                ) < 0.01

                if two_second_gap:
                    net_rise = row["gpu_temp_C"] - first["gpu_temp_C"]

                    for threshold in ROLLING_THRESHOLDS_C:
                        key = "rolling_{:.1f}_alert".format(threshold)
                        row[key] = net_rise >= threshold

    # Future events: temperature rise >= 0.5 C within 5 or 10 seconds.
    for row in rows:
        for horizon in HORIZONS:
            future = lookup.get((
                row["phase"],
                round(row["elapsed_s"] + horizon, 3)
            ))

            event_key = "event_{}s".format(horizon)

            if future is None:
                row[event_key] = None
            else:
                rise = future["gpu_temp_C"] - row["gpu_temp_C"]
                row[event_key] = rise >= EVENT_RISE_C

    detector_names = [
        "one_step",
        "sustained",
        "rolling_0.5",
        "rolling_1.0",
        "rolling_1.5",
    ]

    def alert_value(row, detector):
        if detector == "one_step":
            return row["one_step_alert"]
        if detector == "sustained":
            return row["sustained_alert"]
        return row[detector + "_alert"]

    def metrics(subset, detector, horizon):
        tp = fp = fn = tn = 0

        for row in subset:
            event = row["event_{}s".format(horizon)]

            # Exclude rows without a same-phase future sample.
            if event is None:
                continue

            alert = alert_value(row, detector)

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

    # Save one row per sample with every detector and event label.
    detail_fields = [
        "elapsed_s", "phase", "gpu_temp_C",
        "one_step_alert", "sustained_alert",
        "rolling_0.5_alert", "rolling_1.0_alert",
        "rolling_1.5_alert",
        "event_5s", "event_10s", "applied",
    ]

    with open(OUTPUT, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=detail_fields)
        writer.writeheader()

        for row in rows:
            out = {
                "elapsed_s": row["elapsed_s"],
                "phase": row["phase"],
                "gpu_temp_C": row["gpu_temp_C"],
                "one_step_alert": "YES" if row["one_step_alert"] else "NO",
                "sustained_alert": "YES" if row["sustained_alert"] else "NO",
                "rolling_0.5_alert": (
                    "YES" if row["rolling_0.5_alert"] else "NO"
                ),
                "rolling_1.0_alert": (
                    "YES" if row["rolling_1.0_alert"] else "NO"
                ),
                "rolling_1.5_alert": (
                    "YES" if row["rolling_1.5_alert"] else "NO"
                ),
                "event_5s": (
                    "NA" if row["event_5s"] is None
                    else "YES" if row["event_5s"] else "NO"
                ),
                "event_10s": (
                    "NA" if row["event_10s"] is None
                    else "YES" if row["event_10s"] else "NO"
                ),
                "applied": "NO",
            }
            writer.writerow(out)

    print("GPU rolling-change detector evaluation")
    print("Input:", INPUT)
    print("Detailed output:", OUTPUT)
    print("Event: future GPU rise >= {:.1f} C".format(EVENT_RISE_C))
    print("Only same-phase future samples are scored.")
    print("All scheduling actions remain unapplied.")
    print()

    header = (
        "{:<18} {:>3} {:<12} {:>5} {:>4} {:>4} {:>4} "
        "{:>4} {:>9} {:>8}"
    )
    print(header.format(
        "Phase", "H", "Detector", "N", "TP", "FP",
        "FN", "TN", "Precision", "Recall"
    ))

    report = []

    phases = sorted(by_phase.keys()) + ["ALL_PHASES"]

    for phase in phases:
        subset = rows if phase == "ALL_PHASES" else by_phase[phase]

        for horizon in HORIZONS:
            for detector in detector_names:
                total, tp, fp, fn, tn, precision, recall = metrics(
                    subset, detector, horizon
                )

                print(header.format(
                    phase, horizon, detector, total, tp, fp, fn, tn,
                    "{:.3f}".format(precision)
                    if precision is not None else "N/A",
                    "{:.3f}".format(recall)
                    if recall is not None else "N/A",
                ))

                report.append({
                    "phase": phase,
                    "horizon_s": horizon,
                    "detector": detector,
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

    summary_file = "thermal_rolling_detector_summary_20261026.csv"
    summary_fields = [
        "phase", "horizon_s", "detector", "scored_samples",
        "TP", "FP", "FN", "TN", "precision", "recall",
        "event_rise_C", "applied",
    ]

    with open(summary_file, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=summary_fields)
        writer.writeheader()
        writer.writerows(report)

    print()
    print("Saved detail:", OUTPUT)
    print("Saved summary:", summary_file)
    print("Thresholds are exploratory, not hardware safety limits.")


if __name__ == "__main__":
    main()
