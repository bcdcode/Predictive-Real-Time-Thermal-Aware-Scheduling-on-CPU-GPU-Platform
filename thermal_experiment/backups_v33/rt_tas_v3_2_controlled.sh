#!/bin/bash
set -u

cd "$HOME/thermal_experiment" || exit 1

# ============================================================
# RT-TAS V3.2 CONTROLLED BASELINE EXPERIMENT
# Usage: ./rt_tas_v3_2_controlled.sh BASELINE
# ============================================================

MODE="${1:-}"

if [[ "$MODE" != "BASELINE" ]]; then
    echo "V3.2 currently supports BASELINE mode only."
    echo "Usage: $0 BASELINE"
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

PREDICTOR="$HOME/thermal_experiment/rt_tas_live_predictor_v3_2.py"

STAMP=$(date +%Y%m%d_%H%M%S)

OUT="rt_tas_v3_2_${MODE}_${STAMP}.csv"
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

START_MONO=""

CHROME_PROFILE="/tmp/chromium-v32-$$"
CHROME_LOG="/tmp/chromium-v32-$$.log"
SERVER_LOG="/tmp/server-v32-$$.log"
CPU_LOG="/tmp/cpu-v32-$$.log"
PREDICTOR_LOG="/tmp/predictor-v32-$$.log"


# ============================================================
# SENSOR DISCOVERY
# ============================================================

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


# ============================================================
# ENVIRONMENT CHECKS
# ============================================================

[ -x ./cpu_burn ] || {
    echo "ERROR: cpu_burn missing."
    exit 1
}

[ -f "$GPU_PAGE" ] || {
    echo "ERROR: GPU HTML page missing."
    exit 1
}

[ -f "$PREDICTOR" ] || {
    echo "ERROR: V3.2 predictor missing."
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


# ============================================================
# CLEANUP
# ============================================================

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


# ============================================================
# SENSOR READERS
# ============================================================

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


# ============================================================
# WORKLOAD CONTROL
# ============================================================

set_cpu() {

    local wanted="$1"

    if [ -z "$CPU_PID" ] ||
       ! kill -0 "$CPU_PID" 2>/dev/null; then

        echo "ERROR: CPU worker is not running."

        return 1
    fi

    if [ "$wanted" = ON ] &&
       [ "$CPU_STATE" != ON ]; then

        kill -CONT "$CPU_PID" || return 1

        CPU_STATE=ON

    elif [ "$wanted" = OFF ] &&
         [ "$CPU_STATE" != OFF ]; then

        kill -STOP "$CPU_PID" || return 1

        CPU_STATE=OFF
    fi
}

set_gpu() {

    printf '%s\n' "$1" > "$GPU_CONTROL" || return 1

    GPU_STATE="$1"
}


# ============================================================
# MONOTONIC CLOCK
# ============================================================

mono_now() {

    awk '{print $1}' /proc/uptime
}

monotonic_elapsed() {

    local now

    now=$(mono_now)

    awk -v start="$START_MONO" -v now="$now" \
        'BEGIN {
            printf "%.3f", now-start
        }'
}


# ============================================================
# ABSOLUTE ONE-SECOND SCHEDULING
# ============================================================

wait_next_tick() {

    local target

    target=$(awk \
        -v start="$START_MONO" \
        -v elapsed="$ELAPSED" \
        'BEGIN {
            printf "%.3f", start+elapsed+1
        }')

    python3 - "$target" <<'PY'

import sys
import time

target = float(sys.argv[1])

while True:

    with open("/proc/uptime") as f:
        now = float(f.read().split()[0])

    remaining = target - now

    if remaining <= 0:
        break

    time.sleep(min(remaining, 0.02))

PY
}


# ============================================================
# TELEMETRY FILES
# ============================================================

echo "timestamp,elapsed_s,monotonic_elapsed_s,phase,cpu_tctl_C,gpu_edge_C,gpu_freq_MHz,gpu_activity_proxy,cpu6_freq_MHz,cpu_active,gpu_enabled,gpu_busy_percent" \
    > "$OUT"

echo "timestamp,elapsed_s,phase,mode,prediction_status,cpu_predicted_rise_C,gpu_predicted_rise_C,decision,cpu_action" \
    > "$DECISION_OUT"


# ============================================================
# TELEMETRY LOGGER
# ============================================================

