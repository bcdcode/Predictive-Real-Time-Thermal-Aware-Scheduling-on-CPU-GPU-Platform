#!/bin/bash

C1=0
C2=7

echo "Running two CPU workloads on physical cores $C1 and $C2"

./cpu_burn "$C1" 60 &
P1=$!

./cpu_burn "$C2" 60 &
P2=$!

wait "$P1"
wait "$P2"
