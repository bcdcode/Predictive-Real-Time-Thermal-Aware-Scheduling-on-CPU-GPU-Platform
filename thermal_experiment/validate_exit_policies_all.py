import csv
import glob
import math
import os

FILES = sorted(glob.glob("thermal_predictor_shadow_*.csv"))
LIMITS = [None, 0.125, 0.250, 0.500, 1.000]
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
    events = []
    held_samples = blocked = missing = rising_exits = 0

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
                events.append((i, "ENTER"))
                high = low = 0
            continue

        held_samples += 1

        if low < HOLD_COUNT:
            continue

        d = delta3(rows, i)
        allowed = (
            limit is None or
            (d is not None and d <= limit)
        )

        if allowed:
            if d is not None and d > 0:
                rising_exits += 1
            held = False
            events.append((i, "EXIT"))
            high = low = 0
        else:
            blocked += 1
            if d is None:
                missing += 1
            if policy == "fresh":
                low = 0

    return {
        "entries": sum(k == "ENTER" for _, k in events),
        "exits": sum(k == "EXIT" for _, k in events),
        "transitions": len(events),
        "held": held_samples,
        "blocked": blocked,
        "missing": missing,
        "rising_exits": rising_exits,
        "end_held": held,
        "events": events,
    }

data, skipped = [], []
for path in FILES:
    rows = read_rows(path)
    if rows is None or len(rows) < 6:
        skipped.append(os.path.basename(path))
    else:
        data.append((os.path.basename(path), rows))

print(f"Files discovered: {len(FILES)}")
print(f"Compatible recordings: {len(data)}")
print(f"Skipped recordings: {len(skipped)}")
if skipped:
    print("Skipped:", ", ".join(skipped))
if not data:
    raise SystemExit("No compatible recordings found.")

print("\nAGGREGATE COMPARISON")
print(f"{'LIMIT':10} {'POLICY':11} {'RUNS':4} {'ENTER':6} "
      f"{'EXIT':5} {'TRANS':6} {'HELD':7} {'BLOCKED':8} "
      f"{'NO_DELTA':8} {'RISE_EXIT':9} {'END_HELD':9}")
print("-" * 105)

for limit in LIMITS:
    for policy in ("persistent", "fresh"):
        results = [
            (name, rows, simulate(rows, limit, policy))
            for name, rows in data
        ]
        stats = [s for _, _, s in results]
        label = "BASELINE" if limit is None else f"{limit:.3f} C"
        print(
            f"{label:10} {policy:11} {len(stats):4} "
            f"{sum(s['entries'] for s in stats):6} "
            f"{sum(s['exits'] for s in stats):5} "
            f"{sum(s['transitions'] for s in stats):6} "
            f"{sum(s['held'] for s in stats):7} "
            f"{sum(s['blocked'] for s in stats):8} "
            f"{sum(s['missing'] for s in stats):8} "
            f"{sum(s['rising_exits'] for s in stats):9} "
            f"{sum(s['end_held'] for s in stats):9}"
        )

print("\nRECORDINGS THAT END WITH REVIEW ACTIVE")
for limit in LIMITS:
    for policy in ("persistent", "fresh"):
        names = []
        for name, rows in data:
            s = simulate(rows, limit, policy)
            if s["end_held"]:
                names.append(name)
        label = "BASELINE" if limit is None else f"{limit:.3f} C"
        print(f"{label:10} {policy:11}: {len(names)}")
        for name in names:
            print("  ", name)

print("\nOffline replay only; no CSV or live scheduler files changed.")
