
#!/usr/bin/env python3
import csv
import glob
import os
import sys
import time
from datetime import datetime

import thermal_heldout_test as ml

TRAIN_FILES = [
    "rt_tas_controlled_20261014_011135.csv",
    "rt_tas_controlled_20261011_172905.csv",
]
HORIZONS = (1, 5, 10)
POLL_SECONDS = 0.20
OUTPUT = "thermal_shadow_predictions.csv"

FIELDS = [
    "created_at", "elapsed_s", "phase", "sensor", "horizon_s",
    "model", "actual_now_C", "predicted_C", "target_elapsed_s",
    "actual_future_C", "absolute_error_C", "status"
]


def train_models():
    runs = []
    for path in TRAIN_FILES:
        if not os.path.isfile(path):
            raise SystemExit("Missing training file: " + path)
        rows = ml.load_rows(path)
        runs.append(rows)
        print("Loaded", path, "samples:", len(rows))

    models = {}
    for sensor_name, sensor_column in ml.SENSORS.items():
        for horizon in HORIZONS:
            name, indices = ml.SELECTED[(sensor_name, horizon)]
            if name == "persistence":
                models[(sensor_name, horizon)] = (name, None)
                continue

            examples = []
            for rows in runs:
                examples.extend(
                    ml.build_examples(rows, horizon, sensor_column)
                )
            if len(examples) < 10:
                raise SystemExit(
                    "Insufficient training examples: %s %ds"
                    % (sensor_name, horizon)
                )
            models[(sensor_name, horizon)] = (
                name, ml.fit_ridge(examples, indices)
            )
            print(
                "Trained", sensor_name, horizon, "s:", name,
                "examples:", len(examples)
            )
    return models


def read_live(path):
    try:
        with open(path, newline="") as f:
            reader = csv.DictReader(f)
            required = {
                "elapsed_s", "phase", "cpu_tctl_C", "gpu_edge_C",
                "gpu_freq_MHz", "gpu_activity_proxy",
                "cpu6_freq_MHz", "cpu_active", "gpu_enabled",
            }
            if not reader.fieldnames or not required.issubset(
                set(reader.fieldnames)
            ):
                raise ValueError("Unexpected CSV header")

            rows = []
            for raw in reader:
                try:
                    r = dict(raw)
                    r["elapsed_s"] = float(r["elapsed_s"])
                    for key in (
                        "cpu_tctl_C", "gpu_edge_C", "gpu_freq_MHz",
                        "gpu_activity_proxy", "cpu6_freq_MHz"
                    ):
                        r[key] = float(r[key])
                    r["cpu_active"] = float(
                        r["cpu_active"].strip().upper() == "ON"
                    )
                    r["gpu_enabled"] = float(
                        r["gpu_enabled"].strip().upper() == "ON"
                    )
                    r["phase"] = r["phase"].strip()
                    rows.append(r)
                except (ValueError, AttributeError, KeyError):
                    continue
            return sorted(rows, key=lambda r: r["elapsed_s"])
    except (OSError, csv.Error, ValueError):
        return []


def create_forecast(rows, i, sensor_name, horizon, models):
    start = ml.segment_start(rows, i)
    if i - start + 1 < 3:
        return None

    name, fitted = models[(sensor_name, horizon)]
    x = ml.make_features(rows, i, start, horizon)
    sensor_column = ml.SENSORS[sensor_name]
    current = rows[i][sensor_column]

    if name == "persistence":
        predicted = current
    else:
        predicted = current + ml.predict_delta(x, fitted)

    return {
        "elapsed_s": rows[i]["elapsed_s"],
        "phase": rows[i]["phase"],
        "sensor": sensor_name,
        "horizon_s": horizon,
        "model": name,
        "actual_now_C": current,
        "predicted_C": predicted,
        "target_elapsed_s": rows[i]["elapsed_s"] + horizon,
    }


