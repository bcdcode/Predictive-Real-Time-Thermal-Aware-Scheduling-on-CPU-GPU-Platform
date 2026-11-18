#!/bin/bash

OUT="coupling_final_v2_$(date +%Y%m%d_%H%M%S).csv"

INTERVAL=1
BASELINE=30
ACTIVE=60
COOLDOWN=30
CPU=6

HWCPU="/sys/class/hwmon/hwmon2"
HWGPU="/sys/class/hwmon/hwmon1"

echo "timestamp,phase,cpu_temp_C,gpu_temp_C,gpu_freq_MHz,gpu_activity,cpu_freq_MHz" > "$OUT"

log_phase() {
    local PHASE="$1"
    local SECONDS="$2"

    for ((i=0; i<SECONDS; i++)); do

        TS=$(date +%s)

        CPU_TEMP=$(awk '{printf "%.3f", $1/1000}' \
            "$HWCPU/temp1_input")

        GPU_TEMP=$(awk '{printf "%.3f", $1/1000}' \
            "$HWGPU/temp1_input")

        # freq1_input is in Hz
        GPU_FREQ=$(awk '{printf "%.1f", $1/1000000}' \
            "$HWGPU/freq1_input")

        # Normalize 400 MHz -> 0 and 2000 MHz -> 1
        GPU_ACTIVITY=$(awk -v f="$GPU_FREQ" '
            BEGIN {
                u=(f-400)/(2000-400)
                if(u<0) u=0
                if(u>1) u=1
                printf "%.3f",u
            }')

        CPU_FREQ=$(awk '{printf "%.1f", $1/1000}' \
            "/sys/devices/system/cpu/cpu${CPU}/cpufreq/scaling_cur_freq" \
            2>/dev/null)

        echo "$TS,$PHASE,$CPU_TEMP,$GPU_TEMP,$GPU_FREQ,$GPU_ACTIVITY,$CPU_FREQ" >> "$OUT"

        sleep "$INTERVAL"
    done
}


start_gpu() {

    PROFILE="/tmp/chromium-gpu-rt-tas-final-v2"

    rm -rf "$PROFILE"

    chromium-browser \
        --user-data-dir="$PROFILE" \
        --use-gl=angle \
        --use-angle=gles \
        --ignore-gpu-blocklist \
        --enable-gpu-rasterization \
        --no-first-run \
        --no-default-browser-check \
        "file://$HOME/thermal_experiment/gpu_stress_safe.html" \
        >/tmp/chromium-gpu-rt-tas-final-v2.log 2>&1 &

    CHROME_PID=$!

    echo
    echo "Waiting for GPU workload to become active..."

    ACTIVE_COUNT=0

    for ((i=0; i<60; i++)); do

        sleep 1

        RAW_FREQ=$(cat "$HWGPU/freq1_input")
        GPU_FREQ=$((RAW_FREQ / 1000000))

        echo "GPU frequency: ${GPU_FREQ} MHz"

        if [ "$GPU_FREQ" -ge 1900 ]; then
            ACTIVE_COUNT=$((ACTIVE_COUNT+1))
        else
            ACTIVE_COUNT=0
        fi

        if [ "$ACTIVE_COUNT" -ge 3 ]; then
            echo
            echo "GPU workload confirmed active."
            return 0
        fi

    done

    echo
    echo "ERROR: GPU workload did not reach 1900 MHz."

    stop_gpu

    return 1
}


stop_gpu() {

    if [ -n "$CHROME_PID" ]; then
        kill "$CHROME_PID" 2>/dev/null
        sleep 2
        CHROME_PID=""
    fi
}


echo
echo "=========================================="
echo " CPU-GPU THERMAL COUPLING EXPERIMENT v2"
echo "=========================================="
echo
echo "Output file: $OUT"
echo
echo "CPU used for CPU workload: $CPU"
echo

# ------------------------------------------------
# PHASE 1
# ------------------------------------------------

echo "PHASE 1: BASELINE1"
echo "No GPU workload."
echo

log_phase BASELINE1 "$BASELINE"


# ------------------------------------------------
# PHASE 2
# ------------------------------------------------

echo
echo "PHASE 2: GPU ONLY"
echo

start_gpu || exit 1

log_phase GPU_ONLY "$ACTIVE"

echo
echo "GPU-only phase completed."

stop_gpu


# ------------------------------------------------
# PHASE 3
# ------------------------------------------------

echo
echo "PHASE 3: COOLDOWN1"
echo

log_phase COOLDOWN1 "$COOLDOWN"


# ------------------------------------------------
# PHASE 4
# ------------------------------------------------

echo
echo "PHASE 4: BASELINE2"
echo "No workload."
echo

log_phase BASELINE2 "$BASELINE"


# ------------------------------------------------
# PHASE 5
# ------------------------------------------------

echo
echo "PHASE 5: CPU + GPU"
echo

start_gpu || exit 1

echo
echo "Starting CPU workload on CPU $CPU..."
echo

taskset -c "$CPU" ./cpu_burn "$ACTIVE" \
    >/tmp/cpu_burn_coupling_v2.log 2>&1 &

CPU_PID=$!

log_phase CPU_GPU "$ACTIVE"

wait "$CPU_PID" 2>/dev/null

echo
echo "CPU + GPU phase completed."

stop_gpu


# ------------------------------------------------
# PHASE 6
# ------------------------------------------------

echo
echo "PHASE 6: COOLDOWN2"
echo

log_phase COOLDOWN2 "$COOLDOWN"


# ------------------------------------------------
# DONE
# ------------------------------------------------

echo
echo "=========================================="
echo " EXPERIMENT COMPLETED"
echo "=========================================="
echo
echo "CSV:"
echo "$OUT"
echo

