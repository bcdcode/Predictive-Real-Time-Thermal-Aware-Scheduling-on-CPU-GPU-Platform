#!/bin/bash

OUT="cpu_gpu_coupling_controlled_$(date +%Y%m%d_%H%M%S).csv"

INTERVAL=1
BASELINE=30
ACTIVE=60
COOLDOWN=30
CPU=6

echo "timestamp,phase,cpu_temp_C,gpu_temp_C,gpu_freq_MHz,gpu_power_raw,vddgfx_V,vddnb_V,cpu_freq_MHz" > "$OUT"

read_cpu_temp() {
    awk '{printf "%.3f", $1/1000}' \
        /sys/class/hwmon/hwmon2/temp1_input
}

read_gpu_temp() {
    awk '{printf "%.3f", $1/1000}' \
        /sys/class/hwmon/hwmon1/temp1_input
}

read_gpu_freq() {
    awk '{printf "%.1f", $1/1000000}' \
        /sys/class/hwmon/hwmon1/freq1_input
}

read_gpu_power() {
    awk '{printf "%.6f", $1/1000000}' \
        /sys/class/hwmon/hwmon1/power1_average
}

read_vddgfx() {
    awk '{printf "%.6f", $1/1000}' \
        /sys/class/hwmon/hwmon1/in0_input
}

read_vddnb() {
    awk '{printf "%.6f", $1/1000}' \
        /sys/class/hwmon/hwmon1/in1_input
}

read_cpu_freq() {
    awk '{printf "%.1f", $1/1000}' \
        /sys/devices/system/cpu/cpu${CPU}/cpufreq/scaling_cur_freq
}

log_sample() {
    phase="$1"

    echo "$(date +%s),$phase,$(read_cpu_temp),$(read_gpu_temp),$(read_gpu_freq),$(read_gpu_power),$(read_vddgfx),$(read_vddnb),$(read_cpu_freq)" >> "$OUT"
}

run_phase() {
    phase="$1"
    seconds="$2"

    end=$((SECONDS + seconds))

    while [ "$SECONDS" -lt "$end" ]; do
        log_sample "$phase"
        sleep "$INTERVAL"
    done
}

echo "Output: $OUT"

echo "=== BASELINE ==="
run_phase BASELINE "$BASELINE"

echo "=== CPU ONLY ==="
taskset -c "$CPU" ./cpu_burn "$CPU" "$ACTIVE" &
CPU_PID=$!
run_phase CPU_ONLY "$ACTIVE"
wait "$CPU_PID"

echo "=== COOLDOWN ==="
run_phase COOLDOWN "$COOLDOWN"

echo "=== GPU ONLY ==="
echo "Start/keep gpu_stress_safe.html active now."
read -p "Press ENTER when GPU stress is running..."

run_phase GPU_ONLY "$ACTIVE"

echo "Stop GPU stress now."
read -p "Press ENTER after stopping GPU stress..."

echo "=== COOLDOWN ==="
run_phase COOLDOWN "$COOLDOWN"

echo "=== CPU + GPU ==="
echo "Start/keep gpu_stress_safe.html active."
read -p "Press ENTER when GPU stress is running..."

taskset -c "$CPU" ./cpu_burn "$CPU" "$ACTIVE" &
CPU_PID=$!

run_phase CPU_GPU "$ACTIVE"

wait "$CPU_PID"

echo "Stop GPU stress now."
read -p "Press ENTER after stopping GPU stress..."

echo "=== COOLDOWN ==="
run_phase COOLDOWN "$COOLDOWN"

echo
echo "Experiment complete."
echo "CSV: $OUT"
