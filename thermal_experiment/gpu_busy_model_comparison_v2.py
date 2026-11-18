import csv
import os
import numpy as np

from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.linear_model import Ridge
from sklearn.metrics import mean_absolute_error

# ---------------------------------------------------------
# EXPERIMENT CONFIGURATION
# ---------------------------------------------------------

DATASETS = {
    "RUN1_NOV03": "rt_tas_gpu_busy_aligned.csv",
    "RUN2_NOV05": "rt_tas_gpu_busy_20261105.csv",
    "RUN3_NOV05": "rt_tas_gpu_busy_20261105_run3.csv"
}

HORIZONS = [1, 5, 10]
SLOPE_WINDOW = 5
RIDGE_ALPHA = 1.0

FOLD_OUTPUT = "gpu_busy_model_fold_results_v2.csv"
SUMMARY_OUTPUT = "gpu_busy_model_summary_v2.csv"
PREDICTION_OUTPUT = "gpu_busy_model_predictions_v2.csv"

# Model A: baseline features
BASE_FEATURES = [
    "cpu_tctl_C",
    "gpu_edge_C",
    "cpu_slope_5s",
    "gpu_slope_5s",
    "gpu_freq_MHz",
    "gpu_activity_proxy",
    "cpu6_freq_MHz",
    "cpu_active_binary",
    "gpu_enabled_binary"
]

# Model B: baseline features + actual GPU utilization
BUSY_FEATURES = BASE_FEATURES + ["gpu_busy_percent"]

TARGETS = {
    "CPU": "cpu_tctl_C",
    "GPU": "gpu_edge_C"
}


# ---------------------------------------------------------
# DATA LOADING
# ---------------------------------------------------------

def load_dataset(run_name, filename):
    rows = []

    with open(filename, newline="") as f:
        for row in csv.DictReader(f):
            rows.append(row)

    rows.sort(key=lambda r: int(float(r["elapsed_s"])))

    # Convert numeric columns
    numeric_columns = [
        "elapsed_s",
        "cpu_tctl_C",
        "gpu_edge_C",
        "gpu_freq_MHz",
        "gpu_activity_proxy",
        "cpu6_freq_MHz",
        "gpu_busy_percent"
    ]

    for row in rows:
        for col in numeric_columns:
            row[col] = float(row[col])

        row["cpu_active_binary"] = (
            1.0 if row["cpu_active"].upper() == "ON" else 0.0
        )

        row["gpu_enabled_binary"] = (
            1.0 if row["gpu_enabled"].upper() == "ON" else 0.0
        )

    # Calculate backward-looking 5-second temperature slopes.
    # No future information is used in these features.
    elapsed_lookup = {
        int(row["elapsed_s"]): row for row in rows
    }

    for row in rows:
        t = int(row["elapsed_s"])
        previous = elapsed_lookup.get(t - SLOPE_WINDOW)

        if previous is not None:
            row["cpu_slope_5s"] = (
                row["cpu_tctl_C"] - previous["cpu_tctl_C"]
            ) / SLOPE_WINDOW

            row["gpu_slope_5s"] = (
                row["gpu_edge_C"] - previous["gpu_edge_C"]
            ) / SLOPE_WINDOW
        else:
            row["cpu_slope_5s"] = None
            row["gpu_slope_5s"] = None

    print(
        run_name,
        "loaded:", len(rows),
        "samples from", filename
    )

    return rows


# ---------------------------------------------------------
# CREATE SUPERVISED SAMPLES
# ---------------------------------------------------------

def create_samples(rows, horizon):
    lookup = {
        int(row["elapsed_s"]): row for row in rows
    }

    samples = []

    for row in rows:
        t = int(row["elapsed_s"])

        # Require complete observations throughout the prediction interval.
        interval = [
            lookup.get(second)
            for second in range(t, t + horizon + 1)
        ]

        if any(item is None for item in interval):
            continue

        # Every observation must remain in the starting workload phase.
        if any(
            item["phase"] != row["phase"]
            for item in interval
        ):
            continue

        # Require the backward-looking slope sample.
        previous = lookup.get(t - SLOPE_WINDOW)

        if previous is None:
            continue

        samples.append((row, interval[-1]))

    return samples


# ---------------------------------------------------------
# BUILD MODEL MATRICES
# ---------------------------------------------------------

def build_matrices(samples, feature_names, target_name):
    X = np.array(
        [
            [row[name] for name in feature_names]
            for row, future in samples
        ],
        dtype=float
    )

    y = np.array(
        [future[target_name] for row, future in samples],
        dtype=float
    )

    return X, y


def create_model():
    return make_pipeline(
        StandardScaler(),
        Ridge(alpha=RIDGE_ALPHA)
    )


# ---------------------------------------------------------
# MAIN THREE-FOLD LEAVE-ONE-RUN-OUT EVALUATION
# ---------------------------------------------------------

datasets = {}

print("\n===== LOADING DATASETS =====")

for run_name, filename in DATASETS.items():
    if not os.path.isfile(filename):
        raise SystemExit("Missing dataset: " + filename)

    datasets[run_name] = load_dataset(run_name, filename)


fold_results = []
prediction_results = []

print("\n===== THREE-FOLD MODEL EVALUATION =====")

