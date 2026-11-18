#!/bin/bash
set -u

cd "$HOME/thermal_experiment" || exit 1

# ---------------- CONFIGURATION ----------------
CPU=6
BASELINE=20
ACTIVE=60
COOLDOWN=30
INTERVAL=5
PORT=8765

GPU_CONTROL="$HOME/thermal_experiment/gpu_control.txt"
GPU_PAGE="gpu_workload_controlled.html"
URL="http://127.0.0.1:${PORT}/${GPU_PAGE}?duty=100"

OUT="rt_tas_controlled_$(date +%Y%m%d_%H%M%S).csv"

CPU_PID=""
PREDICTOR_PID=""
SERVER_PID=""
CHROME_PID=""
CPU_STATE=OFF
GPU_STATE=OFF
ELAPSED=0
CLEANING=0

CHROME_PROFILE="/tmp/chromium-rt-tas-$$"
CHROME_LOG="/tmp/chromium-rt-tas-$$.log"
SERVER_LOG="/tmp/rt-tas-server-$$.log"

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
    echo "ERROR: k10temp sensor not found."
    exit 1
}

GPU_HWMON=$(find_hwmon amdgpu) || {
    echo "ERROR: amdgpu sensor not found."
    exit 1
}

[ -x ./cpu_burn ] || {
    echo "ERROR: ./cpu_burn missing or not executable."
    exit 1
}

[ -f "$GPU_PAGE" ] || {
    echo "ERROR: $GPU_PAGE not found."
    exit 1
}

command -v python3 >/dev/null || {
    echo "ERROR: python3 not found."
    exit 1
}

if command -v chromium-browser >/dev/null 2>&1; then
    CHROME_BIN=$(command -v chromium-browser)
elif command -v chromium >/dev/null 2>&1; then
    CHROME_BIN=$(command -v chromium)
else
    echo "ERROR: Chromium executable not found."
    exit 1
fi

CPU_FREQ="/sys/devices/system/cpu/cpu${CPU}/cpufreq/scaling_cur_freq"

# ---------------- CLEANUP ----------------
cleanup() {
    [ "$CLEANING" -eq 1 ] && return
    CLEANING=1

    trap - EXIT INT TERM

    echo
    echo "Cleaning up experiment..."
    # Stop live predictive engine.

    if [ -n "$PREDICTOR_PID" ]; then

        kill "$PREDICTOR_PID" 2>/dev/null || true

        wait "$PREDICTOR_PID" 2>/dev/null || true

        PREDICTOR_PID=""

        echo "Live predictive engine stopped."

    fi
    # Disable GPU workload before closing Chromium.
    printf 'OFF\n' > "$GPU_CONTROL" 2>/dev/null || true
    GPU_STATE=OFF

    # Stop the CPU worker.
    if [ -n "$CPU_PID" ]; then
        kill -CONT "$CPU_PID" 2>/dev/null || true
        kill "$CPU_PID" 2>/dev/null || true
        wait "$CPU_PID" 2>/dev/null || true
        CPU_PID=""
    fi

    # Close only Chromium instances using this experiment's profile.
    if [ -n "$CHROME_PID" ]; then
        pkill -TERM -f -- "$CHROME_PROFILE" 2>/dev/null || true

        for i in {1..5}; do
            pgrep -f -- "$CHROME_PROFILE" >/dev/null || break
            sleep 1
        done

        pkill -KILL -f -- "$CHROME_PROFILE" 2>/dev/null || true
        wait "$CHROME_PID" 2>/dev/null || true
        CHROME_PID=""
    fi

    # Stop the HTTP server started by this script.
    if [ -n "$SERVER_PID" ]; then
        kill "$SERVER_PID" 2>/dev/null || true
        wait "$SERVER_PID" 2>/dev/null || true
        SERVER_PID=""
    fi

    echo "CPU worker stopped."
    echo "Experiment Chromium closed."
    echo "Experiment HTTP server stopped."
    echo "GPU control set to OFF."
    echo "CSV: $HOME/thermal_experiment/$OUT"
}

trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

# ---------------- SENSOR READERS ----------------
read_temp() {
    awk '{printf "%.3f", $1/1000}' "$1"
}

read_gpu_freq() {
    # GPU frequency is in Hz; convert to MHz.
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

    local sensor="/sys/class/drm/card0/device/gpu_busy_percent"

    if [ -r "$sensor" ]; then
        cat "$sensor"
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
    local wanted="$1"

    printf '%s\n' "$wanted" > "$GPU_CONTROL" || return 1
    GPU_STATE="$wanted"
}

# ---------------- LOGGING ----------------
echo "timestamp,elapsed_s,phase,cpu_tctl_C,gpu_edge_C,gpu_freq_MHz,gpu_activity_proxy,cpu6_freq_MHz,cpu_active,gpu_enabled,gpu_busy_percent" > "$OUT"
# ------------------------------------------------------------
# START LIVE PREDICTOR
# ------------------------------------------------------------

PREDICTOR_LOG="$HOME/thermal_experiment/live_predictor_${OUT%.csv}.log"

python3 -u "$HOME/thermal_experiment/rt_tas_live_predictor.py" \
    "$OUT" > "$PREDICTOR_LOG" 2>&1 &

