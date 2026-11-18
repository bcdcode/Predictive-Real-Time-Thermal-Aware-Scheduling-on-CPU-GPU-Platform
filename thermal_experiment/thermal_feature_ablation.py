import csv
import math
import os

FILES = [
    "rt_tas_controlled_20261014_011135.csv",
    "rt_tas_controlled_20261011_172905.csv",
]
HORIZONS = (1, 5, 10)
WINDOW = 5
TOLERANCE = 0.75
RIDGE = 1.0

SENSORS = {"CPU": "cpu_tctl_C", "GPU": "gpu_edge_C"}

# Feature groups:
# A: temperature history
# B: temperature history + workload states
# C: temperature history + frequency/activity
# D: all features
FEATURE_SETS = {
    "A_temp": [0, 1, 2, 3, 4, 10],
    "B_state": [0, 1, 2, 3, 4, 10, 5, 6],
    "C_freq": [0, 1, 2, 3, 4, 10, 7, 8, 9],
    "D_full": list(range(13)),
}


def load_rows(path):
    with open(path, newline="") as f:
        rows = list(csv.DictReader(f))

    for r in rows:
        r["elapsed_s"] = float(r["elapsed_s"])
        for key in (
            "cpu_tctl_C", "gpu_edge_C", "gpu_freq_MHz",
            "gpu_activity_proxy", "cpu6_freq_MHz"
        ):
            r[key] = float(r[key])

        r["cpu_active"] = float(r["cpu_active"].strip().upper() == "ON")
        r["gpu_enabled"] = float(r["gpu_enabled"].strip().upper() == "ON")
        r["phase"] = r["phase"].strip()

    rows.sort(key=lambda r: r["elapsed_s"])
    return rows


def nearest_target(rows, i, horizon):
    desired = rows[i]["elapsed_s"] + horizon
    best = None
    best_error = float("inf")

    for j in range(i + 1, len(rows)):
        error = abs(rows[j]["elapsed_s"] - desired)
        if rows[j]["elapsed_s"] > desired + TOLERANCE:
            break
        if error < best_error:
            best, best_error = j, error

    if best is None or best_error > TOLERANCE:
        return None
    return best


def segment_start(rows, i):
    phase = rows[i]["phase"]
    start = i
    while start > 0 and rows[start - 1]["phase"] == phase:
        start -= 1
    return start


def slope(rows, i, start, sensor):
    history = rows[max(start, i - WINDOW + 1):i + 1]
    if len(history) < 3:
        return 0.0

    ts = [r["elapsed_s"] for r in history]
    ys = [r[sensor] for r in history]
    mt = sum(ts) / len(ts)
    my = sum(ys) / len(ys)
    denom = sum((t - mt) ** 2 for t in ts)

    if denom == 0:
        return 0.0

    return sum((t - mt) * (y - my)
               for t, y in zip(ts, ys)) / denom


def make_features(rows, i, start, horizon):
    r = rows[i]
    # Base feature order is fixed; feature subsets are selected below.
    return [
        1.0,                              # 0 intercept
        r["cpu_tctl_C"],                 # 1 current CPU temperature
        r["gpu_edge_C"],                 # 2 current GPU temperature
        slope(rows, i, start, "cpu_tctl_C"),  # 3 CPU slope
        slope(rows, i, start, "gpu_edge_C"),  # 4 GPU slope
        r["cpu_active"],                 # 5 CPU workload state
        r["gpu_enabled"],                # 6 GPU workload state
        r["cpu6_freq_MHz"] / 1000.0,     # 7 CPU frequency, GHz
        r["gpu_freq_MHz"] / 1000.0,      # 8 GPU frequency, GHz
        r["gpu_activity_proxy"],         # 9 GPU activity proxy
        float(horizon),                  # 10 forecast horizon
        r["cpu_active"] * horizon,       # 11 CPU state x horizon
        r["gpu_enabled"] * horizon,      # 12 GPU state x horizon
    ]


def build_examples(rows, horizon, sensor):
    result = []

    for i in range(len(rows) - 1):
        j = nearest_target(rows, i, horizon)
        if j is None:
            continue

        phase = rows[i]["phase"]
        # Exclude any forecast interval containing a phase transition.
        if any(rows[k]["phase"] != phase for k in range(i, j + 1)):
            continue

        start = segment_start(rows, i)
        if i - start + 1 < 3:
            continue

        current = rows[i][sensor]
        actual = rows[j][sensor]
        trend_slope = slope(rows, i, start, sensor)
        trend_prediction = current + trend_slope * (
            rows[j]["elapsed_s"] - rows[i]["elapsed_s"]
        )

        result.append({
            "x": make_features(rows, i, start, horizon),
            "current": current,
            "actual": actual,
            "delta": actual - current,
            "trend": trend_prediction,
            "phase": phase,
            "start": rows[i]["elapsed_s"],
            "target": rows[j]["elapsed_s"],
        })

    return result


