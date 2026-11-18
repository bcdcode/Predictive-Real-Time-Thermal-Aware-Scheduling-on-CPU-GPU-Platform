#!/usr/bin/env python3
"""RT-TAS V3.3 phase-aware hybrid predictor — prediction only."""

import csv
import os
import sys
import time
import math
import joblib
from datetime import datetime

CPU_MODEL_FILE = "predictive_cpu_model_f_v8.joblib"
GPU_MODEL_FILE = "predictive_gpu_model_e_v8.joblib"

SLOPE_WINDOW = 5

MIN_SAMPLE_INTERVAL = 0.75
MAX_SAMPLE_INTERVAL = 1.25
MIN_SLOPE_INTERVAL = 4.75
MAX_SLOPE_INTERVAL = 5.25

# Same three phases as the V3.2 controlled baseline.
PHASE_DURATIONS = {
    "IDLE_BASELINE1": 20,
    "TA_GPU": 15,
    "COOLDOWN2": 30,
}

# Candidate hybrid selection based on V3.2 RUN1-RUN3.
CPU_HYBRID_METHOD = {
    "IDLE_BASELINE1": "TREND",
    "TA_GPU": "TREND",
    "COOLDOWN2": "PERSISTENCE",
}

GPU_HYBRID_METHOD = {
    "IDLE_BASELINE1": "PERSISTENCE",
    "TA_GPU": "PERSISTENCE",
    "COOLDOWN2": "PERSISTENCE",
}


# ============================================================
# LOAD V8 REFERENCE MODELS
# ============================================================

print("Loading V8 reference models...", flush=True)

for model_file in (CPU_MODEL_FILE, GPU_MODEL_FILE):
    if not os.path.isfile(model_file):
        print("ERROR: model not found:", model_file, flush=True)
        sys.exit(1)

cpu_bundle = joblib.load(CPU_MODEL_FILE)
gpu_bundle = joblib.load(GPU_MODEL_FILE)

cpu_model = cpu_bundle["model"]
gpu_model = gpu_bundle["model"]

CPU_FEATURES = cpu_bundle["features"]
GPU_FEATURES = gpu_bundle["features"]

if cpu_bundle.get("horizon_s") != 1:
    raise RuntimeError("CPU V8 model horizon must be 1")

if gpu_bundle.get("horizon_s") != 1:
    raise RuntimeError("GPU V8 model horizon must be 1")

if len(CPU_FEATURES) != 17 or len(GPU_FEATURES) != 15:
    raise RuntimeError("Unexpected V8 feature count")

print("CPU V8 model loaded:", len(CPU_FEATURES), "features")
print("GPU V8 model loaded:", len(GPU_FEATURES), "features")
print("Mode: FORECAST_ONLY")
print("Admission control: DISABLED", flush=True)


# ============================================================
# HELPERS
# ============================================================

def to_float(value):
    if value is None:
        return None

    value = str(value).strip()

    if value in ("", "NA", "N/A", "None"):
        return None

    try:
        result = float(value)

        if not math.isfinite(result):
            return None

        return result

    except (ValueError, TypeError):
        return None


def make_features(row, five_back, phase_age):

    cpu_temp = to_float(row.get("cpu_tctl_C"))
    gpu_temp = to_float(row.get("gpu_edge_C"))

    old_cpu = to_float(five_back.get("cpu_tctl_C"))
    old_gpu = to_float(five_back.get("gpu_edge_C"))

    if None in (cpu_temp, gpu_temp, old_cpu, old_gpu):
        return None

    phase = row["phase"]
    is_start = phase_age < 5

    cpu_active = row.get("cpu_active", "").strip().upper()
    gpu_enabled = row.get("gpu_enabled", "").strip().upper()

    features = {
        "cpu_tctl_C": cpu_temp,
        "gpu_edge_C": gpu_temp,

        "cpu_slope_5s":
            (cpu_temp - old_cpu) / SLOPE_WINDOW,

        "gpu_slope_5s":
            (gpu_temp - old_gpu) / SLOPE_WINDOW,

        "gpu_freq_MHz":
            to_float(row.get("gpu_freq_MHz")),

        "gpu_activity_proxy":
            to_float(row.get("gpu_activity_proxy")),

        "cpu6_freq_MHz":
            to_float(row.get("cpu6_freq_MHz")),

        "cpu_active_binary":
            float(cpu_active == "ON"),

        "gpu_enabled_binary":
            float(gpu_enabled == "ON"),

        "gpu_busy_percent":
            to_float(row.get("gpu_busy_percent")),

        "simultaneous_start_5s":
            float(phase == "SIMULTANEOUS" and is_start),

        "cooldown1_start_5s":
            float(phase == "COOLDOWN1" and is_start),

        "cooldown2_start_5s":
            float(phase == "COOLDOWN2" and is_start),

        "idle1_start_5s":
            float(phase == "IDLE_BASELINE1" and is_start),

        "idle2_start_5s":
            float(phase == "IDLE_BASELINE2" and is_start),

        "ta_cpu_phase":
            float(phase == "TA_CPU"),

        "ta_gpu_phase":
            float(phase == "TA_GPU"),
    }

    if any(v is None for v in features.values()):
        return None

    return features


