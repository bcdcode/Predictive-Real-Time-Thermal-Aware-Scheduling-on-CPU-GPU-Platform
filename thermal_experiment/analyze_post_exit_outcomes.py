import csv
import glob
import math
import os

FILES = sorted(glob.glob("thermal_predictor_shadow_*.csv"))
LIMITS = [None, 0.125, 0.250, 0.500, 1.000]
POLICIES = ["persistent", "fresh"]
ENTER_SCORE, EXIT_SCORE, HOLD_COUNT = 4, 2, 3

def read_rows(path):
    required = {"elapsed_s", "cpu_tctl_C", "dynamic_score"}
    with open(path, newline="") as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames or not required.issubset(reader.fieldnames):
            return None

        rows = []
        for r in reader:
            try:
                t = float(r["elapsed_s"])
                temp = float(r["cpu_tctl_C"])
                score = float(r["dynamic_score"])
                if not all(math.isfinite(x) for x in (t, temp, score)):
                    continue
                rows.append({
                    "time": t,
                    "temp": temp,
                    "score": score,
                    "timestamp": r.get("timestamp", "")
                })
            except (ValueError, TypeError):
                continue

    rows.sort(key=lambda r: r["time"])
    return rows

def delta3(rows, i):
    now = rows[i]["time"]
    candidates = [
        j for j in range(i)
        if 2.5 <= now - rows[j]["time"] <= 3.5
    ]
    if not candidates:
        return None
    j = min(candidates, key=lambda k:
            abs((now - rows[k]["time"]) - 3.0))
    return rows[i]["temp"] - rows[j]["temp"]

def simulate(rows, limit, policy):
    held = False
    high = low = 0
    exits = []

    for i, r in enumerate(rows):
        score = r["score"]

        if score >= ENTER_SCORE:
            high += 1
            low = 0
        elif score <= EXIT_SCORE:
            low += 1
            high = 0
        else:
            high = low = 0

        if not held:
            if high >= HOLD_COUNT:
                held = True
                high = low = 0
            continue

        if low < HOLD_COUNT:
            continue

        d = delta3(rows, i)
        allowed = (
            limit is None or
            (d is not None and d <= limit)
        )

        if allowed:
            exits.append(i)
            held = False
            high = low = 0
        else:
            if policy == "fresh":
                low = 0

    return exits

def nearest_future(rows, exit_i, target, tolerance=0.6):
    t0 = rows[exit_i]["time"]
    candidates = [
        j for j in range(exit_i + 1, len(rows))
        if abs((rows[j]["time"] - t0) - target) <= tolerance
    ]
    if not candidates:
        return None
    return min(candidates, key=lambda j:
               abs((rows[j]["time"] - t0) - target))

def measure_exit(rows, i):
    t0 = rows[i]["time"]
    temp0 = rows[i]["temp"]

    j3 = nearest_future(rows, i, 3.0)
    j5 = nearest_future(rows, i, 5.0)

    # All available samples strictly after exit, through +5 seconds.
    future = [
        r for r in rows
        if t0 < r["time"] <= t0 + 5.0
    ]

    result = {
        "delta3": None if j3 is None else rows[j3]["temp"] - temp0,
        "delta5": None if j5 is None else rows[j5]["temp"] - temp0,
        "max5": None if not future else
                max(r["temp"] for r in future) - temp0,
        "continued3": None if j3 is None else
                      rows[j3]["temp"] > temp0,
        "continued5": None if j5 is None else
                      rows[j5]["temp"] > temp0,
    }
    return result

data = []
skipped = []

for path in FILES:
    rows = read_rows(path)
    if rows is None or len(rows) < 6:
        skipped.append(os.path.basename(path))
    else:
        data.append((os.path.basename(path), rows))

if not data:
    raise SystemExit("ERROR: No compatible recordings found.")

print(f"Files discovered: {len(FILES)}")
print(f"Compatible recordings: {len(data)}")
print(f"Skipped recordings: {len(skipped)}")

# Cache replay exits and post-exit measurements.
all_results = {}

for limit in LIMITS:
    for policy in POLICIES:
        observations = []
        for name, rows in data:
            for i in simulate(rows, limit, policy):
                m = measure_exit(rows, i)
                observations.append({
                    "file": name,
                    "time": rows[i]["timestamp"],
                    "temp": rows[i]["temp"],
                    **m
                })
        all_results[(limit, policy)] = observations

def summarize(obs, key):
    values = [o[key] for o in obs if o[key] is not None]
    if not values:
        return "n=0"
    avg = sum(values) / len(values)
    positive = sum(v > 0 for v in values)
    negative = sum(v < 0 for v in values)
    zero = len(values) - positive - negative
    return (
        f"n={len(values)} avg={avg:+.3f}C "
        f"up={positive} down={negative} flat={zero}"
    )

print("\nPOST-EXIT TEMPERATURE OUTCOMES")
print("Delta values are measured relative to CPU temperature at exit.")
print("UP/DOWN/FLAT counts use strict positive/negative/zero comparisons.")

for limit in LIMITS:
    for policy in POLICIES:
        obs = all_results[(limit, policy)]
        label = "BASELINE" if limit is None else f"{limit:.3f} C"
        print(f"\n{label} | policy={policy} | exits={len(obs)}")
        print("  Change at +3s:       ", summarize(obs, "delta3"))
        print("  Change at +5s:       ", summarize(obs, "delta5"))
        print("  Max rise within +5s: ", summarize(obs, "max5"))

        c3 = [o for o in obs if o["continued3"] is not None]
        c5 = [o for o in obs if o["continued5"] is not None]
        print(
            f"  Temp above exit at +3s: "
            f"{sum(o['continued3'] for o in c3)}/{len(c3)}"
        )
        print(
            f"  Temp above exit at +5s: "
            f"{sum(o['continued5'] for o in c5)}/{len(c5)}"
        )

print("\nBASELINE EXITS WITH THE LARGEST POST-EXIT RISE")
baseline = all_results[(None, "persistent")]
valid = [o for o in baseline if o["max5"] is not None]

for o in sorted(valid, key=lambda x: x["max5"], reverse=True)[:10]:
    print(
        f"  {o['file']} | {o['time']} | exit={o['temp']:.2f}C "
        f"| max rise in 5s={o['max5']:+.3f}C "
        f"| delta3={o['delta3']} | delta5={o['delta5']}"
    )

print("\nOffline analysis only; source CSVs and live scripts unchanged.")
