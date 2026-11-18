#!/usr/bin/env python3

import csv
import math
import os
from collections import defaultdict

import thermal_heldout_test as ml

RUNS = [
    "rt_tas_controlled_20261011_172905.csv",
    "rt_tas_controlled_20261014_011135.csv",
    "rt_tas_controlled_20261021_163039.csv",
]

HORIZONS = (1, 5, 10)

# Fixed GPU ridge features: intercept, temperatures, temperature slopes,
# horizon and workload state. Do not tune these on a held-out run.
GPU_FEATURES = [0, 1, 2, 3, 4, 10, 5, 6]

PREDICTIONS_FILE = "gpu_model_cv_predictions.csv"
SUMMARY_FILE = "gpu_model_cv_summary.csv"


def mae(errors):
    return sum(abs(e) for e in errors) / len(errors) if errors else float("nan")


def rmse(errors):
    return math.sqrt(sum(e * e for e in errors) / len(errors)) if errors else float("nan")


def evaluate_fold(train_runs, test_rows, test_name, horizon):
    train_examples = []
    for rows in train_runs:
        train_examples.extend(
            ml.build_examples(rows, horizon, ml.SENSORS["GPU"])
        )

    test_examples = ml.build_examples(
        test_rows, horizon, ml.SENSORS["GPU"]
    )

    if not train_examples or not test_examples:
        print("WARNING: insufficient examples for", test_name, horizon)
        return []

    # Fit only on the training runs.
    ridge = ml.fit_ridge(train_examples, GPU_FEATURES)

    results = []

    for e in test_examples:
        predictions = {
            "persistence": e["current"],
            "trend": e["trend"],
            "ridge": e["current"] + ml.predict_delta(e["x"], ridge),
        }

        for model_name, predicted in predictions.items():
            error = predicted - e["actual"]

            results.append({
                "test_run": test_name,
                "horizon_s": horizon,
                "model": model_name,
                "phase": e["phase"],
                "source_elapsed_s": e["start"],
                "target_elapsed_s": e["target"],
                "actual_C": e["actual"],
                "predicted_C": predicted,
                "error_C": error,
                "absolute_error_C": abs(error),
                "squared_error_C2": error * error,
            })

    return results


def main():
    for path in RUNS:
        if not os.path.isfile(path):
            raise SystemExit("Missing dataset: " + path)

    loaded = {path: ml.load_rows(path) for path in RUNS}

    print("GPU model selection")
    print("Validation: leave-one-run-out cross-validation")
    print("Models: persistence, trend, ridge")
    print("Horizons:", HORIZONS)
    print("GPU feature indices:", GPU_FEATURES)

    all_predictions = []

    for test_path in RUNS:
        train_paths = [p for p in RUNS if p != test_path]
        train_runs = [loaded[p] for p in train_paths]

        print("\nHeld-out run:", test_path)
        print("Training runs:", ", ".join(train_paths))

        for horizon in HORIZONS:
            fold = evaluate_fold(
                train_runs,
                loaded[test_path],
                os.path.basename(test_path),
                horizon,
            )
            all_predictions.extend(fold)

    if not all_predictions:
        raise SystemExit("No predictions generated.")

    # Save per-example results for later analysis.
    with open(PREDICTIONS_FILE, "w", newline="") as f:
        writer = csv.DictWriter(
            f, fieldnames=list(all_predictions[0].keys())
        )
        writer.writeheader()
        writer.writerows(all_predictions)

    # Summarize each held-out run separately, then calculate the
    # unweighted mean of the three fold-level metrics.
    fold_groups = defaultdict(list)
    for row in all_predictions:
        key = (
            row["test_run"], int(row["horizon_s"]), row["model"]
        )
        fold_groups[key].append(float(row["error_C"]))

    fold_summary = []
    for (test_run, horizon, model_name), errors in sorted(fold_groups.items()):
        fold_summary.append({
            "test_run": test_run,
            "horizon_s": horizon,
            "model": model_name,
            "samples": len(errors),
            "MAE_C": mae(errors),
            "RMSE_C": rmse(errors),
            "bias_C": sum(errors) / len(errors),
        })

    with open(SUMMARY_FILE, "w", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "test_run", "horizon_s", "model", "samples",
                "MAE_C", "RMSE_C", "bias_C",
            ],
        )
        writer.writeheader()
        writer.writerows(fold_summary)

    print("\n=== Per-fold GPU results ===")
    print("%-18s %3s %-12s %7s %9s %9s %9s" % (
        "Held-out run", "H", "Model", "N",
        "MAE", "RMSE", "Bias"
    ))

    for r in fold_summary:
        print("%-18s %3ds %-12s %7d %9.3f %9.3f %9.3f" % (
            r["test_run"][:18],
            r["horizon_s"],
            r["model"],
            r["samples"],
            r["MAE_C"],
            r["RMSE_C"],
            r["bias_C"],
        ))

    aggregate = defaultdict(list)
    for r in fold_summary:
        aggregate[(r["horizon_s"], r["model"])].append(r)

    print("\n=== Mean of held-out fold metrics ===")
    print("%-8s %-12s %9s %9s %9s" % (
        "Horizon", "Model", "MAE", "RMSE", "Bias"
    ))

    for (horizon, model_name), folds in sorted(aggregate.items()):
        print("%5ds   %-12s %9.3f %9.3f %9.3f" % (
            horizon,
            model_name,
            sum(x["MAE_C"] for x in folds) / len(folds),
            sum(x["RMSE_C"] for x in folds) / len(folds),
            sum(x["bias_C"] for x in folds) / len(folds),
        ))

    print("\nSaved predictions:", PREDICTIONS_FILE)
    print("Saved summary:", SUMMARY_FILE)


if __name__ == "__main__":
    main()
