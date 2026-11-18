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

SENSORS = {
    "CPU": "cpu_tctl_C",
    "GPU": "gpu_edge_C",
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

        r["cpu_active"] = 1.0 if r["cpu_active"].strip().upper() == "ON" else 0.0
        r["gpu_enabled"] = 1.0 if r["gpu_enabled"].strip().upper() == "ON" else 0.0
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

    return best if best is not None and best_error <= TOLERANCE else None


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


def features(rows, i, start, horizon):
    r = rows[i]

    # Frequencies are expressed in GHz to keep numerical scales manageable.
    # GPU activity is a proxy, not a direct utilization/power measurement.
    return [
        1.0,
        r["cpu_tctl_C"],
        r["gpu_edge_C"],
        slope(rows, i, start, "cpu_tctl_C"),
        slope(rows, i, start, "gpu_edge_C"),
        r["cpu_active"],
        r["gpu_enabled"],
        r["cpu6_freq_MHz"] / 1000.0,
        r["gpu_freq_MHz"] / 1000.0,
        r["gpu_activity_proxy"],
        float(horizon),
        r["cpu_active"] * horizon,
        r["gpu_enabled"] * horizon,
    ]


def build_examples(rows, horizon, target_sensor):
    examples = []

    for i in range(len(rows) - 1):
        j = nearest_target(rows, i, horizon)
        if j is None:
            continue

        phase = rows[i]["phase"]

        # Require the entire forecast interval to remain in one phase.
        if any(rows[k]["phase"] != phase for k in range(i, j + 1)):
            continue

        start = segment_start(rows, i)
        if i - start + 1 < 3:
            continue

        x = features(rows, i, start, horizon)
        current = rows[i][target_sensor]
        actual = rows[j][target_sensor]

        # Same samples are used for every baseline and the learned model.
        trend_slope = slope(rows, i, start, target_sensor)
        trend_prediction = current + trend_slope * (
            rows[j]["elapsed_s"] - rows[i]["elapsed_s"]
        )

        examples.append({
            "x": x,
            "target_delta": actual - current,
            "actual": actual,
            "current": current,
            "trend": trend_prediction,
            "horizon": horizon,
            "start_time": rows[i]["elapsed_s"],
            "target_time": rows[j]["elapsed_s"],
            "phase": phase,
        })

    return examples


def solve(matrix, vector):
    """Solve a small linear system using Gaussian elimination."""
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


def fit_ridge(examples):
    if len(examples) < 20:
        raise ValueError("Too few training examples")

    # Standardize non-intercept columns using training data only.
    width = len(examples[0]["x"])
    means = [0.0] * width
    scales = [1.0] * width

    for k in range(1, width):
        means[k] = sum(e["x"][k] for e in examples) / len(examples)
        variance = sum(
            (e["x"][k] - means[k]) ** 2 for e in examples
        ) / len(examples)
        scales[k] = math.sqrt(variance) if variance > 1e-12 else 1.0

    def transform(x):
        return [
            1.0 if k == 0 else (x[k] - means[k]) / scales[k]
            for k in range(width)
        ]

    xt = [transform(e["x"]) for e in examples]
    ys = [e["target_delta"] for e in examples]

    matrix = [[0.0] * width for _ in range(width)]
    vector = [0.0] * width

    for x, y in zip(xt, ys):
        for a in range(width):
            vector[a] += x[a] * y
            for b in range(width):
                matrix[a][b] += x[a] * x[b]

    # Do not penalize the intercept.
    for k in range(1, width):
        matrix[k][k] += RIDGE

    coefficients = solve(matrix, vector)
    return coefficients, means, scales


def predict_delta(x, model):
    coefficients, means, scales = model
    total = coefficients[0]

    for k in range(1, len(x)):
        total += coefficients[k] * (x[k] - means[k]) / scales[k]

    return total


def mae(errors):
    return sum(abs(e) for e in errors) / len(errors) if errors else float("nan")


def rmse(errors):
    return math.sqrt(sum(e * e for e in errors) / len(errors)) if errors else float("nan")


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

            model = fit_ridge(train)
            errors = {"persistence": [], "trend": [], "regression": []}

            for e in test:
                regression = e["current"] + predict_delta(e["x"], model)
                predictions = {
                    "persistence": e["current"],
                    "trend": e["trend"],
                    "regression": regression,
                }

                for name, prediction in predictions.items():
                    errors[name].append(prediction - e["actual"])

                writer.writerow({
                    "train_dataset": train_name,
                    "test_dataset": test_name,
                    "sensor": label,
                    "horizon_s": horizon,
                    "start_elapsed_s": e["start_time"],
                    "target_elapsed_s": e["target_time"],
                    "phase": e["phase"],
                    "actual_C": e["actual"],
                    "persistence_C": e["current"],
                    "trend_C": e["trend"],
                    "regression_C": regression,
                })

            print("%s %2ds | train=%3d test=%3d" %
                  (label, horizon, len(train), len(test)))

            for name in ("persistence", "trend", "regression"):
                print("  %-12s MAE=%s RMSE=%s" % (
                    name, fmt(mae(errors[name])), fmt(rmse(errors[name]))
                ))


def main():
    loaded = {}
    for path in FILES:
        if not os.path.isfile(path):
            raise SystemExit("Missing CSV: " + path)
        loaded[path] = load_rows(path)

    output = "thermal_workload_regression_predictions.csv"
    fields = [
        "train_dataset", "test_dataset", "sensor", "horizon_s",
        "start_elapsed_s", "target_elapsed_s", "phase", "actual_C",
        "persistence_C", "trend_C", "regression_C",
    ]

    with open(output, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()

        evaluate(loaded[FILES[0]], loaded[FILES[1]],
                 FILES[0], FILES[1], writer)
        evaluate(loaded[FILES[1]], loaded[FILES[0]],
                 FILES[1], FILES[0], writer)

    print("\nSaved predictions to:", output)


if __name__ == "__main__":
    main()
