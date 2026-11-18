#!/bin/bash
set -u

cd "$HOME/thermal_experiment" || exit 1

# ============================================================
# RT-TAS V3.1 CONTROLLED ADMISSION EXPERIMENT
# Usage: ./rt_tas_v3_1_controlled.sh BASELINE
#        ./rt_tas_v3_1_controlled.sh POLICY
# ============================================================

MODE="${1:-}"

if [[ "$MODE" != "BASELINE" && "$MODE" != "POLICY" ]]; then
    echo "Usage: $0 BASELINE|POLICY"
    exit 1
fi

CPU=6
BASELINE=20
TA_GPU_DURATION=15
COOLDOWN=30
PORT=8765

GPU_CONTROL="$HOME/thermal_experiment/gpu_control.txt"
GPU_PAGE="gpu_workload_controlled.html"
URL="http://127.0.0.1:${PORT}/${GPU_PAGE}?duty=100"

PREDICTOR="$HOME/thermal_experiment/rt_tas_live_predictor_v3_1.py"

STAMP=$(date +%Y%m%d_%H%M%S)
OUT="rt_tas_v3_1_${MODE}_${STAMP}.csv"
PRED_OUT="${OUT%.csv}_live_predictions.csv"
DECISION_OUT="${OUT%.csv}_admission_log.csv"

CPU_PID=""
PREDICTOR_PID=""
SERVER_PID=""
CHROME_PID=""

CPU_STATE=OFF
GPU_STATE=OFF
ELAPSED=0
CLEANING=0
ADMITTED=0

CHROME_PROFILE="/tmp/chromium-v31-$$"
CHROME_LOG="/tmp/chromium-v31-$$.log"
SERVER_LOG="/tmp/server-v31-$$.log"
CPU_LOG="/tmp/cpu-v31-$$.log"
PREDICTOR_LOG="/tmp/predictor-v31-$$.log"

# ---------------- SENSOR DISCOVERY ----------------

find_hwmon() {
    local wanted="$1"
    local d

    for d in /sys/class/hwmon/hwmon*; do
        [ -r "$d/name" ] || continue

        if [ "$(cat "$d/name")" = "$wanted" ]; then
            echo "$d"
            return 0
        fi
    done

    return 1
}

CPU_HWMON=$(find_hwmon k10temp) || {
    echo "ERROR: k10temp not found."
    exit 1
}

GPU_HWMON=$(find_hwmon amdgpu) || {
    echo "ERROR: amdgpu not found."
    exit 1
}

CPU_FREQ="/sys/devices/system/cpu/cpu${CPU}/cpufreq/scaling_cur_freq"
GPU_BUSY="/sys/class/drm/card0/device/gpu_busy_percent"

[ -x ./cpu_burn ] || {
    echo "ERROR: cpu_burn missing."
    exit 1
}

[ -f "$GPU_PAGE" ] || {
    echo "ERROR: GPU HTML page missing."
    exit 1
}

[ -f "$PREDICTOR" ] || {
    echo "ERROR: V3.1 predictor copy missing."
    exit 1
}

command -v python3 >/dev/null || exit 1
command -v taskset >/dev/null || exit 1

if command -v chromium-browser >/dev/null 2>&1; then
    CHROME_BIN=$(command -v chromium-browser)
elif command -v chromium >/dev/null 2>&1; then
    CHROME_BIN=$(command -v chromium)
else
    echo "ERROR: Chromium not found."
    exit 1
fi

# ---------------- CLEANUP ----------------

