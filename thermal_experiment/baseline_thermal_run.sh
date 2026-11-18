#!/bin/bash

OUT="baseline_thermal_$(date +%Y%m%d_%H%M%S).csv"

echo "timestamp,phase,cpu_temp_C,gpu_temp_C,gpu_freq_MHz,vddgfx_V,vddnb_V,cpu0_freq_MHz,cpu1_freq_MHz,cpu2_freq_MHz,cpu3_freq_MHz,cpu4_freq_MHz,cpu5_freq_MHz,cpu6_freq_MHz,cpu7_freq_MHz,cpu8_freq_MHz,cpu9_freq_MHz,cpu10_freq_MHz,cpu11_freq_MHz,cpu12_freq_MHz,cpu13_freq_MHz,cpu14_freq_MHz,cpu15_freq_MHz" > "$OUT"

read_sensors() {
    ts=$(date +%s.%N)

    cpu_temp=$(awk '{print $1/1000}' /sys/class/hwmon/hwmon2/temp1_input)
    gpu_temp=$(awk '{print $1/1000}' /sys/class/hwmon/hwmon1/temp1_input)
    gpu_freq=$(awk '{print $1/1000000}' /sys/class/hwmon/hwmon1/freq1_input)
    vddgfx=$(awk '{print $1/1000}' /sys/class/hwmon/hwmon1/in0_input)
    vddnb=$(awk '{print $1/1000}' /sys/class/hwmon/hwmon1/in1_input)

    freqs=""

    for cpu in {0..15}; do
        freq_file="/sys/devices/system/cpu/cpu${cpu}/cpufreq/scaling_cur_freq"

        if [ -r "$freq_file" ]; then
            freq=$(awk '{print $1/1000}' "$freq_file")
        else
            freq=0
        fi

        freqs="$freqs,$freq"
    done

    echo "$ts,$PHASE,$cpu_temp,$gpu_temp,$gpu_freq,$vddgfx,$vddnb$freqs" >> "$OUT"
}

echo
echo "=========================================="
echo "Baseline thermal experiment"
echo "=========================================="
echo "Baseline : 20 seconds"
echo "Workload : 60 seconds"
echo "Cooldown : 30 seconds"
echo "Output   : $OUT"
echo "=========================================="
echo

echo "Collecting baseline..."

PHASE="BASELINE"
END=$((SECONDS + 20))

while [ $SECONDS -lt $END ]; do
    read_sensors
    sleep 1
done

echo "Starting baseline workload..."

./baseline_runtime &
PID=$!

PHASE="ACTIVE"

echo "Logging active workload..."

while kill -0 "$PID" 2>/dev/null; do
    read_sensors
    sleep 1
done

wait "$PID"

echo "Workload completed."
echo "Collecting cooldown..."

PHASE="COOLDOWN"
END=$((SECONDS + 30))

while [ $SECONDS -lt $END ]; do
    read_sensors
    sleep 1
done

echo
echo "Experiment complete."
echo "CSV: $OUT"
