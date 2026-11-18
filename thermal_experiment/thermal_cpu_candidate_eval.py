#!/usr/bin/env python3
"""Offline comparison of thermal-warning scores using existing CSV data."""

import csv
from collections import defaultdict

INPUT = "thermal_dynamic_predictions.csv"
OUTPUT = "thermal_cpu_candidate_predictions.csv"
SUMMARY = "thermal_cpu_candidate_summary.csv"

def balanced_metrics(labels, preds):
    tp = sum(y == 1 and p == 1 for y, p in zip(labels, preds))
    fp = sum(y == 0 and p == 1 for y, p in zip(labels, preds))
    fn = sum(y == 1 and p == 0 for y, p in zip(labels, preds))
    tn = sum(y == 0 and p == 0 for y, p in zip(labels, preds))
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    specificity = tn / (tn + fp) if tn + fp else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {
        "N": len(labels), "TP": tp, "FP": fp, "FN": fn, "TN": tn,
        "precision": precision, "recall": recall, "specificity": specificity,
        "balanced_accuracy": (recall + specificity) / 2, "F1": f1,
    }

def choose_threshold(train, score_key):
    values = sorted(set(x[score_key] for x in train))
    candidates = [values[0] - 1] + values + [values[-1] + 1]
    best_key = None
    best_th = candidates[0]

    for th in candidates:
        preds = [int(x[score_key] >= th) for x in train]
        m = balanced_metrics([x["actual"] for x in train], preds)
        nontrivial = int(0 < sum(preds) < len(preds))
        key = (m["balanced_accuracy"], nontrivial, m["F1"], m["precision"], th)
        if best_key is None or key > best_key:
            best_key, best_th = key, th
    return best_th

def main():
    with open(INPUT, newline="") as f:
        raw = list(csv.DictReader(f))

    # One row per sample/horizon, independent of detector copies.
    samples = {}
    for r in raw:
        key = (r["run"], r["horizon"], r["t"], r["phase"])
        if key in samples:
            continue
        samples[key] = {
            "run": r["run"],
            "horizon": r["horizon"],
            "t": float(r["t"]),
            "phase": r["phase"],
            "actual": int(r["actual"]),
            "gpu_state_score": int(r["gpu_state_score"]),
            "dynamic_score": int(r["dynamic_score"]),
            "cpu_score": 2 * int(r["cpu_temp_rising"]) + 2 * int(r["cpu_active"]),
        }

    all_rows = []
    summary = []
    horizons = sorted({x["horizon"] for x in samples.values()}, key=int)
    run_names = sorted({x["run"] for x in samples.values()})

    score_keys = {
        "gpu_state_only": "gpu_state_score",
        "dynamic_detector": "dynamic_score",
        "cpu_informed": "cpu_score",
    }

    for horizon in horizons:
        data = [x for x in samples.values() if x["horizon"] == horizon]

        for held in run_names:
            train = [x for x in data if x["run"] != held]
            test = [x for x in data if x["run"] == held]

            # Thresholds are chosen from training runs only.
            thresholds = {
                name: choose_threshold(train, key)
                for name, key in score_keys.items()
            }

            phase_rates = defaultdict(list)
            for x in train:
                phase_rates[x["phase"]].append(x["actual"])
            overall_rate = sum(x["actual"] for x in train) / len(train)

            # Phase-only predicts the training event rate for that phase.
            # Choose a binary threshold of 0.5, without fitting on the test run.
            phase_predictions = [
                int((sum(phase_rates[x["phase"]]) / len(phase_rates[x["phase"]])
                     if x["phase"] in phase_rates else overall_rate) >= 0.5)
                for x in test
            ]

            predictions = {
                name: [int(x[key] >= thresholds[name]) for x in test]
                for name, key in score_keys.items()
            }
            predictions["phase_only"] = phase_predictions

            for detector, preds in predictions.items():
                for x, pred in zip(test, preds):
                    all_rows.append({
                        **x,
                        "held_out_run": held,
                        "detector": detector,
                        "threshold": thresholds.get(detector, 0.5),
                        "prediction": pred,
                    })

        for detector in list(score_keys) + ["phase_only"]:
            rows = [r for r in all_rows
                    if r["horizon"] == horizon and r["detector"] == detector]
            m = balanced_metrics(
                [r["actual"] for r in rows],
                [r["prediction"] for r in rows]
            )
            summary.append({"horizon": horizon, "detector": detector, **m})

    fields = [
        "run", "held_out_run", "horizon", "t", "phase", "actual",
        "gpu_state_score", "dynamic_score", "cpu_score",
        "detector", "threshold", "prediction",
    ]
    with open(OUTPUT, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(all_rows)

    summary_fields = [
        "horizon", "detector", "N", "TP", "FP", "FN", "TN",
        "precision", "recall", "specificity", "balanced_accuracy", "F1",
    ]
    with open(SUMMARY, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=summary_fields)
        w.writeheader()
        w.writerows(summary)

    print("Offline leave-one-run-out comparison")
    print("Five distinct runs; thresholds fitted on training runs only.")
    print(f"{'Horizon':8} {'Detector':20} {'F1':>7} {'Prec':>7} "
          f"{'Recall':>7} {'BalAcc':>7} {'FP':>5} {'FN':>5}")
    for r in summary:
        print(f"{r['horizon']:>7}s {r['detector']:20} "
              f"{r['F1']:7.3f} {r['precision']:7.3f} "
              f"{r['recall']:7.3f} {r['balanced_accuracy']:7.3f} "
              f"{r['FP']:5d} {r['FN']:5d}")
    print(f"\nCreated: {OUTPUT}, {SUMMARY}")

if __name__ == "__main__":
    main()
