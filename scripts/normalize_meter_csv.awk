BEGIN {
    FS = ";"
    # lo, hi and meter can all be overridden with, e.g.:
    #   awk -v lo="..." -v hi="..." -v meter="..." -f normalize_meter_csv.awk
    if (lo == "") lo = "2025-03-31T22:00:00Z"
    if (hi == "") hi = "2026-06-30T22:00:00Z"
    # No real fallback here on purpose: meter_reading2consumption.py's
    # load_raw_export_folder() always passes -v meter=... explicitly when a
    # value is actually needed (raising its own clear error otherwise,
    # rather than silently mislabeling schema-2 rows under a stale default).
}
FNR == 1 {
    if ($1 == "logical_name") { schema = 1 }
    else if ($1 == "id") { schema = 2 }
    else if ($1 == "no") {
        # Multi-contract dumps (no;meter;id;... or no;cis;meter;id;...) -
        # column order/count varies, so locate "meter"/"value"/"capture_time"
        # by name rather than assuming a fixed position.
        schema = 3
        meter_col = 0; value_col = 0; time_col = 0
        for (i = 1; i <= NF; i++) {
            if ($i == "meter") meter_col = i
            else if ($i == "value") value_col = i
            else if ($i == "capture_time") time_col = i
        }
    }
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
schema == 3 {
    t = $time_col; v = $value_col; m = $meter_col
    if (t >= lo && t < hi) print t ";" v ";" m
    next
}
