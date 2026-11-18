#!/usr/bin/env python3

import csv
import os
import joblib
import numpy as np

from sklearn.preprocessing import StandardScaler
from sklearn.linear_model import Ridge
from sklearn.pipeline import make_pipeline


# ============================================================
# CONFIGURATION: V8
# ============================================================

DATASETS = {
    "RUN1_NOV03": "rt_tas_gpu_busy_aligned.csv",
    "RUN2_NOV05": "rt_tas_gpu_busy_20261105.csv",
    "RUN3_NOV05": "rt_tas_gpu_busy_20261105_run3.csv",
    "RUN4_NOV07": "rt_tas_gpu_busy_20261107_run4.csv",
    "RUN5_NOV07": "rt_tas_gpu_busy_20261107_run5.csv",
    "RUN6_NOV07": "rt_tas_gpu_busy_20261107_run6.csv"
}

HORIZON = 1
SLOPE_WINDOW = 5
RIDGE_ALPHA = 1.0

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

BUSY_FEATURES = BASE_FEATURES + [
    "gpu_busy_percent"
]

MODEL_E_FEATURES = BUSY_FEATURES + [
    "simultaneous_start_5s",
    "cooldown1_start_5s",
    "cooldown2_start_5s",
    "idle1_start_5s",
    "idle2_start_5s"
]

MODEL_F_FEATURES = MODEL_E_FEATURES + [
    "ta_cpu_phase",
    "ta_gpu_phase"
]

FINAL_MODELS = {
    "CPU": {
        "model_name": "F",
        "features": MODEL_F_FEATURES,
        "target": "cpu_tctl_C",
        "output": "predictive_cpu_model_f_v8.joblib"
    },
    "GPU": {
        "model_name": "E",
        "features": MODEL_E_FEATURES,
        "target": "gpu_edge_C",
        "output": "predictive_gpu_model_e_v8.joblib"
    }
}


# ============================================================
# DATA LOADING
# ============================================================

def load_dataset(filename):

    rows = []

    with open(filename, newline="") as f:

        reader = csv.DictReader(f)

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

            row["cpu_active_binary"] = float(
                row["cpu_active"].upper() == "ON"
            )

            row["gpu_enabled_binary"] = float(
                row["gpu_enabled"].upper() == "ON"
            )

            rows.append(row)

    rows.sort(key=lambda r: int(r["elapsed_s"]))

    elapsed_values = [int(r["elapsed_s"]) for r in rows]

    if len(elapsed_values) != len(set(elapsed_values)):
        raise ValueError("Duplicate elapsed seconds: " + filename)

    # Phase features
    phase_start = None
    previous_phase = None

    for row in rows:

        phase = row["phase"]
        elapsed = row["elapsed_s"]

        if phase != previous_phase:
            phase_start = elapsed
            previous_phase = phase

        age = elapsed - phase_start
        row["phase_age_s"] = age

        is_start = age < 5

        row["phase_start_5s"] = float(is_start)

        row["simultaneous_start_5s"] = float(
            phase == "SIMULTANEOUS" and is_start
        )

        row["cooldown1_start_5s"] = float(
            phase == "COOLDOWN1" and is_start
        )

        row["cooldown2_start_5s"] = float(
            phase == "COOLDOWN2" and is_start
        )

        row["idle1_start_5s"] = float(
            phase == "IDLE_BASELINE1" and is_start
        )

        row["idle2_start_5s"] = float(
            phase == "IDLE_BASELINE2" and is_start
        )

        row["ta_cpu_phase"] = float(phase == "TA_CPU")
        row["ta_gpu_phase"] = float(phase == "TA_GPU")

    # Backward-looking slopes
    lookup = {
        int(r["elapsed_s"]): r for r in rows
    }

    for row in rows:

        t = int(row["elapsed_s"])
        previous = lookup.get(t - SLOPE_WINDOW)

        if previous is None:
            row["cpu_slope_5s"] = None
            row["gpu_slope_5s"] = None
        else:
            row["cpu_slope_5s"] = (
                row["cpu_tctl_C"] - previous["cpu_tctl_C"]
            ) / SLOPE_WINDOW

            row["gpu_slope_5s"] = (
                row["gpu_edge_C"] - previous["gpu_edge_C"]
            ) / SLOPE_WINDOW

    return rows


# ============================================================
# CREATE ONE-SECOND TRAINING SAMPLES
# ============================================================

def create_samples(rows, target):

    lookup = {
        int(r["elapsed_s"]): r for r in rows
    }

    X = []
    y = []

    features = FINAL_MODELS[target]["features"]

    for row in rows:

        t = int(row["elapsed_s"])

        current = lookup.get(t)
        future = lookup.get(t + HORIZON)
        previous = lookup.get(t - SLOPE_WINDOW)

        if current is None or future is None or previous is None:
            continue

        # Same phase throughout prediction interval
        if current["phase"] != future["phase"]:
            continue

        values = [current[name] for name in features]

        if any(v is None for v in values):
            continue

        X.append(values)
        y.append(future[FINAL_MODELS[target]["target"]])

    return np.asarray(X, dtype=float), np.asarray(y, dtype=float)


# ============================================================
# LOAD ALL SIX RUNS
# ============================================================

print("\n========================================")
print("FINAL PREDICTIVE MODEL TRAINING")
print("V8 | ONE-SECOND HORIZON")
print("========================================")

datasets = {}

for run, filename in DATASETS.items():

    if not os.path.isfile(filename):
        raise SystemExit("Missing dataset: " + filename)

    datasets[run] = load_dataset(filename)

    print(run, "|", len(datasets[run]), "observations")


# ============================================================
# TRAIN AND SAVE CPU F / GPU E
# ============================================================

for target, config in FINAL_MODELS.items():

    print("\n----------------------------------------")
    print("Training", target, "Model", config["model_name"])
    print("----------------------------------------")

    all_X = []
    all_y = []

    for run, rows in datasets.items():

        X, y = create_samples(rows, target)

        print(run, "| training samples:", len(X))

        if len(X):
            all_X.append(X)
            all_y.append(y)

    if not all_X:
        raise SystemExit("No training samples for " + target)

    X_train = np.vstack(all_X)
    y_train = np.concatenate(all_y)

    model = make_pipeline(
        StandardScaler(),
        Ridge(alpha=RIDGE_ALPHA)
    )

    model.fit(X_train, y_train)

    bundle = {
        "model": model,
        "model_name": config["model_name"],
        "target": target,
        "target_column": config["target"],
        "features": config["features"],
        "horizon_s": HORIZON,
        "slope_window_s": SLOPE_WINDOW,
        "ridge_alpha": RIDGE_ALPHA,
        "training_runs": list(DATASETS.keys()),
        "training_samples": len(X_train),
        "method": "V8 six-run final refit"
    }

    joblib.dump(bundle, config["output"])

    print("Training observations:", len(X_train))
    print("Saved:", config["output"])


print("\n========================================")
print("FINAL MODEL TRAINING COMPLETED")
print("========================================")
