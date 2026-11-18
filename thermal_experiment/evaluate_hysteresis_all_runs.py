import csv
from pathlib import Path
from collections import Counter

FILES = sorted(Path(".").glob("thermal_predictor_shadow_*.csv"))
ENTER_SCORE = 4
EXIT_SCORE = 2

def recorded_state(row):
    action = row.get("recommended_action", "")
    if "KEEP_TWFD_UNCHANGED" in action:
        return "KEEP"
    if "REVIEW_TWFD_PLACEMENT" in action:
        return "REVIEW"
    return "OTHER"

def changes(states):
    return sum(a != b for a, b in zip(states, states[1:]))

def replay(rows, hold):
    state = "KEEP"
    high = low = 0
    states = []
    events = []

    for i, row in enumerate(rows):
        score = float(row["dynamic_score"])

        if score >= ENTER_SCORE:
            high += 1
            low = 0
        elif score <= EXIT_SCORE:
            low += 1
            high = 0
        else:
            high = low = 0

        old = state

        if state == "KEEP" and high >= hold:
            state = "REVIEW"
            high = low = 0
        elif state == "REVIEW" and low >= hold:
            state = "KEEP"
            high = low = 0

        states.append(state)
        if state != old:
            events.append((i, state))

    return states, events

results = []

for path in FILES:
    try:
        with path.open(newline="") as f:
            rows = list(csv.DictReader(f))

        if not rows or not {
            "elapsed_s", "phase", "dynamic_score",
            "cpu_tctl_C", "cpu_temp_rising",
            "recommended_action"
        }.issubset(rows[0]):
            print(f"SKIP {path.name}: missing required columns")
            continue

        rows.sort(key=lambda r: float(r["elapsed_s"]))
        actual = [recorded_state(r) for r in rows]

        item = {
            "file": path.name,
            "n": len(rows),
            "actual_changes": changes(actual),
            "actual_review": actual.count("REVIEW"),
        }

        for hold in (2, 3, 4):
            states, events = replay(rows, hold)
            item[f"h{hold}_changes"] = changes(states)
            item[f"h{hold}_review"] = states.count("REVIEW")

            # CPU-active episodes: first CPU_ACTIVE sample after
            # any non-CPU_ACTIVE sample starts a new episode.
            delays = []
            episode_start = None
            for i, row in enumerate(rows):
                if row["phase"] == "CPU_ACTIVE":
                    if episode_start is None:
                        episode_start = i
                elif episode_start is not None:
                    first_review = next(
                        (j for j in range(episode_start, i)
                         if states[j] == "REVIEW"), None
                    )
                    if first_review is not None:
                        delays.append(
                            float(rows[first_review]["elapsed_s"]) -
                            float(rows[episode_start]["elapsed_s"])
                        )
                    episode_start = None

            if episode_start is not None:
                first_review = next(
                    (j for j in range(episode_start, len(rows))
                     if states[j] == "REVIEW"), None
                )
                if first_review is not None:
                    delays.append(
                        float(rows[first_review]["elapsed_s"]) -
                        float(rows[episode_start]["elapsed_s"])
                    )

            item[f"h{hold}_episodes_with_review"] = len(delays)
            item[f"h{hold}_mean_delay"] = (
                sum(delays) / len(delays) if delays else None
            )

        results.append(item)

    except (OSError, ValueError, KeyError) as e:
        print(f"SKIP {path.name}: {e}")

if not results:
    raise SystemExit("No usable recordings found.")

print(f"\nUsable recordings: {len(results)}")
print(f"Total samples: {sum(r['n'] for r in results)}")
print("\nPER-RUN RESULTS")
print("file,n,actual_changes,actual_review,"
      "h2_changes,h2_review,h2_review_episodes,h2_mean_delay_s,"
      "h3_changes,h3_review,h3_review_episodes,h3_mean_delay_s,"
      "h4_changes,h4_review,h4_review_episodes,h4_mean_delay_s")

for r in results:
    fields = [r["file"], r["n"], r["actual_changes"], r["actual_review"]]
    for h in (2, 3, 4):
        delay = r[f"h{h}_mean_delay"]
        fields += [
            r[f"h{h}_changes"], r[f"h{h}_review"],
            r[f"h{h}_episodes_with_review"],
            f"{delay:.2f}" if delay is not None else "NA"
        ]
    print(",".join(map(str, fields)))

print("\nAGGREGATE COUNTS")
for key, label in [
    ("actual_changes", "Recorded action changes"),
    ("actual_review", "Recorded REVIEW samples"),
    ("h2_changes", "Hold-2 state changes"),
    ("h2_review", "Hold-2 REVIEW samples"),
    ("h3_changes", "Hold-3 state changes"),
    ("h3_review", "Hold-3 REVIEW samples"),
    ("h4_changes", "Hold-4 state changes"),
    ("h4_review", "Hold-4 REVIEW samples"),
]:
    print(f"{label}: {sum(r[key] for r in results)}")

print("\nMean entry delay among episodes that reached REVIEW:")
for h in (2, 3, 4):
    delays = [
        r[f"h{h}_mean_delay"]
        for r in results
        if r[f"h{h}_mean_delay"] is not None
    ]
    print(
        f"Hold {h}: {sum(delays)/len(delays):.2f}s "
        f"across {len(delays)} recording-level averages"
        if delays else f"Hold {h}: no REVIEW episodes detected"
    )

print("\nOffline analysis only; live predictor and scheduler unchanged.")
print("Caution: a recording may contain multiple workload episodes.")
print("Candidate thresholds >=4 to enter and <=2 to exit are experimental.")
