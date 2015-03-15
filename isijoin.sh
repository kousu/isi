#!/bin/sh
# usage: isijoin [savedrecs1.txt savedrecs2.txt ...] > joined.txt
# notice that this just outputs to stdout
# TODO: handle unicode correctly; the raw ISI files come in UTF-8 with a BOM; this script effectively strips that.
#

echo "FN Thomson Reuters Web of Science"
echo "VR 1.0"

for fname in "${@}"; do
  tail -n +3 "${fname}" | head -n -1
done

echo "EF"
