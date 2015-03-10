#!/bin/sh
# usage: isijoin [savedrecs1.txt savedrecs2.txt ...] > joined.txt
# outputs to stdout

echo "FN Thomson Reuters Web of Science"
echo "VR 1.0"

for fname in "${@}"; do
  tail -n +2 "${fname}" | head -n -2
done

echo "EF"