cleanup() {
    [ "$CLEANING" -eq 1 ] && return
    CLEANING=1

    trap - EXIT INT TERM

    echo
    echo "Cleaning up..."

    printf 'OFF\n' > "$GPU_CONTROL" 2>/dev/null || true
    GPU_STATE=OFF

    if [ -n "$CPU_PID" ]; then
        kill -CONT "$CPU_PID" 2>/dev/null || true
        kill "$CPU_PID" 2>/dev/null || true
        wait "$CPU_PID" 2>/dev/null || true
        CPU_PID=""
    fi

    if [ -n "$PREDICTOR_PID" ]; then
        kill "$PREDICTOR_PID" 2>/dev/null || true
        wait "$PREDICTOR_PID" 2>/dev/null || true
        PREDICTOR_PID=""
    fi

    if [ -n "$CHROME_PID" ]; then
        pkill -TERM -f -- "$CHROME_PROFILE" 2>/dev/null || true
        sleep 2
        pkill -KILL -f -- "$CHROME_PROFILE" 2>/dev/null || true
        wait "$CHROME_PID" 2>/dev/null || true
        CHROME_PID=""
    fi

    if [ -n "$SERVER_PID" ]; then
        kill "$SERVER_PID" 2>/dev/null || true
        wait "$SERVER_PID" 2>/dev/null || true
        SERVER_PID=""
    fi

    echo "CPU: OFF"
    echo "GPU: OFF"
    echo "Experiment processes cleaned up."
    echo "Telemetry: $OUT"
    echo "Predictions: $PRED_OUT"
    echo "Admission log: $DECISION_OUT"
}

trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

# ---------------- SENSOR READERS ----------------

read_temp() {
    awk '{printf "%.3f", $1/1000}' "$1"
}

read_gpu_freq() {
    awk '{printf "%.1f", $1/1000000}' \
        "$GPU_HWMON/freq1_input"
}

read_cpu_freq() {
    if [ -r "$CPU_FREQ" ]; then
        awk '{printf "%.1f", $1/1000}' "$CPU_FREQ"
    else
        echo "0.0"
    fi
}

read_gpu_busy() {
    if [ -r "$GPU_BUSY" ]; then
        cat "$GPU_BUSY"
    else
        echo "NA"
    fi
}

# ---------------- WORKLOAD CONTROL ----------------

set_cpu() {
    local wanted="$1"

    if [ -z "$CPU_PID" ] || ! kill -0 "$CPU_PID" 2>/dev/null; then
        echo "ERROR: CPU worker is not running."
        return 1
    fi

    if [ "$wanted" = ON ] && [ "$CPU_STATE" != ON ]; then
        kill -CONT "$CPU_PID" || return 1
        CPU_STATE=ON
    elif [ "$wanted" = OFF ] && [ "$CPU_STATE" != OFF ]; then
        kill -STOP "$CPU_PID" || return 1
        CPU_STATE=OFF
    fi
}

set_gpu() {
    printf '%s\n' "$1" > "$GPU_CONTROL" || return 1
    GPU_STATE="$1"
}

# ---------------- TELEMETRY ----------------

echo "timestamp,elapsed_s,phase,cpu_tctl_C,gpu_edge_C,gpu_freq_MHz,gpu_activity_proxy,cpu6_freq_MHz,cpu_active,gpu_enabled,gpu_busy_percent" > "$OUT"

echo "timestamp,elapsed_s,phase,mode,prediction_status,cpu_predicted_rise_C,gpu_predicted_rise_C,decision,cpu_action" > "$DECISION_OUT"

log_sample() {
    local phase="$1"
    local ct gt gf ga cf gb

    ct=$(read_temp "$CPU_HWMON/temp1_input") || ct="NA"
    gt=$(read_temp "$GPU_HWMON/temp1_input") || gt="NA"
    gf=$(read_gpu_freq) || gf="0.0"
    cf=$(read_cpu_freq)
    gb=$(read_gpu_busy)

    ga=$(awk -v f="$gf" 'BEGIN {
        u=(f-400)/1600
        if (u<0) u=0
        if (u>1) u=1
        printf "%.3f",u
    }')

    printf '%s,%d,%s,%s,%s,%s,%s,%s,%s,%s,%s\n' \
        "$(date '+%Y-%m-%d %H:%M:%S')" \
        "$ELAPSED" "$phase" "$ct" "$gt" "$gf" "$ga" "$cf" \
        "$CPU_STATE" "$GPU_STATE" "$gb" >> "$OUT"
}

