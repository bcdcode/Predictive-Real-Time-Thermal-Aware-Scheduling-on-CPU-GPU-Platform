import csv
import glob
import math

FILES = sorted(glob.glob("thermal_predictor_shadow_*.csv"))
LIMITS = [None, 0.125, 0.250]
REQUIRED = {"elapsed_s", "cpu_tctl_C", "dynamic_score"}

def load(path):
    with open(path, newline="") as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames or not REQUIRED.issubset(reader.fieldnames):
            return []
        result = []
        for r in reader:
            try:
                t = float(r["elapsed_s"])
                temp = float(r["cpu_tctl_C"])
                score = float(r["dynamic_score"])
                if all(math.isfinite(x) for x in (t, temp, score)):
                    result.append({
                        "time": t, "temp": temp, "score": score,
                        "stamp": r.get("timestamp", "")
                    })
            except (ValueError, TypeError, KeyError):
                pass
        return result

def nearest_delta(rows, i, seconds, after=True):
    target = rows[i]["time"] + (seconds if after else -seconds)
    candidates = [
        j for j, r in enumerate(rows)
        if (j > i if after else j < i)
        and abs(r["time"] - target) <= 1.0
    ]
    if not candidates:
        return None
    j = min(candidates, key=lambda k: abs(rows[k]["time"] - target))
    return rows[j]["temp"] - rows[i]["temp"]

def replay(rows, limit):
    held = False
    high = low = 0
    exits = []

    for i, r in enumerate(rows):
        score = r["score"]
        if score >= 4:
            high += 1
            low = 0
        elif score <= 2:
            low += 1
            high = 0
        else:
            high = low = 0

        if not held and high >= 3:
            held = True
            high = low = 0
        elif held and low >= 3:
            d3 = nearest_delta(rows, i, 3, after=False)
            allowed = (
                limit is None or
                (d3 is not None and d3 <= limit)
            )
            if allowed:
                exits.append(i)
                held = False
                high = low = 0

    return exits

data = []
for path in FILES:
    rows = load(path)
    if len(rows) >= 6:
        data.append((path, rows))

print("EXIT OUTCOME SUMMARY")
print("Limit     Exits  With+3s  With+5s  AvgDelta3s  AvgDelta5s")

for limit in LIMITS:
    deltas3, deltas5 = [], []
    for _, rows in data:
        for i in replay(rows, limit):
            d3 = nearest_delta(rows, i, 3, after=True)
            d5 = nearest_delta(rows, i, 5, after=True)
            if d3 is not None:
                deltas3.append(d3)
            if d5 is not None:
                deltas5.append(d5)

    label = "BASELINE" if limit is None else f"{limit:.3f} C"
    pos3 = sum(x > 0 for x in deltas3)
    pos5 = sum(x > 0 for x in deltas5)
    avg3 = sum(deltas3) / len(deltas3) if deltas3 else float("nan")
    avg5 = sum(deltas5) / len(deltas5) if deltas5 else float("nan")
    print(
        f"{label:9} {max(len(deltas3), len(deltas5)):5} "
        f"{pos3:8} {pos5:8} {avg3:11.3f} {avg5:11.3f}"
    )

print("\nPER-EXIT DETAILS")
for limit in LIMITS:
    label = "BASELINE" if limit is None else f"{limit:.3f} C"
    print(f"\n{label}")
    for path, rows in data:
        for i in replay(rows, limit):
            d3 = nearest_delta(rows, i, 3, after=True)
            d5 = nearest_delta(rows, i, 5, after=True)
            fmt = lambda x: "N/A" if x is None else f"{x:+.3f}C"
            print(
                f"{path.split('/')[-1]} {rows[i]['stamp']} "
                f"CPU={rows[i]['temp']:.2f}C "
                f"post3s={fmt(d3)} post5s={fmt(d5)}"
            )

print("\nPositive deltas indicate continued warming after exit.")
print("N/A means the recording did not provide a nearby future sample.")
print("Offline analysis only; no live scheduler changes.")
