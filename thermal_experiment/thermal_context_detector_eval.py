#!/usr/bin/env python3
import csv
import math
import os
import statistics

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
TEMP_THRESHOLDS = (0.5, 1.0, 1.5)

SUMMARY_OUT = "thermal_context_detector_summary.csv"
RESULTS_OUT = "thermal_context_detector_results.csv"


def number(row, key, default=float("nan")):
    try:
        v = float(row.get(key, ""))
        return v if math.isfinite(v) else default
    except (TypeError, ValueError):
        return default


def on_off(value):
    return str(value).strip().upper() in ("ON", "1", "TRUE", "YES")


def load_run(path):
    with open(path, newline="") as f:
        raw = list(csv.DictReader(f))

    if not raw:
        raise ValueError("No CSV rows in " + path)

    required = {
        "elapsed_s", "phase", "gpu_edge_C", "gpu_freq_MHz",
        "gpu_activity_proxy", "cpu_tctl_C", "cpu_active", "gpu_enabled"
    }
    missing = required - set(raw[0].keys())
    if missing:
        raise ValueError("%s missing columns: %s" % (path, sorted(missing)))

    rows = []
    for r in raw:
        rows.append({
            "elapsed_s": number(r, "elapsed_s"),
            "phase": str(r["phase"]).strip(),
            "gpu_edge_C": number(r, "gpu_edge_C"),
            "gpu_freq_MHz": number(r, "gpu_freq_MHz"),
            "gpu_activity_proxy": number(r, "gpu_activity_proxy"),
            "cpu_tctl_C": number(r, "cpu_tctl_C"),
            "cpu_active": int(on_off(r["cpu_active"])),
            "gpu_enabled": int(on_off(r["gpu_enabled"])),
        })

    rows.sort(key=lambda x: x["elapsed_s"])
    return rows


def phase_start(rows, i):
    start = i
    while start > 0 and rows[start - 1]["phase"] == rows[i]["phase"]:
        start -= 1
    return start


def past_index(rows, i, seconds):
    """Find the nearest past sample to i's timestamp minus seconds."""
    target = rows[i]["elapsed_s"] - seconds
    best = None
    best_error = float("inf")

    for j in range(i - 1, -1, -1):
        if rows[j]["phase"] != rows[i]["phase"]:
            break
        error = abs(rows[j]["elapsed_s"] - target)
        if error < best_error:
            best, best_error = j, error
        if rows[j]["elapsed_s"] < target - TOLERANCE:
            break

    if best is not None and best_error <= TOLERANCE:
        return best
    return None


def future_index(rows, i, horizon):
    target = rows[i]["elapsed_s"] + horizon
    best = None
    best_error = float("inf")

    for j in range(i + 1, len(rows)):
        if rows[j]["phase"] != rows[i]["phase"]:
            break
        error = abs(rows[j]["elapsed_s"] - target)
        if error < best_error:
            best, best_error = j, error
        if rows[j]["elapsed_s"] > target + TOLERANCE:
            break

    if best is not None and best_error <= TOLERANCE:
        return best
    return None


def slope_over_recent(rows, i, key, seconds=4):
    """Least-squares slope using only current/past samples in this phase."""
    start = phase_start(rows, i)
    hist = []
    for j in range(start, i + 1):
        if rows[i]["elapsed_s"] - rows[j]["elapsed_s"] <= seconds:
            y = rows[j][key]
            if math.isfinite(y):
                hist.append((rows[j]["elapsed_s"], y))

    if len(hist) < 3:
        return 0.0

    mt = sum(t for t, _ in hist) / len(hist)
    my = sum(y for _, y in hist) / len(hist)
    den = sum((t - mt) ** 2 for t, _ in hist)
    if den <= 0:
        return 0.0

    return sum((t - mt) * (y - my) for t, y in hist) / den


def make_examples(rows, horizon, run_name):
    examples = []

    for i, r in enumerate(rows):
        j = future_index(rows, i, horizon)
        if j is None:
            continue

        # Require a usable two-second past comparison and valid key sensors.
        p = past_index(rows, i, 2)
        if p is None:
            continue

        required_values = [
            r["gpu_edge_C"], rows[p]["gpu_edge_C"],
            r["gpu_freq_MHz"], rows[p]["gpu_freq_MHz"],
            r["gpu_activity_proxy"], rows[p]["gpu_activity_proxy"],
            r["cpu_tctl_C"],
        ]
        if not all(math.isfinite(v) for v in required_values):
            continue

        gpu_temp_delta = r["gpu_edge_C"] - rows[p]["gpu_edge_C"]
        gpu_freq_delta = r["gpu_freq_MHz"] - rows[p]["gpu_freq_MHz"]
        activity_delta = (
            r["gpu_activity_proxy"] - rows[p]["gpu_activity_proxy"]
        )
        cpu_slope = slope_over_recent(rows, i, "cpu_tctl_C")

        # All detector inputs are known at the time of the prediction.
        # No future samples are used to compute these features.
        context_score = (
            1.0 * (gpu_temp_delta >= 0.5)
            + 1.0 * (r["gpu_enabled"] == 1)
            + 1.0 * (
                r["gpu_enabled"] == 1
                and (
                    activity_delta > 0.02
                    or gpu_freq_delta >= 100.0
                )
            )
            + 0.5 * (
                r["gpu_enabled"] == 1
                and r["gpu_activity_proxy"] >= 0.20
            )
            + 0.5 * (
                r["cpu_active"] == 1 and cpu_slope > 0.05
            )
        )

        examples.append({
            "run": run_name,
            "phase": r["phase"],
            "elapsed_s": r["elapsed_s"],
            "horizon_s": horizon,
            "future_rise": int(
                rows[j]["gpu_edge_C"] - r["gpu_edge_C"] >= RISE_C
            ),
            "rolling_delta": gpu_temp_delta,
            "context_score": context_score,
            "gpu_enabled": r["gpu_enabled"],
            "gpu_activity_proxy": r["gpu_activity_proxy"],
            "gpu_freq_delta": gpu_freq_delta,
            "cpu_active": r["cpu_active"],
            "cpu_temp_slope": cpu_slope,
        })

    return examples


