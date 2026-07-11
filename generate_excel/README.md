# Generate Excel from meter data

This folder's original script, `meter_csv2excel.py`, has been superseded by
`scripts/meter_reading2consumption.py` (a superset: also supports `--stdin`,
JSON/XML output, and downsampling). The original is kept for reference at
`scripts/archive/meter_csv2excel.py`.

Usage example:
```bash
python3 scripts/meter_reading2consumption.py --file data.csv --time-col capture_time --value-col long64_value --measurement-col logical_name --divisor 10000 --delimiter ';' --log-level DEBUG
```