log_decision() {
    printf '%s,%d,TA_GPU,%s,%s,%s,%s,%s,%s\n' \
        "$(date '+%Y-%m-%d %H:%M:%S')" \
        "$ELAPSED" "$MODE" "$1" "$2" "$3" "$4" "$5" >> "$DECISION_OUT"
}

# ---------------- LIVE PREDICTION READER ----------------
# Returns a prediction only for the exact current elapsed second.
# A missing or invalid prediction can never admit CPU work.

read_prediction() {
    local target="$1"

    python3 - "$PRED_OUT" "$target" <<'PY'
import csv
import sys
import math
import os

path = sys.argv[1]
target = int(sys.argv[2])

if not os.path.isfile(path):
    print("WAIT")
    raise SystemExit

try:
    with open(path, newline="") as f:
        rows = list(csv.DictReader(f))

    matches = [
        r for r in rows
        if r.get("phase") == "TA_GPU"
        and int(float(r.get("elapsed_s", "-1"))) == target
    ]

    if not matches:
        print("WAIT")
        raise SystemExit

    r = matches[-1]
    status = r.get("prediction_status", "")

    def num(x):
        v = float(x)
        return v if math.isfinite(v) else None

    cpu = num(r["cpu_predicted_1s_C"])
    gpu = num(r["gpu_predicted_1s_C"])
    ca = num(r["cpu_actual_C"])
    ga = num(r["gpu_actual_C"])

    if status != "FORECAST_ONLY" or None in (cpu, gpu, ca, ga):
        print("FOUND|INVALID|NA|NA")
    else:
        print(f"FOUND|FORECAST_ONLY|{cpu-ca:.4f}|{gpu-ga:.4f}")

except Exception:
    print("FOUND|INVALID|NA|NA")
PY
}

# ---------------- WAIT FOR FRESH PREDICTION ----------------

evaluate_policy() {
    local target="$1"
    local result="WAIT"
    local attempt

    for attempt in {1..10}; do
        result=$(read_prediction "$target")

        if [[ "$result" == FOUND* ]]; then
            break
        fi

        sleep 0.1
    done

    if [[ "$result" != FOUND* ]]; then
        log_decision "NO_FRESH_PREDICTION" "NA" "NA" \
            "BASELINE_FALLBACK" "CPU_OFF"
        echo "No fresh prediction at ${target}s. CPU remains OFF."
        return 1
    fi

    IFS='|' read -r tag status cpu_rise gpu_rise <<< "$result"

    if [ "$status" != "FORECAST_ONLY" ]; then
        log_decision "$status" "NA" "NA" \
            "BASELINE_FALLBACK" "CPU_OFF"
        echo "Invalid prediction. CPU remains OFF."
        return 1
    fi

    if awk -v c="$cpu_rise" -v g="$gpu_rise" \
        'BEGIN {exit !(c <= 0.05 && g <= 0.05)}'; then

        log_decision "$status" "$cpu_rise" "$gpu_rise" \
            "CPU_ADMISSION_CANDIDATE" "PULSE_PENDING"

        echo "V3.1 candidate: CPU rise=$cpu_rise GPU rise=$gpu_rise"
        return 0
    else
        log_decision "$status" "$cpu_rise" "$gpu_rise" \
            "DEFER_CPU_ADMISSION" "CPU_OFF"

        echo "V3.1 defer: CPU rise=$cpu_rise GPU rise=$gpu_rise"
        return 1
    fi
}

# ---------------- START HTTP SERVER ----------------

printf 'OFF\n' > "$GPU_CONTROL"

python3 -m http.server "$PORT" --bind 127.0.0.1 \
    > "$SERVER_LOG" 2>&1 &
SERVER_PID=$!

READY=0

for i in {1..20}; do
    if python3 -c "
