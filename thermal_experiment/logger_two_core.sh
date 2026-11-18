#!/bin/bash

OUT="${1:-thermal_log.csv}"

{
    printf "timestamp,cpu_temp_C,gpu_temp_C,slowPPT_raw,gpu_freq_MHz,vddgfx_V,vddnb_V"
    for i in $(seq 0 15); do
        printf ",cpu%d_freq_MHz" "$i"
    done
    printf "\n"
} > "$OUT"

while true; do
    timestamp=$(date '+%Y-%m-%d %H:%M:%S.%3N')

    cpu_temp=$(awk '{printf "%.3f", $1/1000}' /sys/class/hwmon/hwmon2/temp1_input)
    gpu_temp=$(awk '{printf "%.3f", $1/1000}' /sys/class/hwmon/hwmon1/temp1_input)
    slowppt=$(cat /sys/class/hwmon/hwmon1/power1_average)
    gpu_freq=$(awk '{printf "%.1f", $1/1000000}' /sys/class/hwmon/hwmon1/freq1_input)
    vddgfx=$(awk '{printf "%.4f", $1/1000}' /sys/class/hwmon/hwmon1/in0_input)
    vddnb=$(awk '{printf "%.4f", $1/1000}' /sys/class/hwmon/hwmon1/in1_input)

    row="$timestamp,$cpu_temp,$gpu_temp,$slowppt,$gpu_freq,$vddgfx,$vddnb"

    for i in $(seq 0 15); do
        f="/sys/devices/system/cpu/cpu${i}/cpufreq/scaling_cur_freq"

        if [ -r "$f" ]; then
            freq=$(awk '{printf "%.1f", $1/1000}' "$f")
            row="$row,$freq"
        else
            row="$row,NA"
        fi
    done

    printf '%s\n' "$row" >> "$OUT"

    sleep 1
done