log_sample() {

    local phase="$1"

    local ct gt gf ga cf gb me

    ct=$(read_temp "$CPU_HWMON/temp1_input") || ct="NA"

    gt=$(read_temp "$GPU_HWMON/temp1_input") || gt="NA"

    gf=$(read_gpu_freq) || gf="0.0"

    cf=$(read_cpu_freq)

    gb=$(read_gpu_busy)

    me=$(monotonic_elapsed)

    ga=$(awk -v f="$gf" 'BEGIN {

        u=(f-400)/1600

        if (u<0) u=0

        if (u>1) u=1

        printf "%.3f",u

    }')

    printf '%s,%d,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s\n' \
        "$(date '+%Y-%m-%d %H:%M:%S')" \
        "$ELAPSED" \
        "$me" \
        "$phase" \
        "$ct" \
        "$gt" \
        "$gf" \
        "$ga" \
        "$cf" \
        "$CPU_STATE" \
        "$GPU_STATE" \
        "$gb" >> "$OUT"
}


# ============================================================
# BASELINE DECISION LOGGER
# ============================================================

log_decision() {

    printf '%s,%d,TA_GPU,%s,%s,%s,%s,%s,%s\n' \
        "$(date '+%Y-%m-%d %H:%M:%S')" \
        "$ELAPSED" \
        "$MODE" \
        "NOT_APPLICABLE" \
        "NA" \
        "NA" \
        "BASELINE_CPU_DISABLED" \
        "CPU_OFF" >> "$DECISION_OUT"
}


# ============================================================
# START HTTP SERVER
# ============================================================

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


# ============================================================
# START CHROMIUM
# ============================================================

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

    echo "ERROR: Chromium launcher exited."

    echo "Check $CHROME_LOG"

    exit 1
fi


# ============================================================
# START CPU WORKER
# ============================================================

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


# ============================================================
# START LIVE PREDICTOR
# ============================================================

python3 -u "$PREDICTOR" "$OUT" \
    > "$PREDICTOR_LOG" 2>&1 &

PREDICTOR_PID=$!

sleep 1

if ! kill -0 "$PREDICTOR_PID" 2>/dev/null; then

    echo "ERROR: Predictor failed."

    echo "Check $PREDICTOR_LOG"

    exit 1
fi


# ============================================================
# EXPERIMENT START
# ============================================================

START_MONO=$(mono_now)

echo
echo "Monotonic experiment clock started: $START_MONO"

echo
echo "=========================================="
echo "RT-TAS V3.2 CONTROLLED EXPERIMENT"
echo "=========================================="

echo "Mode: $MODE"
echo "Telemetry: $OUT"
echo "Predictions: $PRED_OUT"
echo "Decisions: $DECISION_OUT"

echo "CPU core: $CPU"

echo "Baseline: ${BASELINE}s"
echo "GPU phase: ${TA_GPU_DURATION}s"
echo "Cooldown: ${COOLDOWN}s"

echo "=========================================="


# ============================================================
# PHASE 1: IDLE BASELINE
# ============================================================

echo
echo "Starting IDLE_BASELINE1..."

set_cpu OFF

set_gpu OFF

for ((i=0; i<BASELINE; i++)); do

    log_sample IDLE_BASELINE1

    wait_next_tick

    ELAPSED=$((ELAPSED+1))

done


# ============================================================
# PHASE 2: GPU-ONLY WORKLOAD
# ============================================================

echo
echo "Starting TA_GPU phase..."

set_cpu OFF

set_gpu ON

for ((i=0; i<TA_GPU_DURATION; i++)); do

    log_sample TA_GPU

    log_decision

    wait_next_tick

    ELAPSED=$((ELAPSED+1))

done


# ============================================================
# PHASE 3: COOLDOWN
# ============================================================

echo
echo "Starting COOLDOWN2..."

set_cpu OFF

set_gpu OFF

for ((i=0; i<COOLDOWN; i++)); do

    log_sample COOLDOWN2

    wait_next_tick

    ELAPSED=$((ELAPSED+1))

done


# ============================================================
# EXPERIMENT COMPLETE
# ============================================================

echo
echo "=========================================="
echo "RT-TAS V3.2 EXPERIMENT COMPLETED"
echo "=========================================="

echo "Total telemetry samples: $((BASELINE + TA_GPU_DURATION + COOLDOWN))"

echo "CPU admission occurred: $ADMITTED"

echo "Telemetry: $OUT"

echo "Predictions: $PRED_OUT"

echo "Admission log: $DECISION_OUT"

echo "=========================================="