import urllib.request
r=urllib.request.urlopen('$URL', timeout=1)
assert r.status == 200
" >/dev/null 2>&1; then
        READY=1
        break
    fi

    sleep 0.5
done

if [ "$READY" -ne 1 ]; then
    echo "ERROR: HTTP server did not become ready."
    exit 1
fi

# ---------------- START CHROMIUM ----------------

"$CHROME_BIN" \
    --user-data-dir="$CHROME_PROFILE" \
    --no-first-run \
    --no-default-browser-check \
    --no-sandbox \
    --use-gl=angle \
    --use-angle=gles \
    --ignore-gpu-blocklist \
    --enable-gpu-rasterization \
    "$URL" > "$CHROME_LOG" 2>&1 &

CHROME_PID=$!

sleep 5

if ! kill -0 "$CHROME_PID" 2>/dev/null; then
    echo "ERROR: Chromium launcher exited. Check $CHROME_LOG"
    exit 1
fi

# ---------------- START CPU WORKER ----------------

taskset -c "$CPU" ./cpu_burn "$CPU" 3600 \
    > "$CPU_LOG" 2>&1 &
CPU_PID=$!

sleep 0.3

if ! kill -0 "$CPU_PID" 2>/dev/null; then
    echo "ERROR: CPU worker failed."
    cat "$CPU_LOG"
    exit 1
fi

kill -STOP "$CPU_PID" || exit 1
CPU_STATE=OFF

# ---------------- START PREDICTOR ----------------

python3 -u "$PREDICTOR" "$OUT" \
    > "$PREDICTOR_LOG" 2>&1 &
PREDICTOR_PID=$!

sleep 1

if ! kill -0 "$PREDICTOR_PID" 2>/dev/null; then
    echo "ERROR: Predictor failed. Check $PREDICTOR_LOG"
    exit 1
fi

# ---------------- EXPERIMENT ----------------

echo
echo "RT-TAS V3.1 CONTROLLED EXPERIMENT"
echo "Mode: $MODE"
echo "Telemetry: $OUT"
echo "Predictions: $PRED_OUT"
echo "Decisions: $DECISION_OUT"

# Initial idle baseline.
set_cpu OFF
set_gpu OFF

for ((i=0; i<BASELINE; i++)); do
    log_sample IDLE_BASELINE1
    sleep 1
    ELAPSED=$((ELAPSED+1))
done

# GPU-only phase.
set_cpu OFF
set_gpu ON

echo
echo "Starting 15-second TA_GPU phase."

for ((i=0; i<TA_GPU_DURATION; i++)); do

    log_sample TA_GPU

    # Only evaluate after five seconds of same-phase history.
    if [ "$MODE" = "POLICY" ] &&
       [ "$i" -ge 5 ] &&
       [ "$i" -le 13 ] &&
       [ "$ADMITTED" -eq 0 ]; then

        if evaluate_policy "$ELAPSED"; then

            echo "Admitting one-second CPU pulse."

            set_cpu ON || exit 1
            sleep 1
            set_cpu OFF || exit 1

            log_decision "PULSE_EXECUTED" "NA" "NA" \
                "CPU_PULSE_EXECUTED" "CPU_ON_1S"

            ADMITTED=1

            # The pulse occupies this one-second interval.
            ELAPSED=$((ELAPSED+1))
            continue
        fi
    fi

    if [ "$MODE" = "BASELINE" ]; then
        log_decision "NOT_APPLICABLE" "NA" "NA" \
            "BASELINE_CPU_DISABLED" "CPU_OFF"
    fi

    sleep 1
    ELAPSED=$((ELAPSED+1))
done

# Explicitly stop both workloads before cooldown.
set_cpu OFF
set_gpu OFF

for ((i=0; i<COOLDOWN; i++)); do
    log_sample COOLDOWN2
    sleep 1
    ELAPSED=$((ELAPSED+1))
done

echo
echo "Experiment completed."
echo "CPU admission occurred: $ADMITTED"
echo "Review the telemetry and admission logs."

