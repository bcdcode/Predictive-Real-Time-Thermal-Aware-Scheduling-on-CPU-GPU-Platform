import csv
import os
import numpy as np

from sklearn.preprocessing import StandardScaler
from sklearn.linear_model import Ridge
from sklearn.pipeline import make_pipeline


# ============================================================
# CONFIGURATION: MATCH V8
# ============================================================

DATASETS = {
    "RUN1_NOV03": "rt_tas_gpu_busy_aligned.csv",
    "RUN2_NOV05": "rt_tas_gpu_busy_20261105.csv",
    "RUN3_NOV05": "rt_tas_gpu_busy_20261105_run3.csv",
    "RUN4_NOV07": "rt_tas_gpu_busy_20261107_run4.csv",
    "RUN5_NOV07": "rt_tas_gpu_busy_20261107_run5.csv",
    "RUN6_NOV07": "rt_tas_gpu_busy_20261107_run6.csv"
}

SLOPE_WINDOW = 5
HORIZON = 1
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

MODELS = {
    "E": MODEL_E_FEATURES,
    "F": MODEL_F_FEATURES
}

OUTPUT = "v8_cpu_1s_coefficient_analysis.csv"


# ============================================================
# LOAD DATA AND GENERATE FEATURES
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
        int(r["elapsed_s"]) for r in rows
    ]

    if len(elapsed_values) != len(set(elapsed_values)):
        raise ValueError("Duplicate elapsed seconds: " + filename)

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

    lookup = {
        int(r["elapsed_s"]): r for r in rows
    }

    for row in rows:

        t = int(row["elapsed_s"])
        previous = lookup.get(t - SLOPE_WINDOW)

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

    return rows


# ============================================================
# CREATE SAMPLES: SAME V8 PHASE/HORIZON RULES
# ============================================================

def create_samples(rows):

    lookup = {
        int(r["elapsed_s"]): r for r in rows
    }

    samples = []

    for row in rows:

        t = int(row["elapsed_s"])

        interval = [
            lookup.get(second)
            for second in range(t, t + HORIZON + 1)
        ]

        if any(item is None for item in interval):
            continue

        if any(
            item["phase"] != row["phase"]
            for item in interval
        ):
            continue

        if lookup.get(t - SLOPE_WINDOW) is None:
            continue

        samples.append((row, interval[-1]))

    return samples


# ============================================================
# BUILD MATRICES
# ============================================================

def build_matrices(samples, features):

    X = np.array(
        [
            [row[name] for name in features]
            for row, future in samples
        ],
        dtype=float
    )

    y = np.array(
        [future["cpu_tctl_C"] for row, future in samples],
        dtype=float
    )

    return X, y


# ============================================================
# SIX-FOLD LEAVE-ONE-RUN-OUT COEFFICIENT ANALYSIS
# ============================================================

datasets = {}

print("\nLoading six experimental datasets...")

for run_name, filename in DATASETS.items():

    if not os.path.isfile(filename):
        raise SystemExit("Missing dataset: " + filename)

    datasets[run_name] = load_dataset(filename)
    print(run_name, "|", len(datasets[run_name]), "rows")


results = []

print("\n==============================================")
print("V8 MODEL E vs F COEFFICIENT ANALYSIS")
print("CPU | 1-second horizon | Six-fold LOOR")
print("==============================================")

for heldout_run in DATASETS:

    training_runs = [
        name for name in DATASETS
        if name != heldout_run
    ]

    train_samples = []

    for run_name in training_runs:
        train_samples.extend(
            create_samples(datasets[run_name])
        )

    print(
        "\nHeld-out:", heldout_run,
        "| Training samples:", len(train_samples)
    )

    for model_name, features in MODELS.items():

        X_train, y_train = build_matrices(
            train_samples, features
        )

        model = make_pipeline(
            StandardScaler(),
            Ridge(alpha=RIDGE_ALPHA)
        )

        model.fit(X_train, y_train)

        scaler = model.named_steps["standardscaler"]
        ridge = model.named_steps["ridge"]

        for index, feature in enumerate(features):

            standardized_coef = float(ridge.coef_[index])

            raw_coef = (
                standardized_coef / scaler.scale_[index]
            )

            results.append({
                "heldout_run": heldout_run,
                "model": model_name,
                "feature": feature,
                "standardized_coefficient": standardized_coef,
                "raw_unit_coefficient": raw_coef,
                "feature_scale": float(scaler.scale_[index])
            })


# ============================================================
# SAVE FOLD RESULTS
# ============================================================

fieldnames = [
    "heldout_run",
    "model",
    "feature",
    "standardized_coefficient",
    "raw_unit_coefficient",
    "feature_scale"
]

with open(OUTPUT, "w", newline="") as f:

    writer = csv.DictWriter(
        f, fieldnames=fieldnames
    )

    writer.writeheader()
    writer.writerows(results)


# ============================================================
# PRINT COEFFICIENT COMPARISON
# ============================================================

print("\n==============================================")
print("STANDARDIZED COEFFICIENT COMPARISON")
print("F minus E")
print("==============================================")

print(
    f"{'FEATURE':<27} {'E MEAN':>12} "
    f"{'F MEAN':>12} {'F-E':>12}"
)

print("-" * 67)

features_to_inspect = [
    "cpu_tctl_C",
    "gpu_edge_C",
    "cpu_slope_5s",
    "gpu_slope_5s",
    "gpu_freq_MHz",
    "gpu_activity_proxy",
    "cpu6_freq_MHz",
    "cpu_active_binary",
    "gpu_enabled_binary",
    "gpu_busy_percent",
    "simultaneous_start_5s",
    "cooldown1_start_5s",
    "cooldown2_start_5s",
    "idle1_start_5s",
    "idle2_start_5s",
    "ta_cpu_phase",
    "ta_gpu_phase"
]

for feature in features_to_inspect:

    e_values = [
        r["standardized_coefficient"]
        for r in results
        if r["model"] == "E" and r["feature"] == feature
    ]

    f_values = [
        r["standardized_coefficient"]
        for r in results
        if r["model"] == "F" and r["feature"] == feature
    ]

    e_mean = np.mean(e_values)
    f_mean = np.mean(f_values) if f_values else np.nan

    difference = (
        f_mean - e_mean if f_values else np.nan
    )

    print(
        f"{feature:<27} "
        f"{e_mean:12.5f} "
        f"{f_mean:12.5f} "
        f"{difference:12.5f}"
    )


# ============================================================
# TA COEFFICIENTS PER FOLD
# ============================================================

print("\n==============================================")
print("TA INDICATOR COEFFICIENTS BY HELD-OUT RUN")
print("==============================================")

for run_name in DATASETS:

    print("\n", run_name)

    for feature in ["ta_cpu_phase", "ta_gpu_phase"]:

        value = next(
            r["standardized_coefficient"]
            for r in results
            if r["heldout_run"] == run_name
            and r["model"] == "F"
            and r["feature"] == feature
        )

        print(f"  {feature:<20}: {value:+.6f}")


print("\nSaved:", OUTPUT)
print("Coefficient analysis completed.")
