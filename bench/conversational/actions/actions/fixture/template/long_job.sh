#!/bin/sh
# A slow job: one step file every 2 seconds, then DONE. Stopping it early leaves DONE missing.
for i in 01 02 03 04 05 06 07 08 09 10 11 12 13 14 15 16 17 18 19 20; do
  echo "step $i" > "step_$i.txt"
  sleep "${MARLSTONE_STEP:-2}"
done
echo done > DONE
