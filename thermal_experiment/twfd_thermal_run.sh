#!/bin/bash

OUT="twfd_thermal_$(date +%Y%m%d_%H%M%S).csv"

echo "timestamp,phase,cpu_temp_C,gpu_temp_C,gpu_freq_MHz,vddgfx_V,vddnb_V,cpu0_freq_MHz,cpu1_freq_MHz,cpu2_freq_MHz,cpu3_freq_MHz,cpu4_freq_MHz,cpu5_freq_MHz,cpu6_freq_MHz,cpu7_freq_MHz,cpu8_freq_MHz,cpu9_freq_MHz,cpu10_freq_MHz,cpu11_freq_MHz,cpu12_freq_MHz,cpu13_freq_MHz,cpu14_freq_MHz,cpu15_freq_MHz" > "$OUT"

read_hwmon() {

    CPU_TEMP=$(awk '{print $1/1000}' /sys/class/hwmon/hwmon2/temp1_input 2>/dev/null)
    GPU_TEMP=$(awk '{print $1/1000}' /sys/class/hwmon/hwmon1/temp1_input 2>/dev/null)

    GPU_FREQ=$(awk '{print $1/1000000}' /sys/class/hwmon/hwmon1/freq1_input 2>/dev/null)

    VDDGFX=$(awk '{print $1/1000}' /sys/class/hwmon/hwmon1/in0_input 2>/dev/null)
    VDDNB=$(awk '{print $1/1000}' /sys/class/hwmon/hwmon1/in1_input 2>/dev/null)

    CPU_FREQS=""

    for i in $(seq 0 15); do

        FREQ=$(awk '{print $1/1000}' \
            /sys/devices/system/cpu/cpu${i}/cpufreq/scaling_cur_freq \
            2>/dev/null)

        if [ -z "$FREQ" ]; then
            FREQ=0
        fi

        CPU_FREQS="${CPU_FREQS},${FREQ}"

    done

    echo "$(date +%s.%N),$1,$CPU_TEMP,$GPU_TEMP,$GPU_FREQ,$VDDGFX,$VDDNB$CPU_FREQS" >> "$OUT"
}


echo "Output file: $OUT"

echo
echo "T-WFD thermal experiment"
echo "========================"
echo
echo "Baseline: 20 seconds"
echo "Workload: 60 seconds"
echo "Cooldown: 30 seconds"
echo


echo "Collecting baseline..."

for i in $(seq 1 20); do
    read_hwmon "BASELINE"
    sleep 1
done


echo
echo "Starting T-WFD workload..."
echo

./twfd_runtime &
TWFDPID=$!


echo "Logging active workload..."

while kill -0 "$TWFDPID" 2>/dev/null; do

    read_hwmon "ACTIVE"

    sleep 1

done


wait "$TWFDPID"


echo
echo "Workload completed."
echo "Collecting cooldown..."
echo


for i in $(seq 1 30); do

    read_hwmon "COOLDOWN"

    sleep 1

done


echo
echo "Experiment complete."
echo "CSV: $OUT"
echo

