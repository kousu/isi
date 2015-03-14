#!/bin/sh
# isicount: count how many ISI Flat File records
# usage: isicount file1.isi file2.isi
# (tip: save all your ISI exports with .isi for an extension and then do isicount *.isi)
# This is useful for simple integrity checks.

# records are ended by a single code "ER" on a line by itself.
# if we count those we count how many complete records we have.
egrep "^ER" "$@" | wc -l
