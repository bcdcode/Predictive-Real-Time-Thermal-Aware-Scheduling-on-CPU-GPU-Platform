#!/usr/bin/env python3

import csv
import os
import numpy as np

from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.linear_model import Ridge
from sklearn.metrics import mean_absolute_error


# ============================================================
# EXPERIMENT CONFIGURATION
# ============================================================

DATASETS = {
    "RUN1_NOV03": "rt_tas_gpu_busy_aligned.csv",
    "RUN2_NOV05": "rt_tas_gpu_busy_20261105.csv",
    "RUN3_NOV05": "rt_tas_gpu_busy_20261105_run3.csv"
}

HORIZONS = [1, 5, 10]

SLOPE_WINDOW = 5
RIDGE_ALPHA = 1.0

FOLD_OUTPUT = "gpu_busy_model_fold_results_v3.csv"
SUMMARY_OUTPUT = "gpu_busy_model_summary_v3.csv"
PREDICTION_OUTPUT = "gpu_busy_model_predictions_v3.csv"


# Model A: original baseline features
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


# Model B: baseline + actual GPU busy percentage
BUSY_FEATURES = BASE_FEATURES + [
    "gpu_busy_percent"
]


# Model C: Model B + workload phase age
PHASE_AGE_FEATURES = BUSY_FEATURES + [
    "phase_age_s"
]


MODELS = {
    "A": BASE_FEATURES,
    "B": BUSY_FEATURES,
    "C": PHASE_AGE_FEATURES
}


TARGETS = {
    "CPU": "cpu_tctl_C",
    "GPU": "gpu_edge_C"
}


# ============================================================
# DATA LOADING
# ============================================================

def load_dataset(run_name, filename):

    rows = []

    with open(filename, newline="") as f:
        reader = csv.DictReader(f)

        required = [
            "elapsed_s",
            "phase",
            "cpu_tctl_C",
            "gpu_edge_C",
            "gpu_freq_MHz",
            "gpu_activity_proxy",
            "cpu6_freq_MHz",
            "cpu_active",
            "gpu_enabled",
            "gpu_busy_percent"
        ]

        missing = [
            col for col in required
            if col not in (reader.fieldnames or [])
        ]

        if missing:
            raise ValueError(
                "Missing columns in " + filename + ": "
                + str(missing)
            )

        for row in reader:

            numeric_columns = [
                "elapsed_s",
                "cpu_tctl_C",
                "gpu_edge_C",
                "gpu_freq_MHz",
                "gpu_activity_proxy",
                "cpu6_freq_MHz",
                "gpu_busy_percent"
            ]

            for col in numeric_columns:
                row[col] = float(row[col])

            row["cpu_active_binary"] = (
                1.0 if row["cpu_active"].upper() == "ON"
                else 0.0
            )

            row["gpu_enabled_binary"] = (
                1.0 if row["gpu_enabled"].upper() == "ON"
                else 0.0
            )

            rows.append(row)

    rows.sort(key=lambda r: int(r["elapsed_s"]))

    # --------------------------------------------------------
    # Calculate phase age.
    # Reset the age whenever the phase changes.
    # --------------------------------------------------------

    phase_start = None
    previous_phase = None

    for row in rows:

        phase = row["phase"]
        elapsed = row["elapsed_s"]

        if phase != previous_phase:

            phase_start = elapsed
            previous_phase = phase

        row["phase_age_s"] = elapsed - phase_start

    # --------------------------------------------------------
    # Calculate backward-looking 5-second temperature slopes.
    # --------------------------------------------------------

    elapsed_lookup = {
        int(row["elapsed_s"]): row
        for row in rows
    }

    for row in rows:

        t = int(row["elapsed_s"])

        previous = elapsed_lookup.get(
            t - SLOPE_WINDOW
        )

        if previous is not None:

            row["cpu_slope_5s"] = (
                row["cpu_tctl_C"]
                - previous["cpu_tctl_C"]
            ) / SLOPE_WINDOW

            row["gpu_slope_5s"] = (
                row["gpu_edge_C"]
                - previous["gpu_edge_C"]
            ) / SLOPE_WINDOW

        else:

            row["cpu_slope_5s"] = None
            row["gpu_slope_5s"] = None

    print(
        run_name,
        "| samples:", len(rows),
        "| dataset:", filename
    )

    return rows


