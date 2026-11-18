#!/usr/bin/env python3

import csv
import os
from collections import defaultdict

FILES = [
    "rt_tas_controlled_20261011_172905.csv",
    "rt_tas_controlled_20261014_011135.csv",
    "rt_tas_controlled_20261021_163039.csv",
    "rt_tas_controlled_20261025_175625.csv",
    "rt_tas_controlled_20261026_221300.csv",
]

OUTPUT = "thermal_multirun_detector_results.csv"
SUMMARY = "thermal_multirun_detector_summary.csv"

HORIZONS = (5, 10)
EVENT_RISE_C = 0.5
THRESHOLDS = (0.5, 1.0, 1.5)


def number(row, key):
    try:
        value = row.get(key, "")
        if value == "":
            return None
        return float(value)
    except (ValueError, TypeError):
        return None


def load_run(path):
    rows = []

    with open(path, "r", newline="") as f:
        reader = csv.DictReader(f)
        required = ["elapsed_s", "phase", "gpu_edge_C"]
        missing = [
            col for col in required
            if col not in (reader.fieldnames or [])
        ]

        if missing:
            raise ValueError(
                "{} missing columns: {}".format(path, ", ".join(missing))
            )

        for source in reader:
            elapsed = number(source, "elapsed_s")
            temp = number(source, "gpu_edge_C")

            if elapsed is None or temp is None:
                continue

            rows.append({
                "run": os.path.basename(path),
                "elapsed_s": elapsed,
                "phase": source["phase"],
                "gpu_temp_C": temp,
            })

    rows.sort(key=lambda r: r["elapsed_s"])

    by_phase = defaultdict(list)
    lookup = {}

    for row in rows:
        by_phase[row["phase"]].append(row)
        lookup[(row["phase"], round(row["elapsed_s"], 3))] = row

    # All detectors use current or past readings only.
    for phase, samples in by_phase.items():
        samples.sort(key=lambda r: r["elapsed_s"])

        for i, row in enumerate(samples):
            row["previous_delta_C"] = None
            row["rolling_delta_C"] = None
            row["strict_three_rise"] = False

            if i >= 1:
                prev = samples[i - 1]
                if abs(row["elapsed_s"] - prev["elapsed_s"] - 1.0) < 0.01:
                    row["previous_delta_C"] = (
                        row["gpu_temp_C"] - prev["gpu_temp_C"]
                    )

            if i >= 2:
                first = samples[i - 2]
                middle = samples[i - 1]

                consecutive = (
                    abs(middle["elapsed_s"] - first["elapsed_s"] - 1.0)
                    < 0.01
                    and abs(row["elapsed_s"] - middle["elapsed_s"] - 1.0)
                    < 0.01
                )

                if consecutive:
                    row["rolling_delta_C"] = (
                        row["gpu_temp_C"] - first["gpu_temp_C"]
                    )
                    row["strict_three_rise"] = (
                        first["gpu_temp_C"] < middle["gpu_temp_C"]
                        and middle["gpu_temp_C"] < row["gpu_temp_C"]
                    )

            # Future events are scored only if the target stays in this phase.
            for horizon in HORIZONS:
                future = lookup.get((
                    phase, round(row["elapsed_s"] + horizon, 3)
                ))

                if future is None:
                    row["event_{}s".format(horizon)] = None
                else:
                    row["event_{}s".format(horizon)] = (
                        future["gpu_temp_C"] - row["gpu_temp_C"]
                        >= EVENT_RISE_C
                    )

    return rows


def detector_alert(row, detector, threshold):
    if detector == "one_step":
        value = row["previous_delta_C"]
        return value is not None and value >= threshold

    if detector == "rolling":
        value = row["rolling_delta_C"]
        return value is not None and value >= threshold

    if detector == "sustained":
        value = row["rolling_delta_C"]
        return (
            value is not None
            and row["strict_three_rise"]
            and value >= threshold
        )

    return False


def counts(rows, detector, threshold, horizon):
    tp = fp = fn = tn = 0

    for row in rows:
        event = row["event_{}s".format(horizon)]
        if event is None:
            continue

        alert = detector_alert(row, detector, threshold)

        if alert and event:
            tp += 1
        elif alert and not event:
            fp += 1
        elif not alert and event:
            fn += 1
        else:
            tn += 1

    return tp, fp, fn, tn


def score(rows, detector, threshold, horizon):
    tp, fp, fn, tn = counts(rows, detector, threshold, horizon)
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = (
        2 * precision * recall / (precision + recall)
        if precision + recall else 0.0
    )
    return {
        "N": tp + fp + fn + tn,
        "TP": tp,
        "FP": fp,
        "FN": fn,
        "TN": tn,
        "precision": precision,
        "recall": recall,
        "F1": f1,
        "alerts": tp + fp,
    }


def choose_threshold(training_rows, detector, horizon):
    candidates = []

    for threshold in THRESHOLDS:
        result = score(training_rows, detector, threshold, horizon)

        # Maximize training F1; ties prefer fewer false alarms,
        # then higher precision, then the higher threshold.
        candidates.append((
            result["F1"],
            -result["FP"],
            result["precision"],
            threshold,
            result,
        ))

    candidates.sort(reverse=True)
    best = candidates[0]

    return best[3], best[4]


