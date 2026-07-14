BEGIN {
    FS = ";"
    # lo, hi and meter can all be overridden with, e.g.:
    #   awk -v lo="..." -v hi="..." -v meter="..." -f normalize_meter_csv.awk
    if (lo == "") lo = "2025-03-31T22:00:00Z"
    if (hi == "") hi = "2026-06-30T22:00:00Z"
    if (meter == "") meter = "01005e31803c.1emh0011802881.sm"
}
FNR == 1 {
    if ($1 == "logical_name") { schema = 1 }
    else if ($1 == "id") { schema = 2 }
    else { schema = 0 }
    next
}
schema == 1 {
    t = $2; v = $3; m = $1
    if (t >= lo && t < hi) print t ";" v ";" m
    next
}
schema == 2 {
    t = $6; v = $2; m = meter
    if (t >= lo && t < hi) print t ";" v ";" m
    next
}