def resolve(forecast, rows):
    desired = forecast["target_elapsed_s"]
    source_time = forecast["elapsed_s"]
    phase = forecast["phase"]
    sensor_column = ml.SENSORS[forecast["sensor"]]

    # If any observed sample indicates a phase transition before the
    # target time, this forecast is not eligible for scoring.
    for row in rows:
        if source_time < row["elapsed_s"] <= desired:
            if row["phase"] != phase:
                return "SKIPPED_PHASE_CHANGE", None, None

    candidates = [
        row for row in rows
        if row["elapsed_s"] > source_time
        and row["phase"] == phase
        and abs(row["elapsed_s"] - desired) <= ml.TOLERANCE
    ]
    if candidates:
        target = min(
            candidates,
            key=lambda r: abs(r["elapsed_s"] - desired)
        )
        actual = target[sensor_column]
        return "SCORED", actual, abs(forecast["predicted_C"] - actual)

    # Wait until enough future data should have arrived. If no suitable
    # target exists then, mark it missing rather than inventing a score.
    latest = max((r["elapsed_s"] for r in rows), default=source_time)
    if latest >= desired + ml.TOLERANCE:
        return "SKIPPED_NO_TARGET", None, None
    return None, None, None


def main():
    models = train_models()

    if len(sys.argv) > 2:
        raise SystemExit(
            "Usage: python3 thermal_shadow_mode.py [live_csv]"
        )

    if len(sys.argv) == 2:
        live_path = sys.argv[1]
    else:
        excluded = set(TRAIN_FILES + [
            "rt_tas_controlled_20261021_163039.csv",
            "rt_tas_controlled_successful_backup.csv",
        ])
        candidates = [
            p for p in glob.glob("rt_tas_controlled_*.csv")
            if os.path.basename(p) not in excluded
            and os.path.getsize(p) > 150
        ]
        if not candidates:
            raise SystemExit(
                "No new run CSV found. Start the experiment first, "
                "then pass its CSV filename explicitly."
            )
        live_path = max(candidates, key=os.path.getmtime)

    print("\nShadow mode reading:", live_path)
    print("Output:", OUTPUT)
    print("No CPU/GPU workload control is performed.")
    print("Press Ctrl+C to stop.")

    # Pending forecasts are kept in memory until scored or skipped.
    pending = {}
    issued = set()
    output_exists = os.path.exists(OUTPUT) and os.path.getsize(OUTPUT) > 0

    with open(OUTPUT, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        if not output_exists:
            writer.writeheader()
            f.flush()

        try:
            while True:
                rows = read_live(live_path)

                # Create forecasts only for source rows not already seen.
                for i, row in enumerate(rows):
                    for sensor in ("CPU", "GPU"):
                        for horizon in HORIZONS:
                            key = (
                                row["elapsed_s"], row["phase"],
                                sensor, horizon
                            )
                            if key in issued:
                                continue

                            forecast = create_forecast(
                                rows, i, sensor, horizon, models
                            )
                            if forecast is None:
                                continue

                            latest = rows[-1]["elapsed_s"]
                            if forecast["target_elapsed_s"] <= latest:
                                # This target is already in the past.
                                # Avoid retrospective/live leakage.
                                continue

                            issued.add(key)
                            pending[key] = forecast

                # Resolve forecasts as future telemetry arrives.
                finished = []
                for key, forecast in pending.items():
                    status, actual, error = resolve(forecast, rows)
                    if status is None:
                        continue

                    writer.writerow({
                        "created_at": datetime.now().isoformat(
                            timespec="seconds"
                        ),
                        "elapsed_s": "%.2f" % forecast["elapsed_s"],
                        "phase": forecast["phase"],
                        "sensor": forecast["sensor"],
                        "horizon_s": forecast["horizon_s"],
                        "model": forecast["model"],
                        "actual_now_C": "%.3f" % forecast["actual_now_C"],
                        "predicted_C": "%.3f" % forecast["predicted_C"],
                        "target_elapsed_s": "%.2f" %
                            forecast["target_elapsed_s"],
                        "actual_future_C": (
                            "%.3f" % actual if actual is not None else ""
                        ),
                        "absolute_error_C": (
                            "%.3f" % error if error is not None else ""
                        ),
                        "status": status,
                    })
                    f.flush()
                    finished.append(key)

                for key in finished:
                    del pending[key]

                time.sleep(POLL_SECONDS)

        except KeyboardInterrupt:
            print("\nStopped. Unresolved forecasts were not scored.")

    print("Saved:", OUTPUT)


if __name__ == "__main__":
    main()

