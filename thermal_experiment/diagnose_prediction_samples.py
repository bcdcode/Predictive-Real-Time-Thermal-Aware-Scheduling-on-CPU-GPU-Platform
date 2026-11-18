import csv

FILES = {
    "RUN1": "rt_tas_gpu_busy_aligned.csv",
    "RUN2": "rt_tas_gpu_busy_20261105.csv",
    "RUN3": "rt_tas_gpu_busy_20261105_run3.csv"
}

HORIZONS = [1, 5, 10]

for name, filename in FILES.items():
    with open(filename, newline="") as f:
        rows = list(csv.DictReader(f))

    rows.sort(key=lambda r: int(float(r["elapsed_s"])))

    lookup = {int(float(r["elapsed_s"])): r for r in rows}
    times = [int(float(r["elapsed_s"])) for r in rows]

    print("\n==========", name, "==========")
    print("Rows:", len(rows))
    print("Unique elapsed values:", len(lookup))
    print("Elapsed range:", min(times), "to", max(times))
    print("Duplicate elapsed values:", len(times) - len(set(times)))

    missing = sorted(set(range(min(times), max(times) + 1)) - set(times))
    print("Missing elapsed values:", missing)

    for horizon in HORIZONS:
        valid = 0
        no_future = 0
        phase_mismatch = 0
        no_slope_history = 0

        for row in rows:
            t = int(float(row["elapsed_s"]))
            future = lookup.get(t + horizon)

            if future is None:
                no_future += 1
                continue

            if row["phase"] != future["phase"]:
                phase_mismatch += 1
                continue

            if (t - 5) not in lookup:
                no_slope_history += 1
                continue

            valid += 1

        print(
            "Horizon:", horizon,
            "| Valid:", valid,
            "| No future:", no_future,
            "| Phase mismatch:", phase_mismatch,
            "| No slope history:", no_slope_history
        )
