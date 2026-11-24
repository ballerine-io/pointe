#!/bin/sh
# usage: ./long_job.sh [--out DIR] [--from N]
# Writes step_NN.txt for NN from N (default 1) to 20 into DIR (default: this folder), two seconds apart.
out=. ; from=1
while [ $# -gt 0 ]; do
  case "$1" in
    --out) out="$2"; shift 2 ;;
    --from) from="$2"; shift 2 ;;
    *) echo "usage: ./long_job.sh [--out DIR] [--from N]" >&2; exit 2 ;;
  esac
done
mkdir -p "$out"
i=$from
while [ "$i" -le 20 ]; do
  n=$(printf '%02d' "$i")
  echo "step $n done" > "$out/step_$n.txt"
  echo "wrote $out/step_$n.txt"
  i=$((i + 1))
  [ "$i" -le 20 ] && sleep 2
done
echo "all steps done"
