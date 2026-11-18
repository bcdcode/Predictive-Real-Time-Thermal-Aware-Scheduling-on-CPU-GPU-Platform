#!/usr/bin/env python3
import csv
import math
import os

FILES = [
    "rt_tas_controlled_20261011_172905.csv",
    "rt_tas_controlled_20261014_011135.csv",
    "rt_tas_controlled_20261021_163039.csv",
    "rt_tas_controlled_20261025_175625.csv",
    "rt_tas_controlled_20261026_221300.csv",
]
HORIZONS = (5, 10)
TOLERANCE = 0.75
RISE_C = 0.5

SUMMARY_OUT = "thermal_context_ablation_summary.csv"
DETAIL_OUT = "thermal_context_ablation_details.csv"

DETECTORS = {
    "gpu_temperature_trend": "gpu_temp_score",
    "gpu_workload_state": "gpu_state_score",
    "gpu_frequency_activity": "gpu_freq_activity_score",
    "cpu_activity_temp_trend": "cpu_score",
    "combined_context": "combined_score",
}


def num(row, key):
    try:
        x = float(row.get(key, ""))
        return x if math.isfinite(x) else float("nan")
    except (TypeError, ValueError):
        return float("nan")


def is_on(value):
    return str(value).strip().upper() in ("ON", "1", "TRUE", "YES")


def load_run(path):
    with open(path, newline="") as f:
        raw = list(csv.DictReader(f))
    if not raw:
        raise ValueError("Empty CSV: " + path)

    required = {
        "elapsed_s", "phase", "gpu_edge_C", "gpu_freq_MHz",
        "gpu_activity_proxy", "cpu_tctl_C", "cpu_active", "gpu_enabled"
    }
    missing = required - set(raw[0])
    if missing:
        raise ValueError("%s missing columns: %s" % (path, sorted(missing)))

    rows = []
    for r in raw:
        rows.append({
            "elapsed_s": num(r, "elapsed_s"),
            "phase": str(r["phase"]).strip(),
            "gpu_edge_C": num(r, "gpu_edge_C"),
            "gpu_freq_MHz": num(r, "gpu_freq_MHz"),
            "gpu_activity_proxy": num(r, "gpu_activity_proxy"),
            "cpu_tctl_C": num(r, "cpu_tctl_C"),
            "cpu_active": int(is_on(r["cpu_active"])),
            "gpu_enabled": int(is_on(r["gpu_enabled"])),
        })
    return sorted(rows, key=lambda r: r["elapsed_s"])


def phase_start(rows, i):
    start = i
    while start > 0 and rows[start - 1]["phase"] == rows[i]["phase"]:
        start -= 1
    return start


def past_index(rows, i, seconds):
    target = rows[i]["elapsed_s"] - seconds
    best, error_best = None, float("inf")
    for j in range(i - 1, -1, -1):
        if rows[j]["phase"] != rows[i]["phase"]:
            break
        error = abs(rows[j]["elapsed_s"] - target)
        if error < error_best:
            best, error_best = j, error
        if rows[j]["elapsed_s"] < target - TOLERANCE:
            break
    return best if best is not None and error_best <= TOLERANCE else None


def future_index(rows, i, horizon):
    target = rows[i]["elapsed_s"] + horizon
    best, error_best = None, float("inf")
    for j in range(i + 1, len(rows)):
        if rows[j]["phase"] != rows[i]["phase"]:
            break
        error = abs(rows[j]["elapsed_s"] - target)
        if error < error_best:
            best, error_best = j, error
        if rows[j]["elapsed_s"] > target + TOLERANCE:
            break
    return best if best is not None and error_best <= TOLERANCE else None


def cpu_slope(rows, i, seconds=4):
    start = phase_start(rows, i)
    hist = []
    for j in range(start, i + 1):
        if rows[i]["elapsed_s"] - rows[j]["elapsed_s"] <= seconds:
            y = rows[j]["cpu_tctl_C"]
            if math.isfinite(y):
                hist.append((rows[j]["elapsed_s"], y))
    if len(hist) < 3:
        return 0.0
    mt = sum(t for t, y in hist) / len(hist)
    my = sum(y for t, y in hist) / len(hist)
    den = sum((t - mt) ** 2 for t, y in hist)
    if den <= 0:
        return 0.0
    return sum((t - mt) * (y - my) for t, y in hist) / den


def build_examples(rows, horizon, run_name):
    examples = []
    for i, r in enumerate(rows):
        j = future_index(rows, i, horizon)
        p = past_index(rows, i, 2)
        if j is None or p is None:
            continue

        required_values = [
            r["gpu_edge_C"], rows[p]["gpu_edge_C"],
            r["gpu_freq_MHz"], rows[p]["gpu_freq_MHz"],
            r["gpu_activity_proxy"], rows[p]["gpu_activity_proxy"],
            r["cpu_tctl_C"],
        ]
        if not all(math.isfinite(x) for x in required_values):
            continue

        temp_delta = r["gpu_edge_C"] - rows[p]["gpu_edge_C"]
        freq_delta = r["gpu_freq_MHz"] - rows[p]["gpu_freq_MHz"]
        activity_delta = (
            r["gpu_activity_proxy"] - rows[p]["gpu_activity_proxy"]
        )
        slope = cpu_slope(rows, i)

        # Component scores use current/past data only.
        gpu_temp_score = float(temp_delta >= 0.5)
        gpu_state_score = float(r["gpu_enabled"] == 1)

        # Group frequency/activity signals together.
        gpu_freq_activity_score = (
            float(
                r["gpu_enabled"] == 1
                and (activity_delta > 0.02 or freq_delta >= 100.0)
            )
            + 0.5 * float(
                r["gpu_enabled"] == 1
                and r["gpu_activity_proxy"] >= 0.20
            )
        )

        cpu_score = 0.5 * float(
            r["cpu_active"] == 1 and slope > 0.05
        )

        combined_score = (
            gpu_temp_score
            + gpu_state_score
            + float(
                r["gpu_enabled"] == 1
                and (activity_delta > 0.02 or freq_delta >= 100.0)
            )
            + 0.5 * float(
                r["gpu_enabled"] == 1
                and r["gpu_activity_proxy"] >= 0.20
            )
            + cpu_score
        )

        examples.append({
            "run": run_name,
            "phase": r["phase"],
            "elapsed_s": r["elapsed_s"],
            "horizon_s": horizon,
            "future_rise": int(
                rows[j]["gpu_edge_C"] - r["gpu_edge_C"] >= RISE_C
            ),
            "gpu_temp_score": gpu_temp_score,
            "gpu_state_score": gpu_state_score,
            "gpu_freq_activity_score": gpu_freq_activity_score,
            "cpu_score": cpu_score,
            "combined_score": combined_score,
        })
    return examples