# ============================================================
# CREATE SUPERVISED SAMPLES
# ============================================================

def create_samples(rows, horizon):

    lookup = {
        int(row["elapsed_s"]): row
        for row in rows
    }

    samples = []

    for row in rows:

        t = int(row["elapsed_s"])

        # Require complete observations throughout the
        # prediction interval.
        interval = [
            lookup.get(second)
            for second in range(t, t + horizon + 1)
        ]

        if any(item is None for item in interval):
            continue

        # Do not cross phase boundaries.
        if any(
            item["phase"] != row["phase"]
            for item in interval
        ):
            continue

        # Require backward-looking slope sample.
        if lookup.get(t - SLOPE_WINDOW) is None:
            continue

        samples.append((row, interval[-1]))

    return samples


# ============================================================
# BUILD MODEL MATRICES
# ============================================================

def build_matrices(samples, feature_names, target_name):

    X = np.array(
        [
            [row[name] for name in feature_names]
            for row, future in samples
        ],
        dtype=float
    )

    y = np.array(
        [
            future[target_name]
            for row, future in samples
        ],
        dtype=float
    )

    return X, y


def create_model():

    return make_pipeline(
        StandardScaler(),
        Ridge(alpha=RIDGE_ALPHA)
    )


# ============================================================
# LOAD ALL EXPERIMENTAL RUNS
# ============================================================

datasets = {}

print("\n========================================")
print("GPU BUSY + PHASE AGE MODEL COMPARISON")
print("MODEL A vs MODEL B vs MODEL C")
print("========================================")

print("\n===== LOADING DATASETS =====")

for run_name, filename in DATASETS.items():

    if not os.path.isfile(filename):
        raise SystemExit(
            "Missing dataset: " + filename
        )

    datasets[run_name] = load_dataset(
        run_name,
        filename
    )


# ============================================================
# THREE-FOLD LEAVE-ONE-RUN-OUT VALIDATION
# ============================================================

fold_results = []
prediction_results = []

print("\n===== THREE-FOLD VALIDATION =====")

for heldout_run in DATASETS:

    training_runs = [
        name for name in DATASETS
        if name != heldout_run
    ]

    print("\n----------------------------------------")
    print("HELD-OUT RUN:", heldout_run)
    print("TRAINING RUNS:", training_runs)
    print("----------------------------------------")

    for horizon in HORIZONS:

        train_samples = []

        for run_name in training_runs:

            train_samples.extend(
                create_samples(
                    datasets[run_name],
                    horizon
                )
            )

        test_samples = create_samples(
            datasets[heldout_run],
            horizon
        )

        print(
            "\nHorizon:", horizon,
            "| Training samples:", len(train_samples),
            "| Testing samples:", len(test_samples)
        )

        if not train_samples or not test_samples:

            print("WARNING: Insufficient samples. Skipping.")
            continue

        for target_label, target_column in TARGETS.items():

            models = {}
            predictions = {}
            maes = {}

            # Same train/test samples for all models.
            y_test = np.array([
                future[target_column]
                for current, future in test_samples
            ], dtype=float)

            # --------------------------------------------
            # Train Model A, B and C
            # --------------------------------------------

            for model_name, feature_names in MODELS.items():

                X_train, y_train = build_matrices(
                    train_samples,
                    feature_names,
                    target_column
                )

                X_test, _ = build_matrices(
                    test_samples,
                    feature_names,
                    target_column
                )

                model = create_model()

                model.fit(X_train, y_train)

                pred = model.predict(X_test)

                mae = mean_absolute_error(
                    y_test,
                    pred
                )

                models[model_name] = model
                predictions[model_name] = pred
                maes[model_name] = mae

            # --------------------------------------------
            # Report fold results
            # --------------------------------------------

            improvement_b = (
                maes["B"] - maes["C"]
            )

            improvement_percent = (
                100.0 * improvement_b / maes["B"]
                if maes["B"] != 0 else 0.0
            )

            result = {
                "heldout_run": heldout_run,
                "training_runs": "+".join(training_runs),
                "target": target_label,
                "horizon_s": horizon,
                "train_samples": len(train_samples),
                "test_samples": len(test_samples),
                "model_a_mae_C": maes["A"],
                "model_b_mae_C": maes["B"],
                "model_c_mae_C": maes["C"],
                "model_b_minus_c_mae_C": improvement_b,
                "model_c_improvement_percent": improvement_percent
            }

            fold_results.append(result)

            print("\nTarget:", target_label)

            for name in ("A", "B", "C"):
                print(
                    "Model", name,
                    "MAE: %.4f C" % maes[name]
                )

            print(
                "Model C improvement over B: %.2f%%"
                % improvement_percent
            )

            # --------------------------------------------
            # Save per-sample predictions
            # --------------------------------------------

            for i, (current, future) in enumerate(test_samples):

                prediction_results.append({

                    "heldout_run": heldout_run,
                    "target": target_label,
                    "horizon_s": horizon,

                    "timestamp": current["timestamp"],
                    "phase": current["phase"],
                    "phase_age_s": current["phase_age_s"],

                    "gpu_busy_percent": current["gpu_busy_percent"],

                    "actual_temperature_C": y_test[i],

                    "model_a_prediction_C": predictions["A"][i],
                    "model_b_prediction_C": predictions["B"][i],
                    "model_c_prediction_C": predictions["C"][i],

                    "model_a_absolute_error_C": abs(
                        y_test[i] - predictions["A"][i]
                    ),

                    "model_b_absolute_error_C": abs(
                        y_test[i] - predictions["B"][i]
                    ),

                    "model_c_absolute_error_C": abs(
                        y_test[i] - predictions["C"][i]
                    )
                })


