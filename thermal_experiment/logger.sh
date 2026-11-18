#!/bin/bash

OUT="${1:-thermal_log.csv}"

echo -n "timestamp,cpu_temp_C,gpu_temp_C,gpu_power_W,gpu_freq_MHz,vddgfx_V,vddnb_V" > "$OUT"

for i in $(seq 0 15); do
    echo -n ",cpu${i}_freq_MHz" >> "$OUT"
done
echo >> "$OUT"

while true; do
    timestamp=$(date '+%Y-%m-%d %H:%M:%S.%3N')

    cpu_temp=$(awk '{printf "%.3f", $1/1000}' \
        /sys/class/hwmon/hwmon2/temp1_input)

    gpu_temp=$(awk '{printf "%.3f", $1/1000}' \
        /sys/class/hwmon/hwmon1/temp1_input)

    gpu_power=$(awk '{printf "%.6f", $1/1000000}' \
        /sys/class/hwmon/hwmon1/power1_average)

    gpu_freq=$(awk '{printf "%.1f", $1/1000000}' \
        /sys/class/hwmon/hwmon1/freq1_input)

    vddgfx=$(awk '{printf "%.4f", $1/1000}' \
        /sys/class/hwmon/hwmon1/in0_input)

    vddnb=$(awk '{printf "%.4f", $1/1000}' \
        /sys/class/hwmon/hwmon1/in1_input)

    echo -n "$timestamp,$cpu_temp,$gpu_temp,$gpu_power,$gpu_freq,$vddgfx,$vddnb" >> "$OUT"

    for i in $(seq 0 15); do
        f="/sys/devices/system/cpu/cpu${i}/cpufreq/scaling_cur_freq"

        if [ -r "$f" ]; then
            awk '{printf ",%.1f", $1/1000}' "$f" >> "$OUT"
        else
            echo -n ",NA" >> "$OUT"
        fi
    done

    echo >> "$OUT"

    sleep 1
done
EOF
