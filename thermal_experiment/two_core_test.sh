#!/bin/bash

MODE="$1"

if [ "$MODE" = "hot" ]; then
    C1=6
    C2=7
elif [ "$MODE" = "cool" ]; then
    C1=0
    C2=1
else
    echo "Usage: $0 hot|cool"
    exit 1
fi

echo "Running two CPU workloads on physical cores $C1 and $C2"

./cpu_burn "$C1" 60 &
P1=$!

./cpu_burn "$C2" 60 &
P2=$!

wait "$P1"
wait "$P2"