def main():
    available = []
    missing = []

    for path in FILES:
        if os.path.isfile(path):
            available.append(path)
        else:
            missing.append(path)

    print("Multi-run GPU detector evaluation")
    print("Event definition: future GPU rise >= {:.1f} C".format(EVENT_RISE_C))
    print("Horizons:", HORIZONS)
    print("Threshold candidates:", THRESHOLDS)
    print("Actions applied: NO")
    print()

    for path in available:
        print("Found:", path)

    for path in missing:
        print("MISSING:", path)

    if len(available) < 3:
        print()
        print("ERROR: At least 3 CSV runs are required.")
        print("Check filenames with: ls rt_tas_controlled_*.csv")
        return

    runs = {}

    for path in available:
        try:
            runs[path] = load_run(path)
        except (OSError, ValueError) as exc:
            print("ERROR loading", path, ":", exc)
            return

    print()
    print("Loaded run sample counts:")
    for path in available:
        print(os.path.basename(path), len(runs[path]))

    detectors = ("one_step", "rolling", "sustained")
    detail_rows = []
    summary_rows = []

    # Leave one entire run out at a time.
    for test_path in available:
        training_rows = []

        for path in available:
            if path != test_path:
                training_rows.extend(runs[path])

        test_rows = runs[test_path]
        test_name = os.path.basename(test_path)

        print()
        print("=" * 78)
        print("HELD-OUT RUN:", test_name)
        print("Training runs:", len(available) - 1)
        print("Held-out rows:", len(test_rows))
        print("=" * 78)

        print(
            "{:<10} {:>3} {:>9} {:>5} {:>4} {:>4} {:>4} "
            "{:>4} {:>9} {:>8} {:>7}".format(
                "Detector", "H", "Threshold", "N", "TP", "FP",
                "FN", "TN", "Precision", "Recall", "F1"
            )
        )

        for horizon in HORIZONS:
            for detector in detectors:
                threshold, train_result = choose_threshold(
                    training_rows, detector, horizon
                )
                test_result = score(
                    test_rows, detector, threshold, horizon
                )

                print(
                    "{:<10} {:>3} {:>8.1f}C {:>5} {:>4} {:>4} {:>4} "
                    "{:>4} {:>9.3f} {:>8.3f} {:>7.3f}".format(
                        detector, horizon, threshold, test_result["N"],
                        test_result["TP"], test_result["FP"],
                        test_result["FN"], test_result["TN"],
                        test_result["precision"], test_result["recall"],
                        test_result["F1"]
                    )
                )

                summary_rows.append({
                    "heldout_run": test_name,
                    "training_run_count": len(available) - 1,
                    "horizon_s": horizon,
                    "detector": detector,
                    "selected_threshold_C": threshold,
                    "training_N": train_result["N"],
                    "training_TP": train_result["TP"],
                    "training_FP": train_result["FP"],
                    "training_FN": train_result["FN"],
                    "training_TN": train_result["TN"],
                    "training_precision": round(
                        train_result["precision"], 4
                    ),
                    "training_recall": round(train_result["recall"], 4),
                    "training_F1": round(train_result["F1"], 4),
                    "test_N": test_result["N"],
                    "test_TP": test_result["TP"],
                    "test_FP": test_result["FP"],
                    "test_FN": test_result["FN"],
                    "test_TN": test_result["TN"],
                    "test_precision": round(
                        test_result["precision"], 4
                    ),
                    "test_recall": round(test_result["recall"], 4),
                    "test_F1": round(test_result["F1"], 4),
                    "applied": "NO",
                })

                for row in test_rows:
                    event = row["event_{}s".format(horizon)]
                    if event is None:
                        continue

                    detail_rows.append({
                        "heldout_run": test_name,
                        "elapsed_s": row["elapsed_s"],
                        "phase": row["phase"],
                        "horizon_s": horizon,
                        "detector": detector,
                        "threshold_C": threshold,
                        "gpu_temp_C": row["gpu_temp_C"],
                        "alert": (
                            "YES" if detector_alert(
                                row, detector, threshold
                            ) else "NO"
                        ),
                        "future_rise_event": "YES" if event else "NO",
                        "applied": "NO",
                    })

    summary_fields = [
        "heldout_run", "training_run_count", "horizon_s", "detector",
        "selected_threshold_C",
        "training_N", "training_TP", "training_FP", "training_FN",
        "training_TN", "training_precision", "training_recall",
        "training_F1", "test_N", "test_TP", "test_FP", "test_FN",
        "test_TN", "test_precision", "test_recall", "test_F1", "applied",
    ]

    detail_fields = [
        "heldout_run", "elapsed_s", "phase", "horizon_s", "detector",
        "threshold_C", "gpu_temp_C", "alert", "future_rise_event", "applied",
    ]

    with open(SUMMARY, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=summary_fields)
        writer.writeheader()
        writer.writerows(summary_rows)

    with open(OUTPUT, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=detail_fields)
        writer.writeheader()
        writer.writerows(detail_rows)

    print()
    print("Finished.")
    print("Summary:", SUMMARY)
    print("Per-sample details:", OUTPUT)
    print("Threshold selection used training runs only.")
    print("Held-out runs were not used to select their own thresholds.")
    print("All actions remain unapplied.")


if __name__ == "__main__":
    main()
