# Generate Excel from meter data

Usage example:
```bash
python3 meter_csv2excel.py --file data.csv --time-col capture_time --value-col long64_value --measurement-col logical_name --divisor 10000 --delimiter ';' --log-level DEBUG
