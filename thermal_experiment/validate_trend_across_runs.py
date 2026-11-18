import csv
import glob
import math
import os

FILES = sorted(glob.glob("thermal_predictor_shadow_*.csv"))
LIMITS = [None, 0.125, 0.250, 0.500, 1.000]
ENTER_SCORE, EXIT_SCORE, HOLD_COUNT = 4, 2, 3
REQUIRED = {"elapsed_s", "phase", "cpu_tctl_C", "dynamic_score"}

def read_csv(path):
    with open(path, newline="") as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames or not REQUIRED.issubset(reader.fieldnames):
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
                    "time": t, "temp": temp, "score": score,
                    "phase": r["phase"],
                    "timestamp": r.get("timestamp", "")
                })
            except (ValueError, TypeError, KeyError):
                continue
        return rows

def temp_delta(rows, i):
    now = rows[i]["time"]
    candidates = [
        j for j in range(i)
        if 2.5 <= now - rows[j]["time"] <= 3.5
    ]
    if not candidates:
        return None
    j = min(candidates, key=lambda k: abs(
        (now - rows[k]["time"]) - 3.0
    ))
    return rows[i]["temp"] - rows[j]["temp"]

def simulate(rows, limit):
    held = False
    high = low = 0
    events = []
    held_samples = rising_exits = blocked = 0

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

        if not held and high >= HOLD_COUNT:
            held = True
            events.append((i, "ENTER"))
            high = low = 0

        elif held:
            held_samples += 1
            if low >= HOLD_COUNT:
                d3 = temp_delta(rows, i)
                allowed = (
                    limit is None or
                    (d3 is not None and d3 <= limit)
                )
                if allowed:
                    if d3 is not None and d3 > 0:
                        rising_exits += 1
                    held = False
                    events.append((i, "EXIT"))
                    high = low = 0
                else:
                    blocked += 1

    return {
        "events": events,
        "entries": sum(k == "ENTER" for _, k in events),
        "exits": sum(k == "EXIT" for _, k in events),
        "transitions": len(events),
        "held_samples": held_samples,
        "end_held": held,
        "rising_exits": rising_exits,
        "blocked": blocked,
    }

data, skipped = [], []
for path in FILES:
    rows = read_csv(path)
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

results = {
    limit: [(name, rows, simulate(rows, limit)) for name, rows in data]
    for limit in LIMITS
}

print("\nAGGREGATE COMPARISON")
print("Limit(C)  Runs  Entries  Exits  Transitions  HeldSamples  RisingExits  BlockedChecks  EndHeldRuns")
for limit in LIMITS:
    stats = [s for _, _, s in results[limit]]
    label = "BASELINE" if limit is None else f"{limit:.3f}"
    print(
        f"{label:9} {len(stats):4} "
        f"{sum(s['entries'] for s in stats):8} "
        f"{sum(s['exits'] for s in stats):6} "
        f"{sum(s['transitions'] for s in stats):12} "
        f"{sum(s['held_samples'] for s in stats):12} "
        f"{sum(s['rising_exits'] for s in stats):12} "
        f"{sum(s['blocked'] for s in stats):14} "
        f"{sum(s['end_held'] for s in stats):11}"
    )

print("\nPER-RECORDING SUMMARY")
print("FILE                                      ROWS  BASE_TRANS  BASE_RISE_EXIT  0.125_TRANS  0.125_HELD  0.125_END_HELD")
base = results[None]
strict = results[0.125]
for (name, rows, b), (_, _, s) in zip(base, strict):
    print(
        f"{name:41} {len(rows):5} "
        f"{b['transitions']:11} {b['rising_exits']:15} "
        f"{s['transitions']:12} {s['held_samples']:12} "
        f"{str(s['end_held']):>14}"
    )

print("\nEXITS WITH POSITIVE 3-SECOND TEMPERATURE CHANGE")
for limit in LIMITS:
    label = "BASELINE" if limit is None else f"{limit:.3f} C"
    print(f"\n{label}")
    for name, rows, stats in results[limit]:
        for i, kind in stats["events"]:
            if kind == "EXIT":
                d3 = temp_delta(rows, i)
                if d3 is not None and d3 > 0:
                    print(
                        f"  {name}: {rows[i]['timestamp']} "
                        f"CPU={rows[i]['temp']:.2f}C "
                        f"delta3s=+{d3:.3f}C"
                    )

print("\nOffline analysis only; original CSVs and live scripts were not changed.")