def metrics(examples, field, threshold):
    tp = fp = fn = tn = 0
    for e in examples:
        pred = e[field] >= threshold
        actual = bool(e["future_rise"])
        if pred and actual:
            tp += 1
        elif pred and not actual:
            fp += 1
        elif not pred and actual:
            fn += 1
        else:
            tn += 1

    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = (
        2 * precision * recall / (precision + recall)
        if precision + recall else 0.0
    )

    return {
        "N": len(examples), "TP": tp, "FP": fp, "FN": fn, "TN": tn,
        "precision": precision, "recall": recall, "F1": f1,
    }


def select_threshold(train, field):
    # Use fixed, physically meaningful candidate thresholds.
    # Never allow a negative temperature-rise threshold.
    if field == "rolling_delta":
        candidates = [0.5, 1.0, 1.5]
    else:
        candidates = [1.0, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0]

    scored = []
    for threshold in candidates:
        m = metrics(train, field, threshold)
        # F1 first, then fewer false alarms, then better precision.
        scored.append((
            m["F1"], -m["FP"], m["precision"], threshold
        ))

    return max(scored)[3]


def main():
    loaded = {}
    for path in FILES:
        if not os.path.isfile(path):
            raise FileNotFoundError(
                "Missing %s. Put this script beside the raw CSV files." % path
            )
        loaded[path] = load_run(path)
        print("Loaded %-42s %d rows" % (path, len(loaded[path])))

    all_results = []
    summary = []

    for horizon in HORIZONS:
        examples_by_run = {
            name: make_examples(rows, horizon, name)
            for name, rows in loaded.items()
        }

        for heldout in FILES:
            test = examples_by_run[heldout]
            train = [
                e
                for name, examples in examples_by_run.items()
                if name != heldout
                for e in examples
            ]

            if not train or not test:
                print("Skipping", horizon, heldout, "(insufficient examples)")
                continue

            # Temperature-only baseline: rolling 2-second temperature delta.
            base_threshold = select_threshold(train, "rolling_delta")

            # Workload/context detector: threshold on the combined rule score.
            context_threshold = select_threshold(train, "context_score")

            for detector, field, threshold in (
                ("rolling_temperature_only", "rolling_delta", base_threshold),
                ("workload_context", "context_score", context_threshold),
            ):
                m = metrics(test, field, threshold)
                record = {
                    "heldout_run": heldout,
                    "horizon_s": horizon,
                    "detector": detector,
                    "threshold": threshold,
                    **m,
                }
                summary.append(record)

                for e in test:
                    all_results.append({
                        **e,
                        "heldout_run": heldout,
                        "detector": detector,
                        "threshold": threshold,
                        "prediction": int(e[field] >= threshold),
                    })

                print(
                    "%2ds %-24s heldout=%s threshold=%.3f "
                    "N=%d TP=%d FP=%d FN=%d TN=%d "
                    "P=%.3f R=%.3f F1=%.3f"
                    % (
                        horizon, detector,
                        os.path.basename(heldout),
                        threshold, m["N"], m["TP"], m["FP"],
                        m["FN"], m["TN"], m["precision"],
                        m["recall"], m["F1"],
                    )
                )

    if not summary:
        raise RuntimeError("No results produced; check CSV sampling intervals.")

    with open(SUMMARY_OUT, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(summary[0].keys()))
        w.writeheader()
        w.writerows(summary)

    with open(RESULTS_OUT, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(all_results[0].keys()))
        w.writeheader()
        w.writerows(all_results)

    print("\nSaved:", SUMMARY_OUT)
    print("Saved:", RESULTS_OUT)
    print("\nPOOLED HELD-OUT RESULTS (descriptive; overlapping windows are not independent)")
    for horizon in HORIZONS:
        for detector in ("rolling_temperature_only", "workload_context"):
            pooled = [
                e for e in all_results
                if e["horizon_s"] == horizon and e["detector"] == detector
            ]
            # Each prediction is scored with the threshold selected without
            # using its held-out run.
            tp = sum(e["prediction"] == 1 and e["future_rise"] == 1 for e in pooled)
            fp = sum(e["prediction"] == 1 and e["future_rise"] == 0 for e in pooled)
            fn = sum(e["prediction"] == 0 and e["future_rise"] == 1 for e in pooled)
            tn = sum(e["prediction"] == 0 and e["future_rise"] == 0 for e in pooled)
            p = tp / (tp + fp) if tp + fp else 0.0
            r = tp / (tp + fn) if tp + fn else 0.0
            f1 = 2 * p * r / (p + r) if p + r else 0.0
            print(
                "%2ds %-24s N=%d TP=%d FP=%d FN=%d TN=%d "
                "precision=%.3f recall=%.3f F1=%.3f"
                % (horizon, detector, len(pooled), tp, fp, fn, tn, p, r, f1)
            )


if __name__ == "__main__":
    main()