for heldout_run in DATASETS:

    training_runs = [
        name for name in DATASETS if name != heldout_run
    ]

    print("\n----------------------------------------")
    print("HELD-OUT RUN:", heldout_run)
    print("TRAINING RUNS:", training_runs)
    print("----------------------------------------")

    for horizon in HORIZONS:

        train_samples = []

        for run_name in training_runs:
            train_samples.extend(
                create_samples(datasets[run_name], horizon)
            )

        test_samples = create_samples(
            datasets[heldout_run], horizon
        )

        print(
            "\nHorizon:", horizon, "seconds",
            "| Training samples:", len(train_samples),
            "| Testing samples:", len(test_samples)
        )

        if not train_samples or not test_samples:
            print("WARNING: Insufficient samples. Skipping.")
            continue

        for target_label, target_column in TARGETS.items():

            # Same training and test samples for both models.
            XA_train, y_train = build_matrices(
                train_samples, BASE_FEATURES, target_column
            )

            XA_test, y_test = build_matrices(
                test_samples, BASE_FEATURES, target_column
            )

            XB_train, _ = build_matrices(
                train_samples, BUSY_FEATURES, target_column
            )

            XB_test, _ = build_matrices(
                test_samples, BUSY_FEATURES, target_column
            )

            # -------------------------------
            # MODEL A: BASELINE
            # -------------------------------

            model_a = create_model()
            model_a.fit(XA_train, y_train)

            pred_a = model_a.predict(XA_test)

            mae_a = mean_absolute_error(y_test, pred_a)

            # -------------------------------
            # MODEL B: GPU BUSY AWARE
            # -------------------------------

            model_b = create_model()
            model_b.fit(XB_train, y_train)

            pred_b = model_b.predict(XB_test)

            mae_b = mean_absolute_error(y_test, pred_b)

            improvement = mae_a - mae_b

            improvement_percent = (
                100.0 * improvement / mae_a
                if mae_a != 0 else 0.0
            )

            result = {
                "heldout_run": heldout_run,
                "training_runs": "+".join(training_runs),
                "target": target_label,
                "horizon_s": horizon,
                "train_samples": len(train_samples),
                "test_samples": len(test_samples),
                "model_a_mae_C": mae_a,
                "model_b_mae_C": mae_b,
                "mae_improvement_C": improvement,
                "improvement_percent": improvement_percent
            }

            fold_results.append(result)

            print("\nTarget:", target_label)
            print("Model A MAE: %.4f C" % mae_a)
            print("Model B MAE: %.4f C" % mae_b)
            print("MAE improvement: %.4f C" % improvement)
            print("Improvement: %.2f%%" % improvement_percent)

            # Store per-sample predictions for later analysis.
            for i, (current, future) in enumerate(test_samples):
                prediction_results.append({
                    "heldout_run": heldout_run,
                    "target": target_label,
                    "horizon_s": horizon,
                    "timestamp": current["timestamp"],
                    "phase": current["phase"],
                    "gpu_busy_percent": current["gpu_busy_percent"],
                    "actual_temperature_C": y_test[i],
                    "model_a_prediction_C": pred_a[i],
                    "model_b_prediction_C": pred_b[i],
                    "model_a_absolute_error_C": abs(
                        y_test[i] - pred_a[i]
                    ),
                    "model_b_absolute_error_C": abs(
                        y_test[i] - pred_b[i]
                    )
                })


# ---------------------------------------------------------
# SAVE FOLD RESULTS
# ---------------------------------------------------------

if not fold_results:
    raise SystemExit("ERROR: No evaluation results generated.")

with open(FOLD_OUTPUT, "w", newline="") as f:
    writer = csv.DictWriter(
        f, fieldnames=list(fold_results[0].keys())
    )
    writer.writeheader()
    writer.writerows(fold_results)


# ---------------------------------------------------------
# AGGREGATE RESULTS ACROSS THREE HELD-OUT RUNS
# ---------------------------------------------------------

summary = []

for target in TARGETS:
    for horizon in HORIZONS:

        group = [
            r for r in fold_results
            if r["target"] == target
            and r["horizon_s"] == horizon
        ]

        if not group:
            continue

        # Equal weight per held-out run.
        avg_a = np.mean([
            r["model_a_mae_C"] for r in group
        ])

        avg_b = np.mean([
            r["model_b_mae_C"] for r in group
        ])

        improvement = avg_a - avg_b

        improvement_percent = (
            100.0 * improvement / avg_a
            if avg_a != 0 else 0.0
        )

        summary.append({
            "target": target,
            "horizon_s": horizon,
            "completed_folds": len(group),
            "average_model_a_mae_C": avg_a,
            "average_model_b_mae_C": avg_b,
            "average_mae_improvement_C": improvement,
            "improvement_percent": improvement_percent
        })


with open(SUMMARY_OUTPUT, "w", newline="") as f:
    writer = csv.DictWriter(
        f, fieldnames=list(summary[0].keys())
    )
    writer.writeheader()
    writer.writerows(summary)


# ---------------------------------------------------------
# SAVE PER-SAMPLE PREDICTIONS
# ---------------------------------------------------------

with open(PREDICTION_OUTPUT, "w", newline="") as f:
    writer = csv.DictWriter(
        f, fieldnames=list(prediction_results[0].keys())
    )
    writer.writeheader()
    writer.writerows(prediction_results)


# ---------------------------------------------------------
# FINAL REPORT
# ---------------------------------------------------------

print("\n\n========================================")
print("FINAL MODEL COMPARISON")
print("========================================")

print(
    "%-7s %-8s %-9s %-9s %-12s %-12s" %
    ("TARGET", "HORIZON", "FOLDS", "MODEL A",
     "MODEL B", "IMPROVEMENT")
)

for r in summary:
    print(
        "%-7s %-8ds %-9d %-9.4f %-12.4f %10.2f%%" %
        (
            r["target"],
            r["horizon_s"],
            r["completed_folds"],
            r["average_model_a_mae_C"],
            r["average_model_b_mae_C"],
            r["improvement_percent"]
        )
    )

print("\nSaved results:")
print("1.", FOLD_OUTPUT)
print("2.", SUMMARY_OUTPUT)
print("3.", PREDICTION_OUTPUT)

print("\nEVALUATION COMPLETED")
