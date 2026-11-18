import csv
import math
import os
import thermal_heldout_test as m

TRAIN_FILES = [
    "rt_tas_controlled_20261011_172905.csv",
    "rt_tas_controlled_20261014_011135.csv",
]
TEST_FILE = "rt_tas_controlled_20261026_221300.csv"
OUT_FILE = "thermal_shadow_forecasts_20261026.csv"

# Keep the CPU model choices from the previous held-out evaluation.
CPU_MODELS = {
    1: ("A_temp", [0, 1, 2, 3, 4, 10]),
    5: ("B_state", [0, 1, 2, 3, 4, 10, 5, 6]),
    10: ("B_state", [0, 1, 2, 3, 4, 10, 5, 6]),
}

# GPU persistence is the provisional selected model at all horizons.
# Ridge and trend are retained as comparison candidates.
GPU_MODELS = {
    1: ("persistence", None),
    5: ("persistence", None),
    10: ("persistence", None),
}

SENSORS = {
    "CPU": "cpu_tctl_C",
    "GPU": "gpu_edge_C",
}

def score(errors):
    if not errors:
        return (float("nan"),) * 3
    return (
        sum(abs(e) for e in errors) / len(errors),
        math.sqrt(sum(e * e for e in errors) / len(errors)),
        sum(errors) / len(errors),
    )

def fmt(x):
    return "NA" if not math.isfinite(x) else f"{x:.3f}"

for path in TRAIN_FILES + [TEST_FILE]:
    if not os.path.isfile(path):
        raise SystemExit("Missing input file: " + path)

train_runs = [m.load_rows(path) for path in TRAIN_FILES]
test_rows = m.load_rows(TEST_FILE)

output = []
metrics = {}

for sensor_name, sensor_key in SENSORS.items():
    for horizon in (1, 5, 10):
        train = []
        for run in train_runs:
            train.extend(m.build_examples(run, horizon, sensor_key))

        test = m.build_examples(test_rows, horizon, sensor_key)
        if not train or not test:
            print(f"{sensor_name} {horizon}s: insufficient examples")
            continue

        choices = CPU_MODELS if sensor_name == "CPU" else GPU_MODELS
        selected_name, selected_features = choices[horizon]

        # Ridge comparison model, trained only on Oct 11 + Oct 14.
        ridge_features = (
            selected_features
            if selected_features is not None
            else [0, 1, 2, 3, 4, 10, 5, 6]
        )
        ridge_model = m.fit_ridge(train, ridge_features)

        errors = {
            "persistence": [],
            "trend": [],
            "ridge": [],
            "selected": [],
        }

        for e in test:
            predictions = {
                "persistence": e["current"],
                "trend": e["trend"],
                "ridge": e["current"] + m.predict_delta(e["x"], ridge_model),
            }

            if selected_name == "persistence":
                selected_pred = predictions["persistence"]
            else:
                selected_model = m.fit_ridge(train, selected_features)
                selected_pred = (
                    e["current"] + m.predict_delta(e["x"], selected_model)
                )

            predictions["selected"] = selected_pred

            for name, pred in predictions.items():
                errors[name].append(pred - e["actual"])

            output.append({
                "sensor": sensor_name,
                "horizon_s": horizon,
                "phase": e["phase"],
                "elapsed_s": e["start"],
                "target_elapsed_s": e["target"],
                "actual_now_C": e["current"],
                "persistence_pred_C": predictions["persistence"],
                "trend_pred_C": predictions["trend"],
                "ridge_pred_C": predictions["ridge"],
                "selected_model": selected_name,
                "selected_pred_C": selected_pred,
                "actual_future_C": e["actual"],
                "selected_error_C": selected_pred - e["actual"],
                "selected_abs_error_C": abs(selected_pred - e["actual"]),
                "applied": "NO",
            })

        metrics[(sensor_name, horizon)] = errors

with open(OUT_FILE, "w", newline="") as f:
    fields = list(output[0].keys()) if output else []
    writer = csv.DictWriter(f, fieldnames=fields)
    if fields:
        writer.writeheader()
        writer.writerows(output)

print("\nTRAINING:", ", ".join(TRAIN_FILES))
print("HELD-OUT:", TEST_FILE)
print("No training or feature fitting used the held-out run.")
print("All predictions are retrospective; no scheduling action was applied.")

print("\nSensor Horizon Model        N      MAE     RMSE     Bias")
for (sensor, horizon), model_errors in metrics.items():
    for model_name, errors in model_errors.items():
        mae, rmse, bias = score(errors)
        print(
            f"{sensor:6s} {horizon:7d} {model_name:11s} "
            f"{len(errors):4d} {fmt(mae):>8s} "
            f"{fmt(rmse):>8s} {fmt(bias):>8s}"
        )

print("\nWrote:", OUT_FILE)
