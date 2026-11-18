#!/usr/bin/env python3

import csv
import os
import sys
import time
import math
import joblib
from datetime import datetime


# ============================================================
# CONFIGURATION
# ============================================================

CPU_MODEL_FILE = "predictive_cpu_model_f_v8.joblib"
GPU_MODEL_FILE = "predictive_gpu_model_e_v8.joblib"

SLOPE_WINDOW = 5

# Timing tolerances in seconds.
MIN_SAMPLE_INTERVAL = 0.75
MAX_SAMPLE_INTERVAL = 1.25

MIN_SLOPE_INTERVAL = 4.75
MAX_SLOPE_INTERVAL = 5.25

PHASE_DURATIONS = {
    "IDLE_BASELINE1": 20,
    "SIMULTANEOUS": 60,
    "COOLDOWN1": 30,
    "IDLE_BASELINE2": 20,
    "TA_CPU": 5,
    "TA_GPU": 15,
    "COOLDOWN2": 30
}


# ============================================================
# LOAD TRAINED MODELS
# ============================================================

print("Loading predictive models...", flush=True)

if not os.path.isfile(CPU_MODEL_FILE):
    print("ERROR: CPU model not found:", CPU_MODEL_FILE)
    sys.exit(1)

if not os.path.isfile(GPU_MODEL_FILE):
    print("ERROR: GPU model not found:", GPU_MODEL_FILE)
    sys.exit(1)

cpu_bundle = joblib.load(CPU_MODEL_FILE)
gpu_bundle = joblib.load(GPU_MODEL_FILE)

cpu_model = cpu_bundle["model"]
gpu_model = gpu_bundle["model"]

CPU_FEATURES = cpu_bundle["features"]
GPU_FEATURES = gpu_bundle["features"]

assert cpu_bundle["horizon_s"] == 1
assert gpu_bundle["horizon_s"] == 1

assert len(CPU_FEATURES) == 17
assert len(GPU_FEATURES) == 15

print("CPU Model F loaded:", len(CPU_FEATURES), "features")
print("GPU Model E loaded:", len(GPU_FEATURES), "features")
print("Prediction horizon: 1 logical sample")
print("Slope window: 5 logical samples")
print("Actual timing validation: ENABLED")
print("Automatic workload control: DISABLED")


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


def make_features(row, previous, phase_age):

    cpu_temp = to_float(row.get("cpu_tctl_C"))
    gpu_temp = to_float(row.get("gpu_edge_C"))

    old_cpu = to_float(previous.get("cpu_tctl_C"))
    old_gpu = to_float(previous.get("gpu_edge_C"))

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
            float(phase == "TA_GPU")
    }

    if any(v is None for v in features.values()):
        return None

    return features


# ============================================================
# LIVE PREDICTION
# ============================================================

