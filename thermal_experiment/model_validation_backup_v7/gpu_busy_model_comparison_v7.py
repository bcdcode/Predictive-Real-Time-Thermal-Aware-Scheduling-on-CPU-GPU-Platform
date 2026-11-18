#!/usr/bin/env python3

import csv
import os
import numpy as np

from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.linear_model import Ridge
from sklearn.metrics import mean_absolute_error


# ============================================================
# CONFIGURATION
# ============================================================

DATASETS = {
    "RUN1_NOV03": "rt_tas_gpu_busy_aligned.csv",
    "RUN2_NOV05": "rt_tas_gpu_busy_20261105.csv",
    "RUN3_NOV05": "rt_tas_gpu_busy_20261105_run3.csv",
    "RUN4_NOV07": "rt_tas_gpu_busy_20261107_run4.csv",
    "RUN5_NOV07": "rt_tas_gpu_busy_20261107_run5.csv",
    "RUN6_NOV07": "rt_tas_gpu_busy_20261107_run6.csv"
}

HORIZONS = [1, 5, 10]

SLOPE_WINDOW = 5
RIDGE_ALPHA = 1.0

FOLD_OUTPUT = "gpu_busy_model_fold_results_v7.csv"
SUMMARY_OUTPUT = "gpu_busy_model_summary_v7.csv"
PREDICTION_OUTPUT = "gpu_busy_model_predictions_v7.csv"


# ============================================================
# FEATURES
# ============================================================

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

# Model B: baseline + GPU busy percentage
BUSY_FEATURES = BASE_FEATURES + [
    "gpu_busy_percent"
]

# Model D: Model B + generic phase-start indicator
MODEL_D_FEATURES = BUSY_FEATURES + [
    "phase_start_5s"
]

# Model E: Model B + phase-specific transition indicators
PHASE_SPECIFIC_FEATURES = BUSY_FEATURES + [
    "simultaneous_start_5s",
    "cooldown1_start_5s",
    "cooldown2_start_5s",
    "idle1_start_5s",
    "idle2_start_5s"
]

MODELS = {
    "B": BUSY_FEATURES,
    "D": MODEL_D_FEATURES,
    "E": PHASE_SPECIFIC_FEATURES
}

TARGETS = {
    "CPU": "cpu_tctl_C",
    "GPU": "gpu_edge_C"
}


# ============================================================
# DATA LOADING AND FEATURE GENERATION
# ============================================================