def solve(matrix, vector):
    n = len(vector)
    a = [matrix[i][:] + [vector[i]] for i in range(n)]

    for col in range(n):
        pivot = max(range(col, n), key=lambda r: abs(a[r][col]))
        if abs(a[pivot][col]) < 1e-12:
            raise ArithmeticError("Singular regression system")

        a[col], a[pivot] = a[pivot], a[col]
        scale = a[col][col]

        for k in range(col, n + 1):
            a[col][k] /= scale

        for r in range(n):
            if r == col:
                continue
            factor = a[r][col]
            for k in range(col, n + 1):
                a[r][k] -= factor * a[col][k]

    return [a[i][n] for i in range(n)]


def fit_ridge(examples, indices):
    width = len(indices)
    xs = [[e["x"][k] for k in indices] for e in examples]
    ys = [e["delta"] for e in examples]

    means = [0.0] * width
    scales = [1.0] * width

    # Index 0 is the intercept and is not standardized.
    for k in range(width):
        if indices[k] == 0:
            continue
        means[k] = sum(x[k] for x in xs) / len(xs)
        variance = sum((x[k] - means[k]) ** 2 for x in xs) / len(xs)
        scales[k] = math.sqrt(variance) if variance > 1e-12 else 1.0

    def transform(x):
        return [
            1.0 if indices[k] == 0 else (x[k] - means[k]) / scales[k]
            for k in range(width)
        ]

    tx = [transform(x) for x in xs]
    matrix = [[0.0] * width for _ in range(width)]
    vector = [0.0] * width

    for x, y in zip(tx, ys):
        for a in range(width):
            vector[a] += x[a] * y
            for b in range(width):
                matrix[a][b] += x[a] * x[b]

    # Penalize non-intercept coefficients only.
    for k in range(width):
        if indices[k] != 0:
            matrix[k][k] += RIDGE

    return solve(matrix, vector), means, scales, indices


def predict_delta(x, model):
    coefficients, means, scales, indices = model
    total = 0.0
    for k, source_index in enumerate(indices):
        value = 1.0 if source_index == 0 else (
            x[source_index] - means[k]
        ) / scales[k]
        total += coefficients[k] * value
    return total


def metrics(errors):
    if not errors:
        return float("nan"), float("nan")
    mae = sum(abs(e) for e in errors) / len(errors)
    rmse = math.sqrt(sum(e * e for e in errors) / len(errors))
    return mae, rmse


def fmt(value):
    return "%.3f" % value if math.isfinite(value) else "N/A"


def evaluate(train_rows, test_rows, train_name, test_name, writer):
    print("\nTRAIN:", train_name)
    print("TEST: ", test_name)

    for horizon in HORIZONS:
        for label, sensor in SENSORS.items():
            train = build_examples(train_rows, horizon, sensor)
            test = build_examples(test_rows, horizon, sensor)

            if not train or not test:
                print(label, horizon, "s: insufficient examples")
                continue

            print("\n%s %ds | train=%d test=%d" %
                  (label, horizon, len(train), len(test)))

            for variant, indices in FEATURE_SETS.items():
                model = fit_ridge(train, indices)
                errors = []

                for e in test:
                    prediction = e["current"] + predict_delta(e["x"], model)
                    errors.append(prediction - e["actual"])

                    writer.writerow({
                        "train_dataset": train_name,
                        "test_dataset": test_name,
                        "sensor": label,
                        "horizon_s": horizon,
                        "variant": variant,
                        "start_elapsed_s": e["start"],
                        "target_elapsed_s": e["target"],
                        "phase": e["phase"],
                        "actual_C": e["actual"],
                        "prediction_C": prediction,
                        "error_C": prediction - e["actual"],
                    })

                ma, rm = metrics(errors)
                print("  %-8s MAE=%s RMSE=%s" %
                      (variant, fmt(ma), fmt(rm)))

            # Baselines use exactly the same held-out examples.
            for name, key in (
                ("persistence", "current"),
                ("trend", "trend"),
            ):
                errors = [e[key] - e["actual"] for e in test]
                ma, rm = metrics(errors)
                print("  %-8s MAE=%s RMSE=%s" %
                      (name, fmt(ma), fmt(rm)))


def main():
    rows = {}
    for path in FILES:
        if not os.path.isfile(path):
            raise SystemExit("Missing CSV: " + path)
        rows[path] = load_rows(path)

    output = "thermal_feature_ablation_predictions.csv"
    fields = [
        "train_dataset", "test_dataset", "sensor", "horizon_s",
        "variant", "start_elapsed_s", "target_elapsed_s", "phase",
        "actual_C", "prediction_C", "error_C",
    ]

    with open(output, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        evaluate(rows[FILES[0]], rows[FILES[1]], FILES[0], FILES[1], writer)
        evaluate(rows[FILES[1]], rows[FILES[0]], FILES[1], FILES[0], writer)

    print("\nSaved predictions to:", output)


if __name__ == "__main__":
    main()