def main():

    if len(sys.argv) != 2:

        print(
            "Usage: python3 rt_tas_live_predictor_v3_2.py experiment.csv"
        )

        return 1

    input_file = sys.argv[1]

    if not os.path.isfile(input_file):

        print("ERROR: Input CSV not found:", input_file)

        return 1

    output_file = (
        os.path.splitext(input_file)[0]
        + "_live_predictions.csv"
    )

    print("\nStarting V3.2 live predictive engine")
    print("Input:", input_file)
    print("Output:", output_file)
    print("Mode: SHADOW")
    print("Automatic workload control: DISABLED\n", flush=True)

    history = {}

    previous_phase = None
    phase_start = None

    last_monotonic = None

    # --------------------------------------------------------
    # CHECK INPUT CSV HEADER
    # --------------------------------------------------------

    with open(input_file, "r", newline="") as source:

        header = source.readline()

        if not header:

            print("ERROR: CSV header missing.")

            return 1

        fieldnames = next(csv.reader([header]))

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
        "gpu_busy_percent"
    ]

    missing = [
        name for name in required_columns
        if name not in fieldnames
    ]

    if missing:

        print("ERROR: Required CSV columns missing:")
        print(", ".join(missing))

        print(
            "Use the updated V3.2 controlled experiment script."
        )

        return 1

    # --------------------------------------------------------
    # OUTPUT CSV
    # --------------------------------------------------------

    with open(output_file, "w", newline="") as output:

        writer = csv.writer(output)

        writer.writerow([

            "timestamp",

            "elapsed_s",

            "monotonic_elapsed_s",

            "sample_interval_s",

            "slope_interval_s",

            "phase",

            "cpu_actual_C",

            "cpu_predicted_1s_C",

            "gpu_actual_C",

            "gpu_predicted_1s_C",

            "gpu_busy_percent",

            "prediction_status",

            "recommended_action"

        ])

        output.flush()

        print("Waiting for experiment samples...\n", flush=True)

        # ----------------------------------------------------
        # TAIL INPUT CSV
        # ----------------------------------------------------

        with open(input_file, "r", newline="") as source:

            source.readline()

            while True:

                line = source.readline()

                if not line:

                    time.sleep(0.1)

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

                previous = history.get(
                    elapsed - SLOPE_WINDOW
                )

                # --------------------------------------------
                # ACTUAL TEMPERATURES
                # --------------------------------------------

                cpu_actual = to_float(
                    row.get("cpu_tctl_C")
                )

                gpu_actual = to_float(
                    row.get("gpu_edge_C")
                )

                gpu_busy = to_float(
                    row.get("gpu_busy_percent")
                )

                cpu_prediction = None

                gpu_prediction = None

                slope_interval = None

                status = "FORECAST_ONLY"

                action = "NO_CONTROL_SHADOW_MODE"

                duration = PHASE_DURATIONS.get(phase)

                # ============================================
                # PREDICTION VALIDATION
                # ============================================

                # 1. Avoid predictions near phase boundaries.

                if (
                    duration is not None
                    and phase_age >= duration - 1
                ):

                    status = "PHASE_BOUNDARY_SKIPPED"

                    action = "WAIT_FOR_NEXT_PHASE"

                # 2. Require previous sample from same phase.

                elif (
                    previous is None
                    or previous.get("phase") != phase
                ):

                    status = "WARMUP"

                    action = "COLLECT_FIVE_SECOND_HISTORY"

                # 3. Verify one-second sample cadence.

                elif not sample_timing_valid:

                    status = "SAMPLE_INTERVAL_GAP"

                    action = "WAIT_FOR_REGULAR_SAMPLING"

                else:

                    # ----------------------------------------
                    # VERIFY FIVE-SECOND SLOPE INTERVAL
                    # ----------------------------------------

                    try:

                        previous_monotonic = float(
                            previous["monotonic_elapsed_s"]
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

                        action = (
                            "WAIT_FOR_VALID_FIVE_SECOND_INTERVAL"
                        )

                    else:

                        # ------------------------------------
                        # CREATE V8 FEATURES
                        # ------------------------------------

                        features = make_features(
                            row,
                            previous,
                            phase_age
                        )

                        if features is None:

                            status = "INVALID_FEATURES"

                            action = (
                                "CHECK_SENSOR_OR_CSV_VALUES"
                            )

                        else:

                            # -------------------------------
                            # CPU PREDICTION
                            # -------------------------------

                            cpu_values = [[
                                features[name]
                                for name in CPU_FEATURES
                            ]]

                            # -------------------------------
                            # GPU PREDICTION
                            # -------------------------------

                            gpu_values = [[
                                features[name]
                                for name in GPU_FEATURES
                            ]]

                            cpu_prediction = float(
                                cpu_model.predict(
                                    cpu_values
                                )[0]
                            )

                            gpu_prediction = float(
                                gpu_model.predict(
                                    gpu_values
                                )[0]
                            )

                            if not (
                                math.isfinite(cpu_prediction)
                                and math.isfinite(gpu_prediction)
                            ):

                                cpu_prediction = None

                                gpu_prediction = None

                                status = "INVALID_PREDICTION"

                                action = (
                                    "CHECK_MODEL_OUTPUT"
                                )

                # --------------------------------------------
                # WRITE PREDICTION
                # --------------------------------------------

                timestamp = row.get(
                    "timestamp",
                    datetime.now().strftime(
                        "%Y-%m-%d %H:%M:%S"
                    )
                )

                writer.writerow([

                    timestamp,

                    elapsed,

                    f"{monotonic_elapsed:.3f}",

                    (
                        f"{sample_interval:.3f}"
                        if sample_interval is not None
                        else "NA"
                    ),

                    (
                        f"{slope_interval:.3f}"
                        if slope_interval is not None
                        else "NA"
                    ),

                    phase,

                    cpu_actual,

                    cpu_prediction,

                    gpu_actual,

                    gpu_prediction,

                    gpu_busy,

                    status,

                    action

                ])

                output.flush()

                # --------------------------------------------
                # TERMINAL OUTPUT
                # --------------------------------------------

                if cpu_prediction is not None:

                    print(

                        f"[{elapsed:4d}s] {phase:18s} | "

                        f"CPU {cpu_actual:.2f} -> "
                        f"{cpu_prediction:.2f} C | "

                        f"GPU {gpu_actual:.2f} -> "
                        f"{gpu_prediction:.2f} C | "

                        f"Sample dt={sample_interval:.3f}s | "

                        f"Slope dt={slope_interval:.3f}s",

                        flush=True

                    )

                else:

                    print(

                        f"[{elapsed:4d}s] {phase:18s} | "

                        f"{status}",

                        flush=True

                    )

                # --------------------------------------------
                # HISTORY CLEANUP
                # --------------------------------------------

                cutoff = elapsed - SLOPE_WINDOW - 2

                for old_time in list(history):

                    if old_time < cutoff:

                        del history[old_time]


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":

    try:

        sys.exit(main())

    except KeyboardInterrupt:

        print("\nPredictor stopped.")
