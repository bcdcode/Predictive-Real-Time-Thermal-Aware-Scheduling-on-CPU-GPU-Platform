#!/usr/bin/env python3
import csv
import math
import thermal_heldout_test as ml

TRAIN_FILES = [
    "rt_tas_controlled_20261011_172905.csv",
    "rt_tas_controlled_20261014_011135.csv",
]
TEST_FILE = "rt_tas_controlled_20261026_221300.csv"

HORIZONS = (1, 5, 10)
GPU_FEATURES = [0, 1, 2, 3, 4, 10, 5, 6]

OUTPUT_FILE = "gpu_independent_comparison.csv"


def load_run(path):
    rows = ml.load_rows(path)
    print(f"Loaded {len(rows)} samples from {path}")
    return rows


def main():
    train_runs = [load_run(path) for path in TRAIN_FILES]
    test_rows = load_run(TEST_FILE)

    results = []
    print("\nTraining uses October 11 and October 14 only.")
    print("Testing uses October 26 only.")

    for horizon in HORIZONS:
        train_examples = []
        for rows in train_runs:
            train_examples.extend(
                ml.build_examples(rows, horizon, ml.SENSORS["GPU"])
            )

        test_examples = ml.build_examples(
            test_rows, horizon, ml.SENSORS["GPU"]
        )

        if not train_examples or not test_examples:
            print(f"WARNING: no examples for horizon {horizon}s")
            continue

        ridge_model = ml.fit_ridge(train_examples, GPU_FEATURES)

        print(f"\nHorizon {horizon}s: "
              f"{len(train_examples)} training examples, "
              f"{len(test_examples)} test examples")

        for example in test_examples:
            current = example["current"]
            actual = example["actual"]

            predictions = {
                "persistence": current,
                "trend": example["trend"],
                "ridge": current + ml.predict_delta(
                    example["x"], ridge_model
                ),
            }

            for model_name, predicted in predictions.items():
                error = predicted - actual
                results.append({
                    "test_file": TEST_FILE,
                    "horizon_s": horizon,
                    "phase": example["phase"],
                    "target_elapsed_s": example["target"],
                    "model": model_name,
                    "predicted_C": predicted,
                    "actual_C": actual,
                    "error_C": error,
                    "absolute_error_C": abs(error),
                    "squared_error_C": error * error,
                })

    if not results:
        raise SystemExit("ERROR: no predictions produced.")

    with open(OUTPUT_FILE, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(results[0].keys()))
        writer.writeheader()
        writer.writerows(results)

    print("\n=== October 26 independent GPU comparison ===")
    print(f"{'Horizon':<9} {'Model':<13} {'N':>5} "
          f"{'MAE':>8} {'RMSE':>8} {'Bias':>8}")

    for horizon in HORIZONS:
        for model_name in ("persistence", "trend", "ridge"):
            group = [
                r for r in results
                if r["horizon_s"] == horizon
                and r["model"] == model_name
            ]
            if not group:
                continue

            n = len(group)
            mae = sum(r["absolute_error_C"] for r in group) / n
            rmse = math.sqrt(
                sum(r["squared_error_C"] for r in group) / n
            )
            bias = sum(r["error_C"] for r in group) / n

            print(f"{horizon:>2}s      {model_name:<13} {n:>5} "
                  f"{mae:>8.3f} {rmse:>8.3f} {bias:>8.3f}")

    print(f"\nSaved matched predictions to {OUTPUT_FILE}")
    print("All three models are evaluated on the same test examples "
          "within each horizon.")


if __name__ == "__main__":
    main()