PREDICTOR_PID=$!

sleep 0.2

if ! kill -0 "$PREDICTOR_PID" 2>/dev/null; then

    echo "WARNING: Predictor failed to start."
    echo "Check: $PREDICTOR_LOG"

    PREDICTOR_PID=""

else

    echo "Live predictive engine started."
    echo "PID: $PREDICTOR_PID"
    echo "Log: $PREDICTOR_LOG"

fi
log_sample() {

    local phase="$1"

    local ct gt gf ga cf gb

    ct=$(read_temp "$CPU_HWMON/temp1_input") || ct="NA"

    gt=$(read_temp "$GPU_HWMON/temp1_input") || gt="NA"

    gf=$(read_gpu_freq) || gf="0.0"

    cf=$(read_cpu_freq)

    gb=$(read_gpu_busy)

    # Normalized frequency-based GPU activity proxy.
    ga=$(awk -v f="$gf" 'BEGIN {

        u=(f-400)/1600

        if (u<0) u=0

        if (u>1) u=1

        printf "%.3f",u

    }')

    printf '%s,%d,%s,%s,%s,%s,%s,%s,%s,%s,%s\n' \
        "$(date '+%Y-%m-%d %H:%M:%S')" \
        "$ELAPSED" "$phase" \
        "$ct" "$gt" "$gf" "$ga" "$cf" \
        "$CPU_STATE" "$GPU_STATE" "$gb" >> "$OUT"
}

run_stage() {
    local phase="$1"
    local duration="$2"
    local cpu_on="$3"
    local gpu_on="$4"
    local i

    set_cpu "$cpu_on" || exit 1
    set_gpu "$gpu_on" || exit 1

    echo "[$ELAPSED s] $phase: CPU=$cpu_on GPU=$gpu_on (${duration}s)"

    for ((i=0; i<duration; i++)); do
        log_sample "$phase"
        sleep 1
        ELAPSED=$((ELAPSED+1))
    done
}

# ---------------- START HTTP SERVER ----------------
printf 'OFF\n' > "$GPU_CONTROL"

echo "Starting local HTTP server..."

python3 -m http.server "$PORT" --bind 127.0.0.1 \
    > "$SERVER_LOG" 2>&1 &
SERVER_PID=$!

# Wait up to 10 seconds for the page to become available.
READY=0

for i in {1..20}; do
    if python3 -c "
import urllib.request
u = '$URL'
r = urllib.request.urlopen(u, timeout=1)
assert r.status == 200
" >/dev/null 2>&1; then
        READY=1
        break
    fi

    if ! kill -0 "$SERVER_PID" 2>/dev/null; then
        echo "ERROR: HTTP server exited."
        cat "$SERVER_LOG"
        exit 1
    fi

    sleep 0.5
done

if [ "$READY" -ne 1 ]; then
    echo "ERROR: GPU page did not become available."
    echo "Check port $PORT and $SERVER_LOG."
    exit 1
fi

echo "HTTP server ready."

# ---------------- OPEN CHROMIUM ----------------
echo "Opening controlled GPU workload in Chromium..."

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

echo "Waiting for Chromium/WebGL initialization..."
sleep 5

if ! kill -0 "$CHROME_PID" 2>/dev/null; then
    echo "WARNING: Chromium launcher exited."
    echo "Inspect $CHROME_LOG"
fi

# ---------------- START CPU WORKER ----------------
echo "Starting CPU worker pinned to logical CPU $CPU..."

taskset -c "$CPU" ./cpu_burn "$CPU" 3600 \
    > /tmp/rt-tas-cpu-$$.log 2>&1 &
CPU_PID=$!

sleep 0.3

if ! kill -0 "$CPU_PID" 2>/dev/null; then
    echo "ERROR: CPU worker failed to start."
    cat "/tmp/rt-tas-cpu-$$.log"
    exit 1
fi

kill -STOP "$CPU_PID" || exit 1
CPU_STATE=OFF

# ---------------- EXPERIMENT ----------------
echo
echo "Starting experiment."
echo "Output: $OUT"
echo "Keep the experiment running until completion."

# Initial idle baseline.
run_stage IDLE_BASELINE1 "$BASELINE" OFF OFF

# Simultaneous CPU + GPU baseline.
run_stage SIMULTANEOUS "$ACTIVE" ON ON

# Cooldown.
run_stage COOLDOWN1 "$COOLDOWN" OFF OFF

# Second idle baseline.
run_stage IDLE_BASELINE2 "$BASELINE" OFF OFF

# Alternate CPU-only and GPU-only phases.
SLOTS=$((ACTIVE / INTERVAL))

for ((slot=0; slot<SLOTS; slot++)); do
    if (( slot % 2 == 0 )); then
        run_stage TA_CPU "$INTERVAL" ON OFF
    else
        run_stage TA_GPU "$INTERVAL" OFF ON
    fi
done

# Final cooldown.
run_stage COOLDOWN2 "$COOLDOWN" OFF OFF

echo
echo "Experiment completed successfully."
echo "CSV saved to: $HOME/thermal_experiment/$OUT"
echo "Chromium will now close automatically."