def metrics(examples, field, threshold):
    tp = fp = fn = tn = 0
    for e in examples:
        pred = e[field] >= threshold
        actual = bool(e["future_rise"])
        if pred and actual:
            tp += 1
        elif pred:
            fp += 1
        elif actual:
            fn += 1
        else:
            tn += 1

    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {
        "N": len(examples), "TP": tp, "FP": fp, "FN": fn, "TN": tn,
        "precision": precision, "recall": recall, "F1": f1,
    }


def candidate_thresholds(field):
    # Binary groups are tested as on/off. Fractional combined/frequency
    # scores have explicit positive thresholds.
    if field in ("gpu_temp_score", "gpu_state_score"):
        return [0.5]
    if field == "gpu_freq_activity_score":
        return [0.5, 1.0, 1.5]
    if field == "cpu_score":
        return [0.25]
    if field == "combined_score":
        return [1.0, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0]

    raise ValueError("Unknown score field: " + field)


def choose_threshold(train, field):
    best = None
    for threshold in candidate_thresholds(field):
        m = metrics(train, field, threshold)
        # Maximize F1; tie-break with fewer false positives, then precision.
        key = (m["F1"], -m["FP"], m["precision"], threshold)
        if best is None or key > best[0]:
            best = (key, threshold)
    return best[1]


def main():
    loaded = {}
    for path in FILES:
        if not os.path.isfile(path):
            raise FileNotFoundError("Missing raw run: " + path)
        loaded[path] = load_run(path)
        print("Loaded %-42s %d rows" % (path, len(loaded[path])))

    summary, details = [], []

    for horizon in HORIZONS:
        by_run = {
            name: build_examples(rows, horizon, name)
            for name, rows in loaded.items()
        }

        for heldout in FILES:
            test = by_run[heldout]
            train = [
                e for name, run_examples in by_run.items()
                if name != heldout
                for e in run_examples
            ]
            if not train or not test:
                print("Skipping", horizon, heldout, "(insufficient examples)")
                continue

            for detector, field in DETECTORS.items():
                threshold = choose_threshold(train, field)
                m = metrics(test, field, threshold)
                rec = {
                    "heldout_run": heldout,
                    "horizon_s": horizon,
                    "detector": detector,
                    "score_threshold": threshold,
                    **m,
                }
                summary.append(rec)

                for e in test:
                    details.append({
                        **e,
                        "heldout_run": heldout,
                        "detector": detector,
                        "score_threshold": threshold,
                        "prediction": int(e[field] >= threshold),
                    })

                print(
                    "%2ds %-25s heldout=%s threshold=%.2f "
                    "N=%d TP=%d FP=%d FN=%d TN=%d P=%.3f R=%.3f F1=%.3f"
                    % (
                        horizon, detector, os.path.basename(heldout),
                        threshold, m["N"], m["TP"], m["FP"], m["FN"],
                        m["TN"], m["precision"], m["recall"], m["F1"]
                    )
                )

    if not summary:
        raise RuntimeError("No results produced.")

    with open(SUMMARY_OUT, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(summary[0].keys()))
        w.writeheader()
        w.writerows(summary)

    with open(DETAIL_OUT, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(details[0].keys()))
        w.writeheader()
        w.writerows(details)

    print("\nSaved:", SUMMARY_OUT)
    print("Saved:", DETAIL_OUT)
    print("\nPOOLED HELD-OUT RESULTS")
    print("Horizon,Detector,N,TP,FP,FN,TN,Precision,Recall,F1")

    for horizon in HORIZONS:
        for detector in DETECTORS:
            subset = [
                e for e in details
                if e["horizon_s"] == horizon and e["detector"] == detector
            ]
            tp = sum(e["prediction"] == 1 and e["future_rise"] == 1 for e in subset)
            fp = sum(e["prediction"] == 1 and e["future_rise"] == 0 for e in subset)
            fn = sum(e["prediction"] == 0 and e["future_rise"] == 1 for e in subset)
            tn = sum(e["prediction"] == 0 and e["future_rise"] == 0 for e in subset)
            p = tp / (tp + fp) if tp + fp else 0.0
            r = tp / (tp + fn) if tp + fn else 0.0
            f1 = 2 * p * r / (p + r) if p + r else 0.0
            print(
                "%d,%s,%d,%d,%d,%d,%d,%.3f,%.3f,%.3f"
                % (horizon, detector, len(subset), tp, fp, fn, tn, p, r, f1)
            )


if __name__ == "__main__":
    main()