def model_predict(model, feature_names, features):

    values = [[features[name] for name in feature_names]]

    result = float(model.predict(values)[0])

    if not math.isfinite(result):
        return None

    return result


def format_value(value):
    if value is None:
        return "NA"
    return f"{value:.4f}"


# ============================================================
# LIVE PREDICTION
# ============================================================

def main():

    if len(sys.argv) != 2:
        print(
            "Usage: python3 rt_tas_live_predictor_v3_3.py experiment.csv"
        )
        return 1

    input_file = sys.argv[1]

    if not os.path.isfile(input_file):
        print("ERROR: input CSV not found:", input_file)
        return 1

    output_file = (
        os.path.splitext(input_file)[0]
        + "_live_predictions.csv"
    )

    print("\nStarting RT-TAS V3.3 hybrid predictor")
    print("Input:", input_file)
    print("Output:", output_file)
    print("Mode: FORECAST_ONLY")
    print("Automatic workload control: DISABLED\n", flush=True)

    # --------------------------------------------------------
    # CHECK INPUT CSV HEADER
    # --------------------------------------------------------

    with open(input_file, "r", newline="") as source:

        header_line = source.readline()

        if not header_line:
            print("ERROR: CSV header missing.")
            return 1

        fieldnames = next(csv.reader([header_line]))

    required_columns = [
        "timestamp",
        "elapsed_s",
        "monotonic_elapsed_s",
        "phase",
        "cpu_tctl_C",
        "gpu_edge_C",
        "gpu_freq_MHz",
        "gpu_activity_proxy",
        "cpu6_freq_MHz",
        "cpu_active",
        "gpu_enabled",
        "gpu_busy_percent",
    ]

    missing = [
        name for name in required_columns
        if name not in fieldnames
    ]

    if missing:
        print("ERROR: Required CSV columns missing:")
        print(", ".join(missing))
        return 1

    # --------------------------------------------------------
    # OUTPUT CSV
    # --------------------------------------------------------

    columns = [
        "timestamp",
        "elapsed_s",
        "monotonic_elapsed_s",
        "sample_interval_s",
        "slope_interval_s",
        "phase",

        "cpu_actual_C",
        "cpu_v8_predicted_1s_C",
        "cpu_persistence_predicted_1s_C",
        "cpu_trend_predicted_1s_C",
        "cpu_hybrid_predicted_1s_C",
        "cpu_hybrid_method",

        "gpu_actual_C",
        "gpu_v8_predicted_1s_C",
        "gpu_persistence_predicted_1s_C",
        "gpu_trend_predicted_1s_C",
        "gpu_hybrid_predicted_1s_C",
        "gpu_hybrid_method",

        "gpu_busy_percent",
        "prediction_status",
        "recommended_action",
    ]

    history = {}

    previous_phase = None
    phase_start = None
    last_monotonic = None

    with open(output_file, "w", newline="") as output:

        writer = csv.DictWriter(
            output,
            fieldnames=columns
        )

        writer.writeheader()
        output.flush()

        # ----------------------------------------------------
        # TAIL INPUT CSV
        # ----------------------------------------------------

        with open(input_file, "r", newline="") as source:

            source.readline()

            while True:

                line_position = source.tell()
                line = source.readline()

                if not line:
                    time.sleep(0.1)
                    source.seek(line_position)
                    continue

                try:
                    values = next(csv.reader([line]))
                except csv.Error:
                    print("Skipping malformed CSV row.")
                    continue

                if len(values) != len(fieldnames):
                    print("Skipping malformed CSV row.")
                    continue

                row = dict(zip(fieldnames, values))

                # --------------------------------------------
                # READ TIMING INFORMATION
                # --------------------------------------------

                try:
                    elapsed = int(float(row["elapsed_s"]))
                    monotonic_elapsed = float(
                        row["monotonic_elapsed_s"]
                    )
                    phase = row["phase"].strip()

                except (KeyError, ValueError, TypeError):
                    print("Skipping row with invalid timing.")
                    continue

                if not math.isfinite(monotonic_elapsed):
                    print("Skipping invalid monotonic timestamp.")
                    continue

                # --------------------------------------------
                # SAMPLE INTERVAL VALIDATION
                # --------------------------------------------

                sample_interval = None
                sample_timing_valid = True

                if last_monotonic is not None:

                    sample_interval = (
                        monotonic_elapsed - last_monotonic
                    )

                    if not (
                        MIN_SAMPLE_INTERVAL
                        <= sample_interval
                        <= MAX_SAMPLE_INTERVAL
                    ):
                        sample_timing_valid = False

                last_monotonic = monotonic_elapsed

                # --------------------------------------------
                # PHASE TRACKING
                # --------------------------------------------

                if phase != previous_phase:
                    phase_start = elapsed
                    previous_phase = phase

                phase_age = elapsed - phase_start

                # --------------------------------------------
                # STORE CURRENT SAMPLE
                # --------------------------------------------

                history[elapsed] = row

                one_back = history.get(elapsed - 1)
                five_back = history.get(elapsed - SLOPE_WINDOW)

                # --------------------------------------------
                # INITIALIZE OUTPUT VALUES
                # --------------------------------------------

                cpu_actual = to_float(row.get("cpu_tctl_C"))
                gpu_actual = to_float(row.get("gpu_edge_C"))
                gpu_busy = to_float(row.get("gpu_busy_percent"))

                cpu_v8 = None
                cpu_persist = None
                cpu_trend = None
                cpu_hybrid = None

                gpu_v8 = None
                gpu_persist = None
                gpu_trend = None
                gpu_hybrid = None

                cpu_method = "NA"
                gpu_method = "NA"

                slope_interval = None

                status = "FORECAST_ONLY"
                action = "FORECAST_ONLY_NO_CONTROL"

                # ============================================
                # PREDICTION VALIDATION
                # ============================================

                duration = PHASE_DURATIONS.get(phase)

                if (
                    duration is not None
                    and phase_age >= duration - 1
                ):

                    status = "PHASE_BOUNDARY_SKIPPED"
                    action = "WAIT_FOR_NEXT_PHASE"

                elif (
                    five_back is None
                    or five_back.get("phase") != phase
                ):

                    status = "WARMUP"
                    action = "COLLECT_FIVE_SECOND_HISTORY"

                elif not sample_timing_valid:

                    status = "SAMPLE_INTERVAL_GAP"
                    action = "WAIT_FOR_REGULAR_SAMPLING"

                else:

                    # ----------------------------------------
                    # VERIFY FIVE-SECOND SLOPE INTERVAL
                    # ----------------------------------------

                    try:
                        previous_monotonic = float(
                            five_back["monotonic_elapsed_s"]
                        )

                        slope_interval = (
                            monotonic_elapsed
                            - previous_monotonic
                        )

                    except (
                        KeyError,
                        ValueError,
                        TypeError
                    ):
                        slope_interval = None

                    slope_timing_valid = (
                        slope_interval is not None
                        and MIN_SLOPE_INTERVAL
                        <= slope_interval
                        <= MAX_SLOPE_INTERVAL
                    )

                    if not slope_timing_valid:

                        status = "TIMING_GAP"
                        action = "WAIT_FOR_VALID_FIVE_SECOND_INTERVAL"

                    elif (
                        one_back is None
                        or one_back.get("phase") != phase
                    ):

                        status = "TREND_HISTORY_UNAVAILABLE"
                        action = "WAIT_FOR_SAME_PHASE_PREVIOUS_SAMPLE"

                    else:

                        # ------------------------------------
                        # VERIFY TREND INTERVAL
                        # ------------------------------------

                        try:
                            one_back_monotonic = float(
                                one_back["monotonic_elapsed_s"]
                            )

                            trend_interval = (
                                monotonic_elapsed
                                - one_back_monotonic
                            )

                        except (
                            KeyError,
                            ValueError,
                            TypeError
                        ):
                            trend_interval = None

                        if (
                            trend_interval is None
                            or not (
                                MIN_SAMPLE_INTERVAL
                                <= trend_interval
                                <= MAX_SAMPLE_INTERVAL
                            )
                        ):

                            status = "TREND_TIMING_GAP"
                            action = "WAIT_FOR_VALID_TREND_INTERVAL"

                        else:

                            # --------------------------------
                            # BUILD V8 FEATURES
                            # --------------------------------

                            features = make_features(
                                row,
                                five_back,
                                phase_age
                            )

                            prev_cpu = to_float(
                                one_back.get("cpu_tctl_C")
                            )

                            prev_gpu = to_float(
                                one_back.get("gpu_edge_C")
                            )

                            if (
                                features is None
                                or None in (
                                    cpu_actual,
                                    gpu_actual,
                                    prev_cpu,
                                    prev_gpu
                                )
                            ):

                                status = "INVALID_FEATURES"
                                action = "CHECK_SENSOR_OR_CSV_VALUES"

                            else:

                                # ----------------------------
                                # V8 PREDICTIONS
                                # ----------------------------

                                cpu_v8 = model_predict(
                                    cpu_model,
                                    CPU_FEATURES,
                                    features
                                )

                                gpu_v8 = model_predict(
                                    gpu_model,
                                    GPU_FEATURES,
                                    features
                                )

                                # ----------------------------
                                # PERSISTENCE PREDICTIONS
                                # ----------------------------

                                cpu_persist = cpu_actual
                                gpu_persist = gpu_actual

                                # ----------------------------
                                # TREND PREDICTIONS
                                # ----------------------------

                                cpu_trend = (
                                    cpu_actual
                                    + (cpu_actual - prev_cpu)
                                )

                                gpu_trend = (
                                    gpu_actual
                                    + (gpu_actual - prev_gpu)
                                )

                                # ----------------------------
                                # VALIDATE ALL PREDICTIONS
                                # ----------------------------

                                valid_outputs = (
                                    cpu_v8 is not None
                                    and gpu_v8 is not None
                                    and math.isfinite(cpu_trend)
                                    and math.isfinite(gpu_trend)
                                )

                                if not valid_outputs:

                                    status = "INVALID_PREDICTION"
                                    action = "CHECK_MODEL_OR_BASELINE_OUTPUT"

                                else:

                                    # ------------------------
                                    # PHASE-AWARE SELECTION
                                    # ------------------------

                                    cpu_method = CPU_HYBRID_METHOD.get(
                                        phase,
                                        "V8_FALLBACK"
                                    )

                                    gpu_method = GPU_HYBRID_METHOD.get(
                                        phase,
                                        "V8_FALLBACK"
                                    )

                                    cpu_candidates = {
                                        "V8_FALLBACK": cpu_v8,
                                        "PERSISTENCE": cpu_persist,
                                        "TREND": cpu_trend,
                                    }

                                    gpu_candidates = {
                                        "V8_FALLBACK": gpu_v8,
                                        "PERSISTENCE": gpu_persist,
                                        "TREND": gpu_trend,
                                    }

                                    cpu_hybrid = cpu_candidates[
                                        cpu_method
                                    ]

                                    gpu_hybrid = gpu_candidates[
                                        gpu_method
                                    ]

                # --------------------------------------------
                # WRITE PREDICTION ROW
                # --------------------------------------------

                timestamp = row.get(
                    "timestamp",
                    datetime.now().strftime(
                        "%Y-%m-%d %H:%M:%S"
                    )
                )

                record = {
                    "timestamp": timestamp,
                    "elapsed_s": elapsed,
                    "monotonic_elapsed_s":
                        f"{monotonic_elapsed:.3f}",

                    "sample_interval_s":
                        format_value(sample_interval),

                    "slope_interval_s":
                        format_value(slope_interval),

                    "phase": phase,

                    "cpu_actual_C": cpu_actual,
                    "cpu_v8_predicted_1s_C": cpu_v8,
                    "cpu_persistence_predicted_1s_C": cpu_persist,
                    "cpu_trend_predicted_1s_C": cpu_trend,
                    "cpu_hybrid_predicted_1s_C": cpu_hybrid,
                    "cpu_hybrid_method": cpu_method,

                    "gpu_actual_C": gpu_actual,
                    "gpu_v8_predicted_1s_C": gpu_v8,
                    "gpu_persistence_predicted_1s_C": gpu_persist,
                    "gpu_trend_predicted_1s_C": gpu_trend,
                    "gpu_hybrid_predicted_1s_C": gpu_hybrid,
                    "gpu_hybrid_method": gpu_method,

                    "gpu_busy_percent": gpu_busy,
                    "prediction_status": status,
                    "recommended_action": action,
                }

                writer.writerow(record)
                output.flush()

                # --------------------------------------------
                # TERMINAL OUTPUT
                # --------------------------------------------

                if status == "FORECAST_ONLY":

                    print(
                        f"[{elapsed:3d}s] {phase:16s} | "
                        f"CPU V8={cpu_v8:.2f} "
                        f"P={cpu_persist:.2f} "
                        f"T={cpu_trend:.2f} "
                        f"HYB={cpu_hybrid:.2f}({cpu_method}) | "
                        f"GPU V8={gpu_v8:.2f} "
                        f"P={gpu_persist:.2f} "
                        f"T={gpu_trend:.2f} "
                        f"HYB={gpu_hybrid:.2f}({gpu_method})",
                        flush=True
                    )

                else:

                    print(
                        f"[{elapsed:3d}s] {phase:16s} | {status}",
                        flush=True
                    )

                # --------------------------------------------
                # HISTORY CLEANUP
                # --------------------------------------------

                cutoff = elapsed - SLOPE_WINDOW - 2

                for old_elapsed in list(history):

                    if old_elapsed < cutoff:
                        del history[old_elapsed]


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":

    try:
        sys.exit(main())

    except KeyboardInterrupt:
        print("\nV3.3 predictor stopped.")
