#!/bin/bash

INPUT="core_thermal_table.csv"
OUTPUT="thermal_core_lookup.csv"

awk -F',' '
NR==1 {
    print "core,avg_Tctl_C,thermal_index,normalized_thermal_cost"
    next
}
{
    core=$1
    temp=$2
    thermal_idx=$3

    cost=thermal_idx/3.63

    printf "%d,%.2f,%.2f,%.4f\n",
           core,temp,thermal_idx,cost
}
' "$INPUT" > "$OUTPUT"

echo "Generated $OUTPUT"