def load_dataset(run_name, filename):

    rows = []

    with open(filename, newline="") as f:

        reader = csv.DictReader(f)

        required = [
            "timestamp",
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

    elapsed_values = [
        int(row["elapsed_s"]) for row in rows
    ]

    if len(elapsed_values) != len(set(elapsed_values)):
        raise ValueError(
            "Duplicate elapsed seconds in " + filename
        )

    # --------------------------------------------------------
    # Calculate phase age and transition features.
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

        is_start = row["phase_age_s"] < 5

        row["phase_start_5s"] = (
            1.0 if is_start else 0.0
        )

        row["simultaneous_start_5s"] = (
            1.0 if phase == "SIMULTANEOUS" and is_start
            else 0.0
        )

        row["cooldown1_start_5s"] = (
            1.0 if phase == "COOLDOWN1" and is_start
            else 0.0
        )

        row["cooldown2_start_5s"] = (
            1.0 if phase == "COOLDOWN2" and is_start
            else 0.0
        )

        row["idle1_start_5s"] = (
            1.0 if phase == "IDLE_BASELINE1" and is_start
            else 0.0
        )

        row["idle2_start_5s"] = (
            1.0 if phase == "IDLE_BASELINE2" and is_start
            else 0.0
        )

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

        interval = [
            lookup.get(second)
            for second in range(t, t + horizon + 1)
        ]

        # Reject incomplete intervals.
        if any(item is None for item in interval):
            continue

        # Reject forecasts crossing phase boundaries.
        if any(
            item["phase"] != row["phase"]
            for item in interval
        ):
            continue

        # Require the backward slope observation.
        if lookup.get(t - SLOPE_WINDOW) is None:
            continue

        samples.append((row, interval[-1]))

    return samples


# ============================================================
# BUILD MATRICES
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


# ============================================================
# MODEL
# ============================================================

def create_model():

    return make_pipeline(
        StandardScaler(),
        Ridge(alpha=RIDGE_ALPHA)
    )


# ============================================================
# LOAD FOUR DATASETS
# ============================================================

datasets = {}

print("\n========================================")
print("SIX-RUN PHASE-SPECIFIC MODEL VALIDATION")
print("MODEL B vs MODEL D vs MODEL E")
print("========================================")

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
# SIX-FOLD LEAVE-ONE-RUN-OUT VALIDATION
# ============================================================

fold_results = []
prediction_results = []

print("\n===== SIX-FOLD VALIDATION =====")

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
            "| Training:", len(train_samples),
            "| Testing:", len(test_samples)
        )

        if not train_samples or not test_samples:
            print("WARNING: Insufficient samples.")
            continue

        for target_label, target_column in TARGETS.items():

            y_test = np.array([
                future[target_column]
                for current, future in test_samples
            ], dtype=float)

            predictions = {}
            maes = {}

            # Train B, D and E using identical samples.
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

                predictions[model_name] = pred

                maes[model_name] = mean_absolute_error(
                    y_test,
                    pred
                )

            improvement_d = (
                100.0 * (maes["B"] - maes["D"]) / maes["B"]
                if maes["B"] != 0 else 0.0
            )

            improvement_e = (
                100.0 * (maes["B"] - maes["E"]) / maes["B"]
                if maes["B"] != 0 else 0.0
            )

            fold_results.append({

                "heldout_run": heldout_run,
                "training_runs": "+".join(training_runs),

                "target": target_label,
                "horizon_s": horizon,

                "train_samples": len(train_samples),
                "test_samples": len(test_samples),

                "model_b_mae_C": maes["B"],
                "model_d_mae_C": maes["D"],
                "model_e_mae_C": maes["E"],

                "model_d_improvement_percent": improvement_d,
                "model_e_improvement_percent": improvement_e
            })

            print("\nTarget:", target_label)

            for name in ("B", "D", "E"):

                print(
                    "Model", name,
                    "MAE: %.4f C" % maes[name]
                )

            print(
                "D vs B: %.2f%%" % improvement_d
            )

            print(
                "E vs B: %.2f%%" % improvement_e
            )

            # Save held-out predictions.
            for i, (current, future) in enumerate(test_samples):

                prediction_results.append({

                    "heldout_run": heldout_run,
                    "target": target_label,
                    "horizon_s": horizon,

                    "timestamp": current["timestamp"],
                    "phase": current["phase"],
                    "phase_age_s": current["phase_age_s"],

                    "phase_start_5s": current["phase_start_5s"],

                    "simultaneous_start_5s":
                        current["simultaneous_start_5s"],

                    "cooldown1_start_5s":
                        current["cooldown1_start_5s"],

                    "cooldown2_start_5s":
                        current["cooldown2_start_5s"],

                    "idle1_start_5s":
                        current["idle1_start_5s"],

                    "idle2_start_5s":
                        current["idle2_start_5s"],

                    "gpu_busy_percent": current["gpu_busy_percent"],

                    "actual_temperature_C": y_test[i],

                    "model_b_prediction_C": predictions["B"][i],
                    "model_d_prediction_C": predictions["D"][i],
                    "model_e_prediction_C": predictions["E"][i],

                    "model_b_absolute_error_C": abs(
                        y_test[i] - predictions["B"][i]
                    ),

                    "model_d_absolute_error_C": abs(
                        y_test[i] - predictions["D"][i]
                    ),

                    "model_e_absolute_error_C": abs(
                        y_test[i] - predictions["E"][i]
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

        avg_b = np.mean([
            r["model_b_mae_C"] for r in group
        ])

        avg_d = np.mean([
            r["model_d_mae_C"] for r in group
        ])

        avg_e = np.mean([
            r["model_e_mae_C"] for r in group
        ])

        improvement_d = (
            100.0 * (avg_b - avg_d) / avg_b
            if avg_b != 0 else 0.0
        )

        improvement_e = (
            100.0 * (avg_b - avg_e) / avg_b
            if avg_b != 0 else 0.0
        )

        summary.append({

            "target": target,
            "horizon_s": horizon,
            "completed_folds": len(group),

            "average_model_b_mae_C": avg_b,
            "average_model_d_mae_C": avg_d,
            "average_model_e_mae_C": avg_e,

            "model_d_improvement_percent": improvement_d,
            "model_e_improvement_percent": improvement_e
        })


# ============================================================
# SAVE SUMMARY
# ============================================================

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
print("FINAL SIX-RUN MODEL COMPARISON")
print("========================================")

print(
    "{:<7} {:<8} {:<10} {:<10} {:<10} {:<12} {:<12}".format(
        "TARGET",
        "HORIZON",
        "MODEL B",
        "MODEL D",
        "MODEL E",
        "D vs B (%)",
        "E vs B (%)"
    )
)

for r in summary:

    print(
        "{:<7} {:<8} {:<10.4f} {:<10.4f} {:<10.4f} {:<12.2f} {:<12.2f}".format(
            r["target"],
            str(r["horizon_s"]) + "s",
            r["average_model_b_mae_C"],
            r["average_model_d_mae_C"],
            r["average_model_e_mae_C"],
            r["model_d_improvement_percent"],
            r["model_e_improvement_percent"]
        )
    )

print("\nSaved files:")
print("1.", FOLD_OUTPUT)
print("2.", SUMMARY_OUTPUT)
print("3.", PREDICTION_OUTPUT)

print("\nValidation completed.")
print("Held-out runs were excluded from their respective training folds.")
print("Six independent run-level folds were evaluated.")
