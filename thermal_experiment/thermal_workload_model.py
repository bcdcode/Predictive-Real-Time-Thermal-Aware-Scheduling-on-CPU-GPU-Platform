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
TOLERANCE = 0.75
SENSORS = {
    "CPU": "cpu_tctl_C",
    "GPU": "gpu_edge_C",
}


def load_rows(path):
    with open(path, newline="") as f:
        rows = list(csv.DictReader(f))

    for r in rows:
        r["elapsed_s"] = float(r["elapsed_s"])
        for sensor in SENSORS.values():
            r[sensor] = float(r[sensor])
        r["phase"] = r["phase"].strip()

    rows.sort(key=lambda r: r["elapsed_s"])
    return rows


def nearest_target(rows, i, horizon):
    desired = rows[i]["elapsed_s"] + horizon
    best = None
    best_error = float("inf")

    for j in range(i + 1, len(rows)):
        delta = rows[j]["elapsed_s"] - desired
        if delta > TOLERANCE:
            break
        if abs(delta) < best_error:
            best, best_error = j, abs(delta)

    return best if best is not None and best_error <= TOLERANCE else None


def phase_segment_start(rows, i):
    phase = rows[i]["phase"]
    start = i
    while start > 0 and rows[start - 1]["phase"] == phase:
        start -= 1
    return start


def linear_trend(rows, i, target, start, sensor):
    history = rows[max(start, i - WINDOW + 1):i + 1]
    if len(history) < 3:
        return None

    ts = [r["elapsed_s"] for r in history]
    ys = [r[sensor] for r in history]
    mt = sum(ts) / len(ts)
    my = sum(ys) / len(ys)
    denom = sum((t - mt) ** 2 for t in ts)

    if denom == 0:
        return None

    slope = sum((t - mt) * (y - my)
                for t, y in zip(ts, ys)) / denom
    return my + slope * (rows[target]["elapsed_s"] - mt)


def collect_examples(rows, horizon, sensor):
    examples = []
    for i in range(len(rows) - 1):
        target = nearest_target(rows, i, horizon)
        if target is None:
            continue

        phase = rows[i]["phase"]
        if any(rows[k]["phase"] != phase for k in range(i, target + 1)):
            continue

        start = phase_segment_start(rows, i)
        if i - start + 1 < 3:
            continue

        examples.append({
            "phase": phase,
            "start": i,
            "target": target,
            "actual": rows[target][sensor],
            "current": rows[i][sensor],
            "delta": rows[target][sensor] - rows[i][sensor],
            "trend": linear_trend(rows, i, target, start, sensor),
        })
    return examples


def mae(errors):
    return sum(abs(e) for e in errors) / len(errors) if errors else float("nan")


def rmse(errors):
    return math.sqrt(sum(e * e for e in errors) / len(errors)) if errors else float("nan")


def fmt(x):
    return "%.3f" % x if math.isfinite(x) else "N/A"


def evaluate(train_rows, test_rows, train_name, test_name):
    print("\nTRAIN:", train_name)
    print("TEST: ", test_name)

    for horizon in HORIZONS:
        for label, sensor in SENSORS.items():
            train = collect_examples(train_rows, horizon, sensor)
            test = collect_examples(test_rows, horizon, sensor)

            # Learn average temperature change for each phase from training data.
            phase_deltas = defaultdict(list)
            for e in train:
                phase_deltas[e["phase"]].append(e["delta"])

            learned = {
                phase: sum(values) / len(values)
                for phase, values in phase_deltas.items()
            }

            errors = defaultdict(list)
            skipped_unseen = 0

            for e in test:
                phase = e["phase"]
                if phase not in learned:
                    skipped_unseen += 1
                    continue

                actual = e["actual"]
                predictions = {
                    "persistence": e["current"],
                    "trend": e["trend"],
                    "phase_model": e["current"] + learned[phase],
                }

                for method, prediction in predictions.items():
                    if prediction is not None:
                        errors[method].append(prediction - actual)

            n = len(errors["persistence"])
            print("%s %2ds | n=%3d unseen_phase=%d" %
                  (label, horizon, n, skipped_unseen))
            for method in ("persistence", "trend", "phase_model"):
                print("  %-12s MAE=%s RMSE=%s" % (
                    method,
                    fmt(mae(errors[method])),
                    fmt(rmse(errors[method])),
                ))


def main():
    loaded = {}
    for path in FILES:
        if not os.path.isfile(path):
            raise SystemExit("Missing file: " + path)
        loaded[path] = load_rows(path)

    # Two-fold cross-run evaluation: train on each run, test on the other.
    evaluate(loaded[FILES[0]], loaded[FILES[1]], FILES[0], FILES[1])
    evaluate(loaded[FILES[1]], loaded[FILES[0]], FILES[1], FILES[0])


if __name__ == "__main__":
    main()
