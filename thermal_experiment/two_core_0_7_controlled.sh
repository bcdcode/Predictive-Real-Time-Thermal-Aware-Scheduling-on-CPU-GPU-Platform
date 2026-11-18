#!/bin/bash

echo "Baseline period: 20 seconds"
sleep 20

echo "Starting CPU0 + CPU7 workload"
./cpu_burn 0 60 &
P1=$!

./cpu_burn 7 60 &
P2=$!

wait "$P1"
wait "$P2"

echo "Workload finished"
echo "Cooldown: 30 seconds"
sleep 30

echo "Experiment complete"