# ============================================================
# SAVE FOLD RESULTS
# ============================================================

if not fold_results:
    raise SystemExit("ERROR: No fold results generated.")

with open(FOLD_OUTPUT, "w", newline="") as f:

    writer = csv.DictWriter(
        f,
        fieldnames=list(fold_results[0].keys())
    )

    writer.writeheader()
    writer.writerows(fold_results)


# ============================================================
# AGGREGATE RESULTS
# ============================================================

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

        avg_a = np.mean([
            r["model_a_mae_C"] for r in group
        ])

        avg_b = np.mean([
            r["model_b_mae_C"] for r in group
        ])

        avg_c = np.mean([
            r["model_c_mae_C"] for r in group
        ])

        improvement = avg_b - avg_c

        improvement_percent = (
            100.0 * improvement / avg_b
            if avg_b != 0 else 0.0
        )

        summary.append({

            "target": target,
            "horizon_s": horizon,
            "completed_folds": len(group),

            "average_model_a_mae_C": avg_a,
            "average_model_b_mae_C": avg_b,
            "average_model_c_mae_C": avg_c,

            "model_b_minus_c_mae_C": improvement,
            "model_c_improvement_percent": improvement_percent
        })


with open(SUMMARY_OUTPUT, "w", newline="") as f:

    writer = csv.DictWriter(
        f,
        fieldnames=list(summary[0].keys())
    )

    writer.writeheader()
    writer.writerows(summary)


# ============================================================
# SAVE PREDICTIONS
# ============================================================

with open(PREDICTION_OUTPUT, "w", newline="") as f:

    writer = csv.DictWriter(
        f,
        fieldnames=list(prediction_results[0].keys())
    )

    writer.writeheader()
    writer.writerows(prediction_results)


# ============================================================
# FINAL REPORT
# ============================================================

print("\n\n========================================")
print("FINAL MODEL COMPARISON")
print("========================================")

print(
    "{:<7} {:<8} {:<10} {:<10} {:<10} {:<12}".format(
        "TARGET",
        "HORIZON",
        "MODEL A",
        "MODEL B",
        "MODEL C",
        "C vs B (%)"
    )
)

for r in summary:

    print(
        "{:<7} {:<8} {:<10.4f} {:<10.4f} {:<10.4f} {:<12.2f}".format(
            r["target"],
            str(r["horizon_s"]) + "s",
            r["average_model_a_mae_C"],
            r["average_model_b_mae_C"],
            r["average_model_c_mae_C"],
            r["model_c_improvement_percent"]
        )
    )

print("\nSaved files:")
print("1.", FOLD_OUTPUT)
print("2.", SUMMARY_OUTPUT)
print("3.", PREDICTION_OUTPUT)

print("\nValidation completed.")
print("Held-out runs were excluded from their respective training folds.")

