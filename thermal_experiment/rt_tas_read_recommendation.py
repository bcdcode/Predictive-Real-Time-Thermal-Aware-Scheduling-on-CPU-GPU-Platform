#!/usr/bin/env python3
import csv
import glob
import os
import sys
from datetime import datetime

MAX_AGE_SECONDS = 5
ENTER_THRESHOLD = 4
EXIT_THRESHOLD = 2

STATE_FILE = "rt_tas_shadow_state.txt"
SAMPLE_FILE = "rt_tas_last_sample.txt"


def read_text(path, default=""):
    try:
        with open(path) as f:
            return f.read().strip()
    except FileNotFoundError:
        return default


def atomic_write(path, value):
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        f.write(value + "\n")
    os.replace(tmp, path)


files = sorted(
    glob.glob("thermal_predictor_shadow_*.csv"),
    key=os.path.getmtime,
    reverse=True,
)

if not files:
    print("STATUS=NO_LOG")
    sys.exit(0)

path = files[0]

try:
    with open(path, newline="") as f:
        rows = list(csv.DictReader(f))

    if not rows:
        print("STATUS=EMPTY_LOG")
        sys.exit(0)

    row = rows[-1]
    timestamp = row["timestamp"]
    sample_id = f"{path}|{timestamp}"

    sample_time = datetime.fromisoformat(timestamp).astimezone()
    now = datetime.now().astimezone()
    age = (now - sample_time).total_seconds()

    print(f"FILE={path}")
    print(f"SAMPLE_TIMESTAMP={timestamp}")
    print(f"AGE_SECONDS={age:.1f}")

    if age < -2:
        print("STATUS=CLOCK_MISMATCH")
        sys.exit(0)

    if age > MAX_AGE_SECONDS:
        print("STATUS=STALE")
        sys.exit(0)

    score = int(row["dynamic_score"])
    level = row["prediction_level"]
    phase = row["phase"]

    print("STATUS=FRESH")
    print(f"SCORE={score}")
    print(f"LEVEL={level}")
    print(f"PHASE={phase}")

    previous_sample = read_text(SAMPLE_FILE)

    if sample_id == previous_sample:
        state = read_text(STATE_FILE, "KEEP_TWFD")
        print("SAMPLE_STATUS=DUPLICATE")
        print(f"ENTER_THRESHOLD={ENTER_THRESHOLD}")
        print(f"EXIT_THRESHOLD={EXIT_THRESHOLD}")
        print(f"RECOMMENDATION={state}")
        sys.exit(0)

    state = read_text(STATE_FILE, "KEEP_TWFD")
    if state not in ("KEEP_TWFD", "SHADOW_REVIEW"):
        state = "KEEP_TWFD"

    if score >= ENTER_THRESHOLD:
        state = "SHADOW_REVIEW"
    elif score <= EXIT_THRESHOLD:
        state = "KEEP_TWFD"

    atomic_write(STATE_FILE, state)
    atomic_write(SAMPLE_FILE, sample_id)

    print("SAMPLE_STATUS=NEW")
    print(f"ENTER_THRESHOLD={ENTER_THRESHOLD}")
    print(f"EXIT_THRESHOLD={EXIT_THRESHOLD}")
    print(f"RECOMMENDATION={state}")

except (OSError, ValueError, KeyError, csv.Error) as e:
    print("STATUS=READ_ERROR")
    print(str(e))
    sys.exit(1)
