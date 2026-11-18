import csv
import math
import os
from collections import defaultdict

FILES = [
    "rt_tas_controlled_20261014_011135.csv",
    "rt_tas_controlled_20261011_172905.csv",
]
HORIZONS = (1, 5, 10)
WINDOW = 5
TIME_TOLERANCE = 0.75


def load_csv(path):
    with open(path, newline="") as f:
        rows = list(csv.DictReader(f))

    for row in rows:
        row["elapsed_s"] = float(row["elapsed_s"])
        row["cpu_tctl_C"] = float(row["cpu_tctl_C"])
        row["gpu_edge_C"] = float(row["gpu_edge_C"])
        row["phase"] = row["phase"].strip()

    rows.sort(key=lambda r: r["elapsed_s"])
    return rows


def contiguous_phase_start(rows, index):
    """Find the start of the current contiguous phase segment."""
    phase = rows[index]["phase"]
    start = index
    while start > 0 and rows[start - 1]["phase"] == phase:
        start -= 1
    return start


def nearest_target(rows, index, horizon):
    """Find the nearest future sample at the requested elapsed time."""
    target_time = rows[index]["elapsed_s"] + horizon
    best = None
    best_error = float("inf")

    for j in range(index + 1, len(rows)):
        t = rows[j]["elapsed_s"]
        if t > target_time + TIME_TOLERANCE:
            break
        error = abs(t - target_time)
        if error < best_error:
            best = j
            best_error = error

    if best is None or best_error > TIME_TOLERANCE:
        return None
    return best


def predict_trend(rows, start, index, sensor):
    """Least-squares linear trend over up to WINDOW past/current samples."""
    history = rows[max(start, index - WINDOW + 1):index + 1]
    if len(history) < 3:
        return None

    times = [r["elapsed_s"] for r in history]
    values = [r[sensor] for r in history]

    mean_t = sum(times) / len(times)
    mean_y = sum(values) / len(values)
    denom = sum((t - mean_t) ** 2 for t in times)

    if denom == 0:
        return None

    slope = sum(
        (t - mean_t) * (y - mean_y)
        for t, y in zip(times, values)
    ) / denom

    return values[-1] + slope * (
        rows[index]["elapsed_s"] - mean_t
        + 0  # Keep the fitted history's time origin explicit.
    ) if False else values[-1] + slope * (
        rows[index]["elapsed_s"] - times[-1]
        + (rows[index]["elapsed_s"] + 0)
        - rows[index]["elapsed_s"]
    )


def trend_forecast(rows, start, index, target_index, sensor):
    """Fit temperature versus time and extrapolate to target timestamp."""
    history = rows[max(start, index - WINDOW + 1):index + 1]
    if len(history) < 3:
        return None

    times = [r["elapsed_s"] for r in history]
    values = [r[sensor] for r in history]
    mean_t = sum(times) / len(times)
    mean_y = sum(values) / len(values)
    denom = sum((t - mean_t) ** 2 for t in times)

    if denom == 0:
        return None

    slope = sum(
        (t - mean_t) * (y - mean_y)
        for t, y in zip(times, values)
    ) / denom

    return mean_y + slope * (
        rows[target_index]["elapsed_s"] - mean_t
    )


def score_file(path, writer):
    rows = load_csv(path)
    if not rows:
        print("EMPTY:", path)
        return

    print("\nDataset:", path, "| samples:", len(rows))
    print("  elapsed span: %.1f s" % (
        rows[-1]["elapsed_s"] - rows[0]["elapsed_s"]
    ))

    for horizon in HORIZONS:
        for sensor, label in (
            ("cpu_tctl_C", "CPU"),
            ("gpu_edge_C", "GPU"),
        ):
            errors = defaultdict(list)
            skipped_phase = 0
            skipped_time = 0

            for i in range(len(rows) - 1):
                target = nearest_target(rows, i, horizon)
                if target is None:
                    skipped_time += 1
                    continue

                # Require every sample in the forecast interval
                # to belong to the same contiguous workload phase.
                phase = rows[i]["phase"]
                if any(
                    rows[k]["phase"] != phase
                    for k in range(i, target + 1)
                ):
                    skipped_phase += 1
                    continue

                segment_start = contiguous_phase_start(rows, i)
                if i - segment_start + 1 < 3:
                    continue

                actual = rows[target][sensor]
                persistence = rows[i][sensor]
                trend = trend_forecast(
                    rows, segment_start, i, target, sensor
                )

                if trend is None:
                    continue

                errors["persistence"].append(actual - persistence)
                errors["trend"].append(actual - trend)

                writer.writerow({
                    "dataset": os.path.basename(path),
                    "sensor": label,
                    "horizon_s": horizon,
                    "start_elapsed_s": rows[i]["elapsed_s"],
                    "target_elapsed_s": rows[target]["elapsed_s"],
                    "start_phase": rows[i]["phase"],
                    "target_phase": rows[target]["phase"],
                    "actual_C": actual,
                    "persistence_prediction_C": persistence,
                    "trend_prediction_C": trend,
                    "persistence_error_C": persistence - actual,
                    "trend_error_C": trend - actual,
                })

            print(
                "  %-3s %2ds | n=%3d | "
                "persistence MAE=%s RMSE=%s | trend MAE=%s RMSE=%s"
                % (
                    label, horizon,
                    len(errors["persistence"]),
                    metric(errors["persistence"], "mae"),
                    metric(errors["persistence"], "rmse"),
                    metric(errors["trend"], "mae"),
                    metric(errors["trend"], "rmse"),
                )
            )
            print(
                "       skipped: phase-boundary=%d, no-time-match=%d"
                % (skipped_phase, skipped_time)
            )


def metric(errors, kind):
    if not errors:
        return "N/A"
    if kind == "mae":
        value = sum(abs(e) for e in errors) / len(errors)
    else:
        value = math.sqrt(sum(e * e for e in errors) / len(errors))
    return "%.3f" % value


def main():
    output = "thermal_predictions_validated.csv"
    with open(output, "w", newline="") as f:
        fields = [
            "dataset", "sensor", "horizon_s",
            "start_elapsed_s", "target_elapsed_s",
            "start_phase", "target_phase", "actual_C",
            "persistence_prediction_C", "trend_prediction_C",
            "persistence_error_C", "trend_error_C",
        ]
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()

        for path in FILES:
            if not os.path.isfile(path):
                print("\nMISSING:", path)
                continue
            score_file(path, writer)

    print("\nSaved predictions to:", output)


if __name__ == "__main__":
    main()
