#!/usr/bin/env python3

import csv
import glob
import statistics
from collections import defaultdict

filename = sorted(
    glob.glob("rt_tas_predictive_decisions_replay_*.csv")
)[-1]

groups = defaultdict(list)

with open(filename, newline="") as f:
    for row in csv.DictReader(f):

        phase = row["phase"]

        for sensor in ("cpu", "gpu"):

            current = float(row[sensor + "_current_C"])

            for horizon in (1, 5, 10):

                key = sensor + "_pred_" + str(horizon) + "s_C"

                if row[key] == "":
                    continue

                predicted = float(row[key])

                delta = predicted - current

                groups[(phase, sensor, horizon)].append(delta)


print("\nPREDICTIVE TEMPERATURE TREND ANALYSIS")
print("Input:", filename)

print("\nPositive delta = predicted temperature increase")
print("Negative delta = predicted temperature decrease")

print("\n{:<18} {:<6} {:<8} {:<10} {:<10} {:<10}".format(
    "PHASE", "SENSOR", "HORIZON", "AVG_DELTA",
    "MIN_DELTA", "MAX_DELTA"
))

for key in sorted(groups):

    phase, sensor, horizon = key
    values = groups[key]

    print("{:<18} {:<6} {:<8} {:<10.3f} {:<10.3f} {:<10.3f}".format(
        phase,
        sensor.upper(),
        str(horizon) + "s",
        statistics.mean(values),
        min(values),
        max(values)
    ))

