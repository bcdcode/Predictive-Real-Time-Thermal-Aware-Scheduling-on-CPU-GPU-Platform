import csv
from pathlib import Path

MIN_EPISODE = 3
files = sorted(Path(".").glob("thermal_predictor_shadow_*.csv"))
episodes = []

for path in files:
    with path.open(newline="") as f:
        rows = list(csv.DictReader(f))

    rows.sort(key=lambda r: float(r["elapsed_s"]))
    current = []

    def save_episode():
        if len(current) < MIN_EPISODE:
            return

        temps = [float(r["cpu_tctl_C"]) for r in current]
        scores = [float(r["dynamic_score"]) for r in current]
        episodes.append({
            "file": path.name,
            "start": float(current[0]["elapsed_s"]),
            "end": float(current[-1]["elapsed_s"]),
            "duration": float(current[-1]["elapsed_s"])
                        - float(current[0]["elapsed_s"]) + 1,
            "samples": len(current),
            "start_temp": temps[0],
            "end_temp": temps[-1],
            "delta": temps[-1] - temps[0],
            "mean_score": sum(scores) / len(scores),
            "low_score": sum(s <= 3 for s in scores),
        })

    for r in rows:
        valid = (
            r.get("phase") == "CPU_ACTIVE"
            and r.get("cpu_temp_rising") == "1"
        )

        if valid:
            current.append(r)
        else:
            save_episode()
            current = []

    save_episode()

episodes.sort(key=lambda e: e["delta"], reverse=True)

print("Sustained CPU_ACTIVE rising-temperature episodes")
print("Minimum length:", MIN_EPISODE, "samples")
print("Episodes found:", len(episodes))
print()
print("file | start_s | duration_s | samples | "
      "start_C | end_C | delta_C | mean_score | score<=3")

for e in episodes[:30]:
    print(
        f"{e['file']} | {e['start']:.1f} | "
        f"{e['duration']:.1f} | {e['samples']} | "
        f"{e['start_temp']:.2f} | {e['end_temp']:.2f} | "
        f"{e['delta']:+.2f} | {e['mean_score']:.2f} | "
        f"{e['low_score']}/{e['samples']}"
    )

print()
print("Offline analysis only; no live settings changed.")
